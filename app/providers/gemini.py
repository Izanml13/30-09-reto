"""
Proveedor real: Gemini (Google Generative AI).

Flujo de red del backend hacia Google:
    Flask (cliente HTTP)
      -> HTTPS/TLS 443
      -> generativelanguage.googleapis.com
           POST /v1beta/models/{modelo}:generateContent
           Cabecera: x-goog-api-key: <API_KEY>
           Cuerpo:   contents[].parts[].inline_data{mime_type, data(base64)}

La clave viaja en la cabecera `x-goog-api-key`, nunca en la URL, para que no
quede escrita en los logs de acceso del servidor.
"""
from __future__ import annotations

import base64
import time
from pathlib import Path

from app.config import Config
from app.providers.base import (
    Transcriber,
    TranscriptionResult,
    TranscriptionUnavailable,
)

# Subconjunto de mimetypes que acepta el endpoint de audio de Gemini.
MIME_BY_EXT = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".ogg": "audio/ogg",
    ".webm": "audio/webm",
    ".flac": "audio/flac",
}

PROMPT = (
    "Eres un motor de transcripcion de audio. Transcribe EXACTAMENTE lo que se "
    "oye en la grabacion, sin parafrasear, sin corregir, sin anadir commentary y "
    "sin acentos que no esten en el original. Mantiene la puntuacion natural del "
    "habla y escribe los numeros como se pronuncian. Si el audio esta en "
    "silencio o no contiene voz, responde unicamente con la cadena vacia."
)


class GeminiTranscriber(Transcriber):
    """Transcripcion por lotes usando el modelo multimodal de Gemini."""

    name = "gemini"

    def __init__(self, config: Config):
        self.config = config
        self._client = None
        self._init_error: str | None = None

    # -- Disponibilidad ----------------------------------------------------
    def is_available(self) -> bool:
        return self.config.has_gemini_key and self._init_error is None

    def unavailable_reason(self) -> str | None:
        if not self.config.has_gemini_key:
            return (
                "GEMINI_API_KEY no esta definida. Exporta la clave en el entorno "
                "o en el fichero .env (ver .env.example)."
            )
        return self._init_error

    def _get_client(self):
        """Crea el cliente de google-genapi de forma perezosa."""
        if self._client is not None:
            return self._client
        try:
            from google import genai
        except ImportError as exc:  # pragma: no cover
            self._init_error = f"SDK 'google-genai' no instalado: {exc}"
            raise TranscriptionUnavailable(self._init_error) from exc

        try:
            self._client = genai.Client(api_key=self.config.gemini_api_key)
        except Exception as exc:
            self._init_error = f"No se pudo crear el cliente de Gemini: {exc}"
            raise TranscriptionUnavailable(self._init_error) from exc
        return self._client

    # -- Transcripcion -----------------------------------------------------
    def transcribe(self, audio_path: Path, language: str) -> TranscriptionResult:
        started = time.perf_counter()
        client = self._get_client()

        mime = MIME_BY_EXT.get(audio_path.suffix.lower())
        if mime is None:
            mime = "audio/wav" if self._is_wav(audio_path) else "application/octet-stream"

        with audio_path.open("rb") as fh:
            b64 = base64.b64encode(fh.read()).decode("ascii")

        contents = [
            {
                "role": "user",
                "parts": [
                    {"inline_data": {"mime_type": mime, "data": b64}},
                    {"text": f"{PROMPT}\n\nIdioma esperado del audio: {language}."},
                ],
            }
        ]

        try:
            response = client.models.generate_content(
                model=self.config.gemini_model,
                contents=contents,
                config={
                    "temperature": 0.0,
                    "max_output_tokens": 2048,
                    "http_options": {"timeout": self.config.gemini_timeout_s * 1000},
                },
            )
        except Exception as exc:
            raise TranscriptionUnavailable(self._describe_error(exc)) from exc

        text = (getattr(response, "text", "") or "").strip()
        elapsed_ms = int((time.perf_counter() - started) * 1000)

        usage = getattr(response, "usage_metadata", None)
        raw = {
            "model_version": getattr(response, "model_version", None),
            "finish_reason": str(getattr(response, "finish_reason", "") or ""),
            "input_tokens": getattr(usage, "prompt_token_count", None),
            "output_tokens": getattr(usage, "candidates_token_count", None),
            "audio_bytes_b64": len(b64),
        }

        if not text:
            return TranscriptionResult(
                text="",
                provider=self.name,
                model=self.config.gemini_model,
                language=language,
                duration_ms=elapsed_ms,
                warning="Gemini devio una respuesta vacia.",
                raw=raw,
            )

        return TranscriptionResult(
            text=text,
            provider=self.name,
            model=self.config.gemini_model,
            language=language,
            duration_ms=elapsed_ms,
            raw=raw,
        )

    # -- Utilidades --------------------------------------------------------
    @staticmethod
    def _is_wav(path: Path) -> bool:
        from app import audio_utils

        return audio_utils.is_wav(path)

    @staticmethod
    def _describe_error(exc: Exception) -> str:
        """Convierte la excepcion de la SDK en un mensaje accionable."""
        name = type(exc).__name__
        msg = str(exc)
        hay_clave = any(k in msg for k in ("API key", "api_key", "API_KEY", "PERMISSION_DENIED"))
        if hay_clave or "403" in msg:
            return (
                f"Gemini rechazo la credencial ({name}): {msg}. "
                "Revisa que GEMINI_API_KEY sea valida y que el modelo este "
                "habilitado en el proyecto de Google Cloud."
            )
        if "404" in msg or "NOT_FOUND" in msg:
            return (
                f"El modelo '{msg}' no existe o no esta disponible en tu "
                "proyecto. Prueba con GEMINI_MODEL=gemini-2.5-flash."
            )
        if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
            return f"Limite de peticiones de Gemini alcanzado (cuota): {msg}"
        if "timeout" in msg.lower() or "Deadline" in msg:
            return f"Tiempo de espera agotado hablando con Gemini: {msg}"
        return f"Fallo la llamada a Gemini ({name}): {msg}"
