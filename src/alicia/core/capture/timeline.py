"""Mémoire de partie : de petites captures datées, pour répondre sur ce qui s'est passé avant.

Pendant que la vision en direct tourne, une image réduite (1280 px, JPEG) est gardée toutes
les 30 s dans %LOCALAPPDATA%\\Alicia\\memoire. Si ta question parle du passé (« il y a une
heure », « tout à l'heure », « à 21h30 »), les images de ce moment partent avec elle.

Nettoyage automatique : au lancement puis toutes les heures, les images de plus de 20 h
sont effacées, et jamais plus de 10 000 images ne sont gardées. Option pour tout effacer à
la fermeture, et bouton « Effacer maintenant » dans les réglages.
"""

from __future__ import annotations

import logging
import re
import threading
import time
import unicodedata
from datetime import UTC, datetime, timedelta
from pathlib import Path

from alicia.core.capture.models import Frame

log = logging.getLogger("alicia.capture")

STAMP = "%Y%m%dT%H%M%SZ"


class Timeline:
    def __init__(
        self,
        folder: Path,
        *,
        interval_s: float = 30.0,
        retention_h: float = 20.0,
        max_images: int = 10_000,
        max_side: int = 1280,
        quality: int = 70,
        max_bytes: int = 5 * 1024**3,
    ) -> None:
        self.max_bytes = max_bytes
        self.folder = folder
        self.interval_s = interval_s
        self.retention_h = retention_h
        self.max_images = max_images
        self.max_side = max_side
        self.quality = quality
        self._last = 0.0
        self._lock = threading.Lock()

    # --- écriture -------------------------------------------------------------------------------

    def add(self, frame: Frame, force: bool = False) -> Path | None:
        """Garde une image réduite si l'intervalle est écoulé (appelé à chaque capture)."""
        now = time.monotonic()
        if not force and now - self._last < self.interval_s:
            return None
        self._last = now
        image = frame.image.convert("RGB")
        if max(image.size) > self.max_side:
            image = image.copy()
            image.thumbnail((self.max_side, self.max_side))
        stamp = frame.captured_at.astimezone(UTC).strftime(STAMP)
        path = self.folder / f"{stamp}.jpg"
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            image.save(path, "JPEG", quality=self.quality, optimize=True)
        except OSError as exc:
            log.warning("Mémoire de partie : image non enregistrée (%r)", exc)
            return None
        return path

    # --- lecture --------------------------------------------------------------------------------

    def entries(self) -> list[tuple[datetime, Path]]:
        found = []
        if not self.folder.is_dir():
            return found
        for path in self.folder.glob("*.jpg"):
            try:
                when = datetime.strptime(path.stem, STAMP).replace(tzinfo=UTC)
            except ValueError:
                continue
            found.append((when, path))
        return sorted(found)

    def near(self, when: datetime, count: int = 3) -> list[tuple[datetime, Path]]:
        """Les ``count`` images les plus proches de ``when`` (dans l'ordre du temps)."""
        items = self.entries()
        if not items:
            return []
        closest = sorted(items, key=lambda item: abs((item[0] - when).total_seconds()))[:count]
        return sorted(closest)

    def usage(self) -> tuple[int, int]:
        """(nombre d'images, taille totale en octets)."""
        items = self.entries()
        size = 0
        for _when, path in items:
            try:
                size += path.stat().st_size
            except OSError:
                pass
        return len(items), size

    # --- nettoyage ------------------------------------------------------------------------------

    def cleanup(self, now: datetime | None = None) -> int:
        """Efface les images trop vieilles et celles au-delà du nombre maximal."""
        now = now or datetime.now(UTC)
        limit = now - timedelta(hours=self.retention_h)
        removed = 0
        with self._lock:
            items = self.entries()
            excess = max(0, len(items) - self.max_images)
            sizes = {}
            for _when, path in items:
                try:
                    sizes[path] = path.stat().st_size
                except OSError:
                    sizes[path] = 0
            total = sum(sizes.values())
            for index, (when, path) in enumerate(items):  # du plus ancien au plus récent
                if when < limit or index < excess or total > self.max_bytes:
                    try:
                        path.unlink()
                        removed += 1
                        total -= sizes[path]
                    except OSError:
                        pass
        if removed:
            log.info("Mémoire de partie : %d image(s) effacée(s)", removed)
        return removed

    def clear(self) -> int:
        removed = 0
        with self._lock:
            for _when, path in self.entries():
                try:
                    path.unlink()
                    removed += 1
                except OSError:
                    pass
        log.info("Mémoire de partie effacée (%d image(s))", removed)
        return removed


# --- « il y a une heure », « tout à l'heure », « à 21h30 » ----------------------------------------

_NUMBERS = {
    "un": 1,
    "une": 1,
    "deux": 2,
    "trois": 3,
    "quatre": 4,
    "cinq": 5,
    "six": 6,
    "sept": 7,
    "huit": 8,
    "neuf": 9,
    "dix": 10,
    "quinze": 15,
    "vingt": 20,
    "trente": 30,
    "quarante": 40,
    "cinquante": 50,
}


def _plain(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def find_past_moment(question: str, now: datetime | None = None) -> datetime | None:
    """Moment du passé évoqué dans la question (heure locale du PC), ou None."""
    now = now or datetime.now().astimezone()
    text = _plain(question)
    number = r"(\d+|" + "|".join(_NUMBERS) + r")"
    relative = re.search(number + r"(?:\s*et\s*demie?)?\s*(h\b|heures?|min\b|minutes?|mn\b)", text)
    if relative and re.search(r"\bil y a\b|\bya\b|\bdepuis\b|\bavant\b", text):
        raw = relative.group(1)
        value = int(raw) if raw.isdigit() else _NUMBERS[raw]
        minutes = value * 60 if relative.group(2).startswith("h") else value
        if "demi" in relative.group(0) or text[relative.end() :].lstrip().startswith("et demi"):
            minutes += 30
        return now - timedelta(minutes=minutes)
    if re.search(r"\bil y a une demi.?heure\b", text):
        return now - timedelta(minutes=30)
    absolute = re.search(r"\b(?:a|vers|de)\s+(\d{1,2})\s*h\s*(\d{2})?\b", text)
    if absolute:
        hour, minute = int(absolute.group(1)), int(absolute.group(2) or 0)
        if hour < 24 and minute < 60:
            moment = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if moment > now:
                moment -= timedelta(days=1)
            return moment
    if re.search(r"tout a l.?heure|plus tot|au debut de la partie|la derniere fois", text):
        return now - timedelta(minutes=20)
    return None
