"""Les habitués du chat : il reconnaît les spectateurs qui reviennent.

Pour chaque pseudo : nombre de visites (une visite = un retour après 6 h d'absence), date du
dernier passage et les 3 derniers sujets dont il a parlé avec le robot. Fichier local :
%LOCALAPPDATA%\\Alicia\\habitues.json. Bouton « Oublier les habitués » pour tout effacer.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

log = logging.getLogger("alicia.stream")

NEW_VISIT_S = 6 * 3600
MAX_VIEWERS = 2000


def _ago(seconds: float) -> str:
    if seconds < 3600:
        return "il y a moins d'une heure"
    if seconds < 86400:
        return f"il y a {int(seconds // 3600)} h"
    days = int(seconds // 86400)
    return "hier" if days == 1 else f"il y a {days} jours"


class ViewerBook:
    def __init__(self, path: Path | None = None) -> None:
        if path is None:
            from alicia.core.config import state_dir

            path = state_dir() / "habitues.json"
        self.path = path
        self._lock = threading.Lock()
        self._data: dict[str, dict] | None = None  # type: ignore[type-arg]

    def _load(self) -> dict[str, dict]:  # type: ignore[type-arg]
        if self._data is None:
            try:
                data = json.loads(self.path.read_text("utf-8"))
                self._data = data if isinstance(data, dict) else {}
            except (OSError, ValueError):
                self._data = {}
        return self._data

    def _save(self) -> None:
        data = self._load()
        if len(data) > MAX_VIEWERS:  # les moins récents partent
            keep = sorted(data.items(), key=lambda kv: kv[1].get("last", 0))[-MAX_VIEWERS:]
            self._data = data = dict(keep)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            log.debug("Habitués non enregistrés : %r", exc)

    def seen(self, user: str, now: float | None = None) -> dict:  # type: ignore[type-arg]
        """Un message de ce spectateur ; renvoie sa fiche AVANT la mise à jour."""
        now = time.time() if now is None else now
        key = user.casefold()
        with self._lock:
            data = self._load()
            entry = data.get(key) or {"name": user, "visits": 0, "last": 0.0, "topics": []}
            before = dict(entry)
            last = float(entry.get("last", 0) or 0)
            if not last or now - last > NEW_VISIT_S:
                entry["visits"] = int(entry.get("visits", 0)) + 1
                entry["previous"] = entry.get("last", 0.0)
            entry["last"] = now
            entry["name"] = user
            data[key] = entry
            self._save()
        return before

    def topic(self, user: str, text: str) -> None:
        with self._lock:
            entry = self._load().get(user.casefold())
            if entry is None:
                return
            topics = [t for t in entry.get("topics", []) if t != text[:80]]
            entry["topics"] = (topics + [" ".join(text.split())[:80]])[-3:]
            self._save()

    def note_for(self, user: str, now: float | None = None) -> str:
        """Ce que l'IA doit savoir de ce spectateur (vide pour un nouveau)."""
        now = time.time() if now is None else now
        entry = self._load().get(user.casefold())
        if not entry or int(entry.get("visits", 0)) < 2:
            return "Ce spectateur est nouveau (ou presque) : accueille-le simplement."
        previous = float(entry.get("previous") or entry.get("last") or now)
        out = (
            f"Ce spectateur est un habitué : {entry['visits']}e passage, le précédent "
            f"{_ago(now - previous)}. Tu peux le saluer d'un « re » complice."
        )
        topics = entry.get("topics") or []
        if topics:
            out += " Il t'avait déjà parlé de : " + " ; ".join(f"« {t} »" for t in topics) + "."
        return out

    def count(self) -> int:
        return len(self._load())

    def clear(self) -> None:
        with self._lock:
            self._data = {}
            self._save()
