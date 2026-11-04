"""Personnalité d'un profil, écrite librement dans un fichier .md (ton, humour, façon de parler).

Chaque profil a la sienne : %APPDATA%\\Alicia\\personnalite-<profil>.md (ex. personnalite-alicia.md).
Elle s'ajoute aux consignes du programme sans les remplacer : ne jamais jouer à la place du
joueur, actions sur le PC seulement depuis le catalogue avec confirmation, honnêteté sur ce
qui est visible. Elle reste sur ce PC (jamais envoyée sur GitHub).

Deux modes (personality_mode) : « normal » et « dechaine », changés à la voix (« mode
déchaîné », « lâche-toi » / « mode normal », « calme-toi ») ou dans Profil. Le mode
déchaîné a son propre fichier (personnalite-<profil>-dechaine.md) ; sans fichier, une
consigne de base le décrit. Dans les deux modes, les règles du programme restent
prioritaires (tout public, pas d'insulte, jamais jouer à la place du joueur…).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from alicia.core.config import data_dir

log = logging.getLogger("alicia.app")

MAX_CHARS = 12_000  # au-delà, chaque réponse devient lente et chère
_cache: dict[str, tuple[float, str]] = {}


MODES = ("normal", "dechaine")
MODE_LABELS = {"normal": "Normal", "dechaine": "Déchaîné 🔥"}
DECHAINE_DEFAULT = (
    "Tu passes en MODE DÉCHAÎNÉ : beaucoup plus d'énergie et d'exubérance, réactions "
    "exagérées et théâtrales, onomatopées, vannes et sarcasme, tu taquines ton joueur et "
    "tu le chambres sur ses actions (trash-talk complice, jamais méchant), tu t'enflammes "
    "sur les belles actions. Tu restes toi-même et utile : les conseils restent justes."
)
DECHAINE_LIMITS = (
    "Même déchaîné : aucune insulte, aucune grossièreté forte, rien de blessant, de "
    "haineux, de sexuel ou de romantique, tout public (surtout en live), et les consignes "
    "du joueur restent prioritaires."
)


def personality_file(key: str, mode: str = "normal") -> Path:
    suffix = "-dechaine" if mode == "dechaine" else ""
    return data_dir() / f"personnalite-{key}{suffix}.md"


def _mode_file() -> Path:
    return data_dir() / "personnalite-mode.txt"


def mode() -> str:
    """Le mode de personnalité en cours : « normal » ou « dechaine » (gardé au redémarrage)."""
    try:
        value = _mode_file().read_text("utf-8").strip()
    except OSError:
        return "normal"
    return value if value in MODES else "normal"


def set_mode(value: str) -> str:
    value = value if value in MODES else "normal"
    try:
        path = _mode_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
    except OSError as exc:
        log.warning("Mode de personnalité non enregistré : %r", exc)
    log.info("Personnalité : mode %s", value)
    return value


def _plain(text: str) -> str:
    import unicodedata

    text = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in text if not unicodedata.combining(c)).replace("’", "'")


_WILD = re.compile(
    r"\b(?:mode\s+(?:dechaine|fou|folie|delire|enerve|hype)|dechaine[- ]toi|"
    r"lache[- ]toi|lache[- ]les\s+chevaux|passe\s+en\s+(?:mode\s+)?dechaine|"
    r"active\s+(?:le\s+)?mode\s+dechaine|sois\s+dechaine)"
)
_CALM = re.compile(
    r"\b(?:mode\s+(?:normal|calme|sage|classique)|calme[- ]toi|redeviens\s+normal|"
    r"reviens\s+(?:en\s+)?(?:mode\s+)?normal|(?:desactive|coupe|arrete)\s+(?:le\s+)?"
    r"mode\s+dechaine|sois\s+(?:sage|normal))"
)


def parse_mode_command(text: str) -> str | None:
    """« Mode déchaîné », « lâche-toi » → « dechaine » ; « mode normal », « calme-toi »
    → « normal » ; sinon None (phrase courte seulement : pas au milieu d'une question)."""
    plain = re.sub(r"[^\w' -]", " ", _plain(text))
    if len(plain.split()) > 10:
        return None
    if _CALM.search(plain):
        return "normal"
    if _WILD.search(plain):
        return "dechaine"
    return None


def clean(text: str) -> str:
    """Retire les notes pour les humains (« À régler séparément »…) et limite la taille."""
    text = text.replace("\r\n", "\n").strip()
    text = re.sub(r"(?ims)^#{1,3}\s*(?:à|a) régler séparément.*?(?=^#{1,2}\s|\Z)", "", text).strip()
    return text[:MAX_CHARS]


def load(key: str, which: str = "normal") -> str:
    """Le texte de la personnalité du profil pour ce mode (vide s'il n'y en a pas)."""
    path = personality_file(key, which)
    cache_key = f"{key}:{which}"
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return ""
    cached = _cache.get(cache_key)
    if cached and cached[0] == stamp:
        return cached[1]
    try:
        text = clean(path.read_text("utf-8-sig"))
    except (OSError, UnicodeDecodeError) as exc:
        log.warning("Personnalité illisible (%s) : %r", path, exc)
        return ""
    _cache[cache_key] = (stamp, text)
    return text


def wild_text(key: str) -> str:
    """La personnalité déchaînée : son fichier, sinon la consigne de base."""
    return load(key, "dechaine") or DECHAINE_DEFAULT


def install(key: str, source: Path, which: str = "normal") -> Path:
    """Copie un .md choisi par le joueur comme personnalité du profil (pour ce mode)."""
    text = source.read_text("utf-8-sig")
    target = personality_file(key, which)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    _cache.pop(f"{key}:{which}", None)
    log.info("Personnalité %s du profil %s : %s (%d car.)", which, key, source.name, len(text))
    return target


def remove(key: str, which: str = "normal") -> None:
    try:
        personality_file(key, which).unlink()
    except OSError:
        pass
    _cache.pop(f"{key}:{which}", None)
