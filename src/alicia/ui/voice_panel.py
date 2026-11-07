"""Profil → « VOIX » : deux cartes (voix principale, voix de secours), chacune avec ses propres
réglages, puis la bibliothèque (parcourir, créer une voix).

- Carte : nom, fournisseur, type, statut ; ▶ Écouter · ✎ Modifier · ⇄ Changer.
- Modifier : les réglages de CETTE voix seulement (hauteur, vitesse, robot, clarté,
  réverbération, volume, jeu de voix). Chaque réglage dit s'il est fait par le fournisseur
  (« natif »), sur ton PC (« sur ton PC ») ou impossible avec ce moteur (grisé, avec la raison).
- Bibliothèque : recherche + catégories (Mes voix, Edge, Gemini, ChatGPT, voix générées,
  intégrées) ; chaque voix : ▶ · Principale · Secours.
- Créer une voix : 1 voix de base → 2 réglages → 3 écouter → 4 nom → 5 enregistrer (et
  l'utiliser) ; ou « générer une toute nouvelle voix » avec Gemini 3.8.

Tout passe par ``emit(clé, valeur)`` : c'est la fenêtre principale qui applique et enregistre.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from alicia.core.audio.voice_caps import LABELS, PROVIDERS, capabilities, kind
from alicia.core.config import VoiceSettings
from alicia.ui import theme

GREEN, ORANGE, RED, GREY = "#3ddc84", "#f5a524", "#ff4d6d", "#7f8cc4"
SLOT_COLORS = {"main": theme.CYAN, "backup": ORANGE}
SAMPLE = "Salut, c'est {name} ! Alors, tu comptes jouer correctement aujourd'hui ou je prépare déjà les excuses ?"

# (réglage, minimum, maximum, valeur neutre)
SLIDERS = (
    ("pitch", -12, 12, 0),  # demi-tons × 2
    ("rate", -50, 100, 0),  # %
    ("metal", 0, 100, 0),
    ("bright", 0, 100, 50),
    ("reverb", 0, 100, 0),
    ("volume", 0, 200, 100),
)
CATEGORIES = (
    ("all", "Toutes les voix"),
    ("mine", "🎛 Mes voix"),
    ("edge", "Microsoft Edge (gratuit)"),
    ("gemini", "Gemini 3.1"),
    ("openai", "ChatGPT (OpenAI)"),
    ("designed", "✨ Voix générées (Gemini 3.8)"),
    ("local", "Intégrées (sur ton PC)"),
)


def catalog() -> dict[str, list[tuple[str, str]]]:
    """{moteur: [(nom, libellé)]} des voix prédéfinies."""
    from alicia.ui.settings_page import EDGE_VOICES, GEMINI_VOICES, OPENAI_VOICES

    return {
        "edge": list(EDGE_VOICES),
        "gemini": [(n, f"{n} — {d}") for n, d in GEMINI_VOICES],
        "openai": list(OPENAI_VOICES),
        "kokoro": [("ff_siwis", "Siwis — femme, française")],
    }


BUILT_IN = (
    ("veris", "VIIRUS — petit robot", "la voix robot de VIIRUS, faite sur ton PC"),
    ("voixc", "ALICIA — voix C", "la voix d'ALICIA, faite sur ton PC"),
)


def value_text(key: str, value: int) -> str:
    if key == "pitch":
        return f"{value / 2:+g} demi-ton{'s' if abs(value) > 2 else ''}" if value else "naturelle"
    if key == "rate":
        return f"{100 + value} %" if value else "normale"
    if key == "bright":
        return "neutre" if value == 50 else f"{value} %"
    if key == "reverb":
        return f"{value} %" if value else "aucune"
    if key == "volume":
        return f"{value} %"
    return f"{value} %" if value else "aucun"


def _percent(rate: str) -> int:
    try:
        return int(str(rate).strip().rstrip("%"))
    except ValueError:
        return 0


def _muted(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("muted")
    label.setWordWrap(True)
    return label


def _chip(text: str, color: str) -> QLabel:
    chip = QLabel(text)
    chip.setStyleSheet(
        f"color:{color}; border:1px solid {color}; border-radius:8px; padding:1px 8px;"
        "font-size:8pt; font-weight:600;"
    )
    chip.setMaximumHeight(22)
    chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return chip


# --- ce qui est réglé dans un emplacement --------------------------------------------------


def slot_values(voice: VoiceSettings, slot: str) -> dict[str, object]:
    """Moteur, voix et réglages de la voix principale (``main``) ou de secours (``backup``)."""
    if slot == "main":
        engine = voice.tts_engine
        name = {
            "edge": voice.tts_voice,
            "gemini": voice.gemini_voice,
            "openai": voice.openai_voice,
            "kokoro": voice.kokoro_voice,
        }.get(engine, "")
        rate = (
            round((voice.kokoro_speed - 1) * 100)
            if engine in ("kokoro", "veris", "voixc")
            else _percent(voice.tts_rate)
        )
        return {
            "engine": engine,
            "voice": name,
            "label": voice.voice_name,
            "pitch": round(voice.fx_pitch * 2),
            "rate": rate,
            "metal": voice.fx_metal,
            "bright": voice.fx_bright,
            "reverb": voice.fx_reverb,
            "volume": voice.volume,
            "style": voice.voice_style,
        }
    from alicia.core.audio.speaker import split_backup

    engine, name = split_backup(voice.backup_voice)
    if engine == "custom":
        from alicia.core.audio.custom_voices import get_custom

        custom = get_custom(name)
        engine, name = (custom.engine, custom.voice) if custom else ("local", "")
    return {
        "engine": engine,
        "voice": name,
        "label": voice.backup_name,
        "pitch": round(voice.backup_pitch * 2),
        "rate": _percent(voice.backup_rate),
        "metal": voice.backup_metal,
        "bright": voice.backup_bright,
        "reverb": voice.backup_reverb,
        "volume": voice.backup_volume,
        "style": voice.backup_style,
    }


def voice_label(engine: str, name: str) -> str:
    """« Kore — femme — ferme », « ✨ VIIRUS (byR) »…"""
    if engine in ("veris", "voixc"):
        return next(label for key, label, _ in BUILT_IN if key == engine)
    if engine == "local" or (not name and engine not in ("veris", "voixc")):
        return "Voix robot du profil"
    if engine == "gemini" and name.startswith("voice_"):
        from alicia.core.audio.voice_design import voice_name

        return f"✨ {voice_name(name)}"
    return dict(catalog().get(engine, [])).get(name, name)


def is_tuned(values: dict[str, object]) -> bool:
    return bool(
        values["pitch"]
        or values["metal"]
        or values["bright"] != 50
        or values["reverb"]
        or values["style"]
    )


def describe(values: dict[str, object]) -> tuple[str, str, str]:
    """(nom, fournisseur, type) d'un emplacement."""
    engine, name = str(values["engine"]), str(values["voice"])
    k = kind(engine, name)
    label = str(values["label"] or "") or voice_label(engine, name).split(" — ")[0]
    if k in ("veris", "voixc", "local"):
        typ = "Intégrée"
    elif k == "designed":
        typ = "Sur mesure (voix générée)" + (" · retouchée" if is_tuned(values) else "")
    elif is_tuned(values) or values["label"]:
        typ = "Personnalisée"
    else:
        typ = "Prédéfinie"
    return label, PROVIDERS.get(k, k), typ


