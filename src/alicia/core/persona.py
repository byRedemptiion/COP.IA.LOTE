"""Personnages : le même programme, deux visages (ALICIA ou VIIRUS).

Chacun choisit le sien dans Réglages → Général (``[ui] persona`` dans alicia.toml) :
nom, mot de réveil, portrait, couleurs et voix changent ; le code et les mises à jour
restent communs. Le personnage est fixé au démarrage (changer = redémarrer).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Persona:
    key: str
    name: str  # « Alicia »
    title: str  # « ALICIA »
    wake_name: str  # forme normalisée, sans accent
    wake_forms: frozenset[str]
    portrait: str  # fichier dans alicia.assets
    icon: str
    # Zone du visage dans le portrait, pour le rond (x, y, largeur, hauteur en fractions).
    face_crop: tuple[float, float, float, float]
    identity: str  # première phrase du prompt système
    voice_engine: str  # moteur de voix proposé par défaut
    colors: dict[str, str] = field(default_factory=dict)
    states: dict[str, tuple[int, int, int]] = field(default_factory=dict)
    round_portrait: bool = False  # portrait déjà rond : même cadrage dans le panneau
    feminine: bool = True  # accords des textes (« elle » / « il »)


ALICIA = Persona(
    key="alicia",
    name="Alicia",
    title="ALICIA",
    wake_name="alicia",
    wake_forms=frozenset(
        {
            "alicia",
            "alissia",
            "alicya",
            "alisia",
            "alysia",
            "alycia",
            "allicia",
            "aliciaa",
            "elicia",
            "alice",
            "alisa",
        }
    ),
    portrait="alicia.png",
    icon="alicia.ico",
    face_crop=(0.2, 0.07, 0.58, 0.58),
    identity="Tu es Alicia, une copilote assise virtuellement à côté du joueur.",
    voice_engine="voixc",
)

# VIIRUS (ex-VERIS) : la clé interne reste « veris » pour garder les réglages de chacun.
VIIRUS = Persona(
    key="veris",
    name="Viirus",
    title="VIIRUS",
    wake_name="viirus",
    wake_forms=frozenset(
        {
            "viirus",
            "virus",
            "viruss",
            "virusse",
            "viruse",
            "vyrus",
            "vayrus",
            "vairus",
            "viros",
            "virusz",
            "veris",
            "verise",
            "verisse",
            "verice",
            "veriss",
            "verris",
            "vairis",
            "verys",
            "beris",
            "ferris",
            "feris",
            "veres",
        }
    ),
    portrait="veris.png",
    icon="veris.ico",
    face_crop=(0.06, 0.09, 0.9, 0.9),  # le cercle néon du médaillon
    identity=(
        "Tu es VIIRUS, un petit robot copilote assis virtuellement à côté du joueur "
        "(tu parles de toi au masculin)."
    ),
    voice_engine="veris",
    round_portrait=True,
    feminine=False,
    colors={
        "BG": "#07041c",
        "PANEL": "rgba(22, 12, 58, 0.74)",
        "BORDER": "#3a2a86",
        "CYAN": "#2da8ff",
        "CYAN_SOFT": "#8fd0ff",
        "PINK": "#7c4dff",
        "PINK_SOFT": "#b39dff",
        "RED": "#4a2bb8",
        "GOLD": "#5b9bff",
        "TEXT": "#eeeaff",
        "MUTED": "#8f86c4",
        "DEEP": "#0e0830",
        "GLOW": "#1c1060",
    },
    states={
        "idle": (124, 77, 255),
        "listening": (45, 168, 255),
        "observing": (0, 224, 150),
        "thinking": (179, 157, 255),
        "speaking": (150, 100, 255),
        "action": (91, 155, 255),
        "error": (255, 60, 90),
    },
)

VERIS = VIIRUS  # ancien nom, gardé pour le code existant
PERSONAS: dict[str, Persona] = {p.key: p for p in (ALICIA, VIIRUS)}
# Anciens noms ou noms tapés à la main → profil
_ALIASES = {"viirus": "veris", "virus": "veris"}
OLD_TITLES = {"VERIS": "VIIRUS"}  # un robot pas encore mis à jour s'annonce encore « VERIS »

_current: Persona = ALICIA


def current() -> Persona:
    return _current


def set_current(key: str) -> Persona:
    global _current
    key = (key or "").strip().lower()
    _current = PERSONAS.get(_ALIASES.get(key, key), ALICIA)
    return _current


# --- le joueur : son prénom écrit et comment le prononcer ---------------------------------


@dataclass
class Player:
    name: str = ""  # écrit : « Redemptiion »
    phonetic: str = ""  # dit : « Rédemm-chionne » (laisse vide si la voix le dit bien)


_player = Player()
_pronunciations: dict[str, str] = {}  # nom écrit → prononciation (toi, le pote…)


def player() -> Player:
    return _player


def set_player(name: str, phonetic: str = "") -> Player:
    global _player
    _player = Player(name.strip()[:40], phonetic.strip()[:60])
    register_pronunciation(_player.name, _player.phonetic)
    return _player


def register_pronunciation(written: str, spoken: str) -> None:
    written, spoken = written.strip(), spoken.strip()
    if written and spoken and written.casefold() != spoken.casefold():
        _pronunciations[written] = spoken


def pronounce(text: str) -> str:
    """Le texte à lire à voix haute, avec les prénoms écrits comme ils se prononcent."""
    import re

    for written, spoken in sorted(_pronunciations.items(), key=lambda kv: -len(kv[0])):
        text = re.sub(rf"(?<!\w){re.escape(written)}(?!\w)", spoken, text, flags=re.IGNORECASE)
    return text


_MY_NAME = re.compile(
    r"(?:^|\s)(?:je m'?appelle|je m appelle|appelle[- ]moi|mon (?:pre)?nom c'?est|"
    r"mon (?:pre)?nom est|mon pseudo c'?est|mon pseudo est)\s+([a-z][a-z'-]{1,24})\s*$"
)


def parse_name_command(text: str) -> str | None:
    """« Je m'appelle Yannick » / « appelle-moi Yannick » → "Yannick" (sinon None)."""
    import unicodedata

    plain = unicodedata.normalize("NFKD", text.casefold())
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    plain = re.sub(r"[^\w\s'-]", " ", plain).strip()
    if len(plain.split()) > 8:
        return None
    match = _MY_NAME.search(plain)
    if match is None:
        return None
    word = match.group(1)
    # Reprendre l'écriture d'origine (accents, majuscules) du mot dans la phrase
    original = next((w for w in re.findall(r"[\w'-]+", text) if _strip(w).casefold() == word), word)
    return original[:1].upper() + original[1:]


def _strip(word: str) -> str:
    import unicodedata

    word = unicodedata.normalize("NFKD", word)
    return "".join(c for c in word if not unicodedata.combining(c))
