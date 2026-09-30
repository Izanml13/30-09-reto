"""
Proveedor simulado (fallback).

AVISO IMPORTANTE
---------------
Este proveedor NO hace reconocimiento de voz. No analiza el audio: devuelve
un texto de cortesia claramente etiquetado. Su unica funcion es permitir que
el endpoint, la interfaz y las pruebas se ejecuten de extremo a extremo cuando
no hay credencial de Gemini disponible.

Por eso toda respuesta incluye:
  * `provider: "mock"`  -> identifica el motor en la respuesta de la API
  * `is_fallback: true` -> indica que no es el motor solicitado
  * `warning`           -> explica al usuario lo que esta pasando

Nunca se debe medir precision con este proveedor: un texto fijo da siempre un
WER del 100 %, lo que falsearia la comparativa del reto.
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

from app.config import Config
from app.providers.base import Transcriber, TranscriptionResult

WARNING = (
    "Transcripcion SIMULADA: no se ha analizado el audio porque el proveedor "
    "real (Gemini) no esta disponible. Configura GEMINI_API_KEY para obtener "
    "texto real. No uses esta respuesta para medir precision."
)

TEXTO_MOCK = (
    "[MOCK] Transcripcion simulada del servicio de prueba. "
    "Configure GEMINI_API_KEY para transcribir el audio real."
)


class MockTranscriber(Transcriber):
    """Motor de reserva: siempre disponible, nunca un motor de verdad."""

    name = "mock"

    def __init__(self, config: Config, latency_s: float = 0.35):
        self.config = config
        self.latency_s = latency_s

    def is_available(self) -> bool:
        return True

    def transcribe(self, audio_path: Path, language: str) -> TranscriptionResult:
        started = time.perf_counter()
        # Latencia artificial para que la interfaz se parezca a un motor real.
        time.sleep(self.latency_s)

        digest = hashlib.sha256(audio_path.read_bytes()).hexdigest()[:12]
        elapsed_ms = int((time.perf_counter() - started) * 1000)

        return TranscriptionResult(
            text=TEXTO_MOCK,
            provider=self.name,
            model="simulado-v1",
            language=language,
            duration_ms=elapsed_ms,
            is_fallback=True,
            warning=WARNING,
            raw={"audio_sha256_12": digest, "not_a_real_transcription": True},
        )
