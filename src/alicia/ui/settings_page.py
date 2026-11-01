"""Onglet « Réglages » : micro, voix d'ALICIA, IA, démarrage et raccourcis, au même endroit.

Chaque changement est appliqué tout de suite et enregistré dans %APPDATA%\\Alicia\\alicia.toml.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from alicia.core.config import VoiceSettings
from alicia.core.persona import PERSONAS
from alicia.core.persona import current as current_persona
from alicia.ui.shortcuts_page import ShortcutsPage
from alicia.ui.theme import PROJECT_NAME

EDGE_VOICES = (
    ("fr-FR-DeniseNeural", "Denise (France) — femme, douce"),
    ("fr-FR-VivienneMultilingualNeural", "Vivienne (France) — femme, naturelle"),
    ("fr-FR-EloiseNeural", "Éloïse (France) — voix d'enfant"),
    ("fr-FR-HenriNeural", "Henri (France) — homme"),
    ("fr-FR-RemyMultilingualNeural", "Rémy (France) — homme, naturel"),
    ("fr-CA-SylvieNeural", "Sylvie (Québec) — femme"),
    ("fr-CA-AntoineNeural", "Antoine (Québec) — homme"),
    ("fr-CA-JeanNeural", "Jean (Québec) — homme"),
    ("fr-CA-ThierryNeural", "Thierry (Québec) — homme"),
    ("fr-BE-CharlineNeural", "Charline (Belgique) — femme"),
    ("fr-BE-GerardNeural", "Gérard (Belgique) — homme"),
    ("fr-CH-ArianeNeural", "Ariane (Suisse) — femme"),
    ("fr-CH-FabriceNeural", "Fabrice (Suisse) — homme"),
)
# Voix Gemini (mêmes 30 voix pour toutes les langues) : genre et style donnés par Google
GEMINI_VOICES = (
    ("Leda", "femme — jeune"),
    ("Zephyr", "femme — lumineuse"),
    ("Kore", "femme — ferme"),
    ("Aoede", "femme — légère"),
    ("Callirrhoe", "femme — décontractée"),
    ("Autonoe", "femme — lumineuse"),
    ("Despina", "femme — fluide"),
    ("Erinome", "femme — claire"),
    ("Laomedeia", "femme — enjouée"),
    ("Achernar", "femme — douce"),
    ("Gacrux", "femme — mûre"),
    ("Pulcherrima", "femme — directe"),
    ("Vindemiatrix", "femme — tendre"),
    ("Sulafat", "femme — chaleureuse"),
    ("Puck", "homme — enjoué"),
    ("Fenrir", "homme — excité"),
    ("Charon", "homme — informatif"),
    ("Orus", "homme — ferme"),
    ("Enceladus", "homme — soufflé"),
    ("Iapetus", "homme — clair"),
    ("Umbriel", "homme — décontracté"),
    ("Algieba", "homme — fluide"),
    ("Algenib", "homme — rocailleux"),
    ("Rasalgethi", "homme — informatif"),
    ("Alnilam", "homme — ferme"),
    ("Schedar", "homme — posé"),
    ("Achird", "homme — amical"),
    ("Zubenelgenubi", "homme — détendu"),
    ("Sadachbia", "homme — vif"),
    ("Sadaltager", "homme — savant"),
)
OPENAI_VOICES = (
    ("coral", "Coral — chaleureuse"),
    ("nova", "Nova — jeune et vive"),
    ("shimmer", "Shimmer — douce"),
    ("sage", "Sage — calme"),
    ("marin", "Marin — naturelle"),
    ("ballad", "Ballad — expressive"),
    ("alloy", "Alloy — neutre"),
    ("verse", "Verse — dynamique"),
    ("cedar", "Cedar — voix grave"),
)
SENSITIVITY = {
    1: "Peu sensible (pièce bruyante, casque ouvert)",
    2: "Plutôt peu sensible",
    3: "Normale",
    4: "Sensible",
    5: "Très sensible (micro éloigné, voix basse)",
}


def rate_percent(rate: str) -> int:
    """« +8% » → 8."""
    match = re.fullmatch(r"\s*([+-]?\d+)\s*%\s*", rate or "")
    return int(match.group(1)) if match else 0


def _title(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("sectionTitle")
    return label


def _collapsible(title: str, body: QWidget) -> QWidget:
    """Section repliable : « ▸ Avancé » ouvre / ferme le panneau ``body``."""
    holder = QWidget()
    box = QVBoxLayout(holder)
    box.setContentsMargins(0, 0, 0, 0)
    box.setSpacing(6)
    toggle = QPushButton(f"▸  {title}")
    toggle.setObjectName("ghost")
    toggle.setCheckable(True)
    toggle.setStyleSheet("text-align: left;")
    body.setVisible(False)

    def flip(on: bool) -> None:
        body.setVisible(on)
        toggle.setText(f"{'▾' if on else '▸'}  {title}")

    toggle.toggled.connect(flip)
    box.addWidget(toggle, 0, Qt.AlignmentFlag.AlignLeft)
    box.addWidget(body)
    holder.toggle = toggle  # type: ignore[attr-defined]
    return holder


def _muted(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("muted")
    label.setWordWrap(True)
    return label


def _panel() -> tuple[QFrame, QGridLayout]:
    frame = QFrame()
    frame.setObjectName("panel")
    grid = QGridLayout(frame)
    grid.setContentsMargins(18, 14, 18, 16)
    grid.setHorizontalSpacing(16)
    grid.setVerticalSpacing(10)
    grid.setColumnStretch(1, 1)
    return frame, grid


TABS = (
    ("general", "⚙️  Général"),
    ("copilot", "💡  Copilote"),
    ("profile", "👤  Profil"),
    ("ai", "🧠  IA"),
    ("perception", "👀  Perception"),
    ("games", "▦  Jeux"),
    ("social", "👥  Social"),
    ("stream", "🎥  Stream"),
)
# Anciens noms d'onglets (avant la réorganisation) → nouvel onglet
TAB_ALIASES = {
    "voice": "profile",
    "vision": "perception",
    "keys": "general",
    "duo": "social",
    "people": "social",
}


class SettingsPage(QWidget):
    setting_changed = Signal(str, object)  # (réglage, valeur)
    test_mic = Signal()
    test_voice = Signal()
    open_ai = Signal()

    def __init__(
        self,
        shortcuts: ShortcutsPage,
        input_devices: Callable[[], list[str]] | None = None,
        output_devices: Callable[[], list[str]] | None = None,
    ) -> None:
        super().__init__()
        self._input_devices = input_devices or (lambda: [])
        self._output_devices = output_devices or (lambda: [])
        self._loading = False
        # Onglets en haut, une page courte par thème (Général en premier)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        bar = QHBoxLayout()
        bar.setSpacing(4)
        self.tab_buttons: dict[str, QPushButton] = {}
        self.stack = QStackedWidget()
        self.tabs: dict[str, QWidget] = {}
        self._tab_layouts: dict[str, QVBoxLayout] = {}
        for key, label in TABS:
            button = QPushButton(label)
            button.setObjectName("settingsTab")
            button.setCheckable(True)
            button.clicked.connect(lambda _=False, k=key: self.show_tab(k))
            bar.addWidget(button)
            self.tab_buttons[key] = button
            if key == "games":
                continue  # page ajoutée par la fenêtre principale (add_tab)
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setFrameShape(QFrame.Shape.NoFrame)
            area.setStyleSheet(
                "QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }"
            )
            host = QWidget()
            tab_layout = QVBoxLayout(host)
            tab_layout.setContentsMargins(0, 14, 8, 0)
            tab_layout.setSpacing(14)
            area.setWidget(host)
            self.stack.addWidget(area)
            self.tabs[key] = area
            self._tab_layouts[key] = tab_layout
        bar.addStretch(1)
        line = QFrame()
        line.setObjectName("settingsLine")
        line.setFixedHeight(1)
        outer.addLayout(bar)
        outer.addWidget(line)
        outer.addWidget(self.stack, 1)

        # --- Profil ------------------------------------------------------------------------------
        profile, grid = _panel()
        grid.addWidget(_title(f"PROFIL {PROJECT_NAME}"), 0, 0, 1, 3)
        self.persona_box = QComboBox()
        for persona in PERSONAS.values():
            self.persona_box.addItem(persona.title, persona.key)
        self.persona_box.setCurrentIndex(max(0, self.persona_box.findData(current_persona().key)))
        self.persona_box.setProperty(
            "keep_names", True
        )  # « ALICIA » et « VIIRUS », jamais renommés
        self.persona_box.currentIndexChanged.connect(
            lambda _i: self._emit("persona", self.persona_box.currentData())
        )
        grid.addWidget(QLabel("Profil"), 1, 0)
        grid.addWidget(self.persona_box, 1, 1)
        grid.addWidget(
            _muted(
                "Nom, portrait, couleurs, voix, mot de réveil, icône et raccourci du bureau "
                "(redémarrage)."
            ),
            1,
            2,
        )
        self.player_name = QLineEdit()
        self.player_name.setPlaceholderText("ton prénom ou pseudo, ex. Redemptiion")
        self.player_name.setMaxLength(40)
        self.player_name.editingFinished.connect(
            lambda: self._emit("player_name", self.player_name.text())
        )
        self.player_phonetic = QLineEdit()
        self.player_phonetic.setPlaceholderText(
            "comment le dire, ex. Rédemm-chionne (vide si la voix le dit bien)"
        )
        self.player_phonetic.setMaxLength(60)
        self.player_phonetic.editingFinished.connect(
            lambda: self._emit("player_phonetic", self.player_phonetic.text())
        )
        listen = QPushButton("Écouter")
        listen.clicked.connect(lambda: self._emit("player_test", True))
        grid.addWidget(QLabel("Ton nom"), 2, 0)
        grid.addWidget(self.player_name, 2, 1)
        grid.addWidget(_muted("l'IA sait qui tu es et t'appelle par ton nom"), 2, 2)
        grid.addWidget(QLabel("Prononciation"), 3, 0)
        grid.addWidget(self.player_phonetic, 3, 1)
        grid.addWidget(listen, 3, 2)
        self.personality_state = _muted("")
        self.personality_state.setProperty("keep_names", True)
        personality_buttons = QHBoxLayout()
        for text, key in (
            ("Charger un .md…", "personality_load"),
            ("Modifier", "personality_edit"),
            ("Retirer", "personality_remove"),
        ):
            button = QPushButton(text)
            button.clicked.connect(lambda _=False, k=key: self._emit(k, True))
            personality_buttons.addWidget(button)
        grid.addWidget(QLabel("Personnalité"), 4, 0)
        grid.addWidget(self.personality_state, 4, 1)
        grid.addLayout(personality_buttons, 4, 2)
        self.player_name.setProperty("keep_names", True)
        self.player_phonetic.setProperty("keep_names", True)
        grid.setColumnStretch(2, 1)
        self._tab_layouts["profile"].addWidget(profile)

        anims_panel, grid = _panel()
        grid.addWidget(_title("ANIMATIONS DU ROBOT"), 0, 0, 1, 3)
        self.anims_folder = QLineEdit()
        self.anims_folder.setReadOnly(True)
        open_folder = QPushButton("Ouvrir le dossier")
        open_folder.clicked.connect(lambda: self._emit("overlay_folder", True))
        reload_anims = QPushButton("Recharger")
        reload_anims.clicked.connect(lambda: self._emit("anims_reload", True))
        grid.addWidget(QLabel("Dossier"), 1, 0)
        grid.addWidget(self.anims_folder, 1, 1)
        grid.addWidget(open_folder, 1, 2)
        self.anims_state = _muted("")
        grid.addWidget(self.anims_state, 2, 1)
        grid.addWidget(reload_anims, 2, 2)
        anims_help = _muted(
            "Dépose tes animations dans ce dossier puis clique <b>Recharger</b>. Images "
            "<b>carrées 512 × 512</b>, centrées sur le robot, en <b>.webp animé</b> (ou .gif). "
            "États en boucle : <b>idle</b>, <b>listening</b>, <b>thinking</b>, <b>speaking</b>, "
            "<b>action</b>, <b>error</b>. Gestes joués une fois : <b>wake</b>, <b>nod</b>, "
            "<b>shake</b>, <b>hop</b>, <b>spin</b>, <b>wiggle</b>, <b>look</b>. Bouche qui suit "
            "la voix : <b>speaking_0.png</b> (fermée), <b>speaking_1.png</b>, "
            "<b>speaking_2.png</b>. Seul <b>idle</b> est indispensable ; ce qui manque garde le "
            "portrait."
        )
        anims_help.setTextFormat(Qt.TextFormat.RichText)
        grid.addWidget(anims_help, 3, 0, 1, 3)
        self._tab_layouts["profile"].addWidget(anims_panel)

        # --- Vision ------------------------------------------------------------------------------
        vision, grid = _panel()
        grid.addWidget(_title("VISION"), 0, 0, 1, 3)
        self.vision_box = QComboBox()
        self.vision_box.addItem("L'application (le jeu au premier plan)", "window")
        self.vision_box.addItem("Autour du curseur de la souris", "cursor")
        self.vision_box.addItem("L'écran entier", "screen")
        grid.addWidget(QLabel("ALICIA regarde"), 1, 0)
        grid.addWidget(self.vision_box, 1, 1, 1, 2)
        self.box_size = QComboBox()
        for size, label in (
            ("800x500", "Petite (800 × 500)"),
            ("1280x800", "Moyenne (1280 × 800)"),
            ("1920x1080", "Grande (1920 × 1080)"),
        ):
            self.box_size.addItem(label, size)
        grid.addWidget(QLabel("Zone du curseur"), 2, 0)
        grid.addWidget(self.box_size, 2, 1, 1, 2)
        self.live_box = QCheckBox(
            "Vision en direct : l'écran du moment où tu parles est déjà prêt (pas besoin de F9)"
        )
        self.live_interval = QComboBox()
        for seconds, label in (
            (5.0, "Quand tu parles + toutes les 5 s"),
            (10.0, "Quand tu parles + toutes les 10 s"),
            (30.0, "Quand tu parles + toutes les 30 s"),
        ):
            self.live_interval.addItem(label, seconds)
        grid.addWidget(self.live_box, 4, 0, 1, 2)
        grid.addWidget(self.live_interval, 4, 2)
        grid.addWidget(
            _muted(
                "Les images restent en mémoire sur ton PC : rien n'est envoyé à l'IA tant que tu "
                "ne lui parles pas."
            ),
            5,
            0,
            1,
            3,
        )
        grid.addWidget(
            _muted(
                "Autour du curseur : pointe un objet, un sort ou un texte avec la souris et "
                "demande « c'est quoi ça ? » ; un cercle rose montre à l'IA ce que tu désignes. "
                "Écran entier : utile avec plusieurs fenêtres (guide, carte, chat)."
            ),
            3,
            0,
            1,
            3,
        )
        self._tab_layouts["perception"].addWidget(vision)

        # --- Mémoire de partie ---------------------------------------------------------------
        memory, grid = _panel()
        grid.addWidget(_title("MÉMOIRE DE PARTIE"), 0, 0, 1, 3)
        self.memory_box = QCheckBox(
            "Garder de petites captures datées pour « il y a une heure… », « tout à l'heure… »"
        )
        grid.addWidget(self.memory_box, 1, 0, 1, 3)
        self.memory_interval = QComboBox()
        for seconds, label in (
            (15.0, "Toutes les 15 s"),
            (30.0, "Toutes les 30 s"),
            (60.0, "Toutes les minutes"),
        ):
            self.memory_interval.addItem(label, seconds)
        self.memory_hours = QComboBox()
        for hours, label in (
            (2.0, "2 heures"),
            (8.0, "8 heures"),
            (20.0, "20 heures"),
            (48.0, "2 jours"),
            (168.0, "7 jours"),
            (720.0, "30 jours"),
        ):
            self.memory_hours.addItem(label, hours)
        self.memory_size = QComboBox()
        for size, label in (
            (2.0, "2 Go"),
            (5.0, "5 Go"),
            (20.0, "20 Go"),
            (100.0, "100 Go"),
            (500.0, "500 Go"),
        ):
            self.memory_size.addItem(label, size)
        pick = QPushButton("Choisir un disque / dossier…")
        pick.clicked.connect(lambda: self.setting_changed.emit("memory_folder_pick", True))
        default_folder = QPushButton("Dossier par défaut")
        default_folder.setObjectName("ghost")
        default_folder.clicked.connect(lambda: self.setting_changed.emit("memory_folder", ""))
        grid.addWidget(QLabel("Une image"), 2, 0)
        grid.addWidget(self.memory_interval, 2, 1, 1, 2)
        grid.addWidget(QLabel("Gardées pendant"), 3, 0)
        grid.addWidget(self.memory_hours, 3, 1, 1, 2)
        self.memory_clear_exit = QCheckBox("Tout effacer à la fermeture d'ALICIA")
        grid.addWidget(QLabel("Place maximale"), 4, 0)
        grid.addWidget(self.memory_size, 4, 1, 1, 2)
        grid.addWidget(QLabel("Emplacement"), 5, 0)
        grid.addWidget(pick, 5, 1)
        grid.addWidget(default_folder, 5, 2)
        grid.addWidget(self.memory_clear_exit, 7, 0, 1, 3)
        self.memory_usage = _muted("")
        clear_now = QPushButton("Effacer maintenant")
        clear_now.clicked.connect(lambda: self.setting_changed.emit("memory_clear", True))
        grid.addWidget(self.memory_usage, 8, 0, 1, 2)
        grid.addWidget(clear_now, 8, 2)
        grid.addWidget(
            _muted(
                "Images réduites (environ 100 Ko), sur ton PC seulement, prises pendant la vision "
                "en direct. Nettoyage automatique au lancement et toutes les heures, et jamais "
                "plus de 10 000 images. Elles ne partent à l'IA que si ta question parle du passé. "
                "Avec un disque dédié, choisis-le dans « Emplacement » et monte la durée et la place."
            ),
            9,
            0,
            1,
            3,
        )
        self._tab_layouts["perception"].addWidget(memory)

        # --- Micro -------------------------------------------------------------------------------
        mic, grid = _panel()
        grid.addWidget(_title("MICRO"), 0, 0, 1, 3)
        self.input_box = QComboBox()
        grid.addWidget(QLabel("Micro"), 1, 0)
        grid.addWidget(self.input_box, 1, 1, 1, 2)
        self.mic_level = QProgressBar()
        self.mic_level.setRange(0, 100)
        self.mic_level.setTextVisible(False)
        self.mic_level.setFixedHeight(10)
        self.mic_test = QPushButton("Tester le micro (3 s)")
        self.mic_test.clicked.connect(self.test_mic.emit)
        grid.addWidget(self.mic_test, 2, 0)
        grid.addWidget(self.mic_level, 2, 1, 1, 2)
        self.mic_result = _muted("Parle pendant le test : ALICIA te dit ce qu'elle a compris.")
        grid.addWidget(self.mic_result, 3, 0, 1, 3)
        self.wake_box = QCheckBox("Réveil vocal : commencer sa phrase par « Alicia »")
        grid.addWidget(self.wake_box, 4, 0, 1, 3)
        self.sensitivity = QSlider(Qt.Orientation.Horizontal)
        self.sensitivity.setRange(1, 5)
        self.sensitivity.setPageStep(1)
        self.sensitivity.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.sensitivity_label = _muted("")
        grid.addWidget(QLabel("Sensibilité"), 5, 0)
        grid.addWidget(self.sensitivity, 5, 1)
        grid.addWidget(self.sensitivity_label, 5, 2)
        grid.addWidget(
            _muted(
                "Si ALICIA se réveille toute seule (jeu, amis en vocal), baisse la sensibilité ; "
                "si elle ne t'entend pas dire « Alicia », monte-la."
            ),
            6,
            0,
            1,
            3,
        )
        self._tab_layouts["perception"].addWidget(mic)

        # --- Voix --------------------------------------------------------------------------------
        voice, grid = _panel()
        grid.addWidget(_title("VOIX D'ALICIA"), 0, 0, 1, 3)  # renommée pour VIIRUS
        self.speak_box = QCheckBox("Lire les réponses à voix haute")
        grid.addWidget(self.speak_box, 1, 0, 1, 3)
        self.engine_box = QComboBox()
        self.engine_box.addItem("Edge — voix Microsoft en ligne (plus naturelle)", "edge")
        self.engine_box.addItem("Kokoro — voix sur ton PC (hors ligne)", "kokoro")
        self.engine_box.addItem("OpenAI — voix très réaliste (clé OpenAI, payant)", "openai")
        self.engine_box.addItem("Gemini — 30 voix expressives (ta clé Gemini)", "gemini")
        self.engine_box.addItem("VIIRUS — sa voix de petit garçon robot (sur ton PC)", "veris")
        self.engine_box.addItem("ALICIA — voix C, petite fille (sur ton PC)", "voixc")
        grid.addWidget(QLabel("Moteur"), 2, 0)
        grid.addWidget(self.engine_box, 2, 1, 1, 2)
        self.voice_box = QComboBox()
        for name, label in EDGE_VOICES:
            self.voice_box.addItem(label, name)
        self.voice_label = QLabel("Voix")
        grid.addWidget(self.voice_label, 3, 0)
        grid.addWidget(self.voice_box, 3, 1, 1, 2)
        self.openai_voice_box = QComboBox()
        for name, label in OPENAI_VOICES:
            self.openai_voice_box.addItem(label, name)
        grid.addWidget(self.openai_voice_box, 3, 1, 1, 2)
        self.gemini_voice_box = QComboBox()
        for name, label in GEMINI_VOICES:
            self.gemini_voice_box.addItem(f"{name} — {label}", name)
        grid.addWidget(self.gemini_voice_box, 3, 1, 1, 2)
        self.speed = QSlider(Qt.Orientation.Horizontal)
        self.speed.setRange(-20, 40)
        self.speed.setSingleStep(2)
        self.speed_label = _muted("")
        grid.addWidget(QLabel("Vitesse"), 4, 0)
        grid.addWidget(self.speed, 4, 1)
        grid.addWidget(self.speed_label, 4, 2)
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 200)
        self.volume.setSingleStep(5)
        self.volume.setPageStep(10)
        self.volume_label = _muted("100 %")
        self.volume.valueChanged.connect(lambda v: self.volume_label.setText(f"{v} %"))
        self.volume.sliderReleased.connect(lambda: self._emit("volume", self.volume.value()))
        self.volume.valueChanged.connect(
            lambda v: None if self.volume.isSliderDown() else self._emit("volume", v)
        )
        grid.addWidget(QLabel("Volume"), 7, 0)
        grid.addWidget(self.volume, 7, 1)
        grid.addWidget(self.volume_label, 7, 2)
        grid.addWidget(
            _muted(
                "Volume de la voix du robot seulement (100 % = normal). Si on ne l'entend presque "
                "pas, vérifie aussi le mélangeur de volume de Windows."
            ),
            8,
            0,
            1,
            3,
        )
        self.output_box = QComboBox()
        grid.addWidget(QLabel("Sortie"), 5, 0)
        grid.addWidget(self.output_box, 5, 1, 1, 2)
        self.voice_test = QPushButton("Tester la voix")
        self.voice_test.clicked.connect(self.test_voice.emit)
        grid.addWidget(self.voice_test, 6, 0)
        self._tab_layouts["profile"].addWidget(voice)
        self._tab_layouts["profile"].addWidget(self._voice_gallery())

        # --- Stream ---------------------------------------------------------------------------------
        stream, grid = _panel()
        grid.addWidget(_title("STREAM"), 0, 0, 1, 3)
        self.twitch_input = QLineEdit()
        self.twitch_input.setPlaceholderText("ta chaîne, ex. nova_jagger")
        self.twitch_input.editingFinished.connect(
            lambda: self._emit("twitch_channel", self.twitch_input.text())
        )
        self.twitch_button = QPushButton("Ouvrir le chat Twitch")
        self.twitch_button.clicked.connect(lambda: self._emit("twitch_open", True))
        grid.addWidget(QLabel("Chaîne Twitch"), 1, 0)
        grid.addWidget(self.twitch_input, 1, 1)
        grid.addWidget(self.twitch_button, 1, 2)
        self.twitch_state = _muted("")
        grid.addWidget(self.twitch_state, 2, 1, 1, 2)
        self.overlay_box = QCheckBox("ALICIA sur le stream : page à ajouter dans OBS")
        self.overlay_box.toggled.connect(lambda on: self._emit("overlay", on))
        grid.addWidget(self.overlay_box, 3, 0, 1, 3)
        self.overlay_url = QLineEdit()
        self.overlay_url.setReadOnly(True)
        copy = QPushButton("Copier l'adresse")
        copy.clicked.connect(lambda: self._emit("overlay_copy", True))
        preview = QPushButton("Aperçu")
        preview.clicked.connect(lambda: self._emit("overlay_preview", True))
        anims = QPushButton("Dossier des animations")
        anims.clicked.connect(lambda: self._emit("overlay_folder", True))
        grid.addWidget(QLabel("Adresse"), 4, 0)
        grid.addWidget(self.overlay_url, 4, 1)
        grid.addWidget(copy, 4, 2)
        grid.addWidget(preview, 5, 1)
        grid.addWidget(anims, 5, 2)
        obs_help = _muted(
            "Dans OBS : Sources → + → <b>Navigateur</b> → colle l'adresse, largeur et hauteur "
            "600 × 600 (le fond est déjà transparent). Elle flotte, bouge toute seule, "
            "s'allume quand elle écoute, réfléchit ou parle, et ses réponses s'affichent en "
            "sous-titres.<br>Options à ajouter à l'adresse : <b>?size=200</b> (taille), "
            "<b>&amp;bulle=0</b> (sans sous-titres), <b>&amp;side=top</b> (sous-titres "
            "au-dessus), <b>&amp;roam=1</b> (elle se promène : mets la source en 1920 × 1080)."
            "<br>Animations : voir Réglages → Profil → Animations (les mêmes fichiers servent "
            "au rond de l'appli et à OBS)."
        )
        obs_help.setTextFormat(Qt.TextFormat.RichText)
        grid.addWidget(obs_help, 6, 0, 1, 3)
        self._tab_layouts["stream"].addWidget(stream)

        # --- Duo -----------------------------------------------------------------------------------
        duo, grid = _panel()
        grid.addWidget(_title("SESSION / DUO : DEUX ROBOTS QUI SE PARLENT"), 0, 0, 1, 3)
        me = current_persona()
        other = next((p for p in PERSONAS.values() if p.key != me.key), me)
        self.duo_box = QCheckBox(
            f"Activer le duo (ex. {me.title} chez toi, {other.title} chez ton pote)"
        )
        self.duo_box.setProperty("keep_names", True)
        self.duo_box.toggled.connect(lambda on: self._emit("duo", on))
        grid.addWidget(self.duo_box, 1, 0, 1, 3)
        self.duo_code = QLineEdit()
        self.duo_code.setEchoMode(QLineEdit.EchoMode.Password)
        self.duo_code.setPlaceholderText("le même code sur les deux PC")
        self.duo_code.editingFinished.connect(lambda: self._emit("duo_code", self.duo_code.text()))
        code_buttons = QHBoxLayout()
        new_code = QPushButton("Nouveau code")
        new_code.clicked.connect(lambda: self._emit("duo_new_code", True))
        copy_code = QPushButton("Copier")
        copy_code.clicked.connect(lambda: self._emit("duo_copy_code", True))
        code_buttons.addWidget(new_code)
        code_buttons.addWidget(copy_code)
        grid.addWidget(QLabel("Code de duo"), 2, 0)
        grid.addWidget(self.duo_code, 2, 1)
        grid.addLayout(code_buttons, 2, 2)
        self.duo_turns = QComboBox()
        for turns in (2, 4, 6):
            self.duo_turns.addItem(f"{turns} répliques", turns)
        self.duo_turns.currentIndexChanged.connect(
            lambda _i: self._emit("duo_turns", self.duo_turns.currentData())
        )
        self.duo_start = QPushButton("Envoyer un message…")
        self.duo_start.clicked.connect(lambda: self._emit("duo_start", True))
        grid.addWidget(QLabel("Longueur"), 3, 0)
        grid.addWidget(self.duo_turns, 3, 1)
        grid.addWidget(self.duo_start, 3, 2)
        self.duo_state = _muted("")
        grid.addWidget(self.duo_state, 4, 1, 1, 2)
        self.duo_hear = QCheckBox("Entendre l'autre robot sur mon PC, avec sa voix")
        self.duo_hear.toggled.connect(lambda on: self._emit("duo_hear", on))
        grid.addWidget(self.duo_hear, 6, 0, 1, 3)
        self.duo_chat = QCheckBox(
            "Autoriser les robots à discuter entre eux (sinon ils transmettent seulement)"
        )
        self.duo_chat.toggled.connect(lambda on: self._emit("duo_allow_chat", on))
        grid.addWidget(self.duo_chat, 8, 0, 1, 3)
        self.duo_ai = QComboBox()
        self.duo_ai.currentIndexChanged.connect(
            lambda _i: self._emit("duo_ai", str(self.duo_ai.currentData() or "main|"))
        )
        grid.addWidget(QLabel("IA du duo"), 10, 0)
        grid.addWidget(self.duo_ai, 10, 1, 1, 2)
        duo_help = _muted(
            "Crée un code ici, envoie-le à ton pote (en privé), il le colle chez lui.<br>"
            f"<b>Porte-parole</b> : « {me.name}, demande à {other.name} ce que fait ton pote » → "
            f"{other.title} le dit à ton pote ; il répond « {other.name}, réponds-lui que… ».<br>"
            f"<b>Discussion entre robots</b> (si autorisée) : « {me.name}, discute avec "
            f"{other.name} de WoW ». « Stop » l'arrête des deux côtés.<br>"
            "Les messages sont chiffrés avec ce code et passent par un relais gratuit "
            "(ntfy.sh). Un message de l'autre robot ne peut jamais agir sur ton PC."
        )
        duo_help.setTextFormat(Qt.TextFormat.RichText)
        duo_help.setProperty("keep_names", True)
        grid.addWidget(duo_help, 11, 0, 1, 3)
        self._tab_layouts["social"].addWidget(duo)

        # --- Général -------------------------------------------------------------------------------
        # --- IA & clés : cerveau rapide / cerveau réfléchi ------------------------------------
        self.brain_labels: dict[str, dict[str, QLabel]] = {}

        def brain_card(kind: str, title: str) -> QGridLayout:
            from alicia.core.ai.prompts import BRAIN_ROLES

            card, grid = _panel()
            grid.addWidget(_title(title), 0, 0, 1, 3)
            labels = {
                "provider": QLabel("—"),
                "model": QLabel("—"),
                "state": _muted("● pas encore testé"),
            }
            self.brain_labels[kind] = labels
            grid.addWidget(QLabel("Fournisseur"), 1, 0)  # liste ajoutée par l'appelant
            grid.addWidget(QLabel("Modèle"), 2, 0)
            grid.addWidget(labels["model"], 2, 1)
            roles = {
                "rapide": (
                    "Conversation",
                    "Réactions",
                    "Vision rapide",
                    "Mode Copilote",
                    "Réponses simples",
                ),
                "reflechi": (
                    "Analyse complexe",
                    "Build",
                    "Comparaison",
                    "Stratégie",
                    "Recherche",
                    "Raisonnement",
                ),
            }[kind]
            chips = QHBoxLayout()
            chips.setSpacing(6)
            for role in roles:
                chip = QLabel(role)
                chip.setObjectName("chip")
                chips.addWidget(chip)
            chips.addStretch(1)
            grid.addWidget(QLabel("Rôle"), 3, 0)
            grid.addLayout(chips, 3, 1, 1, 2)
            chips.itemAt(0).widget().setToolTip(BRAIN_ROLES[kind])
            show_prompt = QPushButton("Voir le prompt")
            show_prompt.clicked.connect(lambda _=False: self._emit("brain_prompt", kind))
            grid.addWidget(QLabel("Prompt"), 4, 0)
            grid.addWidget(
                _muted("personnalité du profil + règles + consignes de ce cerveau"), 4, 1
            )
            grid.addWidget(show_prompt, 4, 2)
            test = QPushButton("Tester")
            test.clicked.connect(lambda _=False: self._emit("brain_test", kind))
            grid.addWidget(QLabel("État"), 5, 0)
            grid.addWidget(labels["state"], 5, 1)
            grid.addWidget(test, 5, 2)
            self._tab_layouts["ai"].addWidget(card)
            return grid

        # Fournisseur de chaque cerveau : Gemini, ChatGPT ou Ollama (modèles Ollama plus bas)
        grid = brain_card("rapide", "⚡  CERVEAU RAPIDE")
        self.ai_label = self.brain_labels["rapide"]["provider"]
        self.fast_box = QComboBox()
        for key, label in (
            ("gemini", "Gemini (en ligne, rien sur ton PC) — conseillé en jeu"),
            ("openai", "ChatGPT (en ligne)"),
            ("ollama", "Ollama sur ton PC (modèle choisi plus bas)"),
        ):
            self.fast_box.addItem(label, key)
        self.fast_box.currentIndexChanged.connect(
            lambda _i: self._emit("fast_provider", self.fast_box.currentData())
        )
        grid.addWidget(self.fast_box, 1, 1, 1, 2)

        grid = brain_card("reflechi", "🧠  CERVEAU RÉFLÉCHI")
        self.deep_box = QComboBox()
        for key, label in (
            ("", "Aucun : le cerveau rapide répond à tout"),
            ("gemini", "Gemini (en ligne, rien sur ton PC) — conseillé en jeu"),
            ("openai", "ChatGPT (en ligne, réflexion moyenne)"),
            ("ollama", "Ollama sur ton PC (modèle choisi plus bas, plutôt hors jeu)"),
        ):
            self.deep_box.addItem(label, key)
        self.deep_box.currentIndexChanged.connect(
            lambda _i: self._emit("deep_provider", self.deep_box.currentData())
        )
        self.deep_model = QLineEdit()
        self.deep_model.setPlaceholderText("autre modèle (optionnel)")
        self.deep_model.setToolTip("Vide = le modèle conseillé de ce fournisseur")
        self.deep_model.editingFinished.connect(
            lambda: self._emit("deep_model", self.deep_model.text())
        )
        grid.addWidget(self.deep_box, 1, 1)
        grid.addWidget(self.deep_model, 2, 2)

        # --- Ollama : les modèles locaux des deux cerveaux --------------------------------------
        ollama, grid = _panel()
        grid.addWidget(_title("🖥  OLLAMA (SUR TON PC)"), 0, 0, 1, 3)

        def ollama_box(choices, key: str) -> QComboBox:  # type: ignore[no-untyped-def]
            box = QComboBox()
            box.setEditable(True)
            for name, label in choices:
                box.addItem(label, name)
            box.activated.connect(lambda _i: self._emit(key, self._combo_value(box)))
            box.lineEdit().editingFinished.connect(lambda: self._emit(key, self._combo_value(box)))
            return box

        self.ollama_model = ollama_box(
            (
                ("qwen2.5vl:7b", "qwen2.5vl:7b — 6 Go, voit bien l'écran"),
                ("qwen3-vl:8b", "qwen3-vl:8b — 6 Go, plus récent"),
                ("lfm3-omni:2b", "lfm3-omni:2b — 2,4 Go, ultra rapide, réflexion limitée"),
            ),
            "ollama_model",
        )
        self.ollama_deep_model = ollama_box(
            (
                ("qwen3.8:27b", "qwen3.8:27b — 18 Go, réfléchit bien (hors jeu)"),
                ("qwen3-vl:8b", "qwen3-vl:8b — 6 Go, tient à côté d'un jeu"),
                ("qwen2.5vl:7b", "qwen2.5vl:7b — 6 Go"),
            ),
            "ollama_deep_model",
        )
        self.ollama_states: dict[str, QLabel] = {}
        for row, (label, box, kind) in enumerate(
            (
                ("⚡ Cerveau rapide", self.ollama_model, "rapide"),
                ("🧠 Cerveau réfléchi", self.ollama_deep_model, "reflechi"),
            ),
            start=1,
        ):
            grid.addWidget(QLabel(label), row, 0)
            grid.addWidget(box, row, 1)
            self.ollama_states[kind] = _muted("")
            grid.addWidget(self.ollama_states[kind], row, 2)
        grid.addWidget(
            _muted(
                "Ces modèles servent seulement au cerveau réglé sur « Ollama » au-dessus. Tu peux "
                "taper le nom d'un autre modèle : il est téléchargé tout seul au besoin."
            ),
            3,
            0,
            1,
            3,
        )
        self._ai_ollama = ollama

        routing, grid = _panel()
        grid.addWidget(_title("QUI RÉPOND ?"), 0, 0, 1, 3)
        grid.addWidget(
            _muted(
                "Le profil choisi garde toujours sa personnalité et sa voix : seul le cerveau "
                "change. Par défaut, le <b>cerveau rapide</b> répond. Une question avec "
                "« analyse », « stratégie », « build », « compare », « réfléchis », « pourquoi », "
                "« plan », « meilleure option », « comment battre »… part au <b>cerveau "
                "réfléchi</b>. Sous chaque réponse, on voit lequel a répondu, et le journal "
                "note « [VIIRUS] [Cerveau rapide] modèle, durée, raison du routage ».<br>"
                "En jeu, préfère Gemini ou ChatGPT pour le réfléchi : un gros modèle Ollama "
                "(18 Go) ne tient pas en VRAM à côté du jeu et ferait chauffer le processeur. "
                "Plusieurs clés par fournisseur : bouton « + » dans la fenêtre des clés ; l'IA "
                "du duo se choisit dans l'onglet Social."
            ),
            1,
            0,
            1,
            3,
        )
        for label in routing.findChildren(QLabel):
            label.setTextFormat(Qt.TextFormat.RichText)
        self._tab_layouts["ai"].addWidget(routing)

        # Avancé (replié) : clés API, modèles Ollama
        advanced_ai = QWidget()
        advanced_box = QVBoxLayout(advanced_ai)
        advanced_box.setContentsMargins(0, 0, 0, 0)
        advanced_box.setSpacing(14)
        keys_panel, grid = _panel()
        grid.addWidget(_title("🔑  CLÉS API"), 0, 0, 1, 3)
        change_ai = QPushButton("Gérer mes clés (Gemini, ChatGPT)…")
        change_ai.clicked.connect(self.open_ai.emit)
        grid.addWidget(change_ai, 1, 0)
        grid.addWidget(
            _muted(
                "Plusieurs clés par fournisseur (bouton « + »), test de la clé, choix de la clé "
                "active. Elles restent dans %APPDATA%\\Alicia\\.env, jamais affichées."
            ),
            1,
            1,
            1,
            2,
        )
        advanced_box.addWidget(keys_panel)
        advanced_box.addWidget(self._ai_ollama)
        self._tab_layouts["ai"].addWidget(_collapsible("Avancé : clés API et Ollama", advanced_ai))

        general, grid = _panel()
        grid.addWidget(_title("DÉMARRAGE"), 0, 0, 1, 3)
        self.mode_box = QComboBox()
        self.mode_box.addItem("Seulement le rond d'ALICIA (mode bulle)", "orb")
        self.mode_box.addItem("Le panneau complet", "full")
        self.mode_box.addItem("Comme je l'ai laissé la dernière fois", "last")
        grid.addWidget(QLabel("Au lancement"), 2, 0)
        grid.addWidget(self.mode_box, 2, 1, 1, 2)
        self._tab_layouts["general"].addWidget(general)
        self._tab_layouts["general"].addWidget(self._orb_panel())

        # Visible en stream : rangé dans l'onglet Stream
        stream_visibility, grid = _panel()
        grid.addWidget(_title("VISIBILITÉ"), 0, 0, 1, 3)
        self.stream_box = QCheckBox(
            "Visible en stream : OBS / Discord montrent le rond et la bulle"
        )
        self.stream_box.toggled.connect(lambda on: self._emit("stream_visible", on))
        grid.addWidget(self.stream_box, 1, 0, 1, 3)
        grid.addWidget(
            _muted(
                "Coupé : ils sont invisibles pour les captures. Activé en vision « écran entier » "
                "ou « curseur », l'IA peut aussi les voir sur l'image."
            ),
            2,
            0,
            1,
            3,
        )
        self._tab_layouts["stream"].insertWidget(0, stream_visibility)

        update_panel, grid = _panel()
        grid.addWidget(_title("MISE À JOUR"), 0, 0, 1, 3)
        self.github_token = QLineEdit()
        self.github_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.github_token.setPlaceholderText("seulement si le dépôt est privé (github_pat_…)")
        save_token = QPushButton("Enregistrer")
        save_token.clicked.connect(lambda: self._emit("github_token", self.github_token.text()))
        self.channel_box = QComboBox()
        self.channel_box.addItem("Stable : la version normale", "alice-v0.3")
        self.channel_box.addItem(
            "Test : les nouveautés en essai (peut avoir des bugs)", "alice-test"
        )
        self.channel_box.currentIndexChanged.connect(
            lambda _i: self._emit("update_channel", self.channel_box.currentData())
        )
        self.version_label = _muted("")
        grid.addWidget(QLabel("Version"), 1, 0)
        grid.addWidget(self.version_label, 1, 1, 1, 2)
        grid.addWidget(QLabel("Canal MAJ"), 2, 0)
        grid.addWidget(self.channel_box, 2, 1, 1, 2)
        grid.addWidget(
            _muted("Change de canal puis clique MAJ. Tu peux revenir sur Stable quand tu veux."),
            3,
            1,
            1,
            2,
        )
        grid.addWidget(QLabel("Jeton MAJ"), 4, 0)
        grid.addWidget(self.github_token, 4, 1)
        grid.addWidget(save_token, 4, 2)
        self.github_state = _muted("")
        grid.addWidget(self.github_state, 5, 1, 1, 2)
        self._update_panel = update_panel

        copilot, grid = _panel()
        grid.addWidget(_title("ACTIVATION"), 0, 0, 1, 3)
        self.copilot_box = QCheckBox(
            "Activer le Mode Copilote : il parle de lui-même quand ça vaut le coup"
        )
        self.copilot_box.toggled.connect(lambda on: self._emit("copilot", on))
        grid.addWidget(self.copilot_box, 1, 0, 1, 3)
        grid.addWidget(
            _muted(
                "Aussi avec le bouton 💡 Copilote en haut, le menu de la bulle, ou à la voix : "
                "« active le copilote » / « désactive le copilote »."
            ),
            2,
            0,
            1,
            3,
        )
        self._tab_layouts["copilot"].addWidget(copilot)

        rhythm, grid = _panel()
        grid.addWidget(_title("SPONTANÉITÉ ET RYTHME"), 0, 0, 1, 3)
        self.copilot_spontaneity = QComboBox()
        for key, text in (
            ("discret", "🤫 Discret : seulement ce qui compte vraiment"),
            ("normal", "🙂 Normal : conseils utiles et quelques réactions (conseillé)"),
            ("bavard", "😄 Bavard : il commente plus souvent"),
            ("perso", "Personnalisé (réglé dans Avancé)"),
        ):
            self.copilot_spontaneity.addItem(text, key)
        self.copilot_spontaneity.currentIndexChanged.connect(
            lambda _i: self._emit("copilot_spontaneity", self.copilot_spontaneity.currentData())
        )
        self.copilot_interval = QComboBox()
        for seconds in (15, 20, 30, 45, 60, 90, 120):
            self.copilot_interval.addItem(f"toutes les {seconds} s", float(seconds))
        self.copilot_cooldown = QComboBox()
        for seconds in (20, 30, 60, 90, 120, 180, 300):
            label = (
                f"{seconds} s"
                if seconds < 60
                else f"{seconds // 60} min" + (" 30" if seconds % 60 else "")
            )
            self.copilot_cooldown.addItem(label, float(seconds))
        for row, (label, box, key) in enumerate(
            (
                ("Spontanéité", self.copilot_spontaneity, ""),
                ("Observation", self.copilot_interval, "copilot_interval_s"),
                ("Silence entre deux", self.copilot_cooldown, "copilot_cooldown_s"),
            ),
            start=1,
        ):
            grid.addWidget(QLabel(label), row, 0)
            grid.addWidget(box, row, 1, 1, 2)
            if key:
                box.currentIndexChanged.connect(
                    lambda _i, b=box, k=key: self._emit(k, b.currentData())
                )
        grid.addWidget(
            _muted(
                "Observation : un coup d'œil à l'écran par le cerveau rapide (une requête à l'IA "
                "à chaque fois). Silence : temps minimum entre deux interventions ; une vraie "
                "urgence passe quand même. Il se tait toujours quand tu parles."
            ),
            4,
            0,
            1,
            3,
        )
        self._tab_layouts["copilot"].addWidget(rhythm)

        kinds_panel, grid = _panel()
        grid.addWidget(_title("TYPES D'INTERVENTIONS"), 0, 0, 1, 3)
        self.copilot_kinds: dict[str, QCheckBox] = {}
        for index, (key, text) in enumerate(
            (
                ("conseils", "💡 Conseils : astuces utiles maintenant"),
                ("alertes", "⚠️ Alertes : danger ou erreur à éviter"),
                ("reactions", "✨ Réactions spontanées : exploit, surprise, moment épique"),
                ("humour", "😂 Humour : une remarque drôle sur la situation"),
                ("trashtalk", "🔥 Trash-talk : il te chambre (rarement)"),
                ("duo", "🤝 Interaction avec le Duo : remarques pour tes coéquipiers"),
            )
        ):
            box = QCheckBox(text)
            box.toggled.connect(self._kinds_changed)
            self.copilot_kinds[key] = box
            grid.addWidget(box, 1 + index // 2, index % 2)
        self.copilot_trash = QComboBox()
        for key, text in (
            ("off", "Désactivé"),
            ("leger", "Léger : taquineries gentilles"),
            ("normal", "Normal : il chambre franchement"),
            ("corse", "Corsé : piquant, mais jamais méchant"),
        ):
            self.copilot_trash.addItem(text, key)
        self.copilot_trash.currentIndexChanged.connect(
            lambda _i: self._emit("copilot_trash", self.copilot_trash.currentData())
        )
        grid.addWidget(QLabel("Trash-talk"), 4, 0)
        grid.addWidget(self.copilot_trash, 4, 1)
        grid.addWidget(
            _muted(
                "Pas de phrases toutes faites : il réagit à ce qu'il voit vraiment. Le trash-talk "
                "reste rare (pas à chaque mort), sans insulte ni attaque personnelle. Les "
                "réactions et l'humour sont plus espacés que les conseils."
            ),
            5,
            0,
            1,
            2,
        )
        self._tab_layouts["copilot"].addWidget(kinds_panel)

        advanced, grid = _panel()
        self.copilot_threshold = QComboBox()
        for level, text in (
            (9, "9 — seulement les urgences"),
            (8, "8 — Discret : urgences et vrais bons conseils"),
            (7, "7 — Normal : conseils utiles"),
            (6, "6 — un peu bavard"),
            (5, "5 — Bavard"),
        ):
            self.copilot_threshold.addItem(text, level)
        self.copilot_threshold.currentIndexChanged.connect(
            lambda _i: self._emit("copilot_threshold", self.copilot_threshold.currentData())
        )
        grid.addWidget(QLabel("Importance minimale"), 0, 0)
        grid.addWidget(self.copilot_threshold, 0, 1, 1, 2)
        grid.addWidget(
            _muted(
                "L'IA note chaque coup d'œil de 1 à 10 ; il parle à partir de cette note. "
                "Discret, Normal et Bavard règlent ce seuil pour toi."
            ),
            1,
            0,
            1,
            3,
        )
        self._tab_layouts["copilot"].addWidget(_collapsible("Avancé", advanced))

        # --- Raccourcis ---------------------------------------------------------------------------
        self.shortcuts = shortcuts
        self._tab_layouts["general"].addWidget(shortcuts)
        self._tab_layouts["general"].addWidget(self._update_panel)
        # Profil : identité, voix, catalogue, puis animations
        self._tab_layouts["profile"].removeWidget(anims_panel)
        self._tab_layouts["profile"].addWidget(anims_panel)
        # Perception : vision, micro, compréhension vocale, puis mémoire
        self._tab_layouts["perception"].removeWidget(memory)
        self._tab_layouts["perception"].addWidget(self._understanding_panel())
        self._tab_layouts["perception"].addWidget(memory)
        for tab_layout in self._tab_layouts.values():
            tab_layout.addStretch(1)
        self.show_tab("general")

        # Signaux (ignorés pendant le chargement des valeurs)
        self.input_box.currentIndexChanged.connect(
            lambda _i: self._emit("input_device", self.input_box.currentData())
        )
        self.wake_box.toggled.connect(lambda on: self._emit("wake_word", on))
        self.sensitivity.valueChanged.connect(self._sensitivity_changed)
        self.speak_box.toggled.connect(lambda on: self._emit("speak_answers", on))
        self.engine_box.currentIndexChanged.connect(self._engine_changed)
        self.voice_box.currentIndexChanged.connect(
            lambda _i: self._emit("tts_voice", self.voice_box.currentData())
        )
        self.gemini_voice_box.currentIndexChanged.connect(
            lambda _i: self._emit("gemini_voice", self.gemini_voice_box.currentData())
        )
        self.openai_voice_box.currentIndexChanged.connect(
            lambda _i: self._emit("openai_voice", self.openai_voice_box.currentData())
        )
        self.speed.valueChanged.connect(lambda v: self.speed_label.setText(f"{v:+d} %"))
        self.speed.sliderReleased.connect(lambda: self._emit("speed", self.speed.value()))
        self.output_box.currentIndexChanged.connect(
            lambda _i: self._emit("output_device", self.output_box.currentData())
        )
        self.vision_box.currentIndexChanged.connect(
            lambda _i: self._emit("vision", self.vision_box.currentData())
        )
        self.box_size.currentIndexChanged.connect(
            lambda _i: self._emit("cursor_box", self.box_size.currentData())
        )
        self.live_box.toggled.connect(lambda on: self._emit("live", on))
        self.memory_box.toggled.connect(lambda on: self._emit("memory", on))
        self.memory_interval.currentIndexChanged.connect(
            lambda _i: self._emit("memory_interval_s", self.memory_interval.currentData())
        )
        self.memory_hours.currentIndexChanged.connect(
            lambda _i: self._emit("memory_hours", self.memory_hours.currentData())
        )
        self.memory_clear_exit.toggled.connect(lambda on: self._emit("memory_clear_on_exit", on))
        self.memory_size.currentIndexChanged.connect(
            lambda _i: self._emit("memory_max_gb", self.memory_size.currentData())
        )
        self.live_interval.currentIndexChanged.connect(
            lambda _i: self._emit("live_interval_s", self.live_interval.currentData())
        )
        self.mode_box.currentIndexChanged.connect(
            lambda _i: self._emit("ui_mode", self.mode_box.currentData())
        )

    # --- valeurs --------------------------------------------------------------------------------

    def _emit(self, key: str, value: object) -> None:
        if not self._loading:
            self.setting_changed.emit(key, value)

    def _sensitivity_changed(self, value: int) -> None:
        self.sensitivity_label.setText(SENSITIVITY.get(value, ""))
        self._emit("wake_sensitivity", value)

    def _voice_gallery(self) -> QWidget:
        """Toutes les voix, chacune avec ▶ Écouter et Choisir."""
        panel, grid = _panel()
        grid.addWidget(_title("🎧  CATALOGUE DES VOIX"), 0, 0, 1, 4)
        grid.addWidget(
            _muted(
                "Écoute chaque voix avec la même phrase, puis choisis-la. Edge : gratuit, en "
                "ligne. Gemini : ta clé Gemini (modèle en préversion, quota gratuit limité)."
            ),
            1,
            0,
            1,
            4,
        )
        self.effect_box = QComboBox()
        for key, label in (
            ("", "Aucun : la voix telle quelle"),
            ("enfant", "🧒 Enfant : plus aiguë, plus jeune"),
            ("robot", "🤖 Petit robot : métallique, un peu aiguë"),
            ("robot_enfant", "🤖 VIIRUS : petit garçon robot, aigu et espiègle"),
            ("gros_robot", "🦾 Gros robot : grave et métallique"),
        ):
            self.effect_box.addItem(label, key)
        self.effect_box.currentIndexChanged.connect(
            lambda _i: self._emit("voice_effect", self.effect_box.currentData())
        )
        grid.addWidget(QLabel("Effet"), 2, 0)
        grid.addWidget(self.effect_box, 2, 1, 1, 3)
        grid.addWidget(
            _muted(
                "L'effet s'ajoute à la voix choisie (Edge, Gemini, OpenAI, Kokoro) et s'entend "
                "aussi dans les écoutes d'essai. Avec Gemini et OpenAI, la voix reçoit en plus la "
                "consigne de jouer un enfant ou un robot."
            ),
            3,
            0,
            1,
            4,
        )
        self.gallery_buttons: dict[str, QPushButton] = {}
        row = 4
        for engine, title, voices in (
            ("edge", "VOIX EDGE (MICROSOFT)", [(n, label) for n, label in EDGE_VOICES]),
            ("gemini", "VOIX GEMINI (GOOGLE)", [(n, f"{n} — {d}") for n, d in GEMINI_VOICES]),
        ):
            header = QLabel(title)
            header.setObjectName("sectionTitle")
            grid.addWidget(header, row, 0, 1, 4)
            row += 1
            for name, label in voices:
                key = f"{engine}|{name}"
                grid.addWidget(QLabel(label), row, 0, 1, 2)
                listen = QPushButton("▶ Écouter")
                listen.clicked.connect(lambda _=False, k=key: self._emit("voice_preview", k))
                choose = QPushButton("Choisir")
                choose.setObjectName("ghost")
                choose.clicked.connect(lambda _=False, k=key: self._emit("voice_choose", k))
                grid.addWidget(listen, row, 2)
                grid.addWidget(choose, row, 3)
                self.gallery_buttons[key] = choose
                row += 1
        self.gallery_state = _muted("")
        grid.addWidget(self.gallery_state, row, 0, 1, 4)
        return panel

    def mark_chosen_voice(self, key: str) -> None:
        for name, button in self.gallery_buttons.items():
            button.setText("✓ Choisie" if name == key else "Choisir")

    def _show_voice_list(self, engine: str) -> None:
        self.voice_box.setVisible(engine == "edge")
        self.openai_voice_box.setVisible(engine == "openai")
        self.gemini_voice_box.setVisible(engine == "gemini")
        self.voice_label.setVisible(engine in ("edge", "openai", "gemini"))

    def _engine_changed(self) -> None:
        self._show_voice_list(self.engine_box.currentData())
        self._emit("tts_engine", self.engine_box.currentData())

    @staticmethod
    def _fill_devices(box: QComboBox, names: list[str], current: str, default: str) -> None:
        box.clear()
        box.addItem(default, "")
        for name in names:
            box.addItem(name, name)
        if current and box.findData(current) < 0:
            box.addItem(f"{current} (introuvable)", current)
        box.setCurrentIndex(max(0, box.findData(current)))

    def load(self, voice: VoiceSettings, wake_on: bool, ui_mode: str, ai_text: str) -> None:
        """Affiche les réglages actuels (sans rien déclencher)."""
        self._loading = True
        try:
            try:
                inputs, outputs = self._input_devices(), self._output_devices()
            except Exception:  # noqa: BLE001 - pas de carte son : menus réduits au défaut
                inputs, outputs = [], []
            self._fill_devices(
                self.input_box, inputs, voice.input_device, "Micro Windows par défaut"
            )
            self._fill_devices(
                self.output_box, outputs, voice.output_device, "Sortie Windows par défaut"
            )
            self.wake_box.setChecked(wake_on)
            self.sensitivity.setValue(voice.wake_sensitivity)
            self.sensitivity_label.setText(SENSITIVITY.get(voice.wake_sensitivity, ""))
            self.speak_box.setChecked(voice.speak_answers)
            self.engine_box.setCurrentIndex(max(0, self.engine_box.findData(voice.tts_engine)))
            self._show_voice_list(voice.tts_engine)
            if self.openai_voice_box.findData(voice.openai_voice) < 0:
                self.openai_voice_box.addItem(voice.openai_voice, voice.openai_voice)
            self.openai_voice_box.setCurrentIndex(
                self.openai_voice_box.findData(voice.openai_voice)
            )
            if self.voice_box.findData(voice.tts_voice) < 0:
                self.voice_box.addItem(voice.tts_voice, voice.tts_voice)
            self.voice_box.setCurrentIndex(self.voice_box.findData(voice.tts_voice))
            if self.gemini_voice_box.findData(voice.gemini_voice) < 0:
                self.gemini_voice_box.addItem(voice.gemini_voice, voice.gemini_voice)
            self.gemini_voice_box.setCurrentIndex(
                self.gemini_voice_box.findData(voice.gemini_voice)
            )
            self.effect_box.setCurrentIndex(max(0, self.effect_box.findData(voice.voice_effect)))
            self.volume.setValue(voice.volume)
            self.volume_label.setText(f"{voice.volume} %")
            chosen = {"edge": voice.tts_voice, "gemini": voice.gemini_voice}.get(voice.tts_engine)
            self.mark_chosen_voice(f"{voice.tts_engine}|{chosen}" if chosen else "")
            percent = rate_percent(voice.tts_rate)
            self.speed.setValue(percent)
            self.speed_label.setText(f"{percent:+d} %")
            self.mode_box.setCurrentIndex(max(0, self.mode_box.findData(ui_mode)))
            self.ai_label.setText(ai_text)
        finally:
            self._loading = False

    def _kinds_changed(self) -> None:
        kinds = [k for k, box in self.copilot_kinds.items() if box.isChecked()]
        self.copilot_trash.setEnabled("trashtalk" in kinds)
        if "trashtalk" in kinds and self.copilot_trash.currentData() == "off" and not self._loading:
            self.copilot_trash.setCurrentIndex(self.copilot_trash.findData("leger"))
        self._emit("copilot_kinds", ",".join(kinds))

    def load_copilot(self, copilot) -> None:  # type: ignore[no-untyped-def]
        self._loading = True
        try:
            self.copilot_box.setChecked(copilot.enabled)
            self.copilot_spontaneity.setCurrentIndex(
                max(0, self.copilot_spontaneity.findData(copilot.spontaneity))
            )
            from alicia.core.copilot import kinds_from

            enabled = kinds_from(copilot.kinds)
            for key, box in self.copilot_kinds.items():
                box.setChecked(key in enabled)
            self.copilot_trash.setCurrentIndex(max(0, self.copilot_trash.findData(copilot.trash)))
            self.copilot_trash.setEnabled("trashtalk" in enabled)
            for box, value in (
                (self.copilot_interval, float(copilot.interval_s)),
                (self.copilot_threshold, int(copilot.threshold)),
                (self.copilot_cooldown, float(copilot.cooldown_s)),
            ):
                index = box.findData(value)
                if index < 0:
                    box.addItem(str(value), value)
                    index = box.count() - 1
                box.setCurrentIndex(index)
        finally:
            self._loading = False

    @staticmethod
    def _combo_value(box: QComboBox) -> str:
        """Valeur d'une liste modifiable : le modèle choisi, ou le texte tapé."""
        text = box.currentText().strip()
        index = box.findText(text)
        if index >= 0 and box.itemData(index):
            return str(box.itemData(index))
        return text.split(" ")[0]

    def load_brains(self, ai) -> None:  # type: ignore[no-untyped-def]
        self._loading = True
        try:
            for box, wanted in ((self.ollama_deep_model, ai.ollama.deep_model or "qwen3.8:27b"),):
                found = box.findData(wanted)
                if found < 0:
                    box.addItem(wanted, wanted)
                    found = box.findData(wanted)
                box.setCurrentIndex(found)
            self.fast_box.setCurrentIndex(max(0, self.fast_box.findData(ai.provider)))
            self.deep_model.setVisible(ai.deep_provider in ("gemini", "openai"))
            index = self.ollama_model.findData(ai.ollama.model)
            if index < 0:
                self.ollama_model.addItem(ai.ollama.model, ai.ollama.model)
                index = self.ollama_model.findData(ai.ollama.model)
            self.ollama_model.setCurrentIndex(index)
            self.deep_box.setCurrentIndex(max(0, self.deep_box.findData(ai.deep_provider)))
            self.deep_model.setText(ai.deep_model)
        finally:
            self._loading = False

    def show_brain(self, kind: str, provider: str, model: str, state: str | None = None) -> None:
        labels = self.brain_labels[kind]
        labels["provider"].setText(provider)
        labels["model"].setText(model)
        if state is not None:
            labels["state"].setText(state)

    def show_tab(self, key: str) -> None:
        key = TAB_ALIASES.get(key, key)
        """Affiche l'onglet ``key`` (general, profile, ai, voice, vision, keys, stream, duo, people, games)."""
        widget = self.tabs.get(key)
        if widget is None:
            return
        self.stack.setCurrentWidget(widget)
        for name, button in self.tab_buttons.items():
            button.setChecked(name == key)
        self.current_tab = key

    def add_tab(self, key: str, widget: QWidget) -> None:
        """Ajoute une page déjà construite (Jeux : un onglet ; Personnes : en haut de Social)."""
        if key == "people":
            widget.setMinimumHeight(460)  # la page a déjà ses panneaux et son titre
            self._tab_layouts["social"].insertWidget(0, widget)
            return
        holder = QWidget()
        box = QVBoxLayout(holder)
        box.setContentsMargins(0, 14, 0, 0)
        box.addWidget(widget)
        self.stack.addWidget(holder)
        self.tabs[key] = holder

    def _orb_panel(self) -> QWidget:
        """Général → Mode bulle : apparence, position, comportement, stream."""
        panel, grid = _panel()
        grid.addWidget(_title("MODE BULLE"), 0, 0, 1, 4)
        self.orb_size = QSlider(Qt.Orientation.Horizontal)
        self.orb_size.setRange(120, 480)
        self.orb_size_label = _muted("")
        self.orb_size.valueChanged.connect(lambda v: self.orb_size_label.setText(f"{v} px"))
        self.orb_size.sliderReleased.connect(lambda: self._emit("orb_size", self.orb_size.value()))
        self.orb_opacity = QSlider(Qt.Orientation.Horizontal)
        self.orb_opacity.setRange(30, 100)
        self.orb_opacity_label = _muted("")
        self.orb_opacity.valueChanged.connect(lambda v: self.orb_opacity_label.setText(f"{v} %"))
        self.orb_opacity.sliderReleased.connect(
            lambda: self._emit("orb_pref", ("opacity", self.orb_opacity.value() / 100))
        )
        grid.addWidget(QLabel("Apparence"), 1, 0)
        grid.addWidget(QLabel("Taille"), 1, 1)
        grid.addWidget(self.orb_size, 1, 2)
        grid.addWidget(self.orb_size_label, 1, 3)
        grid.addWidget(QLabel("Opacité"), 2, 1)
        grid.addWidget(self.orb_opacity, 2, 2)
        grid.addWidget(self.orb_opacity_label, 2, 3)
        self.orb_checks: dict[str, QCheckBox] = {}
        rows = (
            ("Apparence", "show_hud", "Anneaux animés (HUD) autour du robot"),
            ("", "show_labels", "Nom et état sous le rond"),
            ("", "anims", "Animations du robot"),
            ("Position", "remember_position", "Se souvenir de la position"),
            ("Comportement", "on_top", "Toujours au-dessus des autres fenêtres"),
            ("", "locked", "Verrouiller la position (on la change en mode édition)"),
            ("", "click_opens", "Clic gauche : ouvrir COP'IA'LOTE"),
            ("", "dblclick_opens", "Double-clic : ouvrir COP'IA'LOTE"),
        )
        for row, (section, key, text) in enumerate(rows, start=3):
            if section:
                grid.addWidget(QLabel(section), row, 0)
            box = QCheckBox(text)
            box.toggled.connect(lambda on, k=key: self._emit("orb_pref", (k, on)))
            self.orb_checks[key] = box
            grid.addWidget(box, row, 1, 1, 3)
            if key == "remember_position":
                reset = QPushButton("Réinitialiser la position")
                reset.clicked.connect(lambda: self._emit("orb_reset_position", True))
                grid.addWidget(box, row, 1, 1, 2)
                grid.addWidget(reset, row, 3)
        self.orb_stream_box = QCheckBox("Visible dans OBS / Discord (aussi dans l'onglet Stream)")
        self.orb_stream_box.toggled.connect(lambda on: self._emit("stream_visible", on))
        grid.addWidget(QLabel("Stream"), 11, 0)
        grid.addWidget(self.orb_stream_box, 11, 1, 1, 3)
        grid.addWidget(
            _muted(
                "Pour placer le rond et la bulle, régler la bulle de texte (largeur, police, "
                "durée) : clic droit sur le rond → ✏ Mode édition."
            ),
            12,
            0,
            1,
            4,
        )
        grid.setColumnStretch(2, 1)
        return panel

    def load_orb(self, prefs: dict, size: int) -> None:  # type: ignore[type-arg]
        self._loading = True
        try:
            self.orb_size.setValue(size)
            self.orb_size_label.setText(f"{size} px")
            opacity = int(round(float(prefs.get("opacity", 1.0)) * 100))
            self.orb_opacity.setValue(opacity)
            self.orb_opacity_label.setText(f"{opacity} %")
            for key, box in self.orb_checks.items():
                box.setChecked(bool(prefs.get(key)))
            self.orb_stream_box.setChecked(self.stream_box.isChecked())
        finally:
            self._loading = False

    def _understanding_panel(self) -> QWidget:
        """Comment ta voix devient une question pour l'IA (Entendu → Compris)."""
        panel, grid = _panel()
        grid.addWidget(_title("COMPRÉHENSION VOCALE"), 0, 0, 1, 3)
        steps = _muted(
            "<b>🎙 Audio</b> → <b>Entendu</b> (transcription brute sur ton PC) → "
            "<b>Compris</b> (noms corrigés : joueurs, robots, personnes) → <b>IA</b>.<br>"
            "La conversation affiche ce qui a été <b>compris</b> et envoyé au cerveau. "
            "La transcription brute reste dans le <b>Journal</b> (« Entendu : … ») pour comparer."
        )
        steps.setTextFormat(Qt.TextFormat.RichText)
        grid.addWidget(steps, 1, 0, 1, 2)
        logs = QPushButton("Ouvrir le journal")
        logs.clicked.connect(lambda: self._emit("show_logs", True))
        grid.addWidget(logs, 1, 2)
        return panel

    def show_anims(self, folder: str, found: dict) -> None:  # type: ignore[type-arg]
        self.anims_folder.setText(folder)
        if not found:
            self.anims_state.setText("Aucune animation pour l'instant : le portrait est utilisé.")
            return
        missing = [
            n
            for n in ("idle", "listening", "thinking", "speaking", "action", "error")
            if n not in found
        ]
        text = "✓ Trouvées : " + ", ".join(found)
        if missing:
            text += " — manquent : " + ", ".join(missing)
        self.anims_state.setText(text)

    def show_personality(self, text: str) -> None:
        self.personality_state.setText(text)

    def load_player(self, player) -> None:  # type: ignore[no-untyped-def]
        self._loading = True
        try:
            self.player_name.setText(player.name)
            self.player_phonetic.setText(player.phonetic)
        finally:
            self._loading = False

    def load_duo(self, duo, has_token: bool, ai_choices=()) -> None:  # type: ignore[no-untyped-def]
        self._loading = True
        try:
            self.duo_box.setChecked(duo.enabled)
            self.duo_chat.setChecked(duo.allow_chat)
            self.duo_ai.clear()
            for label, (provider, slot) in ai_choices:
                self.duo_ai.addItem(label, f"{provider}|{slot}")
            index = self.duo_ai.findData(f"{duo.provider}|{duo.key_slot}")
            self.duo_ai.setCurrentIndex(max(0, index))
            self.duo_hear.setChecked(duo.hear_peer)
            self.duo_code.setText(duo.code.get())
            index = self.duo_turns.findData(duo.max_turns)
            if index < 0:
                self.duo_turns.addItem(f"{duo.max_turns} répliques", duo.max_turns)
                index = self.duo_turns.findData(duo.max_turns)
            self.duo_turns.setCurrentIndex(index)
        finally:
            self._loading = False
        self.github_state.setText(
            "Jeton enregistré ✓ (les MAJ marchent avec un dépôt privé)" if has_token else ""
        )

    def show_duo(self, text: str) -> None:
        self.duo_state.setText(text)

    def load_stream(self, stream) -> None:  # type: ignore[no-untyped-def]
        self._loading = True
        try:
            self.twitch_input.setText(stream.twitch_channel)
            self.overlay_box.setChecked(stream.overlay)
        finally:
            self._loading = False
        self.show_channel(stream.twitch_channel, valid=True)

    def show_channel(self, channel: str, valid: bool = True) -> None:
        self.twitch_input.setText(channel or self.twitch_input.text())
        if not valid:
            self.twitch_state.setText("⚠ Nom de chaîne invalide (3 à 25 lettres, chiffres ou _).")
        elif channel:
            self.twitch_state.setText(
                f"twitch.tv/{channel} — aussi dans le menu du rond (clic droit)."
            )
        else:
            self.twitch_state.setText("")

    def show_overlay(self, url: str | None) -> None:
        """None : coupé ; "" : impossible de démarrer ; sinon l'adresse à coller dans OBS."""
        if url:
            self.overlay_url.setText(url)
        elif url == "":
            self.overlay_url.setText("⚠ Impossible de démarrer (port occupé ?)")
        else:
            self.overlay_url.setText("coupé")

    def load_memory(self, capture, usage: str) -> None:  # type: ignore[no-untyped-def]
        self._loading = True
        try:
            self.memory_box.setChecked(capture.memory)
            for box, value, unit in (
                (self.memory_interval, capture.memory_interval_s, "s"),
                (self.memory_size, capture.memory_max_gb, "Go"),
                (self.memory_hours, capture.memory_hours, "h"),
            ):
                if box.findData(value) < 0:
                    box.addItem(f"{value:g} {unit}", value)
                box.setCurrentIndex(box.findData(value))
            self.memory_clear_exit.setChecked(capture.memory_clear_on_exit)
            self.memory_usage.setText(usage)
        finally:
            self._loading = False

    def load_vision(
        self, mode: str, box: tuple[int, int], live: bool = True, interval: float = 1.0
    ) -> None:
        self._loading = True
        try:
            self.live_box.setChecked(live)
            index = self.live_interval.findData(interval)
            if index < 0:
                self.live_interval.addItem(f"Toutes les {interval:g} s", interval)
                index = self.live_interval.findData(interval)
            self.live_interval.setCurrentIndex(index)
            self.vision_box.setCurrentIndex(max(0, self.vision_box.findData(mode)))
            key = f"{box[0]}x{box[1]}"
            if self.box_size.findData(key) < 0:
                self.box_size.addItem(f"Personnalisée ({box[0]} × {box[1]})", key)
            self.box_size.setCurrentIndex(self.box_size.findData(key))
        finally:
            self._loading = False

    def show_mic_level(self, level: float) -> None:
        self.mic_level.setValue(int(max(0.0, min(1.0, level)) * 100))
