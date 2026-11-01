"""Panneau « DUO » de la page principale : qui est là avec ton robot, en temps réel.

Résumé seulement : la configuration reste dans Réglages → Social.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from alicia.core.duo_presence import label
from alicia.ui.theme import MUTED, TEXT

DOT = {
    "present": ("●", "#3ddc84"),
    "speaking": ("●", "#22e3ff"),
    "connecting": ("◌", "#f5b62a"),
    "absent": ("○", MUTED),
    "unavailable": ("○", "#ff4d6d"),
    "off": ("○", MUTED),
    "active": ("●", "#3ddc84"),
}


class DuoPanel(QFrame):
    manage = Signal()  # « Gérer le Duo » → Réglages → Social

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("panel")
        box = QVBoxLayout(self)
        box.setContentsMargins(14, 12, 14, 12)
        box.setSpacing(8)
        title = QLabel("DUO")
        title.setObjectName("sectionTitle")
        box.addWidget(title)
        rows = QWidget()
        self.grid = QGridLayout(rows)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(10)
        self.grid.setVerticalSpacing(2)
        self.rows: dict[str, tuple[QLabel, QLabel, QLabel]] = {}
        for index, key in enumerate(("me", "peer")):
            dot, name, state = QLabel(), QLabel(), QLabel()
            name.setStyleSheet(f"color:{TEXT}; font-weight:600;")
            name.setProperty("keep_names", True)
            state.setObjectName("muted")
            state.setProperty("keep_names", True)
            self.grid.addWidget(dot, index * 2, 0)
            self.grid.addWidget(name, index * 2, 1)
            self.grid.addWidget(state, index * 2 + 1, 1)
            self.rows[key] = (dot, name, state)
        self.grid.setColumnStretch(1, 1)
        box.addWidget(rows)
        self.summary = QLabel("")
        self.summary.setObjectName("sectionTitle")
        self.summary.setProperty("keep_names", True)
        box.addWidget(self.summary)
        box.addStretch(1)
        button = QPushButton("Gérer le Duo")
        button.clicked.connect(self.manage.emit)
        box.addWidget(button)

    def _row(self, key: str, state: str, name: str, text: str) -> None:
        dot, name_label, state_label = self.rows[key]
        symbol, color = DOT.get(state, DOT["off"])
        dot.setText(symbol)
        dot.setStyleSheet(f"color:{color}; font-size:14pt;")
        name_label.setText(name)
        state_label.setText(text)

    def show_state(
        self, me: str, me_state: str, peer: str, peer_state: str, player: str, feminine: bool
    ) -> None:
        """Met à jour le panneau (appelé toutes les ~2 s par la fenêtre principale)."""
        self._row("me", "active", me, me_state)
        text = label(peer_state, feminine)
        if player and peer_state in ("present", "speaking"):
            text += f" · avec {player}"
        self._row("peer", peer_state, peer, text)
        if peer_state == "off":
            summary = "DUO DÉSACTIVÉ"
        elif peer_state in ("present", "speaking"):
            summary = "MODE DUO ACTIF"
        else:
            elision = "D'" if peer[:1].upper() in "AEIOUY" else "DE "
            summary = f"EN ATTENTE {elision}{peer.upper()}"
        self.summary.setText(summary)
        self.summary.setStyleSheet(
            "color:#3ddc84;" if peer_state in ("present", "speaking") else f"color:{MUTED};"
        )
