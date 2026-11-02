"""Modèles vocaux locaux : emplacement et téléchargement explicite (jamais pendant une question)."""

from __future__ import annotations

import logging
import shutil
import urllib.request
from pathlib import Path

from alicia.core.config import state_dir
from alicia.core.errors import AliciaError

log = logging.getLogger("alicia.audio")

KOKORO_RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1"
KOKORO_FILES = {"kokoro-v1.0.onnx": 300_000_000, "voices-v1.0.bin": 20_000_000}


def models_dir() -> Path:
    return state_dir() / "models"


def kokoro_paths() -> tuple[Path, Path]:
    folder = models_dir() / "kokoro"
    return folder / "kokoro-v1.0.onnx", folder / "voices-v1.0.bin"


def whisper_dir() -> Path:
    return models_dir() / "whisper"


def kokoro_ready() -> bool:
    return all(
        path.is_file() and path.stat().st_size > KOKORO_FILES[path.name] for path in kokoro_paths()
    )


def download_kokoro(progress=print) -> None:  # type: ignore[no-untyped-def]
    for path in kokoro_paths():
        if path.is_file() and path.stat().st_size > KOKORO_FILES[path.name]:
            progress(f"{path.name} déjà présent")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        url = f"{KOKORO_RELEASE}/{path.name}"
        progress(f"Téléchargement de {path.name} ({KOKORO_FILES[path.name] // 1_000_000} Mo+)…")
        temporary = path.with_suffix(path.suffix + ".part")
        try:
            with urllib.request.urlopen(url, timeout=60) as response, temporary.open("wb") as out:
                shutil.copyfileobj(response, out, length=1 << 20)
        except OSError as exc:
            raise AliciaError(
                f"Téléchargement de la voix Kokoro impossible ({path.name}).", detail=repr(exc)
            ) from exc
        temporary.replace(path)
        log.info("Modèle Kokoro téléchargé : %s", path)


def download_whisper(model: str, progress=print) -> None:  # type: ignore[no-untyped-def]
    """Télécharge le modèle Whisper (Hugging Face) en le chargeant une première fois."""
    from alicia.core.audio.stt import LocalTranscriber

    progress(
        f"Préparation du modèle Whisper « {model} » (première fois : plusieurs centaines de Mo)…"
    )
    LocalTranscriber(model).load()
