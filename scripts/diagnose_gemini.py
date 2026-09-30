#!/usr/bin/env python
"""
diagnose_gemini.py
==================
Diagnostico paso a paso de la conexion con Gemini. Pensado para depurar
rapidamente por que una transcripcion falla, separando cada causa posible:

    1. ¿La API key esta presente y tiene formato valido?
    2. ¿Se alcanza el endpoint por HTTPS?
    3. ¿La key es aceptada?              -> GET  /v1beta/models
    4. ¿El modelo existe y admite audio? -> GET  /v1beta/models/{modelo}
    5. ¿La transcripcion devuelve texto?  -> POST :generateContent con audio

Uso:
    python scripts/diagnose_gemini.py
    python scripts/diagnose_gemini.py --model gemini-3.5-transcribe
    python scripts/diagnose_gemini.py --audio audios/audio1_frase_corta.wav

La clave NUNCA se imprime: solo su formato y los ultimos 4 caracteres.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Modelos dedicados a transcripcion, por orden de preferencia.
MODELOS_SUGERIDOS = ["gemini-3.5-transcribe", "gemini-3.8-flash", "gemini-2.5-flash"]

BASE = "https://generativelanguage.googleapis.com/v1beta"


def ok(msg: str) -> None:
    print(f"  \033[32m[OK]\033[0m    {msg}")


def fail(msg: str) -> None:
    print(f"  \033[31m[FAIL]\033[0m  {msg}")


def warn(msg: str) -> None:
    print(f"  \033[33m[WARN]\033[0m  {msg}")


def step(n: int, title: str) -> None:
    print(f"\n\033[1m[{n}] {title}\033[0m")


def mask(key: str) -> str:
    if len(key) <= 8:
        return "*(demasiado corta)"
    return f"{key[:6]}...{key[-4:]}  (longitud {len(key)})"


def load_key() -> str:
    """Busca la clave en el entorno o en los .env habituales."""
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if key:
        return key
    for candidate in (ROOT / ".env", Path.home() / ".env"):
        if candidate.is_file():
            for line in candidate.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("GEMINI_API_KEY"):
                    return line.split("=", 1)[1].strip().strip("'\"")
    return ""


def http(method: str, url: str, key: str, body: dict | None = None, timeout: int = 60):
    """Peticion HTTP minima (sin dependencias) para aislar la capa de red."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("x-goog-api-key", key)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw or "{}")
        except json.JSONDecodeError:
            return e.code, {"raw": raw}
    except urllib.error.URLError as e:
        return 0, {"error": {"message": f"No se pudo abrir la conexion: {e.reason}"}}


def main() -> int:
    ap = argparse.ArgumentParser(description="Diagnostico de la conexion con Gemini.")
    ap.add_argument("--model", default=os.getenv("GEMINI_MODEL", ""), help="Modelo a probar.")
    ap.add_argument("--audio", default="audios/audio1_frase_corta.wav")
    args = ap.parse_args()

    print("=" * 66)
    print(" DIAGNOSTICO GEMINI  |  ASIX Speech-to-Text")
    print("=" * 66)

    # -- 1 ---------------------------------------------------------------
    step(1, "Credenciales")
    key = load_key()
    if not key:
        fail("No se encontro GEMINI_API_KEY en el entorno ni en .env")
        print("\n    Como conseguirla: https://aistudio.google.com/apikey")
        return 1
    ok(f"Clave encontrada: {mask(key)}")
    if re.fullmatch(r"AIza[0-9A-Za-z_-]{35}", key):
        ok("Formato con pinta de API key de Google AI Studio (AIza...)")
    else:
        warn("El formato NO es el habitual de AI Studio (AIza...), pero puede ser valida.")

    # -- 2 ---------------------------------------------------------------
    step(2, "Conectividad HTTPS")
    status, payload = http("GET", f"{BASE}/models?pageSize=1", key, timeout=20)
    if status == 0:
        fail(f"Sin conectividad: {payload.get('error', {}).get('message')}")
        print("\n    Revisa la conexion a internet o un proxy corporativo.")
        return 1
    ok(f"El endpoint responde (HTTP {status}). Se alcanza generativelanguage.googleapis.com")

    # -- 3 ---------------------------------------------------------------
    step(3, "Credenciales aceptadas por Google")
    if status == 200:
        ok("La API key es valida y el proyecto tiene acceso.")
    elif status in (400, 401, 403):
        fail(f"HTTP {status}: Google rechaza la credencial.")
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        print("\n    Causas: key caducada, cuota de facturacion cerrada o API no habilitada.")
        return 1
    else:
        fail(f"HTTP inesperado {status}")
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 1

    # -- 4 ---------------------------------------------------------------
    step(4, "Modelo y soporte de audio")
    status, listing = http("GET", f"{BASE}/models?pageSize=200", key, timeout=30)
    disponibles = sorted(
        m["name"].replace("models/", "") for m in listing.get("models", [])
    )
    candidatos = [args.model] if args.model else MODELOS_SUGERIDOS
    elegido = None
    for cand in candidatos:
        if cand in disponibles:
            elegido = cand
            ok(f"Modelo '{cand}' existe.")
            break
        warn(f"Modelo '{cand}' NO existe en tu proyecto.")
    if elegido is None:
        fail(f"Ninguno de {candidatos} esta disponible.")
        print("\n    Modelos con soporte de audio que si existen:")
        for n in disponibles:
            if "transcribe" in n or "flash" in n or "omni" in n:
                print(f"      - {n}")
        return 1

    status, info = http("GET", f"{BASE}/models/{elegido}", key, timeout=30)
    if status == 200:
        metodos = info.get("supportedGenerationMethods", [])
        if "generateContent" in metodos:
            ok(f"Soporta generateContent. Metodos: {', '.join(metodos)}")
        else:
            warn(f"No declara generateContent. Metodos: {', '.join(metodos) or 'desconocidos'}")

    # -- 5 ---------------------------------------------------------------
    step(5, "Transcripcion real")
    audio_path = ROOT / args.audio
    if not audio_path.is_file():
        fail(f"No existe el audio {audio_path}")
        print("    Genera los audios con: ./scripts/generate_audios.sh")
        return 1

    data = base64.b64encode(audio_path.read_bytes()).decode()
    body = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"inline_data": {"mime_type": "audio/wav", "data": data}},
                    {"text": "Transcribe exactamente el audio, sin commentary."},
                ],
            }
        ],
        "generationConfig": {"temperature": 0},
    }
    print(f"  Enviando {audio_path.name} ({audio_path.stat().st_size / 1024:.0f} KB) "
          f"a {elegido}...")
    status, resp = http("POST", f"{BASE}/models/{elegido}:generateContent", key, body)

    if status != 200:
        fail(f"HTTP {status}")
        print(json.dumps(resp, indent=2, ensure_ascii=False)[:1200])
        return 1

    try:
        texto = resp["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        print(json.dumps(resp, indent=2, ensure_ascii=False)[:1200])
        fail("La respuesta no contiene texto en candidates[0].content.parts[0].")
        return 1

    ok("Transcripcion recibida:")
    print(f"\n      >>> {texto.strip()}\n")

    print("=" * 66)
    print(f" RESULTADO: GEMINI FUNCIONA con el modelo '{elegido}'.")
    print(f" Copia esta linea a tu .env:  GEMINI_MODEL={elegido}")
    print("=" * 66)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