# --- éditeur de réglages (carte « Modifier », et créateur) ---------------------------------


class TuningEditor(QWidget):
    """Les réglages d'UNE voix, avec pour chacun : natif / sur ton PC / indisponible."""

    def __init__(self, on_change: Callable[[str, object], None] | None = None) -> None:
        super().__init__()
        self.on_change = on_change
        self._loading = False
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        self.rows: dict[str, tuple[QWidget, QLabel, QLabel, QLabel]] = {}
        for row, (key, low, high, _neutral) in enumerate(SLIDERS):
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(low, high)
            value = _muted("")
            value.setMinimumWidth(110)
            slider.valueChanged.connect(lambda v, k=key, lab=value: lab.setText(value_text(k, v)))
            slider.sliderReleased.connect(lambda k=key, s=slider: self._changed(k, s.value()))
            slider.valueChanged.connect(
                lambda v, k=key, s=slider: None if s.isSliderDown() else self._changed(k, v)
            )
            name = QLabel(LABELS[key])
            badge = QLabel()
            badge.setMaximumHeight(22)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            why = _muted("")
            grid.addWidget(name, row * 2, 0)
            grid.addWidget(slider, row * 2, 1)
            grid.addWidget(value, row * 2, 2)
            grid.addWidget(badge, row * 2, 3)
            grid.addWidget(why, row * 2 + 1, 1, 1, 3)
            self.rows[key] = (slider, name, badge, why)
        self.style = QLineEdit()
        self.style.setPlaceholderText(
            "ex. petit robot espiègle, joyeux, légèrement mécanique, débit dynamique"
        )
        self.style.editingFinished.connect(lambda: self._changed("style", self.style.text()))
        row = len(SLIDERS) * 2
        style_name, style_badge, style_why = QLabel(LABELS["style"]), QLabel(), _muted("")
        style_badge.setMaximumHeight(22)
        style_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(style_name, row, 0)
        grid.addWidget(self.style, row, 1, 1, 2)
        grid.addWidget(style_badge, row, 3)
        grid.addWidget(style_why, row + 1, 1, 1, 3)
        self.rows["style"] = (self.style, style_name, style_badge, style_why)
        grid.setColumnStretch(1, 1)
        legend = QHBoxLayout()
        legend.addWidget(_chip("natif", GREEN))
        legend.addWidget(QLabel("fait par le fournisseur"))
        legend.addSpacing(12)
        legend.addWidget(_chip("sur ton PC", theme.CYAN))
        legend.addWidget(QLabel("appliqué au son reçu, gratuit, sans quota"))
        legend.addStretch(1)
        grid.addLayout(legend, row + 2, 0, 1, 4)

    def _changed(self, key: str, value: object) -> None:
        if not self._loading and self.on_change is not None:
            self.on_change(key, value)

    def show_caps(self, engine: str, voice: str) -> None:
        for key, (state, reason) in capabilities(engine, voice).items():
            widget, name, badge, why = self.rows[key]
            on = state != "off"
            widget.setEnabled(on)
            name.setEnabled(on)
            if state == "native":
                badge.setText("natif")
                badge.setStyleSheet(_chip("", GREEN).styleSheet())
            elif state == "local":
                badge.setText("sur ton PC")
                badge.setStyleSheet(_chip("", theme.CYAN).styleSheet())
            else:
                badge.setText("indisponible")
                badge.setStyleSheet(_chip("", GREY).styleSheet())
            why.setText(("⛔ " if not on else "ℹ ") + reason if reason else "")
            why.setVisible(bool(reason))

    def load(self, values: dict[str, object]) -> None:
        self._loading = True
        try:
            for key, *_ in SLIDERS:
                slider = self.rows[key][0]
                slider.setValue(int(values[key]))  # type: ignore[attr-defined, call-overload]
            self.style.setText(str(values.get("style") or ""))
        finally:
            self._loading = False
        self._refresh_texts()

    def _refresh_texts(self) -> None:
        layout = self.layout()
        assert isinstance(layout, QGridLayout)
        for row, (key, *_rest) in enumerate(SLIDERS):
            item = layout.itemAtPosition(row * 2, 2)
            slider = self.rows[key][0]
            if item is not None and isinstance(item.widget(), QLabel):
                item.widget().setText(value_text(key, slider.value()))  # type: ignore[attr-defined, union-attr]

    def values(self) -> dict[str, object]:
        out: dict[str, object] = {key: self.rows[key][0].value() for key, *_ in SLIDERS}  # type: ignore[attr-defined]
        out["style"] = self.style.text().strip() if self.style.isEnabled() else ""
        return out

    def reset(self) -> None:
        self.load({key: neutral for key, _low, _high, neutral in SLIDERS} | {"style": ""})


