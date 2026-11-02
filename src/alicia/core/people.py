"""Personnes / Duo : les gens avec qui tu joues, et tous les noms qui les désignent.

Une personne a un identifiant interne unique : « Yannick », « Nova » et « NovaJagger »
désignent la même personne, sans créer trois fiches. Chaque nom peut avoir sa
prononciation (pour la voix et pour la reconnaissance vocale), sans changer le nom affiché.
Les personnes cochées « présentes » sont données au robot comme contexte de la session.

Fichier : %APPDATA%\\Alicia\\personnes.json (sur ce PC seulement).
"""

from __future__ import annotations

import difflib
import json
import logging
import re
import secrets
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path

from alicia.core.config import data_dir

log = logging.getLogger("alicia.app")


def plain(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in text if not unicodedata.combining(c)).strip()


@dataclass
class Person:
    id: str = field(default_factory=lambda: secrets.token_hex(4))
    first_name: str = ""
    last_name: str = ""
    nickname: str = ""  # pseudo principal
    aliases: list[str] = field(default_factory=list)  # autres pseudos, surnoms
    pronunciations: dict[str, str] = field(default_factory=dict)  # nom → comment le dire
    notes: str = ""  # infos utiles (jeux, rôle, préférences…)
    present: bool = False  # dans la session actuelle

    def names(self) -> list[str]:
        seen: list[str] = []
        for name in (self.first_name, self.nickname, *self.aliases, self.last_name):
            name = name.strip()
            if name and plain(name) not in {plain(n) for n in seen}:
                seen.append(name)
        return seen

    @property
    def display(self) -> str:
        """« Yannick / Nova » : prénom et pseudo principal."""
        main = [n for n in (self.first_name, self.nickname) if n.strip()]
        return " / ".join(main) or (self.aliases[0] if self.aliases else "Sans nom")

    def describe(self) -> str:
        others = [n for n in self.names() if n not in (self.first_name, self.nickname)]
        text = self.display
        if others:
            text += f" (aussi appelé : {', '.join(others)})"
        if self.notes.strip():
            text += f" — {self.notes.strip()}"
        return text


class PeopleStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or data_dir() / "personnes.json"
        self.people: list[Person] = []
        self.load()

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text("utf-8"))
        except (OSError, ValueError):
            self.people = []
            return
        people = []
        for entry in raw.get("people", []) if isinstance(raw, dict) else []:
            if isinstance(entry, dict):
                known = {k: v for k, v in entry.items() if k in Person.__dataclass_fields__}
                people.append(Person(**known))
        self.people = people
        self._apply_pronunciations()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"people": [asdict(p) for p in self.people]}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)
        self._apply_pronunciations()
        log.info("Personnes enregistrées : %d", len(self.people))

    def upsert(self, person: Person) -> Person:
        for index, existing in enumerate(self.people):
            if existing.id == person.id:
                self.people[index] = person
                break
        else:
            self.people.append(person)
        self.save()
        return person

    def remove(self, person_id: str) -> None:
        self.people = [p for p in self.people if p.id != person_id]
        self.save()

    def present(self) -> list[Person]:
        return [p for p in self.people if p.present]

    def find(self, name: str, fuzzy: bool = True) -> Person | None:
        """La personne désignée par un nom ou un alias (« Nova » → Yannick)."""
        wanted = plain(name)
        if not wanted:
            return None
        for person in self.people:
            if wanted in {plain(n) for n in person.names()}:
                return person
        if not fuzzy or len(wanted) < 4:
            return None
        best, score = None, 0.0
        for person in self.people:
            for known in person.names():
                ratio = difflib.SequenceMatcher(None, wanted, plain(known)).ratio()
                if ratio > score:
                    best, score = person, ratio
        return best if score >= 0.84 else None

    def all_names(self, only_present: bool = False) -> list[str]:
        people = self.present() if only_present else self.people
        return [name for person in people for name in person.names()]

    def context(self) -> str:
        """Pour le prompt : qui est là, et sous quels noms."""
        present = self.present()
        if not present:
            return ""
        lines = "\n".join(f"- {p.describe()}" for p in present)
        return (
            "\nPersonnes présentes avec le joueur (chacune peut être appelée par n'importe "
            "lequel de ses noms ; « lui » / « elle » désigne en général la dernière personne "
            f"mentionnée) :\n{lines}\n"
        )

    def _apply_pronunciations(self) -> None:
        from alicia.core.persona import register_pronunciation

        for person in self.people:
            for written, spoken in person.pronunciations.items():
                register_pronunciation(written, spoken)


# Le carnet utilisé par le programme (chargé par la fenêtre principale)
_store: PeopleStore | None = None


def store() -> PeopleStore | None:
    return _store


def set_store(value: PeopleStore | None) -> None:
    global _store
    _store = value


def people_context() -> str:
    return _store.context() if _store is not None else ""


def known_names() -> list[str]:
    return _store.all_names() if _store is not None else []


def canonical_names(text: str, extra: list[str] | None = None) -> str:
    """Remet les noms connus à leur bonne orthographe (« nova jager » → « NovaJagger »).

    Mot à mot (et par paires de mots), en tolérant les petites fautes de la dictée."""
    names = [*known_names(), *(extra or [])]
    if not names or not text:
        return text
    index = {plain(n).replace(" ", ""): n for n in names if len(n) >= 3}
    tokens = re.findall(r"\w+|\W+", text)
    out: list[str] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if not re.match(r"\w", token):
            out.append(token)
            i += 1
            continue
        # deux mots collés (« nova jagger » → « NovaJagger »)
        if i + 2 < len(tokens) and re.match(r"\s+$", tokens[i + 1]):
            pair = plain(token + tokens[i + 2])
            match = _closest(pair, index)
            if match and len(pair) >= 6:
                out.append(match)
                i += 3
                continue
        match = _closest(plain(token), index)
        out.append(match or token)
        i += 1
    return "".join(out)


def _closest(word: str, index: dict[str, str]) -> str | None:
    if word in index:
        return index[word]
    if len(word) < 4:
        return None
    found = difflib.get_close_matches(word, list(index), n=1, cutoff=0.84)
    return index[found[0]] if found else None
