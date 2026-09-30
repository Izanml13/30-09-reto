"""
Registro de proveedores de transcripcion.

La app pide un proveedor por nombre (`"gemini"` o `"mock"`). Este modulo es
el unico que conoce las clases concretas: anadir un motor nuevo se reduce a
una entrada en el diccionario.
"""
from __future__ import annotations

from app.config import Config
from app.providers.base import (
    Transcriber,
    TranscriptionResult,
    TranscriptionUnavailable,
)
from app.providers.gemini import GeminiTranscriber
from app.providers.mock import MockTranscriber

FACTORIES = {
    "gemini": GeminiTranscriber,
    "mock": MockTranscriber,
}


def build(name: str, config: Config) -> Transcriber:
    """Instancia el proveedor pedido por su identificador."""
    try:
        factory = FACTORIES[name]
    except KeyError as exc:
        raise KeyError(
            f"Proveedor '{name}' desconocido. Disponibles: {', '.join(FACTORIES)}"
        ) from exc
    return factory(config)


def build_with_fallback(name: str, config: Config) -> tuple[Transcriber, bool]:
    """
    Devuelve (proveedor, usando_fallback).

    Solo cae al proveedor simulado cuando el proveedor pedido existe pero no
    esta operativo (sin credencial, o falla en caliente).

    Un nombre de proveedor desconocido SIEMPRE es un error: si no, una
    errata en el cliente devolveria 200 con una transcripcion simulada en
    lugar de un 400, que es justo lo que este servicio debe evitar.
    """
    provider = build(name, config)  # propaga KeyError

    if not provider.is_available():
        if not config.allow_mock_fallback:
            raise TranscriptionUnavailable(provider.unavailable_reason() or "no disponible")
        return MockTranscriber(config), True

    return provider, False


__all__ = [
    "FACTORIES",
    "Transcriber",
    "TranscriptionResult",
    "TranscriptionUnavailable",
    "GeminiTranscriber",
    "MockTranscriber",
    "build",
    "build_with_fallback",
]
