"""
Configuracion de la aplicacion.

Todas las variables se leen del entorno y pueden fijarse en un fichero `.env`.
Este modulo no importa nada de Flask: la configuracion es independiente del
framework, lo que permite reutilizarla desde scripts de linea de comandos.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env_files() -> list[Path]:
    """
    Carga las variables de entorno desde dos ficheros, en este orden:

        1. ~/.env   -> credenciales personales ya configuradas en el equipo
        2. <proyecto>/.env -> tiene prioridad sobre el anterior

    Asi el proyecto funciona sin copiar la API key a ningun fichero del
    repositorio, pero sigue permitiendo un .env propio por equipo.
    """
    cargados: list[Path] = []
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - dotenv es opcional
        return cargados

    home_env = Path.home() / ".env"
    if home_env.is_file():
        load_dotenv(home_env, override=False)
        cargados.append(home_env)

    project_env = BASE_DIR / ".env"
    if project_env.is_file():
        load_dotenv(project_env, override=True)
        cargados.append(project_env)

    return cargados


ENV_FILES_LOADED = _load_env_files()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "si", "sí", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    try:
        return int(raw) if raw is not None else default
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Config:
    """Parametros de ejecucion del servicio de transcripcion."""

    # --- Servidor HTTP -----------------------------------------------------
    host: str = field(default_factory=lambda: os.getenv("STT_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: _env_int("STT_PORT", 5000))
    debug: bool = field(default_factory=lambda: _env_bool("STT_DEBUG", True))

    # --- Gemini ------------------------------------------------------------
    gemini_api_key: str = field(
        default_factory=lambda: os.getenv("GEMINI_API_KEY", "").strip()
    )
    gemini_model: str = field(
        default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
    )
    gemini_timeout_s: int = field(default_factory=lambda: _env_int("GEMINI_TIMEOUT_S", 60))
    #: Si True, ante cualquier fallo de Gemini se cae al proveedor simulado.
    allow_mock_fallback: bool = field(
        default_factory=lambda: _env_bool("STT_ALLOW_MOCK_FALLBACK", True)
    )

    # --- Validacion de audio ----------------------------------------------
    max_upload_mb: int = field(default_factory=lambda: _env_int("STT_MAX_UPLOAD_MB", 25))
    allowed_extensions: tuple = (".wav", ".mp3", ".m4a", ".ogg", ".webm", ".flac")
    default_language: str = field(
        default_factory=lambda: os.getenv("STT_DEFAULT_LANG", "es-ES")
    )

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def has_gemini_key(self) -> bool:
        return bool(self.gemini_api_key)

    def summary(self) -> dict:
        """Estado de la configuracion, sin filtrar el valor de la API key."""
        return {
            "gemini_api_key_configurada": self.has_gemini_key,
            "gemini_model": self.gemini_model,
            "gemini_timeout_s": self.gemini_timeout_s,
            "allow_mock_fallback": self.allow_mock_fallback,
            "max_upload_mb": self.max_upload_mb,
            "allowed_extensions": list(self.allowed_extensions),
            "default_language": self.default_language,
            "ficheros_env_cargados": [str(p) for p in ENV_FILES_LOADED],
        }


config = Config()
