"""Reconnaissance locale des demandes d'action (« éteins le PC », « monte le son »…).

Principe repris de huburton/jarvis (MIT) : un routeur par mots-clés devant l'IA. Il est
instantané, gratuit, hors ligne et ne peut choisir qu'une action du catalogue : aucune
commande libre n'est jamais exécutée. Tout ce qui n'est pas reconnu part à l'IA comme
une question sur le jeu.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

NUMBER_WORDS = {
    "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6, "sept": 7,
    "huit": 8, "neuf": 9, "dix": 10, "onze": 11, "douze": 12, "treize": 13, "quatorze": 14,
    "quinze": 15, "seize": 16, "vingt": 20, "trente": 30, "quarante": 40, "cinquante": 50,
    "soixante": 60, "cent": 100,
}  # fmt: skip


@dataclass(frozen=True)
class Intent:
    name: str
    params: dict[str, object] = field(default_factory=dict)
    phrase: str = ""


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.replace("’", "'")
    text = re.sub(r"[^\w%' ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_number(text: str) -> int | None:
    """« 20 », « vingt », « vingt-cinq », « trente et une »… → entier (jusqu'à 199)."""
    match = re.search(r"\b(\d{1,3})\b", text)
    if match:
        return int(match.group(1))
    total, found = 0, False
    for word in re.split(r"[\s-]+", text):
        if word in NUMBER_WORDS:
            value = NUMBER_WORDS[word]
            total = total * value if value == 100 and total else total + value
            found = True
        elif found and word not in ("et",):
            break
    return total if found else None


_PC = r"(?:le |l')?(?:pc|ordi|ordinateur|machine)"
_ME = r"(?:moi |m')?"

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("cancel_shutdown", re.compile(r"\bannule[rz]?\b.*\b(?:extinction|arret|redemarrage|eteindre)\b")),
    ("shutdown", re.compile(rf"\b(?:eteins|eteint|eteindre|eteignez|arrete|arreter)\b.*\b{_PC}\b")),
    ("shutdown", re.compile(r"\bextinction (?:du |de l')?(?:pc|ordi|ordinateur)\b")),
    ("restart", re.compile(rf"\b(?:redemarre|redemarrer|reboot|relance)\b.*\b{_PC}\b")),
    ("sleep", re.compile(rf"\b(?:mets?|met|passe)\b.*\ben veille\b|\bveille\b.*\b{_PC}\b")),
    ("lock", re.compile(rf"\b(?:verrouille|verrouiller|verouille|bloque)\b.*\b{_PC}\b|\bverrouille la session\b")),
    ("mute", re.compile(r"\b(?:coupe|couper|mute)\b.*\b(?:son|volume)\b")),
    ("unmute", re.compile(r"\b(?:remets?|reactive|retablis)\b.*\b(?:son|volume)\b")),
    ("volume_set", re.compile(r"\bvolume\b.*\b(?:a|sur)\b\s+(\w[\w-]*(?: et \w+)?)\s*(?:%|pour ?cent)?")),
    ("volume_up", re.compile(r"\b(?:monte|augmente|plus fort|hausse)\b.*\b(?:son|volume)\b|\bplus fort\b")),
    ("volume_down", re.compile(r"\b(?:baisse|diminue|moins fort)\b.*\b(?:son|volume)\b|\bmoins fort\b")),
    ("timer", re.compile(rf"\b(?:minuteur|chrono|timer|rappelle[ -]?{_ME}|previens[ -]?{_ME})\b.*\b(?:dans|de)\b")),
    ("launch", re.compile(r"\b(?:lance|lancer|ouvre|ouvrir|demarre|demarrer)\b\s+(?:l'appli |l'application |le |la |les )?(.+)")),
    ("close", re.compile(r"\b(?:ferme|fermer|quitte|quitter)\b\s+(?:l'appli |l'application |le |la |les )?(.+)")),
]  # fmt: skip

UNITS = [
    (re.compile(r"\bheures?\b"), 3600),
    (re.compile(r"\bminutes?\b|\bmin\b"), 60),
    (re.compile(r"\bsecondes?\b|\bsec\b"), 1),
]


def _timer(norm: str, phrase: str) -> Intent | None:
    match = re.search(r"\b(?:dans|de)\b\s+(.+)", norm)
    if not match:
        return None
    rest = match.group(1)
    amount = parse_number(rest)
    if amount is None:
        return None
    seconds = None
    for pattern, factor in UNITS:
        if pattern.search(rest):
            seconds = amount * factor
            break
    if seconds is None:
        seconds = amount * 60  # « dans 20 » → minutes
    label_match = re.search(
        r"\b(?:minutes?|secondes?|heures?|min|sec)\b\s+(?:de |d'|pour |que )?(.+)", rest
    )
    label = label_match.group(1).strip() if label_match else ""
    return Intent("timer", {"seconds": seconds, "label": label}, phrase)


def parse_intent(text: str, apps: dict[str, object] | None = None) -> Intent | None:
    """Renvoie l'action demandée, ou None si c'est une question pour l'IA."""
    norm = normalize(text)
    if not norm:
        return None
    apps = apps or {}
    for name, pattern in PATTERNS:
        match = pattern.search(norm)
        if not match:
            continue
        if name == "volume_set":
            value = parse_number(match.group(1))
            if value is None:
                continue
            return Intent(name, {"percent": max(0, min(100, value))}, text)
        if name in ("volume_up", "volume_down"):
            step = parse_number(norm) or 10
            return Intent(name, {"step": max(1, min(50, step))}, text)
        if name == "timer":
            intent = _timer(norm, text)
            if intent:
                return intent
            continue
        if name in ("launch", "close"):
            app = _match_app(match.group(1), apps)
            if app is None:
                continue  # « ouvre l'inventaire » : question de jeu, pas une appli
            return Intent(name, {"app": app}, text)
        return Intent(name, {}, text)
    return None


def _match_app(spoken: str, apps: dict[str, object]) -> str | None:
    spoken = normalize(spoken)
    for name in sorted(apps, key=len, reverse=True):
        if normalize(name) and normalize(name) in spoken:
            return name
    return None


_YES = re.compile(
    r"\b(?:oui|ouais|ok|okay|d'accord|confirme|vas[ -]?y|go|valide|c'est bon|bien sur|exact)\b"
)
_NO = re.compile(r"\b(?:non|nan|annule|stop|arrete|pas|surtout pas|laisse tomber|attends?)\b")


def parse_confirmation(text: str) -> bool | None:
    """Oui → True, non → False, autre → None. Une négation l'emporte toujours (prudence)."""
    norm = normalize(text)
    if _NO.search(norm):
        return False
    if _YES.search(norm):
        return True
    return None
