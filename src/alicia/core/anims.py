"""Animations des robots : un dossier par personnage, des fichiers nommés par état.

%LOCALAPPDATA%\\Alicia\\anims\\viirus\\  (et ...\\anims\\alicia\\ pour ALICIA)

- États (en boucle) : idle, listening, thinking, speaking, action, error
- Gestes (une fois) : wake, nod, shake, hop, spin, wiggle, look
- Bouche synchronisée sur la voix (facultatif) : speaking_0.png, speaking_1.png, speaking_2.png
- Portrait de remplacement (facultatif) : portrait.png

Formats : .webp animé ou .gif (rond de l'appli et OBS), .png fixe ; .webm seulement pour OBS.
"""

from __future__ import annotations

from pathlib import Path

from alicia.core.config import state_dir

STATES = ("idle", "listening", "thinking", "speaking", "action", "error")
GESTURES = ("wake", "nod", "shake", "hop", "spin", "wiggle", "look")
APP_FORMATS = (".webp", ".gif", ".png")
OVERLAY_FORMATS = (".webm", ".webp", ".gif", ".png", ".mp4")
LIPS = ("speaking_0.png", "speaking_1.png", "speaking_2.png")


def folder_name(persona) -> str:  # type: ignore[no-untyped-def]
    """« viirus » pour VIIRUS, « alicia » pour ALICIA (le nom affiché, en minuscules)."""
    return persona.title.casefold()


def anim_dir(persona=None) -> Path:  # type: ignore[no-untyped-def]
    from alicia.core.persona import current

    return state_dir() / "anims" / folder_name(persona or current())


def find(name: str, folder: Path, formats: tuple[str, ...] = APP_FORMATS) -> Path | None:
    for ext in formats:
        path = folder / f"{name}{ext}"
        if path.is_file():
            return path
    return None


def lip_frames(folder: Path) -> list[Path]:
    """Images de bouche (fermée, ouverte, grande ouverte) : au moins les deux premières."""
    frames = [folder / name for name in LIPS if (folder / name).is_file()]
    return frames if len(frames) >= 2 and frames[0].name == LIPS[0] else []


def inventory(folder: Path) -> dict[str, str]:
    """Ce qui a été trouvé : {nom : fichier} (pour l'écran des réglages)."""
    found: dict[str, str] = {}
    for name in (*STATES, *GESTURES, "portrait"):
        path = find(name, folder, OVERLAY_FORMATS)
        if path is not None:
            found[name] = path.name
    if lip_frames(folder):
        found["bouche"] = ", ".join(p.name for p in lip_frames(folder))
    return found
