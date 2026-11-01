"""Choisir l'IA d'ALICIA et coller sa clé, sans ouvrir de fichier.

Affiché au premier lancement quand aucune clé n'est configurée, puis à tout moment
depuis le bouton « IA » du panneau ou le menu du rond. Les clés sont écrites dans
%APPDATA%\\Alicia\\.env, sur ce PC seulement, et n'apparaissent jamais dans le journal.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)

from alicia.core.ai.providers import gemini as gemini_provider
from alicia.core.ai.providers import openai as openai_provider
from alicia.core.config import GeminiSettings, OpenAISettings
from alicia.ui.naming import rename_widgets
from alicia.ui.theme import DEEP, PINK, STYLESHEET, title_font

OLLAMA_URL = "https://ollama.com/download"


@dataclass(frozen=True)
class KeyProvider:
    key: str
    env: str  # variable du .env
    title: str
    url: str
    button: str
    steps: str
    placeholder: str


KEY_PROVIDERS = {
    "gemini": KeyProvider(
        "gemini",
        "GEMINI_API_KEY",
        "Gemini (Google) — recommandé, gratuit pour commencer",
        gemini_provider.KEY_URL,
        "Ouvrir la page Gemini pour créer ma clé  ↗",
        "Crée ta clé gratuite (compte Google, 1 minute) : « Create API key », "
        "copie-la et colle-la ici.",
        "Colle ta clé Gemini ici",
    ),
    "openai": KeyProvider(
        "openai",
        "OPENAI_API_KEY",
        "ChatGPT (OpenAI) — payant à l'usage",
        openai_provider.KEY_URL,
        "Ouvrir la page OpenAI pour créer ma clé  ↗",
        "Sur la plateforme OpenAI : ajoute du crédit (l'abonnement ChatGPT ne compte pas "
        "pour l'API), puis « Create new secret key », copie-la et colle-la ici.",
        "Colle ta clé OpenAI ici (sk-…)",
    ),
}


class _Bridge(QObject):
    checked = Signal(object)  # message d'erreur ou None


class SetupDialog(QDialog):
    """Retourne (fournisseur, clé) via `choice` quand l'utilisateur valide."""

    def __init__(
        self,
        provider: str = "gemini",
        has_key: bool | dict[str, bool] = False,
        parent=None,  # type: ignore[no-untyped-def]
        gemini: GeminiSettings | None = None,
        openai: OpenAISettings | None = None,
        keys: dict[str, list[tuple[str, str]]] | None = None,
    ) -> None:
        super().__init__(parent)
        # Clés déjà enregistrées par fournisseur : [(emplacement .env, nom affiché)], la 1re
        # est celle utilisée. Les valeurs ne sont jamais transmises à cette fenêtre.
        self.saved_keys = {k: list(v) for k, v in (keys or {}).items()}
        self.removed: set[str] = set()
        self.active: dict[str, str] = {k: v[0][0] for k, v in self.saved_keys.items() if v}
        self.gemini_settings = gemini
        self.openai_settings = openai
        if isinstance(has_key, dict):
            self._has_keys = dict(has_key)
        else:
            self._has_keys = {provider: bool(has_key)}
        for key, slots in self.saved_keys.items():
            self._has_keys[key] = bool(slots)
        self.setWindowTitle("ALICIA — choisis ton IA")
        self.setStyleSheet(STYLESHEET + "QDialog { background: " + DEEP + "; }")
        self.setMinimumWidth(600)
        self.choice: tuple[str, str] | None = None
        self.key_name = ""  # nom de la nouvelle clé
        self.activate: str | None = None  # emplacement de la clé à utiliser
        self.remove: tuple[str, ...] = ()
        self._bridge = _Bridge()
        self._bridge.checked.connect(self._checked)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        title = QLabel("CHOISIS LE CERVEAU D'ALICIA")
        title.setFont(title_font(15))
        title.setStyleSheet(f"color:{PINK};")
        layout.addWidget(title)
        intro = QLabel(
            "ALICIA a besoin d'une IA pour comprendre ton écran et te répondre. "
            "Ta clé reste sur ce PC (jamais partagée, jamais affichée dans le journal)."
        )
        intro.setObjectName("muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.radios: dict[str, QRadioButton] = {}
        group = QButtonGroup(self)
        for key in ("gemini", "openai", "ollama"):
            info = KEY_PROVIDERS.get(key)
            radio = QRadioButton(info.title if info else "Ollama — IA locale sur ton PC (avancé)")
            group.addButton(radio)
            self.radios[key] = radio
            layout.addWidget(radio)
        self.gemini = self.radios["gemini"]
        self.openai = self.radios["openai"]
        self.ollama = self.radios["ollama"]

        # Zone de clé (Gemini ou OpenAI), placée sous le fournisseur choisi
        self.gemini_box = QFrame()
        self.gemini_box.setObjectName("panel")
        box = QVBoxLayout(self.gemini_box)
        box.setContentsMargins(16, 12, 16, 12)
        self.open_page = QPushButton("")
        self.open_page.setObjectName("primary")
        self.open_page.clicked.connect(self._open_key_page)
        self.steps = QLabel("")
        self.steps.setWordWrap(True)
        self.key_input = QLineEdit()
        self.key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Nom (facultatif) : perso, Nova…")
        self.name_input.setMaximumWidth(190)
        self.test_button = QPushButton("Tester")
        self.test_button.clicked.connect(self.test_key)
        # Clés déjà enregistrées : choisir celle utilisée, en supprimer, en ajouter une (+)
        self.keys_title = QLabel("TES CLÉS")
        self.keys_title.setObjectName("sectionTitle")
        self.keys_list = QVBoxLayout()
        self.keys_list.setSpacing(4)
        self.keys_group = QButtonGroup(self)
        self.add_button = QPushButton("＋  Ajouter une autre clé")
        self.add_button.setObjectName("ghost")
        self.add_button.clicked.connect(self._show_add_row)
        self.add_row = QFrame()
        row = QHBoxLayout(self.add_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.name_input)
        row.addWidget(self.key_input, 1)
        row.addWidget(self.test_button)
        box.addWidget(self.open_page)
        box.addWidget(self.steps)
        box.addWidget(self.keys_title)
        box.addLayout(self.keys_list)
        box.addWidget(self.add_button)
        box.addWidget(self.add_row)
        layout.addWidget(self.gemini_box)

        # Ollama
        self.ollama_box = QFrame()
        self.ollama_box.setObjectName("panel")
        obox = QVBoxLayout(self.ollama_box)
        obox.setContentsMargins(16, 12, 16, 12)
        ollama_help = QLabel(
            "Installe Ollama : ALICIA le démarre toute seule et télécharge son modèle d'images "
            "(environ 6 Go) au premier usage. Gratuit et hors ligne, mais il faut une bonne "
            "carte graphique, et c'est plus lent et moins précis (pas de recherche web)."
        )
        ollama_help.setWordWrap(True)
        ollama_help.setObjectName("muted")
        open_ollama = QPushButton("Télécharger Ollama  ↗")
        open_ollama.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(OLLAMA_URL)))
        obox.addWidget(ollama_help)
        obox.addWidget(open_ollama)
        layout.addWidget(self.ollama_box)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        buttons = QHBoxLayout()
        later = QPushButton("Plus tard")
        later.setObjectName("ghost")
        later.clicked.connect(self.reject)
        self.save_button = QPushButton("Enregistrer")
        self.save_button.setObjectName("primary")
        self.save_button.clicked.connect(self.save)
        buttons.addWidget(later)
        buttons.addStretch(1)
        buttons.addWidget(self.save_button)
        layout.addLayout(buttons)

        self.radios.get(provider, self.gemini).setChecked(True)
        for radio in self.radios.values():
            radio.toggled.connect(self._sync)
        self._sync()
        rename_widgets(self)

    # --- affichage ------------------------------------------------------------------------------

    def provider(self) -> str:
        return next((k for k, r in self.radios.items() if r.isChecked()), "gemini")

    def _sync(self) -> None:
        provider = self.provider()
        info = KEY_PROVIDERS.get(provider)
        layout = self.layout()
        for box in (self.gemini_box, self.ollama_box):
            layout.removeWidget(box)
        target = self.gemini_box if info is not None else self.ollama_box
        layout.insertWidget(layout.indexOf(self.radios[provider]) + 1, target)
        other = self.ollama_box if info is not None else self.gemini_box
        layout.insertWidget(layout.indexOf(self.status), other)
        self.gemini_box.setVisible(info is not None)
        self.ollama_box.setVisible(info is None)
        if info is not None:
            self.steps.setText(info.steps)
            self.open_page.setText(info.button)
            self.key_input.clear()
            self.name_input.clear()
            self._fill_keys(provider)
            has = self._has_keys.get(provider)
            self.key_input.setPlaceholderText(
                "Clé déjà enregistrée : laisse vide pour la garder"
                if has and not self.saved_keys.get(provider)
                else info.placeholder
            )
        self.status.setText("")
        self.adjustSize()

    def _remaining(self, provider: str) -> list[tuple[str, str]]:
        return [
            (slot, name)
            for slot, name in self.saved_keys.get(provider, [])
            if slot not in self.removed
        ]

    def _fill_keys(self, provider: str) -> None:
        """Liste des clés enregistrées du fournisseur, avec leur bouton ✕."""
        while self.keys_list.count():
            item = self.keys_list.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for button in self.keys_group.buttons():
            self.keys_group.removeButton(button)
        keys = self._remaining(provider)
        if keys and self.active.get(provider) not in {slot for slot, _ in keys}:
            self.active[provider] = keys[0][0]
        for slot, name in keys:
            line = QFrame()
            row = QHBoxLayout(line)
            row.setContentsMargins(0, 0, 0, 0)
            radio = QRadioButton(name)
            radio.setChecked(slot == self.active.get(provider))
            radio.toggled.connect(
                lambda on, p=provider, s=slot: on and self.active.__setitem__(p, s)
            )
            self.keys_group.addButton(radio)
            delete = QPushButton("✕")
            delete.setObjectName("ghost")
            delete.setFixedWidth(36)
            delete.setToolTip("Supprimer cette clé de ce PC")
            delete.clicked.connect(lambda _=False, p=provider, s=slot: self._remove_key(p, s))
            row.addWidget(radio, 1)
            row.addWidget(delete)
            self.keys_list.addWidget(line)
        self.keys_title.setVisible(bool(keys))
        self.add_button.setVisible(bool(keys))
        self.add_row.setVisible(not keys)  # aucune clé : le champ pour la coller est ouvert

    def _remove_key(self, provider: str, slot: str) -> None:
        self.removed.add(slot)
        self._has_keys[provider] = bool(self._remaining(provider))
        self._fill_keys(provider)
        self.adjustSize()

    def _show_add_row(self) -> None:
        self.add_row.setVisible(True)
        self.key_input.setFocus()
        self.adjustSize()

    def _open_key_page(self) -> None:
        info = KEY_PROVIDERS.get(self.provider())
        if info is not None:
            QDesktopServices.openUrl(QUrl(info.url))

    # --- vérification et validation -------------------------------------------------------------

    def test_key(self) -> None:
        key = self.key_input.text().strip()
        if not key:
            self.status.setText("Colle d'abord ta clé.")
            return
        provider = self.provider()
        self.test_button.setEnabled(False)
        self.status.setText("Vérification de la clé…")

        def run() -> None:
            if provider == "openai":
                problem = openai_provider.check_openai_key(key, self.openai_settings)
            else:
                problem = gemini_provider.check_gemini_key(key, self.gemini_settings)
            self._bridge.checked.emit(problem)

        threading.Thread(target=run, daemon=True).start()

    def _checked(self, problem: str | None) -> None:
        self.test_button.setEnabled(True)
        self.status.setText(f"⚠ {problem}" if problem else "✓ Clé valide : tu peux enregistrer.")

    def save(self) -> None:
        provider = self.provider()
        key = self.key_input.text().strip()
        if provider in KEY_PROVIDERS and not key and not self._has_keys.get(provider):
            name = "Gemini" if provider == "gemini" else "OpenAI"
            self.status.setText(f"Colle ta clé {name} (ou choisis « Plus tard »).")
            return
        self.key_name = self.name_input.text().strip()
        self.activate = None if key else self.active.get(provider)
        self.remove = tuple(
            slot for slot, _ in self.saved_keys.get(provider, []) if slot in self.removed
        )
        self.choice = (provider, key)
        self.accept()
