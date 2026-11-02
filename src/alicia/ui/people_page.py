"""Onglet « Personnes » : les gens avec qui tu joues, leurs pseudos et comment les dire."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from alicia.core.people import PeopleStore, Person


def _muted(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("muted")
    label.setWordWrap(True)
    return label


class PeoplePage(QWidget):
    changed = Signal()  # le carnet a changé (prompt, voix, duo à mettre à jour)

    def __init__(self, store: PeopleStore) -> None:
        super().__init__()
        self.store = store
        self.current: Person | None = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        # --- liste ----------------------------------------------------------------------------
        left = QFrame()
        left.setObjectName("panel")
        left_box = QVBoxLayout(left)
        title = QLabel("PERSONNES")
        title.setObjectName("sectionTitle")
        left_box.addWidget(title)
        left_box.addWidget(_muted("Coche celles qui jouent avec toi maintenant."))
        self.list = QListWidget()
        self.list.itemSelectionChanged.connect(self._selected)
        self.list.itemChanged.connect(self._presence_changed)
        left_box.addWidget(self.list, 1)
        add = QPushButton("＋  Ajouter une personne")
        add.setObjectName("primary")
        add.clicked.connect(self.new_person)
        left_box.addWidget(add)
        left.setMinimumWidth(280)
        layout.addWidget(left, 1)

        # --- fiche ----------------------------------------------------------------------------
        right = QFrame()
        right.setObjectName("panel")
        grid = QGridLayout(right)
        grid.setVerticalSpacing(10)
        self.form_title = QLabel("FICHE")
        self.form_title.setObjectName("sectionTitle")
        grid.addWidget(self.form_title, 0, 0, 1, 2)
        self.first_name = QLineEdit()
        self.first_name.setPlaceholderText("ex. Yannick")
        self.last_name = QLineEdit()
        self.last_name.setPlaceholderText("facultatif")
        self.nickname = QLineEdit()
        self.nickname.setPlaceholderText("ex. Nova")
        self.aliases = QLineEdit()
        self.aliases.setPlaceholderText("séparés par des virgules, ex. NovaJagger, Yann")
        self.pronunciations = QPlainTextEdit()
        self.pronunciations.setPlaceholderText(
            "un nom par ligne, ex.\nYannick = Ya-nik\nNovaJagger = Nova Djagueur"
        )
        self.pronunciations.setObjectName("field")
        self.pronunciations.setFixedHeight(90)
        self.notes = QLineEdit()
        self.notes.setPlaceholderText("infos utiles : joue tank, son main WoW est Pal…")
        self.present = QCheckBox("Présent dans la session actuelle")
        for row, (label, widget) in enumerate(
            (
                ("Prénom", self.first_name),
                ("Nom", self.last_name),
                ("Pseudo principal", self.nickname),
                ("Autres pseudos / alias", self.aliases),
                ("Prononciations", self.pronunciations),
                ("Notes", self.notes),
            ),
            start=1,
        ):
            grid.addWidget(QLabel(label), row, 0, Qt.AlignmentFlag.AlignTop)
            grid.addWidget(widget, row, 1)
        grid.addWidget(self.present, 7, 1)
        buttons = QHBoxLayout()
        self.delete = QPushButton("Supprimer")
        self.delete.setObjectName("ghost")
        self.delete.clicked.connect(self.delete_person)
        save = QPushButton("Enregistrer")
        save.setObjectName("primary")
        save.clicked.connect(self.save_person)
        buttons.addWidget(self.delete)
        buttons.addStretch(1)
        buttons.addWidget(save)
        grid.addLayout(buttons, 8, 0, 1, 2)
        grid.addWidget(
            _muted(
                "Tous ces noms désignent la même personne : « dis à Yannick… » et « demande à "
                "Nova… » visent le même pote. La prononciation sert seulement à la voix et à la "
                "reconnaissance vocale : le nom affiché ne change pas."
            ),
            9,
            0,
            1,
            2,
        )
        grid.setRowStretch(10, 1)
        layout.addWidget(right, 2)
        self.refresh()
        self.new_person()

    # --- liste ------------------------------------------------------------------------------

    def refresh(self, select: str | None = None) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        for person in self.store.people:
            item = QListWidgetItem(person.display)
            item.setData(Qt.ItemDataRole.UserRole, person.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if person.present else Qt.CheckState.Unchecked)
            others = [n for n in person.names() if n not in person.display]
            item.setToolTip(", ".join(others) if others else person.display)
            self.list.addItem(item)
            if person.id == select:
                item.setSelected(True)
        self.list.blockSignals(False)

    def _person(self, person_id: str) -> Person | None:
        return next((p for p in self.store.people if p.id == person_id), None)

    def _selected(self) -> None:
        items = self.list.selectedItems()
        if items:
            person = self._person(items[0].data(Qt.ItemDataRole.UserRole))
            if person is not None:
                self.show_person(person)

    def _presence_changed(self, item: QListWidgetItem) -> None:
        person = self._person(item.data(Qt.ItemDataRole.UserRole))
        if person is None:
            return
        person.present = item.checkState() == Qt.CheckState.Checked
        self.store.save()
        if self.current is not None and self.current.id == person.id:
            self.present.setChecked(person.present)
        self.changed.emit()

    # --- fiche ------------------------------------------------------------------------------

    def new_person(self) -> None:
        self.list.clearSelection()
        self.show_person(Person())
        self.form_title.setText("NOUVELLE PERSONNE")
        self.first_name.setFocus()

    def show_person(self, person: Person) -> None:
        self.current = person
        self.form_title.setText(person.display.upper() if person.names() else "FICHE")
        self.first_name.setText(person.first_name)
        self.last_name.setText(person.last_name)
        self.nickname.setText(person.nickname)
        self.aliases.setText(", ".join(person.aliases))
        self.pronunciations.setPlainText(
            "\n".join(f"{name} = {spoken}" for name, spoken in person.pronunciations.items())
        )
        self.notes.setText(person.notes)
        self.present.setChecked(person.present)
        self.delete.setEnabled(any(p.id == person.id for p in self.store.people))

    def save_person(self) -> Person | None:
        person = self.current or Person()
        person.first_name = self.first_name.text().strip()
        person.last_name = self.last_name.text().strip()
        person.nickname = self.nickname.text().strip()
        person.aliases = [a.strip() for a in self.aliases.text().split(",") if a.strip()]
        spoken: dict[str, str] = {}
        for line in self.pronunciations.toPlainText().splitlines():
            if "=" in line:
                name, _, value = line.partition("=")
                if name.strip() and value.strip():
                    spoken[name.strip()] = value.strip()
        person.pronunciations = spoken
        person.notes = self.notes.text().strip()
        person.present = self.present.isChecked()
        if not person.names():
            self.form_title.setText("⚠ DONNE AU MOINS UN PRÉNOM OU UN PSEUDO")
            return None
        self.store.upsert(person)
        self.refresh(select=person.id)
        self.show_person(person)
        self.changed.emit()
        return person

    def delete_person(self) -> None:
        if self.current is None:
            return
        self.store.remove(self.current.id)
        self.refresh()
        self.new_person()
        self.changed.emit()
