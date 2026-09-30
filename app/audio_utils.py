"""
Utilidades de audio: validacion de la subida, deteccion de formato y
normalizacion a WAV PCM 16 kHz mono.

Por que normalizar
-----------------
El endpoint de audio de Gemini espera audio legible (PCM/WAV) y funciona mejor
a 16 kHz mono. Los navegadores y microfonos entregan formatos dispares
(webm/opus en Chrome, m4a/aac en Safari). `afconvert` (incluido de serie en
macOS) permite convertir sin depender de ffmpeg.
"""
from __future__ import annotations

import shutil
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path

TARGET_RATE = 16000
TARGET_CHANNELS = 1


class AudioError(ValueError):
    """Error de validacion o de conversion de audio."""


@dataclass
class AudioInfo:
    """Metadatos del audio recibido."""

    filename: str
    size_bytes: int
    path: Path
    mime_type: str = "application/octet-stream"
    duration_s: float | None = None
    sample_rate: int | None = None
    channels: int | None = None
    sample_width: int | None = None
    format_name: str | None = None
    converted: bool = False

    def to_dict(self) -> dict:
        return {
            "filename": self.filename,
            "size_bytes": self.size_bytes,
            "mime_type": self.mime_type,
            "duration_s": round(self.duration_s, 3) if self.duration_s else None,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "format_name": self.format_name,
            "normalizado_a_wav_16k_mono": self.converted,
        }


def validate_extension(filename: str, allowed: tuple) -> str:
    """Comprueba la extension y devuelve la extension en minusculas."""
    ext = Path(filename).suffix.lower()
    if not ext:
        raise AudioError(
            f"El fichero '{filename}' no tiene extension. "
            f"Formatos admitidos: {', '.join(allowed)}"
        )
    if ext not in allowed:
        raise AudioError(
            f"Formato '{ext}' no admitido. Se aceptan: {', '.join(allowed)}"
        )
    return ext


def is_wav(path: Path) -> bool:
    """
    Deteccion de WAV por firma RIFF (no por extension).

    Cabecera WAV estandar (little-endian), 12 bytes minimos:
        offset  0..3   'RIFF'
        offset  4..7   tamano del fichero menos 8   <- NO es 'WAVE'
        offset  8..11  'WAVE'
    """
    try:
        with path.open("rb") as fh:
            cabecera = fh.read(12)
    except OSError:
        return False
    return len(cabecera) >= 12 and cabecera[0:4] == b"RIFF" and cabecera[8:12] == b"WAVE"


def read_wav_metadata(path: Path) -> dict | None:
    """Extrae duracion/frecuencia/canales de un WAV legible por el modulo `wave`."""
    if not is_wav(path):
        return None
    try:
        with wave.open(str(path), "rb") as wav:
            frames = wav.getnframes()
            rate = wav.getframerate() or 1
            return {
                "duration_s": frames / rate,
                "sample_rate": rate,
                "channels": wav.getnchannels(),
                "sample_width": wav.getsampwidth(),
                "format_name": "WAV PCM",
            }
    except (wave.Error, OSError):
        return None


def has_afconvert() -> bool:
    return shutil.which("afconvert") is not None


def to_wav_16k_mono(src: Path, dest: Path) -> bool:
    """
    Convierte `src` a WAV PCM 16-bit mono 16 kHz usando afconvert.
    Devuelve True si la conversion se realizo, False si no era necesario.
    """
    meta = read_wav_metadata(src)
    if (
        meta
        and meta["sample_rate"] == TARGET_RATE
        and meta["channels"] == TARGET_CHANNELS
    ):
        return False

    if not has_afconvert():
        raise AudioError(
            "El audio no esta en WAV 16 kHz mono y 'afconvert' no esta "
            "disponible en el sistema. Reexporta el audio como WAV 16 kHz mono."
        )

    cmd = [
        "afconvert",
        "-f", "WAVE",
        "-d", f"LEI16@{TARGET_RATE}",
        "-c", str(TARGET_CHANNELS),
        str(src),
        str(dest),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired as exc:  # pragma: no cover
        raise AudioError("La conversion de audio excedio el tiempo maximo.") from exc

    if proc.returncode != 0 or not dest.exists():
        raise AudioError(
            "No se pudo convertir el audio a WAV 16 kHz mono: "
            f"{(proc.stderr or proc.stdout or '').strip()}"
        )
    return True


def prepare(
    src: Path,
    dest: Path,
    filename: str,
    size_bytes: int,
    mime_type: str = "application/octet-stream",
) -> AudioInfo:
    """
    Pipeline de entrada: valida, normaliza y devuelve los metadatos del audio.
    Es el unico punto del backend que decide como se prepara el fichero.
    """
    info = AudioInfo(
        filename=filename,
        size_bytes=size_bytes,
        path=src,
        mime_type=mime_type,
    )

    if size_bytes == 0:
        raise AudioError("El fichero de audio esta vacio.")
    if is_wav(src):
        meta = read_wav_metadata(src)
        if meta:
            info.duration_s = meta["duration_s"]
            info.sample_rate = meta["sample_rate"]
            info.channels = meta["channels"]
            info.sample_width = meta["sample_width"]
            info.format_name = meta["format_name"]
        info.converted = to_wav_16k_mono(src, dest)
        info.path = dest if info.converted else src
    else:
        info.format_name = Path(filename).suffix.lstrip(".").upper() or "desconocido"
        info.converted = True
        if to_wav_16k_mono(src, dest):
            info.path = dest
            meta = read_wav_metadata(dest)
            if meta:
                info.duration_s = meta["duration_s"]
                info.sample_rate = meta["sample_rate"]
                info.channels = meta["channels"]
                info.format_name = f"{info.format_name} -> WAV PCM"

    return info
