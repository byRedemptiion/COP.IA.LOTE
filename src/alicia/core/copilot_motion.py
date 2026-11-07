"""Copilote : regarder quand ça compte (tout se calcule sur le PC, sans IA).

1. Mouvement : une miniature en niveaux de gris (32 × 18) de chaque image, comparée à celle
   du dernier coup d'œil envoyé à l'IA.
   - écran immobile (menu, perso à l'arrêt, chargement) → pas d'appel à l'IA (2 min au plus,
     puis un coup d'œil de contrôle) ;
   - gros changement d'un coup (combat qui démarre, écran qui rougit, mort) → coup d'œil
     immédiat, sans attendre le prochain tour ;
   - l'intervalle s'adapte : plus court quand ça bouge beaucoup, plus long au calme.
2. État de partie : ce que l'IA a vu aux derniers coups d'œil, horodaté (« en combat contre
   un kobold, depuis 40 s »), rappelé au coup d'œil suivant pour qu'elle sache ce qui est
   en cours et ce qui est TERMINÉ.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

import numpy as np

SIZE = (32, 18)
STILL = 0.012  # en dessous : rien n'a vraiment bougé depuis le dernier coup d'œil
BIG = 0.10  # au-dessus : gros changement → coup d'œil tout de suite
MIN_GAP_S = 3.0  # jamais deux coups d'œil à moins de 3 s
MAX_SKIP_S = 120.0  # écran immobile : un coup d'œil de contrôle toutes les 2 min


def signature(image) -> np.ndarray:  # type: ignore[no-untyped-def]
    """Miniature en niveaux de gris (valeurs 0-1) : quelques millisecondes."""
    factor = max(1, min(image.width // (SIZE[0] * 4), image.height // (SIZE[1] * 4)))
    small = (image.reduce(factor) if factor > 1 else image).convert("L").resize(SIZE)
    return np.asarray(small, dtype=np.float32) / 255.0


def difference(a: np.ndarray | None, b: np.ndarray | None) -> float:
    if a is None or b is None or a.shape != b.shape:
        return 1.0
    return float(np.mean(np.abs(a - b)))


class MotionWatch:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.last_look_at: float | None = None
        self.look_sig: np.ndarray | None = None  # image du dernier coup d'œil envoyé
        self.prev_sig: np.ndarray | None = None
        self.activity = 0.0  # mouvement moyen récent (image à image)

    def interval(self, base_s: float) -> float:
        """Intervalle adapté : action → plus court, calme → plus long."""
        if self.activity >= 0.05:
            return max(MIN_GAP_S + 2, base_s * 0.75)
        if self.activity <= 0.01:
            return min(MAX_SKIP_S, base_s * 2.0)
        return base_s

    def decide(self, sig: np.ndarray, base_s: float, now: float | None = None) -> tuple[bool, str]:
        """(faut-il regarder maintenant ?, pourquoi)."""
        now = time.monotonic() if now is None else now
        step = difference(sig, self.prev_sig)
        before = self.activity  # mouvement habituel juste avant cette image
        if self.prev_sig is not None:
            self.activity = 0.7 * self.activity + 0.3 * step
        self.prev_sig = sig
        if self.last_look_at is None:
            return True, "premier coup d'œil"
        since = now - self.last_look_at
        if since < MIN_GAP_S:
            return False, "trop tôt"
        changed = difference(sig, self.look_sig)
        # Gros changement SOUDAIN (pas un simple mouvement de caméra en pleine action) :
        # l'image saute alors que l'écran était plutôt calme juste avant.
        sudden = step >= max(BIG, before * 3) and changed >= BIG
        if sudden and since >= max(MIN_GAP_S, base_s * 0.4):
            return True, f"gros changement soudain à l'écran ({changed:.2f})"
        if since < self.interval(base_s):
            return False, "pas encore l'heure"
        if changed < STILL and since < MAX_SKIP_S:
            return False, "écran immobile (aucun appel à l'IA)"
        return True, "tour normal"

    def looked(self, sig: np.ndarray | None, now: float | None = None) -> None:
        self.last_look_at = time.monotonic() if now is None else now
        if sig is not None:
            self.look_sig = sig


@dataclass
class StateLine:
    text: str
    since: float  # time.time() du début de cet état
    seen: float  # dernière fois qu'il a été vu


class GameState:
    """Ce que l'IA a vu aux derniers coups d'œil (« combat contre un kobold »), horodaté."""

    def __init__(self, keep: int = 4) -> None:
        self.lines: deque[StateLine] = deque(maxlen=keep)

    def clear(self) -> None:
        self.lines.clear()

    def update(self, text: str, now: float | None = None) -> None:
        text = " ".join(str(text or "").split())[:140]
        if not text:
            return
        now = time.time() if now is None else now
        last = self.lines[-1] if self.lines else None
        if last is not None and _same(last.text, text):
            last.seen = now  # le même état continue : on garde son heure de début
            return
        self.lines.append(StateLine(text, now, now))

    def note(self, now: float | None = None) -> str:
        if not self.lines:
            return ""
        from alicia.core.ai.base import ago

        now = time.time() if now is None else now
        rows = []
        for i, line in enumerate(self.lines):
            current = i == len(self.lines) - 1
            if current:
                lasted = int(now - line.since)
                rows.append(f"- [{ago(line.seen, now)}] {line.text} (depuis {lasted} s)")
            else:
                rows.append(f"- [{ago(line.seen, now)}, TERMINÉ] {line.text}")
        return (
            "ÉTAT DE PARTIE vu aux coups d'œil précédents (horodaté ; compare avec l'image : "
            "si ce n'est plus à l'écran, c'est fini) :\n" + "\n".join(rows) + "\n"
        )


def _same(a: str, b: str) -> bool:
    import difflib

    return difflib.SequenceMatcher(None, a.casefold(), b.casefold()).ratio() >= 0.7
