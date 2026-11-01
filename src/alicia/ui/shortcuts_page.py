"""Onglet « Raccourcis » : changer la touche pour parler à ALICIA et celle de l'analyse."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from alicia.ui.hotkey import hotkey_label
from alicia.ui.theme import GOLD, PINK, title_font

_NAMED = {
    Qt.Key.Key_Insert: "insert",
    Qt.Key.Key_Home: "home",
    Qt.Key.Key_End: "end",
    Qt.Key.Key_PageUp: "pageup",
    Qt.Key.Key_PageDown: "pagedown",
    Qt.Key.Key_Pause: "pause",
    Qt.Key.Key_ScrollLock: "scrolllock",
    Qt.Key.Key_CapsLock: "capslock",
    Qt.Key.Key_Tab: "tab",
    Qt.Key.Key_Space: "space",
}
_MODIFIER_KEYS = {Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_Shift, Qt.Key.Key_Meta}
_MOUSE = {
    Qt.MouseButton.XButton1: "mouse4",
    Qt.MouseButton.XButton2: "mouse5",
    Qt.MouseButton.MiddleButton: "mousemiddle",
}

VOICE_COMMANDS = (
    ("« Alicia, … »", "pose ta question ou fais ta demande sans toucher au clavier"),
    ("« Alicia » … (pause) …", "elle passe au cyan et attend ta demande"),
    (
        "« Alicia, stop »",
        "elle se tait et annule l'analyse en cours (aussi « tais-toi », « chut »)",
    ),
    ("« Alicia, lance Discord »", "ouvre une appli de ta liste (Discord, Spotify, Steam…)"),
    ("« Alicia, monte le son » / « volume à 30 »", "règle le volume de Windows"),
    ("« Alicia, rappelle-moi dans 10 minutes de … »", "rappel dit à voix haute"),
    (
        "« Alicia, éteins le PC »",
        "« oui » directement (sans redire Alicia), puis 20 s pour « annule »",
    ),
    ("« Alicia, … » pendant qu'elle parle", "elle se tait et écoute ta nouvelle demande"),
)


def _modifiers_text(modifiers: Qt.KeyboardModifier) -> list[str]:
    parts = []
    if modifiers & Qt.KeyboardModifier.ControlModifier:
        parts.append("ctrl")
    if modifiers & Qt.KeyboardModifier.AltModifier:
        parts.append("alt")
    if modifiers & Qt.KeyboardModifier.ShiftModifier:
        parts.append("shift")
    return parts


def key_to_hotkey(key: int, modifiers: Qt.KeyboardModifier, native_vk: int = 0) -> str | None:
    """Touche Qt → texte de raccourci (« ctrl+f9 », « num5 », « vk226 » pour la touche < d'un
    clavier AZERTY), ou None si non prise en charge."""
    if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F24:
        name = f"f{key - Qt.Key.Key_F1 + 1}"
    elif modifiers & Qt.KeyboardModifier.KeypadModifier and Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
        name = f"num{key - Qt.Key.Key_0}"
    elif Qt.Key.Key_A <= key <= Qt.Key.Key_Z or Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
        name = chr(key).lower()
    elif key in _NAMED:
        name = _NAMED[Qt.Key(key)]
    elif 0 < native_vk < 255:
        # Autres touches (<, ², ù, chiffres AZERTY sans Maj…) : code de touche Windows.
        name = f"vk{native_vk}"
    else:
        return None
    return "+".join([*_modifiers_text(modifiers), name])


class KeyCaptureButton(QPushButton):
    """Clique, puis appuie sur la touche (ou un bouton latéral de souris) voulue."""

    captured = Signal(str)
    capturing = Signal(bool)

    def __init__(self, text: str = "") -> None:
        super().__init__()
        self.setCheckable(True)
        self.setMinimumWidth(220)
        self.setFont(title_font(12))
        self.current = text
        self._show()
        self.clicked.connect(self._toggle)

    def set_hotkey(self, text: str) -> None:
        self.current = text
        self._show()

    def _show(self) -> None:
        self.setText(hotkey_label(self.current) if self.current else "Aucun")

    def _toggle(self, on: bool) -> None:
        if on:
            self.setText("Appuie sur une touche…  (Échap : annuler)")
            self.grabKeyboard()
            self.capturing.emit(True)
        else:
            self._finish(None)

    def _finish(self, text: str | None) -> None:
        self.releaseKeyboard()
        self.setChecked(False)
        self._show()
        self.capturing.emit(False)
        if text:
            self.captured.emit(text)

    def keyPressEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        if not self.isChecked():
            super().keyPressEvent(event)
            return
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self._finish(None)
            return
        if key in _MODIFIER_KEYS:
            return  # on attend la touche qui accompagne Ctrl / Alt / Maj
        text = key_to_hotkey(key, event.modifiers(), event.nativeVirtualKey())
        if text is None:
            self.setText("Touche non prise en charge, essaie une autre")
            return
        self._finish(text)

    def mousePressEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        if self.isChecked() and event.button() in _MOUSE:
            name = _MOUSE[event.button()]
            self._finish("+".join([*_modifiers_text(event.modifiers()), name]))
            return
        super().mousePressEvent(event)


class ShortcutsPage(QWidget):
    change_requested = Signal(str, str)  # (« talk » | « analyze », raccourci)
    capturing = Signal(bool)  # pendant la saisie, les raccourcis globaux sont suspendus

    ACTIONS = (
        ("talk", "Parler à ALICIA", "Maintiens la touche, parle, relâche."),
        ("analyze", "Analyse rapide de l'écran", "Un appui : capture du jeu et conseil immédiat."),
    )

    def __init__(self, current: dict[str, str]) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        title = QLabel("RACCOURCIS")
        title.setFont(title_font(16))
        title.setStyleSheet(f"color:{PINK};")
        layout.addWidget(title)

        keys = QFrame()
        keys.setObjectName("panel")
        grid = QGridLayout(keys)
        grid.setContentsMargins(18, 16, 18, 16)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(10)
        self.buttons: dict[str, KeyCaptureButton] = {}
        self.states: dict[str, QLabel] = {}
        for row, (action, name, help_text) in enumerate(self.ACTIONS):
            label = QLabel(name)
            label.setFont(title_font(12))
            label.setStyleSheet(f"color:{GOLD};")
            helper = QLabel(help_text)
            helper.setObjectName("muted")
            text_box = QVBoxLayout()
            text_box.addWidget(label)
            text_box.addWidget(helper)
            button = KeyCaptureButton(current.get(action, ""))
            button.captured.connect(lambda text, a=action: self.change_requested.emit(a, text))
            button.capturing.connect(self.capturing.emit)
            state = QLabel("")
            state.setObjectName("muted")
            state.setWordWrap(True)
            self.buttons[action], self.states[action] = button, state
            grid.addLayout(text_box, row, 0)
            grid.addWidget(button, row, 1)
            grid.addWidget(state, row, 2)
        grid.setColumnStretch(2, 1)
        layout.addWidget(keys)

        note = QLabel(
            "Clique sur une touche puis appuie sur la nouvelle : touches F1 à F24, lettres, "
            "chiffres, pavé numérique, Inser, Début, Fin, Pause, <, ², ù…, avec ou sans Ctrl / Alt / Maj, "
            "ou un <b>bouton latéral de la souris</b> (pratique pour parler en jouant).<br>"
            "Une touche du clavier est réservée à ALICIA (le jeu ne la reçoit plus tant qu'elle "
            "est ouverte) ; un bouton de souris reste aussi transmis au jeu."
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        note.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(note)

        voice = QFrame()
        voice.setObjectName("panel")
        voice_layout = QGridLayout(voice)
        voice_layout.setContentsMargins(18, 14, 18, 14)
        voice_layout.setVerticalSpacing(8)
        heading = QLabel("COMMANDES VOCALES (réveil « Alicia » activé)")
        heading.setObjectName("sectionTitle")
        voice_layout.addWidget(heading, 0, 0, 1, 2)
        for row, (phrase, meaning) in enumerate(VOICE_COMMANDS, start=1):
            said = QLabel(phrase)
            said.setStyleSheet(f"color:{PINK};")
            what = QLabel(meaning)
            what.setObjectName("muted")
            what.setWordWrap(True)
            voice_layout.addWidget(said, row, 0)
            voice_layout.addWidget(what, row, 1)
        voice_layout.setColumnStretch(1, 1)
        layout.addWidget(voice)
        layout.addStretch(1)

    def set_state(self, action: str, text: str, current: str | None = None) -> None:
        if current is not None:
            self.buttons[action].set_hotkey(current)
        self.states[action].setText(text)
