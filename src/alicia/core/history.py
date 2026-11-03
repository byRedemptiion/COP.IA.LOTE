"""Historique du duo : ce que les deux robots se disent, dans l'ordre, sans rien effacer.

Seulement les échanges entre robots (pas tes questions à ton propre robot). Gardé sur ce PC
(%LOCALAPPDATA%\\Alicia\\historique.json, 300 lignes au plus) pour le retrouver après un
redémarrage. Bouton « Effacer » dans le panneau Historique.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path

log = logging.getLogger("alicia.app")

MAX_LINES = 300
KINDS = ("duo", "peer")  # seulement les deux robots (v0.16.2 gardait aussi tes questions)


@dataclass(frozen=True)
class Line:
    at: float  # horodatage (secondes)
    who: str  # « Toi », « VIIRUS », « ALICIA → VIIRUS »…
    text: str
    kind: str = "duo"  # duo (mon robot → l'autre) | peer (l'autre robot)


class History:
    def __init__(self, path: Path | None = None) -> None:
        if path is None:
            from alicia.core.config import state_dir

            path = state_dir() / "historique.json"
        self.path = path
        self.lines: list[Line] = self._load()
        self.font_size = 9
        try:
            prefs = json.loads(self._prefs().read_text("utf-8"))
            self.font_size = max(6, min(20, int(prefs.get("font_size", 9))))
        except (OSError, ValueError, TypeError, AttributeError):
            pass

    def _prefs(self) -> Path:
        return self.path.with_name("historique_reglages.json")

    def set_font_size(self, size: int) -> None:
        self.font_size = size
        try:
            self._prefs().write_text(json.dumps({"font_size": size}), "utf-8")
        except OSError:
            pass

    def _load(self) -> list[Line]:
        try:
            data = json.loads(self.path.read_text("utf-8"))
        except (OSError, ValueError):
            return []
        lines = []
        for item in data if isinstance(data, list) else []:
            try:
                lines.append(
                    Line(
                        float(item["at"]),
                        str(item["who"]),
                        str(item["text"]),
                        str(item.get("kind", "")),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return [line for line in lines if line.kind in KINDS][-MAX_LINES:]

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + ".tmp")
            data = [asdict(line) for line in self.lines]
            tmp.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
            tmp.replace(self.path)
        except OSError as exc:
            log.debug("Historique non enregistré : %r", exc)

    def add(self, who: str, text: str, kind: str = "duo") -> Line | None:
        text = " ".join(str(text).split()).strip()
        if not text:
            return None
        last = self.lines[-1] if self.lines else None
        if last is not None and last.who == who and last.text == text:
            return None  # même phrase réaffichée (réécoute, bulle…) : une seule ligne
        line = Line(time.time(), who, text[:2000], kind)
        self.lines.append(line)
        del self.lines[:-MAX_LINES]
        self._save()
        return line

    def clear(self) -> None:
        self.lines = []
        self._save()
