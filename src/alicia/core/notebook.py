"""Carnet de partie : ce que tu demandes au robot de retenir, jeu par jeu.

« VIIRUS, retiens que je joue Ashe en support », « note que le boss craint le feu » :
la note est gardée pour ce jeu (ou en général hors jeu) et rappelée à l'IA à chaque
question et à chaque coup d'œil du Copilote, d'une session à l'autre.
Fichier : %APPDATA%\\Alicia\\carnet.json (sur ce PC seulement).
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from pathlib import Path

log = logging.getLogger("alicia.app")

MAX_NOTES = 30  # par jeu
GENERAL = "general"


def _plain(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in text if not unicodedata.combining(c))


class Notebook:
    def __init__(self, path: Path | None = None) -> None:
        if path is None:
            from alicia.core.config import data_dir

            path = data_dir() / "carnet.json"
        self.path = path

    def _load(self) -> dict[str, dict]:  # type: ignore[type-arg]
        try:
            data = json.loads(self.path.read_text("utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self, data: dict) -> None:  # type: ignore[type-arg]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def games(self) -> list[tuple[str, str, int]]:
        """[(clé, nom affiché, nombre de notes)]"""
        return [
            (key, str(entry.get("name") or key), len(entry.get("notes", [])))
            for key, entry in self._load().items()
            if entry.get("notes")
        ]

    def notes(self, key: str) -> list[str]:
        entry = self._load().get(key) or {}
        return [str(n) for n in entry.get("notes", [])]

    def add(self, key: str, name: str, note: str) -> bool:
        note = " ".join(note.split()).strip(" .")[:300]
        if len(note) < 3:
            return False
        data = self._load()
        entry = data.setdefault(key, {"name": name, "notes": []})
        entry["name"] = name or entry.get("name") or key
        notes = [n for n in entry.get("notes", []) if _plain(n) != _plain(note)]
        notes.append(note[:1].upper() + note[1:])
        entry["notes"] = notes[-MAX_NOTES:]
        self._save(data)
        log.info("Carnet (%s) : note ajoutée", entry["name"])
        return True

    def remove(self, key: str, index: int) -> None:
        data = self._load()
        notes = (data.get(key) or {}).get("notes", [])
        if 0 <= index < len(notes):
            del notes[index]
            self._save(data)

    def forget(self, key: str, words: str) -> int:
        """Retire les notes qui contiennent ces mots ; « tout » vide le carnet du jeu."""
        data = self._load()
        entry = data.get(key)
        if not entry:
            return 0
        notes = entry.get("notes", [])
        wanted = _plain(words).strip()
        if wanted in ("", "tout", "tout ca", "le carnet", "tes notes", "les notes"):
            kept: list[str] = []
        else:
            kept = [n for n in notes if wanted not in _plain(n)]
        removed = len(notes) - len(kept)
        entry["notes"] = kept
        self._save(data)
        return removed

    def prompt_note(self, key: str, name: str) -> str:
        """Ce que l'IA doit savoir (notes du jeu + notes générales)."""
        lines = self.notes(key) if key != GENERAL else []
        general = self.notes(GENERAL)
        out = ""
        if lines:
            out += f"\nCarnet du joueur pour {name} (ce qu'il t'a demandé de retenir) :\n"
            out += "\n".join(f"- {n}" for n in lines)
        if general:
            out += "\nCarnet général du joueur :\n" + "\n".join(f"- {n}" for n in general)
        return out


_ADD = re.compile(
    r"^(?:\w+\s*,\s*|\w+\s+(?=retiens|note|souviens|rappelle|n'?oublie|garde|memorise))?(?:retiens|retenir|note|noter|notes|souviens[- ]toi|rappelle[- ]toi|"
    r"n'?oublie pas|garde en (?:tete|memoire)|memorise)\s+(?:bien\s+)?(?:que|qu'|:)?\s*(.+)$"
)
_FORGET = re.compile(
    r"^(?:\w+\s*,\s*|\w+\s+(?=oublie|efface|supprime))?(?:oublie|efface|supprime)\s+(?:que|qu'|la note)?\s*(.+)$"
)
_LIST = re.compile(
    r"(?:qu'?est[- ]ce que tu as note|qu'?as[- ]tu note|tu as note quoi|lis (?:moi )?(?:le |mon )?"
    r"carnet|(?:c'?est )?quoi (?:mes|tes) notes|qu'?est[- ]ce que tu (?:as )?retenu|"
    r"tu te souviens de quoi)"
)


def _same_length(text: str) -> str:
    """Minuscules sans accents, même longueur que le texte (pour en reprendre des morceaux)."""
    out = []
    for c in text:
        base = "".join(
            x for x in unicodedata.normalize("NFKD", c.lower()) if not unicodedata.combining(x)
        )
        out.append(base[:1] if len(base) >= 1 else c)
    return "".join(out).replace("’", "'")


def parse_note_command(text: str) -> tuple[str, str] | None:
    """(« add », note) | (« forget », mots) | (« list », "") | None."""
    original = " ".join(text.split())
    plain = _same_length(original)
    if _LIST.search(plain):
        return "list", ""
    if len(plain.split()) > 40:
        return None
    match = _ADD.match(plain)
    if match and len(match.group(1).split()) >= 2:
        return "add", original[match.start(1) :].strip(" .!")
    match = _FORGET.match(plain)
    if match and re.search(
        r"\b(?:oublie|efface|supprime)\s+(?:que|qu'|la note|le carnet|tes notes)", plain
    ):
        words = match.group(1).strip(" .!")
        return "forget", "tout" if words in ("le carnet", "tes notes", "") else words
    return None


_DEBRIEF = re.compile(
    r"\b(?:debrief|debriefing|bilan de (?:la |ma |cette )?(?:partie|game|session)|"
    r"resume (?:de |moi )?(?:la |ma |cette )?(?:partie|game|session)|"
    r"comment j'?ai joue|j'?ai bien joue|qu'?est[- ]ce que j'?aurais du faire)\b"
)


def parse_debrief_command(text: str) -> bool:
    """« Fais-moi le débrief », « bilan de la partie », « comment j'ai joué ? »."""
    plain = _same_length(" ".join(text.split()))
    return len(plain.split()) <= 14 and bool(_DEBRIEF.search(plain))
