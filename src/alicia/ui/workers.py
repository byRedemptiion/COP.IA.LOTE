"""Exécution hors du thread Qt : l'interface ne fige jamais pendant capture ou IA."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Signal

log = logging.getLogger("alicia.ui")


class TaskSignals(QObject):
    progress = Signal(int, object)  # (génération, donnée intermédiaire)
    finished = Signal(int, object)  # (génération, résultat)
    failed = Signal(int, object)  # (génération, exception)


class Task(QRunnable):
    """Exécute ``fn(emit)`` ; ``emit(x)`` envoie une donnée intermédiaire à l'UI."""

    def __init__(self, generation: int, fn: Callable[[Callable[[Any], None]], Any]) -> None:
        super().__init__()
        self.generation = generation
        self.fn = fn
        self.signals = TaskSignals()
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            try:
                result = self.fn(lambda item: self.signals.progress.emit(self.generation, item))
            except Exception as exc:  # noqa: BLE001 - transmis à l'UI, journalisé là-bas
                self.signals.failed.emit(self.generation, exc)
            else:
                self.signals.finished.emit(self.generation, result)
        except RuntimeError:
            pass  # fenêtre fermée pendant la tâche (fermeture d'ALICIA) : plus personne à prévenir


class LogBridge(QObject):
    line = Signal(str)


class VoiceBridge(QObject):
    """Relaie l'état de la voix (thread audio) vers l'interface."""

    state = Signal(str, object)  # (« speaking » | « idle » | « error », message)
    reminder = Signal(str)  # rappel de minuteur (thread du minuteur → interface)
    wake = Signal()  # « Alicia » entendu
    wake_command = Signal(object)  # PreparedAudio : la demande qui suit le mot de réveil
    wake_cancel = Signal(str)  # mot de réveil sans demande exploitable
    wake_stop = Signal()  # « Alicia, stop »
    notice = Signal(str)  # message court venu d'un thread de fond
    duo = Signal(object)  # message reçu de l'autre robot (dict déchiffré)


class QtLogHandler(logging.Handler):
    """Relaie les logs vers le panneau de l'interface (thread-safe via signal Qt)."""

    def __init__(self, bridge: LogBridge) -> None:
        super().__init__()
        self.bridge = bridge

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.bridge.line.emit(self.format(record))
        except RuntimeError:
            pass  # interface déjà détruite
