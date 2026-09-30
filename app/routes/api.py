"""
Endpoints HTTP del servicio de transcripcion.

    GET  /api/health          -> estado del servicio y de los proveedores
    POST /api/transcribe      -> recibe audio y devuelve la transcripcion
    GET  /api/providers       -> proveedores registrados y su disponibilidad
"""
from __future__ import annotations

import json
import logging
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request

from app import audio_utils, metrics
from app.providers import build_with_fallback
from app.providers.base import TranscriptionResult, TranscriptionUnavailable

log = logging.getLogger(__name__)
api = Blueprint("api", __name__, url_prefix="/api")

# Estado volátil del proceso (por ejemplo, la cache del sondeo de Gemini).
app_state: dict = {}


def _config():
    return current_app.config["STT_CONFIG"]


# ----------------------------------------------------------------------
# GET /api/health
# ----------------------------------------------------------------------
@api.get("/health")
def health():
    """
    Estado del servicio.

    Distingue con cuidado entre "hay credencial configurada" y "Gemini
    responde de verdad": en este proyecto la clave existe pero el acceso a
    generateContent esta denegado por Google, y announcing "operativo" solo
    porque hay una clave seria mentirle al usuario.
    """
    cfg = _config()

    gemini_key = cfg.has_gemini_key
    gemini_probe = None
    if gemini_key:
        # Sondeo minimo: una peticion de texto de 1 token. Cuesta casi nada
        # y confirma si la generacion esta permitida.
        gemini_probe = sondear_gemini(cfg)

    if not gemini_key:
        estado_gemini = "sin_credencial"
        detalle = "GEMINI_API_KEY no configurada: se usara el proveedor simulado."
    elif gemini_probe is None:
        estado_gemini = "credencial_presente"
        detalle = "Hay API key; el estado real se comprueba al transcribir."
    elif gemini_probe["operativo"]:
        estado_gemini = "operativo"
        detalle = "Gemini responde correctamente."
    else:
        estado_gemini = "bloqueado"
        detalle = gemini_probe["detalle"]

    return jsonify(
        {
            "estado": "ok",
            "servicio": "ASIX Speech-to-Text API",
            "version": "1.0.0",
            "gemini": {
                "estado": estado_gemini,
                # Se mantiene 'operativo' por compatibilidad, pero refleja el
                # sondeo real y no solo la presencia de la clave.
                "operativo": estado_gemini == "operativo",
                "credencial_configurada": gemini_key,
                "sondeo": gemini_probe,
                "detalle": detalle,
            },
            "config": cfg.summary(),
        }
    )


def sondear_gemini(cfg) -> dict | None:
    """
    Comprueba de verdad si Gemini permite generar contenido.

    Hace la llamada mas barata posible (1 token de salida) y cachea el
    resultado 5 minutos para no gastar cuota en cada comprobacion de salud.
    """
    cache = app_state.setdefault("sondeo_gemini", {})
    ahora = time.monotonic()
    # Con la cache vacia hay que sondear de verdad: sin comprobar que 'ts'
    # exista, un now pequeno (maquina recien arrancada) haria pasar la
    # ventana de cache y devolveria una sonda sin 'operativo'.
    if "ts" in cache and (ahora - cache["ts"]) < 300:
        return {k: v for k, v in cache.items() if k != "ts"}

    try:
        provider, fell_back = build_with_fallback("gemini", cfg)
    except Exception as exc:  # pragma: no cover
        resultado = {"operativo": False, "detalle": str(exc)}
        cache.update(resultado, ts=ahora)
        return resultado

    if fell_back:
        cache.update(
            {"operativo": False, "detalle": provider.unavailable_reason()}, ts=ahora
        )
        return {k: v for k, v in cache.items() if k != "ts"}

    try:
        cliente = provider._get_client()  # noqa: SLF001
        resp = cliente.models.generate_content(
            model=cfg.gemini_model,
            contents="Responde solo: OK",
            config={
                "temperature": 0.0,
                "max_output_tokens": 1,
                "http_options": {"timeout": 15000},
            },
        )
        _ = getattr(resp, "text", None)
        resultado = {
            "operativo": True,
            "modelo": cfg.gemini_model,
            "detalle": "generateContent responde.",
        }
    except Exception as exc:
        resultado = {
            "operativo": False,
            "modelo": cfg.gemini_model,
            "detalle": provider._describe_error(exc),  # noqa: SLF001
        }

    cache.update(resultado, ts=ahora)
    return {k: v for k, v in cache.items() if k != "ts"}