# --- carte d'un emplacement -----------------------------------------------------------------


class SlotCard(QFrame):
    def __init__(self, slot: str, emit: Callable[[str, object], None], panel: VoicePanel) -> None:
        super().__init__()
        self.slot, self.emit, self.panel = slot, emit, panel
        color = SLOT_COLORS[slot]
        self.setObjectName("voiceCard")
        self.setStyleSheet(
            f"QFrame#voiceCard {{ border:1px solid {color}; border-radius:12px;"
            f" background: rgba(10, 18, 58, 0.55); }}"
        )
        box = QVBoxLayout(self)
        box.setContentsMargins(16, 12, 16, 14)
        box.setSpacing(6)
        head = QHBoxLayout()
        title = QLabel("VOIX PRINCIPALE" if slot == "main" else "VOIX DE SECOURS")
        title.setStyleSheet(f"color:{color}; font-weight:700; letter-spacing:2px;")
        head.addWidget(title)
        head.addStretch(1)
        self.status = QLabel("")
        head.addWidget(self.status)
        box.addLayout(head)
        self.name = QLabel("")
        self.name.setProperty("keep_names", True)  # « VIIRUS (byR) » reste tel quel
        self.name.setStyleSheet(f"color:{theme.TEXT}; font-size:15pt; font-weight:700;")
        self.name.setWordWrap(True)
        box.addWidget(self.name)
        self.meta = _muted("")
        box.addWidget(self.meta)
        self.note = _muted("")
        box.addWidget(self.note)
        buttons = QHBoxLayout()
        listen = QPushButton("▶ Écouter")
        listen.clicked.connect(lambda: emit("slot_preview", slot))
        self.edit = QPushButton("✎ Modifier")
        self.edit.setCheckable(True)
        self.edit.toggled.connect(lambda on: panel.open_editor(slot if on else ""))
        change = QPushButton("⇄ Changer")
        change.setObjectName("ghost")
        change.clicked.connect(lambda: panel.open_library(slot))
        for button in (listen, self.edit, change):
            buttons.addWidget(button)
        buttons.addStretch(1)
        box.addLayout(buttons)
        if slot == "backup":
            self.enabled = QCheckBox("Activer la voix de secours")
            self.enabled.setToolTip(
                "Oui : elle prend le relais quand la principale ne répond pas (quota épuisé, "
                "coupure, panne). Non : la réponse reste écrite si la principale échoue."
            )
            self.enabled.toggled.connect(lambda on: emit("backup_enabled", on))
            box.addWidget(self.enabled)

    def show_values(self, voice: VoiceSettings, in_use: bool) -> None:
        values = slot_values(voice, self.slot)
        name, provider, typ = describe(values)
        self.name.setText(name)
        self.meta.setText(f"{provider}  ·  {typ}")
        engine = str(values["engine"])
        missing = (engine == "gemini" and not voice.gemini_key) or (
            engine == "openai" and not voice.openai_key
        )
        note = ""
        if self.slot == "main":
            if missing:
                text, color = "● Clé manquante", RED
                note = "Ajoute la clé dans IA → Avancé → Gérer mes clés."
            elif in_use:
                text, color = "● En pause", ORANGE
                note = "Indisponible pour l'instant (quota ou coupure) : le secours parle."
            else:
                text, color = "● Active", GREEN
        else:
            self.enabled.blockSignals(True)
            self.enabled.setChecked(voice.backup_enabled)
            self.enabled.blockSignals(False)
            if not voice.backup_enabled:
                text, color = "○ Désactivée", GREY
            elif missing:
                text, color = "● Clé manquante", RED
                note = "Sans clé, c'est la voix robot du profil qui prendra le relais."
            elif in_use:
                text, color = "● En cours d'utilisation", ORANGE
                note = "Voix de secours en cours d'utilisation (la principale ne répond pas)."
            else:
                text, color = "● Prête (automatique)", GREEN
        self.status.setText(text)
        self.status.setStyleSheet(f"color:{color}; font-weight:600;")
        self.note.setText(note)
        self.note.setVisible(bool(note))


