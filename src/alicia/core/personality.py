"""Personnalité d'un profil, écrite librement dans un fichier .md (ton, humour, façon de parler).

Chaque profil a la sienne : %APPDATA%\\Alicia\\personnalite-<profil>.md (ex. personnalite-alicia.md).
Elle s'ajoute aux consignes du programme sans les remplacer : ne jamais jouer à la place du
joueur, actions sur le PC seulement depuis le catalogue avec confirmation, honnêteté sur ce
qui est visible. Elle reste sur ce PC (jamais envoyée sur GitHub).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from alicia.core.config import data_dir

log = logging.getLogger("alicia.app")

MAX_CHARS = 12_000  # au-delà, chaque réponse devient lente et chère
_cache: dict[str, tuple[float, str]] = {}


def personality_file(key: str) -> Path:
    return data_dir() / f"personnalite-{key}.md"


def clean(text: str) -> str:
    """Retire les notes pour les humains (« À régler séparément »…) et limite la taille."""
    text = text.replace("\r\n", "\n").strip()
    text = re.sub(r"(?ims)^#{1,3}\s*(?:à|a) régler séparément.*?(?=^#{1,2}\s|\Z)", "", text).strip()
    return text[:MAX_CHARS]


def load(key: str) -> str:
    """Le texte de la personnalité du profil (vide s'il n'y en a pas)."""
    path = personality_file(key)
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return ""
    cached = _cache.get(key)
    if cached and cached[0] == stamp:
        return cached[1]
    try:
        text = clean(path.read_text("utf-8-sig"))
    except (OSError, UnicodeDecodeError) as exc:
        log.warning("Personnalité illisible (%s) : %r", path, exc)
        return ""
    _cache[key] = (stamp, text)
    return text


def install(key: str, source: Path) -> Path:
    """Copie un .md choisi par le joueur comme personnalité du profil."""
    text = source.read_text("utf-8-sig")
    target = personality_file(key)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    _cache.pop(key, None)
    log.info("Personnalité du profil %s : %s (%d caractères)", key, source.name, len(text))
    return target


def remove(key: str) -> None:
    try:
        personality_file(key).unlink()
    except OSError:
        pass
    _cache.pop(key, None)
