"""Contexte de session (V0.1 : historique court). Conçu pour accueillir la mémoire de V0.5."""

from __future__ import annotations

import threading
from collections import deque

from alicia.core.ai.base import Turn


class SessionContext:
    def __init__(self, history_turns: int = 3) -> None:
        self._lock = threading.Lock()
        self._turns: deque[Turn] = deque(maxlen=max(history_turns, 1))
        self._history_turns = history_turns
        self.facts: dict[str, str] = {}  # infos données par le joueur (V0.5)

    def history(self) -> tuple[Turn, ...]:
        if self._history_turns == 0:
            return ()
        with self._lock:
            return tuple(self._turns)

    def record(self, question: str, answer: str) -> None:
        with self._lock:
            self._turns.append(Turn(question, answer))

    def clear(self) -> None:
        with self._lock:
            self._turns.clear()
            self.facts.clear()

    @property
    def last(self) -> Turn | None:
        with self._lock:
            return self._turns[-1] if self._turns else None
