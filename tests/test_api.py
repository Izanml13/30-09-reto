"""
Tests de validacion de audio y del contrato HTTP de la API.

No se sale a la red: el proveedor `mock` es siempre disponible, asi que las
rutas se prueban de forma determinista.
"""
import io
import json as _json
import wave
from pathlib import Path

import pytest

from app import audio_utils
from app.main import create_app
from app.providers.mock import MockTranscriber

ROOT = Path(__file__).resolve().parent.parent
AUDIO1 = ROOT / "audios" / "audio1_frase_corta.wav"


@pytest.fixture(scope="module")
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def wav_en_memoria(duracion_s: float = 0.5, rate: int = 16000) -> bytes:
    """Construye un WAV valido en memoria para las pruebas."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(duracion_s * rate))
    buf.seek(0)
    return buf.read()


# --------------------------------------------------------------- audio_utils
def test_is_wav_detecta_riff_wave():
    assert audio_utils.is_wav(AUDIO1) is True


def test_is_wav_rechaza_no_wav(tmp_path):
    p = tmp_path / "falso.wav"
    p.write_bytes(b"\x00" * 100)
    assert audio_utils.is_wav(p) is False


def test_is_wav_no_cree_por_extension(tmp_path):
    """Un .txt renombrado a .wav no debe considerarse WAV."""
    p = tmp_path / "mentira.wav"
    p.write_bytes(b"esto es texto plano, no un WAV")
    assert audio_utils.is_wav(p) is False


def test_read_wav_metadata_de_audio_real():
    meta = audio_utils.read_wav_metadata(AUDIO1)
    assert meta is not None
    assert meta["sample_rate"] == 16000
    assert meta["channels"] == 1
    assert 2.0 < meta["duration_s"] < 4.0


def test_validate_extension_admite_wav():
    assert audio_utils.validate_extension("a.wav", (".wav",)) == ".wav"


def test_validate_extension_rechaza_no_admitido():
    with pytest.raises(audio_utils.AudioError):
        audio_utils.validate_extension("a.exe", (".wav", ".mp3"))


def test_validate_extension_exige_extension():
    with pytest.raises(audio_utils.AudioError):
        audio_utils.validate_extension("audio", (".wav",))


def test_prepare_no_reconvierte_si_ya_esta_en_formato(tmp_path):
    dest = tmp_path / "salida.wav"
    info = audio_utils.prepare(AUDIO1, dest, AUDIO1.name, AUDIO1.stat().st_size)
    assert info.converted is False
    assert info.sample_rate == 16000
    assert info.channels == 1
    assert info.duration_s is not None
    assert not dest.exists()


# ------------------------------------------------------------------------ API
def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    d = r.get_json()
    assert d["estado"] == "ok"
    assert "gemini" in d
    assert "config" in d


def test_health_no_filtra_la_api_key(client):
    """La clave no debe aparecer nunca en la respuesta."""
    crudo = client.get("/api/health").get_data(as_text=True)
    assert "GEMINI_API_KEY=" not in crudo
    assert "x-goog-api-key" not in crudo


def test_health_distingue_credencial_de_operatividad(client):
    """
    Que haya una API key no significa que Gemini funcione: en este proyecto
    la clave existe pero el acceso a generateContent esta denegado por
    Google. El endpoint debe decirlo, no anunciar 'operativo'.
    """
    from app.routes.api import app_state

    app_state.pop("sondeo_gemini", None)
    d = client.get("/api/health").get_json()["gemini"]

    assert d["estado"] in {"operativo", "bloqueado", "credencial_presente", "sin_credencial"}
    if d["credencial_configurada"]:
        # Con credencial presente, el estado debe venir de un sondeo real.
        assert d["sondeo"] is not None
        assert d["operativo"] == d["sondeo"]["operativo"]
    else:
        assert d["operativo"] is False
        assert d["estado"] == "sin_credencial"


def test_providers(client):
    r = client.get("/api/providers")
    assert r.status_code == 200
    nombres = [p["nombre"] for p in r.get_json()["registrados"]]
    assert "gemini" in nombres and "mock" in nombres


def test_groundtruth_servido(client):
    r = client.get("/api/groundtruth")
    assert r.status_code == 200
    assert len(r.get_json()["audios"]) == 3


def test_transcribe_sin_fichero_400(client):
    r = client.post("/api/transcribe", data={})
    assert r.status_code == 400
    assert r.get_json()["error"] == "falta_fichero_audio"


def test_transcribe_extension_invalida_415(client):
    r = client.post(
        "/api/transcribe",
        data={"audio": (io.BytesIO(b"texto"), "notas.txt")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 415
    assert r.get_json()["error"] == "formato_no_admitido"


def test_transcribe_fichero_vacio_400(client):
    r = client.post(
        "/api/transcribe",
        data={"audio": (io.BytesIO(b""), "vacio.wav")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 400
    assert r.get_json()["error"] == "audio_vacio"


def test_transcribe_con_proveedor_mock(client):
    r = client.post(
        "/api/transcribe",
        data={
            "audio": (io.BytesIO(wav_en_memoria()), "prueba.wav"),
            "language": "es-ES",
            "provider": "mock",
        },
        content_type="multipart/form-data",
    )
    assert r.status_code == 200
    d = r.get_json()
    assert d["provider"] == "mock"
    assert d["is_fallback"] is True
    assert d["text"]
    # La respuesta simulada debe avisar de que no ha analizado el audio.
    assert "MOCK" in d["text"]
    assert d["warning"]


def test_transcribe_audio_real_mock_conserva_metadatos(client):
    with AUDIO1.open("rb") as fh:
        datos = fh.read()
    r = client.post(
        "/api/transcribe",
        data={
            "audio": (io.BytesIO(datos), AUDIO1.name),
            "provider": "mock",
        },
        content_type="multipart/form-data",
    )
    assert r.status_code == 200
    audio = r.get_json()["audio"]
    assert audio["sample_rate"] == 16000
    assert audio["channels"] == 1
    assert audio["duration_s"] == pytest.approx(2.91, abs=0.05)
    assert audio["normalizado_a_wav_16k_mono"] is False


def test_transcribe_proveedor_desconocido_400(client):
    r = client.post(
        "/api/transcribe",
        data={
            "audio": (io.BytesIO(wav_en_memoria()), "p.wav"),
            "provider": "whisper-inexistente",
        },
        content_type="multipart/form-data",
    )
    assert r.status_code == 400
    assert r.get_json()["error"] == "proveedor_desconocido"


def test_evaluate_wer(client):
    r = client.post(
        "/api/evaluate",
        json={"referencia": "hola mundo", "hipotesis": "hola monton"},
    )
    assert r.status_code == 200
    d = r.get_json()
    assert d["wer_porcentaje"] == 50.0
    assert d["sustituciones"] == 1
    assert d["evaluable"] is True


def test_evaluate_sin_referencia_400(client):
    r = client.post("/api/evaluate", json={"hipotesis": "hola"})
    assert r.status_code == 400


def test_evaluate_no_evaluable(client):
    r = client.post(
        "/api/evaluate",
        json={
            "referencia": "hola mundo",
            "hipotesis": "[MOCK] texto",
            "evaluable": False,
            "motivo_no_evaluable": "proveedor simulado",
        },
    )
    d = r.get_json()
    assert d["evaluable"] is False
    assert d["motivo_no_evaluable"] == "proveedor simulado"


@pytest.fixture
def isolate_resultados(monkeypatch, tmp_path):
    """
    Redirige resultados/ a un directorio temporal.

    Imprescindible: /api/report/webspeech escribe en disco. Sin esto, los
    tests dejarian transcripciones ficticias en resultados/webspeech.json y
    scripts/evaluate.py las mediria como si fueran reales (un WER de 0 % con
    el texto de referencia es exactamente el dato que hay que evitar).
    """
    import app.config as config_module

    destino = tmp_path / "resultados"
    destino.mkdir()
    monkeypatch.setattr(config_module, "BASE_DIR", tmp_path)
    return destino


def test_report_webspeech_guarda(client, isolate_resultados):
    """El navegador devuelve su transcripcion y el servidor la archiva."""
    r = client.post(
        "/api/report/webspeech",
        json={
            "audio_id": "audio1_frase_corta",
            "hipotesis": "frase de prueba",
            "idioma": "es-ES",
        },
    )
    assert r.status_code == 200
    assert r.get_json()["guardado"] is True

    datos = _json.loads(
        (isolate_resultados / "webspeech.json").read_text(encoding="utf-8")
    )
    assert any(x["audio_id"] == "audio1_frase_corta" for x in datos["resultados"])


def test_report_webspeech_reemplaza_en_lugar_de_duplicar(client, isolate_resultados):
    for texto in ("primera version", "segunda version"):
        client.post("/api/report/webspeech",
                    json={"audio_id": "audio9", "hipotesis": texto})

    datos = _json.loads(
        (isolate_resultados / "webspeech.json").read_text(encoding="utf-8")
    )
    audio9 = [x for x in datos["resultados"] if x["audio_id"] == "audio9"]
    assert len(audio9) == 1
    assert audio9[0]["hipotesis"] == "segunda version"


def test_tests_no_contaminan_resultados_reales():
    """El fichero real de resultados no debe contener datos de test."""
    real = Path(__file__).resolve().parent.parent / "resultados" / "webspeech.json"
    if not real.is_file():
        return  # todavia no se ha capturado nada: correcto
    datos = _json.loads(real.read_text(encoding="utf-8"))
    for entrada in datos["resultados"]:
        assert entrada["audio_id"] != "audio9"
        assert entrada["hipotesis"] not in ("frase de prueba", "segunda version")


# ------------------------------------------------------- diagnostico /api/diag
def test_diag_sin_registros(client, isolate_resultados):
    r = client.get("/api/diag")
    assert r.status_code == 200
    assert r.get_json()["registros"] == []


def test_diag_guarda(client, isolate_resultados):
    r = client.post("/api/diag", json={
        "navegador": "Safari",
        "detalle": "17.0",
        "util": True,
    })
    assert r.status_code == 200
    assert r.get_json()["guardado"] is True

    registros = client.get("/api/diag").get_json()["registros"]
    assert len(registros) == 1
    assert registros[0]["util_para_opcion_a"] is True


def test_diag_sustituye_por_navegador(client, isolate_resultados):
    """Un navegador se registra una sola vez, no se acumulan duplicados."""
    for util in (False, True):
        client.post("/api/diag", json={"navegador": "Brave", "util": util})
    client.post("/api/diag", json={"navegador": "Chrome", "util": True})

    registros = client.get("/api/diag").get_json()["registros"]
    nombres = [r["navegador"] for r in registros]
    assert sorted(nombres) == ["Brave", "Chrome"]
    brave = next(r for r in registros if r["navegador"] == "Brave")
    assert brave["util_para_opcion_a"] is True  # el ultimo gana


def test_diag_exige_navegador(client, isolate_resultados):
    r = client.post("/api/diag", json={"util": True})
    assert r.status_code == 400
    assert r.get_json()["error"] == "faltan_campos"


def test_report_webspeech_exige_campos(client):
    r = client.post("/api/report/webspeech", json={"hipotesis": "sin id"})
    assert r.status_code == 400
    assert r.get_json()["error"] == "faltan_campos"


def test_404_json(client):
    r = client.get("/ruta/que/no/existe")
    assert r.status_code == 404
    assert r.get_json()["error"] == "no_encontrado"


def test_index_sirve_la_interfaz(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"Speech" in r.data


# ------------------------------------------------------------ proveedor mock
def test_mock_siempre_disponible():
    from app.config import config

    t = MockTranscriber(config, latency_s=0.0)
    assert t.is_available() is True


def test_mock_se_declara_no_real(tmp_path):
    from app.config import config

    p = tmp_path / "a.wav"
    p.write_bytes(wav_en_memoria(0.1))
    res = MockTranscriber(config, latency_s=0.0).transcribe(p, "es-ES")
    assert res.is_fallback is True
    assert res.raw["not_a_real_transcription"] is True
    assert "MOCK" in res.text
