#!/usr/bin/env python
"""
evaluate.py
===========
Mide la precision de los motores de transcripcion sobre los 3 audios de
prueba y genera el informe de comparativa del reto.

Metrica: WER (Word Error Rate) sobre la verdad terreno de
`audios/ground_truth.json`.

    WER = (Sustituciones + Borrados + Insertados) / Palabras de la referencia

El script llama al endpoint Flask (proveedor Gemini) para cada audio y, si se
le pasa un fichero con transcripciones de la Web Speech API, incluye esa
columna en la comparativa.

Uso:
    # 1. Arranca el servidor en otra terminal:  python run.py
    # 2. Solo el endpoint (Gemini o mock):
    python scripts/evaluate.py --endpoint http://127.0.0.1:5000

    # 3. Endpoint + Web Speech API:
    python scripts/evaluate.py --endpoint http://127.0.0.1:5000 \
        --webspeech resultados/webspeech.json

    # 4. Sin servidor (solo reevaluar datos ya guardados):
    python scripts/evaluate.py --offline

Salida:
    resultados/informe.json   datos crudos
    resultados/informe.md     tabla comparativa lista para el informe
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.metrics import calcular_wer  # noqa: E402

GT_PATH = ROOT / "audios" / "ground_truth.json"
OUT_DIR = ROOT / "resultados"


# ---------------------------------------------------------------- utilidades
def cargar_verdad_terreno() -> list[dict]:
    if not GT_PATH.is_file():
        raise SystemExit(
            "No existe audios/ground_truth.json.\n"
            "Ejecuta primero:  ./scripts/generate_audios.sh"
        )
    return json.loads(GT_PATH.read_text(encoding="utf-8"))["audios"]


def llamar_endpoint(url: str, audio: Path, language: str, provider: str) -> dict:
    """POST multipart/form-data al endpoint, usando solo la stdlib."""
    boundary = "----ASIXSTT7f3c9b1e"
    campos = {
        "language": language,
        "provider": provider,
    }

    def parte(nombre: str, valor: str) -> bytes:
        return (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{nombre}"\r\n\r\n'
            f"{valor}\r\n"
        ).encode("utf-8")

    cuerpo = b"".join(parte(k, v) for k, v in campos.items())
    cab = audio.read_bytes()
    cuerpo += (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="audio"; '
        f'filename="{audio.name}"\r\n'
        f"Content-Type: audio/wav\r\n\r\n"
    ).encode("utf-8") + cab + f"\r\n--{boundary}--\r\n".encode("utf-8")

    req = urllib.request.Request(url, data=cuerpo, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("Accept", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return {"http_status": resp.status, **json.loads(resp.read().decode())}
    except urllib.error.HTTPError as e:
        crudo = e.read().decode(errors="replace")
        try:
            detalle = json.loads(crudo)
        except json.JSONDecodeError:
            detalle = {"error": "respuesta_no_json", "detalle": crudo[:400]}
        return {"http_status": e.code, **detalle}
    except urllib.error.URLError as e:
        return {"http_status": 0, "error": "sin_conexion", "detalle": str(e.reason)}


def cargar_json(opcion: str | None) -> list[dict]:
    """Carga transcripciones guardadas (Web Speech API u offline)."""
    if not opcion:
        return []
    p = Path(opcion)
    if not p.is_absolute():
        p = ROOT / p
    if not p.is_file():
        print(f"[AVISO] No existe {p}: se omite esa columna.", file=sys.stderr)
        return []
    datos = json.loads(p.read_text(encoding="utf-8"))
    return datos.get("resultados", datos if isinstance(datos, list) else [])


# ------------------------------------------------------------------- informe
def construir_informe(
    verdad: list[dict],
    endpoint: list[dict],
    webspeech: list[dict],
) -> dict:
    por_id_ws = {r.get("audio_id"): r for r in webspeech if r.get("audio_id")}
    por_id_ep = {r.get("audio_id"): r for r in endpoint if r.get("audio_id")}

    filas = []
    for item in verdad:
        aid = item["id"]
        ref = item["referencia"]

        ep = por_id_ep.get(aid)
        if ep:
            # El proveedor simulado no analiza el audio: no se mide.
            evaluable = ep.get("evaluable", ep.get("provider") != "mock")
            w_ep = calcular_wer(
                ref,
                ep.get("hipotesis", ""),
                evaluable=evaluable,
                motivo_no_evaluable=ep.get("motivo"),
            )
        else:
            evaluable = False
            w_ep = calcular_wer(
                ref, "", evaluable=False, motivo_no_evaluable="sin ejecutar"
            )

        ws = por_id_ws.get(aid)
        if ws:
            w_ws = calcular_wer(ref, ws.get("hipotesis", ""), evaluable=True)
        else:
            w_ws = calcular_wer(
                ref, "", evaluable=False, motivo_no_evaluable="no capturado"
            )

        filas.append({
            "audio_id": aid,
            "archivo": item["archivo"],
            "voz": item.get("voz"),
            "nivel": item.get("nivel"),
            "duracion_s": None,
            "referencia": ref,
            "webspeech": {
                "hipotesis": ws.get("hipotesis") if ws else None,
                "evaluable": bool(ws),
                "resultado": w_ws.to_dict(),
            },
            "endpoint": {
                "hipotesis": ep.get("hipotesis") if ep else None,
                "provider": ep.get("provider") if ep else None,
                "evaluable": evaluable,
                "http_status": ep.get("http_status") if ep else None,
                "servicio_ms": ep.get("servicio_ms") if ep else None,
                "resultado": w_ep.to_dict(),
            },
        })

    def media(evaluaciones: list[dict]) -> float | None:
        vals = [
            e["resultado"]["wer"]
            for e in evaluaciones
            if e["resultado"]["evaluable"]
        ]
        return round(statistics.mean(vals), 4) if vals else None

    return {
        "metrica": "WER (Word Error Rate) = (S + B + I) / palabras_referencia",
        "nota_metrica": (
            "El texto se normaliza (minusculas, sin acentos ni puntuacion) "
            "antes de comparar, de modo que diferencias tipograficas no "
            "cuentan como error. El WER no tiene cota superior."
        ),
        "audios": filas,
        "resumen": {
            "webspeech_wer_medio": media([f["webspeech"] for f in filas]),
            "endpoint_wer_medio": media([f["endpoint"] for f in filas]),
            "audios_con_webspeech": sum(1 for f in filas if f["webspeech"]["evaluable"]),
            "audios_con_endpoint": sum(
                1 for f in filas if f["endpoint"]["evaluable"]
            ),
        },
    }


def render_markdown(informe: dict) -> str:
    r = informe["resumen"]

    def celda(evaluacion: dict) -> str:
        res = evaluacion["resultado"]
        if not res["evaluable"]:
            return "n/d"
        return f"{res['wer_porcentaje']:.2f} %"

    lineas = [
        "| Audio | Nivel | Referencia | Web Speech API | WER API | Endpoint | WER Endpoint |",
        "|---|---|---|---|---|---|---|",
    ]
    for f in informe["audios"]:
        ws = f["webspeech"]
        ep = f["endpoint"]
        hs = f'`{ws["hipotesis"]}`' if ws["evaluable"] else "*no capturado*"
        he = (
            f'`{ep["provider"]}`: {ep["hipotesis"]}'
            if ep["evaluable"]
            else f'*{ep["provider"] or "sin ejecutar"}: no evaluable*'
        )
        lineas.append(
            f"| `{f['audio_id']}` | {f['nivel']} | {f['referencia']} | "
            f"{hs} | {celda(ws)} | {he} | {celda(ep)} |"
        )

    medio_api = (
        f"**{r['webspeech_wer_medio'] * 100:.2f} %**"
        if r["webspeech_wer_medio"] is not None else "no medible"
    )
    medio_ep = (
        f"**{r['endpoint_wer_medio'] * 100:.2f} %**"
        if r["endpoint_wer_medio"] is not None else "no medible"
    )

    return "\n".join([
        "# Comparativa de precision — Reto Speech-to-Text",
        "",
        f"Metrica: {informe['metrica']}",
        "",
        f"> {informe['nota_metrica']}",
        "",
        *lineas,
        "",
        "## Resumen",
        "",
        "| Motor | Audios medidos | WER medio |",
        "|---|---|---|",
        f"| Web Speech API (navegador) | {r['audios_con_webspeech']}/3 | {medio_api} |",
        f"| Endpoint Flask -> Gemini | {r['audios_con_endpoint']}/3 | {medio_ep} |",
        "",
    ])


# ---------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description="Evalua la precision de los motores STT.")
    ap.add_argument("--endpoint", default="http://127.0.0.1:5000",
                    help="URL del servicio Flask.")
    ap.add_argument("--webspeech", default="resultados/webspeech.json",
                    help="JSON con transcripciones de la Web Speech API.")
    ap.add_argument("--provider", default="gemini",
                    help="Proveedor pedido al endpoint.")
    ap.add_argument("--language", default="es-ES")
    ap.add_argument("--offline", action="store_true",
                    help="No llamar al endpoint; usar resultados/endpoint.json.")
    ap.add_argument("--out", default="resultados", help="Carpeta de salida.")
    args = ap.parse_args()

    verdad = cargar_verdad_terreno()
    OUT_DIR.mkdir(exist_ok=True)

    # ---- endpoint ------------------------------------------------------
    if args.offline:
        endpoint = cargar_json("resultados/endpoint.json")
        print("[i] Modo offline: usando resultados/endpoint.json")
    else:
        endpoint = []
        url = f"{args.endpoint.rstrip('/')}/api/transcribe"
        print(f"[*] Endpoint: {url}  (proveedor={args.provider})\n")
        for item in verdad:
            audio = ROOT / "audios" / item["archivo"]
            r = llamar_endpoint(url, audio, args.language, args.provider)
            provider = r.get("provider", "?")
            evaluable = provider != "mock"
            fila = {
                "audio_id": item["id"],
                "archivo": item["archivo"],
                "hipotesis": r.get("text", ""),
                "provider": provider,
                "evaluable": evaluable,
                "http_status": r.get("http_status"),
                "servicio_ms": r.get("servicio_ms"),
                "motivo": (
                    None if evaluable
                    else r.get("warning") or r.get("detalle")
                ),
            }
            endpoint.append(fila)
            marca = "OK" if evaluable else "no evaluable"
            print(f"  [{marca:>12}] {item['id']:24} -> {provider} "
                  f"({r.get('servicio_ms', '?')} ms)")
            if not evaluable:
                print(f"                  {fila['motivo'][:110]}")

    (OUT_DIR / "endpoint.json").write_text(
        json.dumps({"resultados": endpoint}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # ---- Web Speech API -------------------------------------------------
    webspeech = cargar_json(args.webspeech)
    print(f"\n[*] Transcripciones Web Speech API cargadas: {len(webspeech)}")

    # ---- informe -------------------------------------------------------
    informe = construir_informe(verdad, endpoint, webspeech)
    (OUT_DIR / "informe.json").write_text(
        json.dumps(informe, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    md = render_markdown(informe)
    (OUT_DIR / "informe.md").write_text(md + "\n", encoding="utf-8")

    print("\n" + "=" * 78)
    print(md)
    print("=" * 78)
    print(f"Guardado en {OUT_DIR}/informe.md y {OUT_DIR}/informe.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
