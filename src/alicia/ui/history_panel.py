"""Panneau « HISTORIQUE DU DUO » (à droite de la page principale) : ce que les deux robots
se disent (VIIRUS ⇄ ALICIA), dans l'ordre. Tes échanges avec ton propre robot n'y sont pas.

Contrairement à la zone CONVERSATION (qui montre seulement le dernier échange), rien ne s'y
efface quand un robot parle : chaque phrase s'ajoute en bas.
"""

from __future__ import annotations

import html
import time

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from alicia.core.history import History, Line
from alicia.ui.theme import CYAN, MUTED, PINK_SOFT, TEXT

COLORS = {
    "me": "#3ddc84",
    "robot": CYAN,
    "duo": CYAN,
    "peer": PINK_SOFT,
    "copilot": "#f5b62a",
    "chat": "#b48cff",
    "info": MUTED,
}


SIZES = (7, 8, 9, 10, 11, 12, 14)  # taille du texte (points)
DEFAULT_SIZE = 9


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
        title = QLabel("HISTORIQUE DU DUO")
        title.setObjectName("sectionTitle")
        head.addWidget(title)
        head.addStretch(1)
        tools = QHBoxLayout()  # 2e ligne : le titre reste lisible même panneau étroit
        self.size_box = QComboBox()
        self.size_box.setToolTip("Taille du texte de l'historique")
        for size in SIZES:
            self.size_box.addItem(f"Aa {size}", size)
        tools.addWidget(QLabel("Texte"))
        tools.addWidget(self.size_box)
        tools.addStretch(1)
        clear = QPushButton("Effacer")
        clear.setObjectName("ghost")
        clear.setToolTip("Vider l'historique du duo")
        clear.clicked.connect(self.clear)
        tools.addWidget(clear)
        close = QPushButton("✕")
        close.setObjectName("ghost")
        close.setToolTip("Masquer l'historique (bouton « Historique » en bas pour le revoir)")
        close.setFixedWidth(32)
        close.clicked.connect(self.hide_requested.emit)
        head.addWidget(close)
        box.addLayout(head)
        box.addLayout(tools)
        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(False)
        self.view.setPlaceholderText(
            "Ce que les deux robots se disent s'affichera ici, sans s'effacer."
        )
        self.view.setProperty("keep_names", True)  # les noms écrits ici restent tels quels
        box.addWidget(self.view, 1)
        self.setMinimumWidth(240)
        self.size_box.setCurrentIndex(max(0, self.size_box.findData(history.font_size)))
        self.set_font_size(history.font_size)
        self.size_box.currentIndexChanged.connect(
            lambda _i: self.set_font_size(int(self.size_box.currentData()), save=True)
        )
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

    def add(self, who: str, text: str, kind: str = "duo") -> None:
        line = self.history.add(who, text, kind)
        if line is not None:
            self._append(line)

    def set_font_size(self, size: int, save: bool = False) -> None:
        self.view.setStyleSheet(f"QTextBrowser {{ font-size: {size}pt; }}")
        if save:
            self.history.set_font_size(size)

    def clear(self) -> None:
        self.history.clear()
        self.view.clear()

    def text(self) -> str:
        return self.view.toPlainText()
