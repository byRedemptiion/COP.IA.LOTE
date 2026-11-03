"""Historique de la conversation : tout ce qui a été dit, dans l'ordre, sans rien effacer.

Toi, ton robot, l'autre robot du duo, le Copilote, le chat… Gardé sur ce PC
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


@dataclass(frozen=True)
class Line:
    at: float  # horodatage (secondes)
    who: str  # « Toi », « VIIRUS », « ALICIA → VIIRUS »…
    text: str
    kind: str = "me"  # me | robot | peer | copilot | chat | info


class History:
    def __init__(self, path: Path | None = None) -> None:
        if path is None:
            from alicia.core.config import state_dir

            path = state_dir() / "historique.json"
        self.path = path
        self.lines: list[Line] = self._load()

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
                        str(item.get("kind", "me")),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return lines[-MAX_LINES:]

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + ".tmp")
            data = [asdict(line) for line in self.lines]
            tmp.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
            tmp.replace(self.path)
        except OSError as exc:
            log.debug("Historique non enregistré : %r", exc)

    def add(self, who: str, text: str, kind: str = "me") -> Line | None:
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