# ----------------------------------------------------------------------
# GET /api/providers
# ----------------------------------------------------------------------
@api.get("/providers")
def providers():
    cfg = _config()
    return jsonify(
        {
            "registrados": [
                {
                    "nombre": "gemini",
                    "descripcion": "Google Gemini (procesamiento por lotes)",
                    "requiere_api_key": True,
                    "disponible": cfg.has_gemini_key,
                },
                {
                    "nombre": "mock",
                    "descripcion": "Simulador de reserva (NO transcribe audio real)",
                    "requiere_api_key": False,
                    "disponible": True,
                },
            ],
            "por_defecto": "gemini",
        }
    )


# ----------------------------------------------------------------------
# POST /api/transcribe
# ----------------------------------------------------------------------
@api.post("/transcribe")
def transcribe():
    """
    Recibe un fichero de audio (multipart/form-data, campo `audio`) y devuelve
    la transcripcion en texto plano.

    Parametros de formulario opcionales:
        language  - codigo BCP-47, por defecto "es-ES"
        provider  - "gemini" (por defecto) o "mock"
    """
    cfg = _config()
    started = time.perf_counter()

    upload = request.files.get("audio")
    if upload is None or not upload.filename:
        return (
            jsonify(
                {
                    "error": "falta_fichero_audio",
                    "detalle": "Envia el audio en multipart/form-data con el campo 'audio'.",
                }
            ),
            400,
        )

    language = (request.form.get("language") or cfg.default_language).strip()
    provider_name = (request.form.get("provider") or "gemini").strip().lower()

    try:
        audio_utils.validate_extension(upload.filename, cfg.allowed_extensions)
    except audio_utils.AudioError as exc:
        return jsonify({"error": "formato_no_admitido", "detalle": str(exc)}), 415

    ext = Path(upload.filename).suffix.lower()
    tmpdir = Path(tempfile.mkdtemp(prefix="stt_"))
    raw_path = tmpdir / f"entrada{ext}"
    norm_path = tmpdir / "normalizado.wav"

    try:
        upload.save(raw_path)
        size = raw_path.stat().st_size
        if size == 0:
            return jsonify({"error": "audio_vacio", "detalle": "El fichero tiene 0 bytes."}), 400
        if size > cfg.max_upload_bytes:
            return (
                jsonify(
                    {
                        "error": "audio_demasiado_grande",
                        "detalle": f"Maximo {cfg.max_upload_mb} MB.",
                    }
                ),
                413,
            )

        try:
            info = audio_utils.prepare(
                src=raw_path,
                dest=norm_path,
                filename=upload.filename,
                size_bytes=size,
                mime_type=upload.mimetype or "application/octet-stream",
            )
        except audio_utils.AudioError as exc:
            return jsonify({"error": "audio_invalido", "detalle": str(exc)}), 400

        try:
            provider, fell_back = build_with_fallback(provider_name, cfg)
        except KeyError as exc:
            return jsonify({"error": "proveedor_desconocido", "detalle": str(exc)}), 400
        except TranscriptionUnavailable as exc:
            return jsonify({"error": "proveedor_no_disponible", "detalle": str(exc)}), 503

        if fell_back:
            log.warning(
                "Proveedor '%s' no disponible; usando 'mock'. Motivo: %s",
                provider_name,
                provider.unavailable_reason() or "desconocido",
            )

        try:
            result: TranscriptionResult = provider.transcribe(
                audio_path=info.path, language=language
            )
        except TranscriptionUnavailable as exc:
            if cfg.allow_mock_fallback and provider.name != "mock":
                log.error("Gemini fallo (%s); reintentando con 'mock'.", exc)
                provider, _ = build_with_fallback("mock", cfg)
                result = provider.transcribe(audio_path=info.path, language=language)
                result.warning = (
                    f"Gemini no pudo transcribir y se activo el proveedor simulado. "
                    f"Motivo: {exc}"
                )
            else:
                return (
                    jsonify({"error": "transcripcion_fallida", "detalle": str(exc)}),
                    502,
                )

        total_ms = int((time.perf_counter() - started) * 1000)
        payload = result.to_dict()
        payload["audio"] = info.to_dict()
        payload["servicio_ms"] = total_ms
        payload["proveedor_pedido"] = provider_name
        return jsonify(payload), 200

    finally:
        # El audio es dato de usuario: se borra en cuanto se responde.
        for p in (raw_path, norm_path):
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
        try:
            tmpdir.rmdir()
        except OSError:
            pass


# ----------------------------------------------------------------------
# GET /api/groundtruth
# ----------------------------------------------------------------------
@api.get("/groundtruth")
def groundtruth():
    """Verdad terreno de los audios de prueba (la genera generate_audios.sh)."""
    from app.config import BASE_DIR

    path = BASE_DIR / "audios" / "ground_truth.json"
    if not path.is_file():
        return (
            jsonify(
                {
                    "error": "sin_verdad_terreno",
                    "detalle": "Ejecuta ./scripts/generate_audios.sh para crearla.",
                }
            ),
            404,
        )
    return jsonify(json.loads(path.read_text(encoding="utf-8")))


