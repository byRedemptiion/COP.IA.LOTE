"""Onglet « Jeux » : la liste des jeux, puis la fiche d'un jeu avec ses sites de référence."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from alicia.core.capture.models import WindowInfo
from alicia.games.profiles import GameProfile
from alicia.games.store import GameDraft, GameStore, normalize_site
from alicia.ui.theme import BORDER, GOLD, PINK, title_font

COLUMNS = 3


def _title(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("sectionTitle")
    return label


def _muted(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setObjectName("muted")
    label.setWordWrap(True)
    return label


def _install_folder(exe_path: str) -> str:
    """Dossier qui contient le programme : « …\\_retail_\\Wow.exe » → « _retail_ »."""
    parts = [p for p in exe_path.replace("\\", "/").split("/") if p]
    return parts[-2].lower() if len(parts) >= 2 else ""


def _split(text: str) -> list[str]:
    return [part.strip() for part in text.replace(";", ",").split(",") if part.strip()]


class GameCard(QFrame):
    """Carte cliquable d'un jeu."""

    clicked = Signal(str)

    def __init__(self, key: str, name: str, details: str, badge: str = "") -> None:
        super().__init__()
        self.key = key
        self.setObjectName("gameCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(118)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        top = QHBoxLayout()
        title = QLabel(name)
        title.setFont(title_font(13))
        title.setWordWrap(True)
        title.setStyleSheet(f"color:{PINK if key else GOLD}; background: transparent;")
        top.addWidget(title, 1)
        if badge:
            chip = QLabel(badge)
            chip.setObjectName("chip")
            top.addWidget(chip, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(top)
        info = _muted(details)
        info.setStyleSheet("background: transparent;")
        layout.addWidget(info)
        layout.addStretch(1)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(
            event.position().toPoint()
        ):
            self.clicked.emit(self.key)


class GamesPage(QStackedWidget):
    games_changed = Signal()  # la liste ou un jeu a changé : menus à rafraîchir
    use_game = Signal(str)  # « Utiliser ce jeu maintenant »

    def __init__(
        self,
        store: GameStore,
        active_game: Callable[[], str] | None = None,
        current_window: Callable[[], WindowInfo | None] | None = None,
        side_panel: QWidget | None = None,
    ) -> None:
        super().__init__()
        self.store = store
        self.active_game = active_game or (lambda: "auto")
        self.current_window = current_window or (lambda: None)
        self.side_panel = side_panel  # à droite de la liste : la fenêtre du jeu observée
        self.editing: str | None = None  # clé du jeu ouvert, None = nouveau jeu
        self._build_list()
        self._build_detail()
        self.addWidget(self.list_page)
        self.addWidget(self.detail_page)
        self.refresh()

    # --- page 1 : tous les jeux -----------------------------------------------------------------

    def _build_list(self) -> None:
        self.list_page = QWidget()
        page = QHBoxLayout(self.list_page)
        page.setContentsMargins(0, 0, 0, 0)
        page.setSpacing(16)
        main = QWidget()
        layout = QVBoxLayout(main)
        layout.setContentsMargins(0, 0, 0, 0)
        page.addWidget(main, 1)
        if self.side_panel is not None:
            self.side_panel.setFixedWidth(320)
            page.addWidget(self.side_panel)
        head = QHBoxLayout()
        title = QLabel("TES JEUX")
        title.setFont(title_font(16))
        title.setStyleSheet(f"color:{PINK};")
        head.addWidget(title)
        head.addStretch(1)
        self.add_button = QPushButton("＋  Ajouter un jeu")
        self.add_button.setObjectName("primary")
        self.add_button.clicked.connect(lambda: self.open_game(None))
        head.addWidget(self.add_button)
        layout.addLayout(head)
        hidden_row = QHBoxLayout()
        self.hidden_label = _muted("")
        self.unhide_button = QPushButton("Remettre les jeux retirés")
        self.unhide_button.setObjectName("ghost")
        self.unhide_button.clicked.connect(self._unhide)
        hidden_row.addWidget(self.hidden_label, 1)
        hidden_row.addWidget(self.unhide_button)
        layout.addLayout(hidden_row)
        layout.addWidget(
            _muted(
                "Pour chaque jeu, ALICIA sait de quoi il s'agit et cherche d'abord sur tes "
                "sites de référence. Clique sur un jeu pour gérer ses sites."
            )
        )
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 8, 0, 0)
        self.grid.setSpacing(14)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(
            "QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }"
        )
        scroll.setWidget(self.grid_host)
        layout.addWidget(scroll, 1)

    def refresh(self) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        hidden = self.store.hidden_keys()
        self.hidden_label.setText(
            f"{len(hidden)} jeu{'x' if len(hidden) > 1 else ''} retiré{'s' if len(hidden) > 1 else ''}"
            " de ta liste."
            if hidden
            else ""
        )
        self.unhide_button.setVisible(bool(hidden))
        active = self.active_game()
        cards = []
        for profile in self.store.games():
            sites = len(profile.sources)
            details = f"{sites} site{'s' if sites > 1 else ''} de référence"
            if profile.sources:
                details += " · " + ", ".join(profile.sources[:2])
                if sites > 2:
                    details += "…"
            badge = ""
            if profile.key == active:
                badge = "EN COURS"
            elif not self.store.is_builtin(profile.key):
                badge = "AJOUTÉ"
            elif self.store.is_modified(profile.key):
                badge = "MODIFIÉ"
            cards.append(GameCard(profile.key, profile.name, details, badge))
        for index, card in enumerate(cards):
            card.clicked.connect(self.open_game)
            self.grid.addWidget(card, index // COLUMNS, index % COLUMNS)
        for col in range(COLUMNS):
            self.grid.setColumnStretch(col, 1)
        self.grid.setRowStretch(len(cards) // COLUMNS + 1, 1)

    # --- page 2 : la fiche d'un jeu -------------------------------------------------------------

    def _build_detail(self) -> None:
        self.detail_page = QWidget()
        layout = QVBoxLayout(self.detail_page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        top = QHBoxLayout()
        back = QPushButton("‹  Tous les jeux")
        back.setObjectName("ghost")
        back.clicked.connect(self.show_list)
        top.addWidget(back)
        top.addStretch(1)
        self.copy_button = QPushButton("Dupliquer")
        self.copy_button.setToolTip(
            "Crée une copie de ce jeu (par exemple une autre version de WoW) à adapter"
        )
        self.copy_button.clicked.connect(self.duplicate)
        top.addWidget(self.copy_button)
        self.use_button = QPushButton("Utiliser ce jeu maintenant")
        self.use_button.clicked.connect(self._use)
        top.addWidget(self.use_button)
        layout.addLayout(top)

        self.detail_title = QLabel("")
        self.detail_title.setFont(title_font(18))
        self.detail_title.setStyleSheet(f"color:{PINK};")
        layout.addWidget(self.detail_title)

        # Sites de référence
        self.sites = QListWidget()
        self.sites.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.sites.itemDoubleClicked.connect(self._open_site)
        self.site_input = QLineEdit()
        self.site_input.setPlaceholderText(
            "Colle une adresse : icy-veins.com/wow-forever, https://…"
        )
        self.site_input.returnPressed.connect(self._add_site)
        add_site = QPushButton("Ajouter")
        add_site.clicked.connect(self._add_site)
        add_row = QHBoxLayout()
        add_row.addWidget(self.site_input, 1)
        add_row.addWidget(add_site)
        up = QPushButton("↑")
        down = QPushButton("↓")
        remove = QPushButton("Retirer")
        for button in (up, down):
            button.setFixedWidth(44)
        up.clicked.connect(lambda: self._move_site(-1))
        down.clicked.connect(lambda: self._move_site(1))
        remove.clicked.connect(self._remove_site)
        order_row = QHBoxLayout()
        order_row.addWidget(
            _muted("Du plus fiable au moins fiable. Glisse-les pour changer l'ordre."), 1
        )
        order_row.addWidget(up)
        order_row.addWidget(down)
        order_row.addWidget(remove)
        self.site_error = _muted("")
        self.site_error.setStyleSheet("color:#ff3b5c;")
        sites_panel = self._panel(
            _title("SITES DE RÉFÉRENCE"),
            _muted("Avec la recherche web, ALICIA cherche ici en premier."),
            (self.sites, 1),
            order_row,
            add_row,
            self.site_error,
        )

        # Reconnaissance et contexte
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Nom du jeu")
        self.name_input.textChanged.connect(
            lambda text: self.detail_title.setText(text.upper() or "NOUVEAU JEU")
        )
        self.exe_input = QLineEdit()
        self.exe_input.setPlaceholderText("wow.exe, wowclassic.exe")
        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("world of warcraft")
        self.folder_input = QLineEdit()
        self.folder_input.setPlaceholderText("_retail_, _classic_, _forever_")
        self.window_hint = _muted("")
        self.fill_button = QPushButton("Remplir avec la fenêtre du jeu")
        self.fill_button.setToolTip(
            "Reprend le programme et le dossier de la fenêtre observée (onglet Jeux, à droite)"
        )
        self.fill_button.clicked.connect(self._fill_from_window)
        self.browse_button = QPushButton("Choisir le .exe du jeu…")
        self.browse_button.setToolTip(
            "Va chercher le programme du jeu sur ton disque : COP'IA'LOTE le reconnaîtra à "
            "coup sûr, même si sa fenêtre a un titre bizarre"
        )
        self.browse_button.clicked.connect(self._browse_exe)
        self.context_input = QPlainTextEdit()
        self.context_input.setPlaceholderText(
            "Ce qu'ALICIA doit savoir : le genre, ce qui compte à l'écran, les pièges…"
        )
        self.context_input.setStyleSheet(
            "QPlainTextEdit { font-family: 'Bahnschrift', 'Segoe UI'; font-size: 10.5pt;"
            " color: #e9eeff; background: rgba(2,10,16,0.6); border: 1px solid " + BORDER + ";"
            " border-radius: 8px; padding: 6px; }"
        )
        info_panel = self._panel(
            _title("RECONNAISSANCE"),
            _muted("Nom"),
            self.name_input,
            _muted("Programme(s) du jeu, séparés par des virgules"),
            self.exe_input,
            _muted("Ou un mot du titre de sa fenêtre"),
            self.title_input,
            _muted(
                "Dossier d'installation : sépare les versions d'un même jeu "
                "(WoW actuel « _retail_ », Classic « _classic_ », Forever « _forever_ »)"
            ),
            self.folder_input,
            self.window_hint,
            self._row(self.fill_button, self.browse_button),
            _title("CE QU'ALICIA SAIT DU JEU"),
            (self.context_input, 1),
        )

        columns = QHBoxLayout()
        columns.setSpacing(14)
        columns.addWidget(sites_panel, 1)
        columns.addWidget(info_panel, 1)
        layout.addLayout(columns, 1)

        bottom = QHBoxLayout()
        self.saved_label = _muted("")
        self.reset_button = QPushButton("Rétablir l'original")
        self.reset_button.setObjectName("ghost")
        self.reset_button.clicked.connect(self._reset)
        self.delete_button = QPushButton("Supprimer ce jeu")
        self.delete_button.setObjectName("ghost")
        self.delete_button.clicked.connect(self._delete)
        self.save_button = QPushButton("Enregistrer")
        self.save_button.setObjectName("primary")
        self.save_button.clicked.connect(self.save)
        bottom.addWidget(self.reset_button)
        bottom.addWidget(self.delete_button)
        bottom.addStretch(1)
        bottom.addWidget(self.saved_label)
        bottom.addWidget(self.save_button)
        layout.addLayout(bottom)

    @staticmethod
    def _row(*widgets: QWidget) -> QHBoxLayout:
        row = QHBoxLayout()
        for widget in widgets:
            row.addWidget(widget)
        return row

    @staticmethod
    def _panel(*items) -> QFrame:  # type: ignore[no-untyped-def]
        frame = QFrame()
        frame.setObjectName("panel")
        box = QVBoxLayout(frame)
        box.setContentsMargins(14, 12, 14, 12)
        box.setSpacing(6)
        for item in items:
            stretch = 0
            if isinstance(item, tuple):
                item, stretch = item
            if isinstance(item, QHBoxLayout | QVBoxLayout):
                box.addLayout(item)
            else:
                box.addWidget(item, stretch)
        return frame

    # --- navigation -----------------------------------------------------------------------------

    def show_list(self) -> None:
        self.refresh()
        self.setCurrentWidget(self.list_page)

    def open_game(self, key: str | None) -> None:
        """Ouvre la fiche d'un jeu (None : nouveau jeu, prérempli avec la fenêtre observée)."""
        self.editing = key
        profile: GameProfile | None = self.store.profiles.get(key) if key else None
        if profile is not None:
            draft = GameDraft.from_profile(profile)
        else:
            window = self.current_window()
            draft = GameDraft("", [], [], [], "")
            if window is not None and window.exe_name:
                draft.exe_names = [window.exe_name.lower()]
                draft.folders = [_install_folder(window.exe_path)] if window.exe_path else []
                draft.folders = [f for f in draft.folders if f]
                draft.name = window.title
        self.name_input.setText(draft.name)
        self.detail_title.setText(draft.name.upper() or "NOUVEAU JEU")
        self.exe_input.setText(", ".join(draft.exe_names))
        self.title_input.setText(", ".join(draft.title_keywords))
        self.folder_input.setText(", ".join(draft.folders))
        window = self.current_window()
        self.window_hint.setText(
            f"Fenêtre observée : {window.exe_path or window.exe_name or window.title}"
            if window is not None
            else "Aucune fenêtre observée : choisis-la à droite de la liste des jeux."
        )
        self.fill_button.setEnabled(window is not None and bool(window.exe_name))
        self.context_input.setPlainText(draft.context)
        self.sites.clear()
        for site in draft.sources:
            self._append_site(site)
        self.site_input.clear()
        self.site_error.setText("")
        self.saved_label.setText("")
        builtin = key is not None and self.store.is_builtin(key)
        self.reset_button.setVisible(builtin)
        self.reset_button.setEnabled(builtin and self.store.is_modified(key or ""))
        self.delete_button.setVisible(key is not None)
        self.delete_button.setText("Retirer de ma liste" if builtin else "Supprimer ce jeu")
        self.use_button.setEnabled(key is not None)
        self.copy_button.setEnabled(key is not None)
        self.setCurrentWidget(self.detail_page)
        (self.site_input if key else self.name_input).setFocus()

    # --- sites ----------------------------------------------------------------------------------

    def _append_site(self, site: str) -> None:
        item = QListWidgetItem(f"🌐  {site}")
        item.setData(Qt.ItemDataRole.UserRole, site)
        item.setToolTip("Double-clic : ouvrir le site")
        self.sites.addItem(item)

    def site_list(self) -> list[str]:
        return [
            self.sites.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.sites.count())
        ]

    def _add_site(self) -> None:
        site = normalize_site(self.site_input.text())
        if not site:
            self.site_error.setText(
                "Adresse non reconnue : écris par exemple icy-veins.com/wow-forever"
            )
            return
        if site in self.site_list():
            self.site_error.setText("Ce site est déjà dans la liste.")
            return
        self._append_site(site)
        self.site_input.clear()
        self.site_error.setText("")
        self.saved_label.setText("Pense à enregistrer.")

    def _remove_site(self) -> None:
        row = self.sites.currentRow()
        if row >= 0:
            self.sites.takeItem(row)
            self.saved_label.setText("Pense à enregistrer.")

    def _move_site(self, step: int) -> None:
        row = self.sites.currentRow()
        target = row + step
        if row < 0 or not 0 <= target < self.sites.count():
            return
        item = self.sites.takeItem(row)
        self.sites.insertItem(target, item)
        self.sites.setCurrentRow(target)
        self.saved_label.setText("Pense à enregistrer.")

    def _open_site(self, item: QListWidgetItem) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl("https://" + item.data(Qt.ItemDataRole.UserRole)))

    # --- enregistrement -------------------------------------------------------------------------

    def save(self) -> str | None:
        draft = GameDraft(
            self.name_input.text(),
            _split(self.exe_input.text()),
            _split(self.title_input.text()),
            self.site_list(),
            self.context_input.toPlainText(),
            _split(self.folder_input.text()),
        )
        try:
            key = self.store.save(self.editing, draft)
        except (ValueError, OSError) as exc:
            self.saved_label.setText(f"⚠ {exc}")
            return None
        self.editing = key
        self.saved_label.setText("Enregistré ✓")
        builtin = self.store.is_builtin(key)
        self.reset_button.setVisible(builtin)
        self.reset_button.setEnabled(builtin)
        self.delete_button.setVisible(True)
        self.delete_button.setText("Retirer de ma liste" if builtin else "Supprimer ce jeu")
        self.use_button.setEnabled(True)
        self.copy_button.setEnabled(True)
        self.games_changed.emit()
        return key

    def _reset(self) -> None:
        if self.editing is None:
            return
        key = self.editing
        self.store.reset(key)
        self.games_changed.emit()
        if self.store.is_builtin(key):
            self.open_game(key)
            self.saved_label.setText("Original rétabli ✓")
        else:
            self.show_list()

    def _delete(self) -> None:
        """Jeu fourni : retiré de la liste (rétablissable) ; jeu ajouté : supprimé."""
        if self.editing is None:
            return
        self.store.hide(self.editing)
        self.games_changed.emit()
        self.show_list()

    def _unhide(self) -> None:
        self.store.unhide_all()
        self.games_changed.emit()
        self.refresh()

    def _browse_exe(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(
            self, "Programme du jeu", "C:/Program Files", "Programmes (*.exe)"
        )
        if path:
            self.add_exe(path)

    def add_exe(self, path: str) -> None:
        """Ajoute un programme (et son dossier d'installation) à la reconnaissance."""
        exe = path.replace("\\", "/").split("/")[-1].lower()
        if not exe.endswith(".exe"):
            return
        exes = _split(self.exe_input.text())
        if exe not in exes:
            exes.append(exe)
        self.exe_input.setText(", ".join(exes))
        folder = _install_folder(path)
        folders = _split(self.folder_input.text())
        if folder and folder not in folders and folder not in ("bin", "binaries", "win64", "x64"):
            folders.append(folder)
        self.folder_input.setText(", ".join(folders))
        if not self.name_input.text().strip():
            self.name_input.setText(exe.removesuffix(".exe"))
        self.saved_label.setText("Pense à enregistrer.")

    def _fill_from_window(self) -> None:
        window = self.current_window()
        if window is None or not window.exe_name:
            return
        exes = _split(self.exe_input.text())
        if window.exe_name.lower() not in exes:
            exes.append(window.exe_name.lower())
        self.exe_input.setText(", ".join(exes))
        folder = _install_folder(window.exe_path)
        folders = _split(self.folder_input.text())
        if folder and folder not in folders:
            folders.append(folder)
        self.folder_input.setText(", ".join(folders))
        self.saved_label.setText("Pense à enregistrer.")

    def duplicate(self) -> None:
        """Ouvre une copie du jeu affiché, comme nouveau jeu (rien n'est écrit avant Enregistrer)."""
        if self.editing is None:
            return
        name = self.name_input.text().strip()
        self.editing = None
        self.name_input.setText(f"{name} (copie)")
        self.folder_input.clear()
        self.reset_button.setVisible(False)
        self.delete_button.setVisible(False)
        self.use_button.setEnabled(False)
        self.copy_button.setEnabled(False)
        self.saved_label.setText("Copie : change le nom et le dossier, puis enregistre.")
        self.name_input.setFocus()
        self.name_input.selectAll()

    def _use(self) -> None:
        if self.editing is not None:
            self.use_game.emit(self.editing)
            self.refresh()