# --- le panneau complet ----------------------------------------------------------------------


class VoicePanel(QFrame):
    def __init__(self, emit: Callable[[str, object], None]) -> None:
        super().__init__()
        self.emit = emit
        self.voice: VoiceSettings | None = None
        self.in_use = False
        self.setObjectName("panel")
        box = QVBoxLayout(self)
        box.setContentsMargins(18, 14, 18, 16)
        box.setSpacing(12)
        title = QLabel("VOIX D'ALICIA")  # renommée pour VIIRUS
        title.setObjectName("sectionTitle")
        box.addWidget(title)
        general = QHBoxLayout()
        self.speak_box = QCheckBox("Lire les réponses à voix haute")
        self.speak_box.toggled.connect(lambda on: emit("speak_answers", on))
        general.addWidget(self.speak_box)
        general.addSpacing(18)
        general.addWidget(QLabel("Sortie"))
        self.output_box = QComboBox()
        self.output_box.currentIndexChanged.connect(
            lambda _i: emit("output_device", self.output_box.currentData())
        )
        general.addWidget(self.output_box, 1)
        self.test_button = QPushButton("Tester la voix")
        general.addWidget(self.test_button)
        box.addLayout(general)
        # Les deux voix, côte à côte
        cards = QHBoxLayout()
        cards.setSpacing(14)
        self.cards = {slot: SlotCard(slot, emit, self) for slot in ("main", "backup")}
        cards.addWidget(self.cards["main"], 1)
        cards.addWidget(self.cards["backup"], 1)
        box.addLayout(cards)
        # Modifier : réglages de la voix ouverte
        self.editor_frame = QFrame()
        self.editor_frame.setObjectName("voiceEditor")
        editor_box = QVBoxLayout(self.editor_frame)
        editor_box.setContentsMargins(16, 12, 16, 12)
        editor_head = QHBoxLayout()
        self.editor_title = QLabel("")
        editor_head.addWidget(self.editor_title)
        editor_head.addStretch(1)
        save_mine = QPushButton("💾 Garder dans Mes voix")
        save_mine.setObjectName("ghost")
        save_mine.setToolTip("Enregistre cette voix et ses réglages dans Mes voix (bibliothèque)")
        save_mine.clicked.connect(lambda: emit("slot_to_library", self.editing))
        reset = QPushButton("Réinitialiser")
        reset.setObjectName("ghost")
        reset.setToolTip("Remet les réglages de cette voix à zéro")
        reset.clicked.connect(lambda: emit("slot_reset", self.editing))
        close = QPushButton("Fermer")
        close.setObjectName("ghost")
        close.clicked.connect(lambda: self.open_editor(""))
        for button in (save_mine, reset, close):
            editor_head.addWidget(button)
        editor_box.addLayout(editor_head)
        self.editor_info = _muted("")
        editor_box.addWidget(self.editor_info)
        self.editor = TuningEditor(lambda k, v: emit("slot_edit", (self.editing, k, v)))
        editor_box.addWidget(self.editor)
        self.editor_frame.setVisible(False)
        self.editing = ""
        box.addWidget(self.editor_frame)
        # Bibliothèque
        library_head = QHBoxLayout()
        library_title = QLabel("BIBLIOTHÈQUE DE VOIX")
        library_title.setObjectName("sectionTitle")
        library_head.addWidget(library_title)
        library_head.addStretch(1)
        self.browse_button = QPushButton("📚 Parcourir les voix")
        self.browse_button.setCheckable(True)
        self.browse_button.toggled.connect(self._show_library)
        self.create_button = QPushButton("✨ Créer une voix")
        self.create_button.setCheckable(True)
        self.create_button.toggled.connect(self._show_creator)
        library_head.addWidget(self.browse_button)
        library_head.addWidget(self.create_button)
        box.addLayout(library_head)
        self.library = self._build_library()
        self.library.setVisible(False)
        box.addWidget(self.library)
        self.creator = self._build_creator()
        self.creator.setVisible(False)
        box.addWidget(self.creator)
        self.state = _muted("")  # messages (écoute, erreurs, enregistrement)
        box.addWidget(self.state)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_status)
        self.timer.start(2000)

    # --- cartes ------------------------------------------------------------------------------

    def load(self, voice: VoiceSettings) -> None:
        self.voice = voice
        self.speak_box.blockSignals(True)
        self.speak_box.setChecked(voice.speak_answers)
        self.speak_box.blockSignals(False)
        self.refresh_status(force=True)
        if self.editing:
            self._load_editor()
        self._mark_library()

    def refresh_status(self, force: bool = False) -> None:
        if self.voice is None or (not force and not self.isVisible()):
            return  # minuteur : rien à rafraîchir quand l'onglet n'est pas affiché
        from alicia.core.audio.speaker import backup_in_use

        self.in_use = backup_in_use()
        for card in self.cards.values():
            card.show_values(self.voice, self.in_use)

    def open_editor(self, slot: str) -> None:
        self.editing = slot
        for name, card in self.cards.items():
            card.edit.blockSignals(True)
            card.edit.setChecked(name == slot)
            card.edit.blockSignals(False)
        self.editor_frame.setVisible(bool(slot))
        if slot:
            color = SLOT_COLORS[slot]
            self.editor_frame.setStyleSheet(
                f"QFrame#voiceEditor {{ border:1px solid {color}; border-radius:12px; }}"
            )
            self._load_editor()

    def _load_editor(self) -> None:
        if self.voice is None or not self.editing:
            return
        values = slot_values(self.voice, self.editing)
        name, provider, _typ = describe(values)
        color = SLOT_COLORS[self.editing]
        which = "VOIX PRINCIPALE" if self.editing == "main" else "VOIX DE SECOURS"
        self.editor_title.setText(f"✎ MODIFIER — {which} : {name}")
        self.editor_title.setStyleSheet(f"color:{color}; font-weight:700;")
        self.editor_info.setText(
            f"Ces réglages ne concernent que la {which.lower()} ({provider}). Ils "
            "s'appliquent tout de suite ; ▶ Écouter sur la carte pour entendre le rendu réel."
        )
        self.editor.show_caps(str(values["engine"]), str(values["voice"]))
        self.editor.load(values)

    # --- bibliothèque ------------------------------------------------------------------------

    def _show_library(self, on: bool) -> None:
        self.library.setVisible(on)
        if on:
            self.create_button.setChecked(False)
            self.refresh_library()

    def _show_creator(self, on: bool) -> None:
        self.creator.setVisible(on)
        if on:
            self.browse_button.setChecked(False)

    def open_library(self, slot: str) -> None:
        self.browse_button.setChecked(True)
        which = "principale" if slot == "main" else "de secours"
        button = "Principale" if slot == "main" else "Secours"
        self.library_hint.setText(f"⇄ Choisis la nouvelle voix {which} : bouton « {button} ».")
        self.library_hint.setVisible(True)

    def _build_library(self) -> QWidget:
        holder = QFrame()
        box = QVBoxLayout(holder)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(8)
        self.library_hint = QLabel("")
        self.library_hint.setStyleSheet(f"color:{ORANGE}; font-weight:600;")
        self.library_hint.setVisible(False)
        box.addWidget(self.library_hint)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("🔎 Rechercher (nom, homme, femme, robot…)")
        self.search.textChanged.connect(lambda _t: self._filter())
        self.category = QComboBox()
        for key, label in CATEGORIES:
            self.category.addItem(label, key)
        self.category.currentIndexChanged.connect(lambda _i: self._filter())
        filters.addWidget(self.search, 1)
        filters.addWidget(self.category)
        box.addLayout(filters)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setMinimumHeight(320)
        scroll.setMaximumHeight(460)
        inner = QWidget()
        self.rows_box = QVBoxLayout(inner)
        self.rows_box.setContentsMargins(0, 0, 8, 0)
        self.rows_box.setSpacing(4)
        self.rows_box.addStretch(1)
        scroll.setWidget(inner)
        box.addWidget(scroll)
        self.row_widgets: list[tuple[QWidget, str, str]] = []  # (ligne, catégorie, texte)
        self.main_buttons: dict[str, QPushButton] = {}
        self.backup_buttons: dict[str, QPushButton] = {}
        return holder

    def refresh_library(self) -> None:
        from alicia.core.audio import voice_design
        from alicia.core.audio.custom_voices import load_custom

        for widget, _cat, _text in self.row_widgets:
            widget.deleteLater()
        self.row_widgets.clear()
        self.main_buttons.clear()
        self.backup_buttons.clear()
        entries: list[tuple[str, str, str, str, str]] = []  # catégorie, clé, nom, fournisseur, desc
        for voice in load_custom():
            base = voice_label(voice.engine, voice.voice).split(" — ")[0]
            entries.append(
                (
                    "mine",
                    f"custom|{voice.id}",
                    voice.name,
                    PROVIDERS.get(kind(voice.engine, voice.voice), voice.engine),
                    f"à partir de {base}" + (f" · « {voice.style} »" if voice.style else ""),
                )
            )
        for voice in voice_design.load_voices():
            entries.append(
                (
                    "designed",
                    f"gemini|{voice.id}",
                    f"✨ {voice.name}",
                    PROVIDERS["designed"],
                    voice.description[:90],
                )
            )
        for engine in ("edge", "gemini", "openai"):
            for name, label in catalog()[engine]:
                short, _, desc = label.partition(" — ")
                entries.append((engine, f"{engine}|{name}", short, PROVIDERS[engine], desc))
        for engine, label, desc in BUILT_IN:
            entries.append(("local", f"{engine}|", label, PROVIDERS[engine], desc))
        for cat, key, name, provider, desc in entries:
            self._add_row(cat, key, name, provider, desc)
        self._filter()
        self._mark_library()

    def _add_row(self, cat: str, key: str, name: str, provider: str, desc: str) -> None:
        row = QFrame()
        row.setObjectName("voiceRow")
        row.setStyleSheet(
            f"QFrame#voiceRow {{ border-bottom:1px solid {theme.BORDER}; }}"
            f"QFrame#voiceRow:hover {{ background: rgba(34, 227, 255, 0.06); }}"
        )
        line = QHBoxLayout(row)
        line.setContentsMargins(6, 4, 6, 4)
        text = QVBoxLayout()
        title = QLabel(name)
        title.setProperty("keep_names", True)
        title.setStyleSheet(f"color:{theme.TEXT}; font-weight:600;")
        text.addWidget(title)
        meta = _muted(f"{provider}" + (f" · {desc}" if desc else ""))
        text.addWidget(meta)
        line.addLayout(text, 1)
        listen = QPushButton("▶")
        listen.setToolTip("Écouter")
        listen.setFixedWidth(44)
        if key.startswith("custom|"):
            listen.clicked.connect(lambda _=False, k=key: self.emit("custom_listen", k[7:]))
        else:
            listen.clicked.connect(lambda _=False, k=key: self.emit("voice_preview", k))
        line.addWidget(listen)
        for slot, label, store in (
            ("main", "Principale", self.main_buttons),
            ("backup", "Secours", self.backup_buttons),
        ):
            button = QPushButton(label)
            button.setObjectName("ghost")
            button.setMinimumWidth(118)
            button.clicked.connect(lambda _=False, s=slot, k=key: self.emit("slot_assign", (s, k)))
            line.addWidget(button)
            store[key] = button
        if cat in ("mine", "designed"):
            edit = QPushButton("✏️")
            edit.setFixedWidth(40)
            delete = QPushButton("✕")
            delete.setFixedWidth(40)
            if cat == "mine":
                voice_id = key[7:]
                edit.setToolTip("Modifier (dans « Créer une voix »)")
                edit.clicked.connect(lambda _=False, v=voice_id: self.edit_custom(v))
                delete.setToolTip("Supprimer de Mes voix")
                delete.clicked.connect(lambda _=False, v=voice_id: self.emit("custom_delete", v))
            else:
                voice_id = key.split("|", 1)[1]
                edit.setToolTip("Renommer")
                edit.clicked.connect(lambda _=False, v=voice_id: self.emit("voice_rename", v))
                delete.setToolTip("Supprimer (aussi chez Google)")
                delete.clicked.connect(lambda _=False, v=voice_id: self.emit("voice_delete", v))
            line.addWidget(edit)
            line.addWidget(delete)
        self.rows_box.insertWidget(self.rows_box.count() - 1, row)
        haystack = f"{name} {provider} {desc}".casefold()
        self.row_widgets.append((row, cat, haystack))

    def _filter(self) -> None:
        cat = self.category.currentData()
        words = self.search.text().casefold().split()
        for row, row_cat, haystack in self.row_widgets:
            shown = (cat == "all" or cat == row_cat) and all(w in haystack for w in words)
            row.setVisible(shown)

    def _slot_key(self, slot: str) -> str:
        if self.voice is None:
            return ""
        values = slot_values(self.voice, slot)
        engine, name = str(values["engine"]), str(values["voice"])
        if engine in ("veris", "voixc"):
            return f"{engine}|"
        from alicia.core.audio.custom_voices import load_custom

        label = str(values["label"] or "")
        for custom in load_custom():  # une de Mes voix, choisie telle quelle
            if custom.name == label and custom.engine == engine and custom.voice == name:
                return f"custom|{custom.id}"
        return f"{engine}|{name}"

    def _mark_library(self) -> None:
        for slot, store, label in (
            ("main", self.main_buttons, "Principale"),
            ("backup", self.backup_buttons, "Secours"),
        ):
            chosen = self._slot_key(slot)
            for key, button in store.items():
                button.setText(f"✓ {label}" if key == chosen else label)

    # --- créer une voix ----------------------------------------------------------------------

    def _build_creator(self) -> QWidget:
        holder = QFrame()
        holder.setObjectName("voiceEditor")
        holder.setStyleSheet(
            f"QFrame#voiceEditor {{ border:1px solid {theme.PINK}; border-radius:12px; }}"
        )
        box = QVBoxLayout(holder)
        box.setContentsMargins(16, 12, 16, 14)
        box.setSpacing(8)
        mode = QHBoxLayout()
        self.mode_tune = QPushButton("🎛 Régler une voix existante")
        self.mode_new = QPushButton("✨ Générer une nouvelle voix (Gemini 3.8)")
        for button in (self.mode_tune, self.mode_new):
            button.setCheckable(True)
            mode.addWidget(button)
        mode.addStretch(1)
        box.addLayout(mode)
        self.mode_tune.setChecked(True)
        self.mode_tune.clicked.connect(lambda: self._creator_mode("tune"))
        self.mode_new.clicked.connect(lambda: self._creator_mode("new"))
        # --- Régler une voix existante
        self.tune_box = QWidget()
        tune = QVBoxLayout(self.tune_box)
        tune.setContentsMargins(0, 0, 0, 0)
        tune.addWidget(
            _muted(
                "Part d'une voix qui existe déjà (Edge, Gemini, ChatGPT, Kokoro) et applique tes "
                "réglages : rien n'est créé chez le fournisseur."
            )
        )
        step = self._step
        tune.addWidget(step("1", "Voix de base"))
        base = QHBoxLayout()
        self.cv_engine = QComboBox()
        for key, label in (
            ("edge", "Microsoft Edge (gratuit)"),
            ("gemini", "Gemini 3.1 (ta clé)"),
            ("openai", "ChatGPT (ta clé OpenAI)"),
            ("kokoro", "Kokoro (sur ton PC)"),
        ):
            self.cv_engine.addItem(label, key)
        self.cv_voice = QComboBox()
        self.cv_engine.currentIndexChanged.connect(lambda _i: self._cv_fill_voices())
        base.addWidget(self.cv_engine)
        base.addWidget(self.cv_voice, 1)
        tune.addLayout(base)
        tune.addWidget(step("2", "Réglages"))
        start = QHBoxLayout()
        start.addWidget(QLabel("Point de départ"))
        self.cv_start = QComboBox()
        for key, label in (
            ("", "Naturel"),
            ("masculin", "♂ Masculin"),
            ("feminin", "♀ Féminin"),
            ("enfant", "✨ Jeune"),
            ("robot", "🤖 Robot"),
            ("robote", "🤖 Petite robote"),
            ("robot_enfant", "🤖 Petit robot"),
            ("gros_robot", "🦾 Gros robot"),
        ):
            self.cv_start.addItem(label, key)
        self.cv_start.currentIndexChanged.connect(lambda _i: self._cv_preset())
        start.addWidget(self.cv_start, 1)
        tune.addLayout(start)
        self.cv_editor = TuningEditor()
        tune.addWidget(self.cv_editor)
        tune.addWidget(step("3", "Écouter"))
        listen = QPushButton("▶ Écouter le résultat")
        listen.clicked.connect(lambda: self.emit("custom_preview", self.custom_draft()))
        tune.addWidget(listen, 0, Qt.AlignmentFlag.AlignLeft)
        tune.addWidget(step("4", "Nom"))
        self.cv_name = QLineEdit()
        self.cv_name.setPlaceholderText("ex. VIIRUS — Robot espiègle")
        tune.addWidget(self.cv_name)
        tune.addWidget(step("5", "Enregistrer et utiliser"))
        save_row = QHBoxLayout()
        for label, use, primary in (
            ("💾 Enregistrer seulement", "", False),
            ("💾 + Voix principale", "main", True),
            ("💾 + Voix de secours", "backup", False),
        ):
            button = QPushButton(label)
            if primary:
                button.setObjectName("primary")
            button.clicked.connect(lambda _=False, u=use: self._cv_save(u))
            save_row.addWidget(button)
        fresh = QPushButton("Nouvelle")
        fresh.setObjectName("ghost")
        fresh.clicked.connect(self.reset_creator)
        save_row.addWidget(fresh)
        save_row.addStretch(1)
        tune.addLayout(save_row)
        box.addWidget(self.tune_box)
        # --- Générer une nouvelle voix (Gemini 3.8)
        self.new_box = QWidget()
        self._designed_form(self.new_box)
        self.new_box.setVisible(False)
        box.addWidget(self.new_box)
        self._cv_editing = ""
        self._cv_fill_voices()
        self.cv_editor.reset()
        self.cv_editor.show_caps("edge", "")
        return holder

    @staticmethod
    def _step(number: str, text: str) -> QLabel:
        label = QLabel(f"{number} · {text.upper()}")
        label.setStyleSheet(f"color:{theme.PINK_SOFT}; font-weight:700; letter-spacing:1px;")
        return label

    def _creator_mode(self, mode: str) -> None:
        self.mode_tune.setChecked(mode == "tune")
        self.mode_new.setChecked(mode == "new")
        self.tune_box.setVisible(mode == "tune")
        self.new_box.setVisible(mode == "new")

    def _designed_form(self, holder: QWidget) -> None:
        from alicia.core.audio.voice_design import PRESETS

        box = QVBoxLayout(holder)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(
            _muted(
                "Crée une TOUTE NOUVELLE voix chez Google à partir d'une description (âge "
                "apparent, timbre, énergie, accent) : un nouvel actif vocal, gardé un an dans "
                "ton projet Google. Elle compte sur le quota Gemini 3.8. Ensuite, elle apparaît "
                "dans la bibliothèque (✨ Voix générées)."
            )
        )
        top = QHBoxLayout()
        self.design_preset = QComboBox()
        self.design_preset.setProperty("keep_names", True)
        for label in PRESETS:
            self.design_preset.addItem(label, label)
        self.design_name = QLineEdit()
        self.design_name.setPlaceholderText("Nom, ex. VIIRUS (byR)")
        top.addWidget(QLabel("Modèle"))
        top.addWidget(self.design_preset, 1)
        top.addWidget(self.design_name, 1)
        box.addLayout(top)
        self.design_text = QPlainTextEdit()
        self.design_text.setObjectName("field")
        self.design_text.setFixedHeight(80)
        box.addWidget(self.design_text)

        def preset(_i: int = 0) -> None:
            label = self.design_preset.currentData()
            self.design_text.setPlainText(PRESETS.get(label, ""))
            self.design_name.setText(str(label).split(" — ")[0] + " (sur mesure)")

        self.design_preset.currentIndexChanged.connect(preset)
        preset()
        row = QHBoxLayout()
        self.design_button = QPushButton("✨ Générer et écouter")
        self.design_button.setObjectName("primary")
        self.design_button.clicked.connect(
            lambda: self.emit(
                "voice_design", (self.design_name.text(), self.design_text.toPlainText())
            )
        )
        row.addWidget(self.design_button)
        self.design_state = _muted("")
        row.addWidget(self.design_state, 1)
        box.addLayout(row)

    def _cv_fill_voices(self, chosen: str = "") -> None:
        engine = self.cv_engine.currentData()
        self.cv_voice.clear()
        for name, label in catalog().get(engine, []):
            self.cv_voice.addItem(label, name)
        self.cv_voice.setCurrentIndex(max(0, self.cv_voice.findData(chosen)))
        self.cv_editor.show_caps(engine, "")

    def _cv_preset(self) -> None:
        from alicia.core.audio.speaker import FX_PRESETS

        pitch, metal, bright = FX_PRESETS.get(self.cv_start.currentData(), (0.0, 0, 50))
        values = self.cv_editor.values()
        values.update(pitch=round(pitch * 2), metal=metal, bright=bright)
        self.cv_editor.load(values)

    def custom_draft(self) -> dict[str, object]:
        values = self.cv_editor.values()
        return {
            "id": self._cv_editing,
            "name": self.cv_name.text().strip(),
            "engine": self.cv_engine.currentData(),
            "voice": self.cv_voice.currentData() or "",
            "pitch": int(values["pitch"]) / 2,  # type: ignore[call-overload]
            "metal": values["metal"],
            "bright": values["bright"],
            "reverb": values["reverb"],
            "rate": values["rate"],
            "volume": values["volume"],
            "style": values["style"],
        }

    def _cv_save(self, use: str) -> None:
        if not self.cv_name.text().strip():
            self.cv_name.setText(f"{self.cv_voice.currentText().split(' — ')[0]} perso")
        self.emit("custom_save", self.custom_draft() | {"use": use})

    def reset_creator(self) -> None:
        self._cv_editing = ""
        self.cv_name.clear()
        self.cv_start.blockSignals(True)
        self.cv_start.setCurrentIndex(0)
        self.cv_start.blockSignals(False)
        self.cv_editor.reset()

    def edit_custom(self, voice_id: str) -> None:
        """✏️ d'une de Mes voix : elle revient dans « Créer une voix » pour être retouchée."""
        from alicia.core.audio.custom_voices import get_custom

        voice = get_custom(voice_id)
        if voice is None:
            return
        self.create_button.setChecked(True)
        self._creator_mode("tune")
        self._cv_editing = voice.id
        self.cv_engine.blockSignals(True)
        self.cv_engine.setCurrentIndex(max(0, self.cv_engine.findData(voice.engine)))
        self.cv_engine.blockSignals(False)
        self._cv_fill_voices(voice.voice)
        self.cv_start.blockSignals(True)
        self.cv_start.setCurrentIndex(0)
        self.cv_start.blockSignals(False)
        self.cv_editor.load(
            {
                "pitch": round(voice.pitch * 2),
                "rate": voice.rate,
                "metal": voice.metal,
                "bright": voice.bright,
                "reverb": voice.reverb,
                "volume": voice.volume,
                "style": voice.style,
            }
        )
        self.cv_name.setText(voice.name)
        self.state.setText(f"✏️ « {voice.name} » : retouche-la, puis 💾 Enregistrer.")
