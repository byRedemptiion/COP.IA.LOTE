"""Panneau « HISTORIQUE » (à droite de la page principale) : la conversation complète.

Contrairement à la zone CONVERSATION (qui montre seulement le dernier échange), rien ne s'y
efface quand un robot parle : chaque phrase s'ajoute en bas.
"""

from __future__ import annotations

import html
import time

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QTextBrowser, QVBoxLayout

from alicia.core.history import History, Line
from alicia.ui.theme import CYAN, MUTED, PINK_SOFT, TEXT

COLORS = {
    "me": "#3ddc84",
    "robot": CYAN,
    "peer": PINK_SOFT,
    "copilot": "#f5b62a",
    "chat": "#b48cff",
    "info": MUTED,
}


class HistoryPanel(QFrame):
    hide_requested = Signal()

    def __init__(self, history: History) -> None:
        super().__init__()
        self.history = history
        self.setObjectName("panel")
        box = QVBoxLayout(self)
        box.setContentsMargins(14, 12, 14, 12)
        box.setSpacing(8)
        head = QHBoxLayout()
        title = QLabel("HISTORIQUE")
        title.setObjectName("sectionTitle")
        head.addWidget(title)
        head.addStretch(1)
        clear = QPushButton("Effacer")
        clear.setObjectName("ghost")
        clear.setToolTip("Vider l'historique de la conversation")
        clear.clicked.connect(self.clear)
        head.addWidget(clear)
        close = QPushButton("✕")
        close.setObjectName("ghost")
        close.setToolTip("Masquer l'historique (bouton « Historique » en bas pour le revoir)")
        close.setFixedWidth(32)
        close.clicked.connect(self.hide_requested.emit)
        head.addWidget(close)
        box.addLayout(head)
        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(False)
        self.view.setPlaceholderText("Ce que vous vous dites s'affichera ici, sans s'effacer.")
        self.view.setProperty("keep_names", True)  # les noms écrits ici restent tels quels
        box.addWidget(self.view, 1)
        self.setMinimumWidth(240)
        for line in history.lines:
            self._append(line)

    @staticmethod
    def _html(line: Line) -> str:
        color = COLORS.get(line.kind, TEXT)
        when = time.strftime("%H:%M", time.localtime(line.at))
        return (
            f'<p style="margin:0 0 8px 0;"><span style="color:{MUTED};">{when}</span> '
            f'<b style="color:{color};">{html.escape(line.who)}</b><br>'
            f'<span style="color:{TEXT};">{html.escape(line.text)}</span></p>'
        )

    def _append(self, line: Line) -> None:
        bar = self.view.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 30
        self.view.append(self._html(line))
        if at_bottom:  # on suit la conversation, sauf si tu relis plus haut
            bar.setValue(bar.maximum())

    def add(self, who: str, text: str, kind: str = "me") -> None:
        line = self.history.add(who, text, kind)
        if line is not None:
            self._append(line)

    def clear(self) -> None:
        self.history.clear()
        self.view.clear()

    def text(self) -> str:
        return self.view.toPlainText()