# ----------------------------------------------------------------------
# POST /api/evaluate
# ----------------------------------------------------------------------
@api.post("/evaluate")
def evaluate():
    """
    Calcula el WER de una transcripcion frente a su referencia.

    JSON: {referencia, hipotesis, evaluable?, quitar_stopwords?, audio_id?}
    """
    data = request.get_json(silent=True) or {}
    referencia = (data.get("referencia") or "").strip()
    hipotesis = (data.get("hipotesis") or "").strip()
    if not referencia:
        return jsonify({"error": "falta_referencia"}), 400

    result = metrics.calcular_wer(
        referencia,
        hipotesis,
        evaluable=bool(data.get("evaluable", True)),
        quitar_stopwords=bool(data.get("quitar_stopwords", False)),
        motivo_no_evaluable=data.get("motivo_no_evaluable"),
    )
    payload = result.to_dict()
    payload["audio_id"] = data.get("audio_id")
    return jsonify(payload)


# ----------------------------------------------------------------------
# POST /api/report/webspeech
# ----------------------------------------------------------------------
@api.post("/report/webspeech")
def report_webspeech():
    """
    Recibe una transcripcion obtenida con la Web Speech API y la guarda en
    resultados/webspeech.json, donde scripts/evaluate.py la recoge para
    medir el WER.

    Permite cerrar la comparativa de forma automatica: el navegador es quien
    produce el texto y el servidor solo lo almacena y lo mide con la misma
    metrica que el resto de motores.
    """
    data = request.get_json(silent=True) or {}
    audio_id = (data.get("audio_id") or "").strip()
    hipotesis = data.get("hipotesis")
    if not audio_id or not isinstance(hipotesis, str):
        return jsonify({"error": "faltan_campos", "detalle": "Se requiere audio_id e hipotesis."}), 400

    # Se resuelve en tiempo de llamada (no en el import) para que las
    # pruebas puedan redirigir BASE_DIR a un temporal.
    from app.config import BASE_DIR as base_dir

    destino = base_dir / "resultados" / "webspeech.json"
    destino.parent.mkdir(exist_ok=True)

    if destino.is_file():
        documento = json.loads(destino.read_text(encoding="utf-8"))
    else:
        documento = {
            "metodo": "Web Speech API",
            "nota": "Transcripciones capturadas en el navegador y medidas con el mismo WER.",
            "resultados": [],
        }

    documento["resultados"] = [
        r for r in documento["resultados"] if r.get("audio_id") != audio_id
    ]
    documento["resultados"].append({
        "audio_id": audio_id,
        "hipotesis": hipotesis,
        "navegador": data.get("navegador"),
        "idioma": data.get("idioma"),
        "confianza": data.get("confianza"),
        "origen": data.get("origen", "manual"),
        "ts": data.get("ts") or datetime.now(timezone.utc).isoformat(),
    })
    documento["resultados"].sort(key=lambda r: r["audio_id"])
    destino.write_text(
        json.dumps(documento, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    return jsonify({"guardado": True, "audio_id": audio_id, "total": len(documento["resultados"])})


# ----------------------------------------------------------------------
# Diagnostico de compatibilidad de navegador
# ----------------------------------------------------------------------
def _diag_path():
    from app.config import BASE_DIR

    destino = BASE_DIR / "resultados"
    destino.mkdir(exist_ok=True)
    return destino / "diagnostico.json"


@api.post("/diag")
def diag_guardar():
    """
    Registra el resultado de web/diagnostico.html para comparar navegadores
    sin repetir la prueba en cada equipo.
    """
    data = request.get_json(silent=True) or {}
    if not data.get("navegador"):
        return jsonify({"error": "faltan_campos"}), 400

    registro = {
        "navegador": data.get("navegador"),
        "detalle": data.get("detalle"),
        "microfono": data.get("micfono"),
        "motor_voz": data.get("motor_voz"),
        "transcripcion": data.get("transcripcion"),
        "util_para_opcion_a": bool(data.get("util")),
        "ts": datetime.now(timezone.utc).isoformat(),
    }

    path = _diag_path()
    doc = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"registros": []}
    # Un solo registro por navegador: se sustituye el anterior.
    doc["registros"] = [
        r for r in doc["registros"]
        if r.get("navegador") != registro["navegador"]
    ]
    doc["registros"].append(registro)
    doc["registros"].sort(key=lambda r: str(r.get("navegador")))
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")

    return jsonify({"guardado": True, "total": len(doc["registros"])})


@api.get("/diag")
def diag_ver():
    """Lista los diagnosticos de compatibilidad registrados."""
    path = _diag_path()
    if not path.is_file():
        return jsonify({"registros": [], "detalle": "todavia no se ha ejecutado ninguno"})
    return jsonify(json.loads(path.read_text(encoding="utf-8")))
