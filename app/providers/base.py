"""
Contrato comun de todos los motores de transcripcion.

La API de Flask no conoce el motor concreto: pide un `Transcriber` y recibe
un `TranscriptionResult`. Anadir un motor nuevo (por ejemplo Whisper local o
Azure Speech) no obliga a tocar ni las rutas ni la vista HTML.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


@dataclass
class TranscriptionResult:
    """Respuesta normalizada de cualquier motor de transcripcion."""

    text: str
    provider: str
    model: str
    language: str
    duration_ms: int
    is_fallback: bool = False
    confidence: float | None = None
    warning: str | None = None
    error: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        data = asdict(self)
        return data


class Transcriber(abc.ABC):
    """Interfaz de un motor de transcripcion."""

    #: Identificador corto que se expone en la API (p. ej. "gemini").
    name: str = "abstract"

    @abc.abstractmethod
    def is_available(self) -> bool:
        """True si el motor puede ejecutarse ahora mismo."""

    @abc.abstractmethod
    def transcribe(self, audio_path: Path, language: str) -> TranscriptionResult:
        """Transcribe un fichero de audio y devuelve el resultado."""

    # -- Utilidades compartidas ------------------------------------------
    @staticmethod
    def measure_ms(audio_path: Path) -> int:
        from app import audio_utils

        meta = audio_utils.read_wav_metadata(audio_path) or {}
        duration = meta.get("duration_s")
        return int(duration * 1000) if duration else 0

    def unavailable_reason(self) -> str | None:
        """Motivo por el que el motor no esta disponible, o None si lo esta."""
        return None


class TranscriptionUnavailable(RuntimeError):
    """El motor no puede ejecutar la transcribe (config o indisponibilidad)."""
