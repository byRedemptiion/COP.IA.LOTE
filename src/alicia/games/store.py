"""Modifier les profils de jeu depuis l'interface : lecture et écriture de games.toml.

Le fichier du joueur ne contient que ses jeux et ses changements ; les profils fournis
avec ALICIA restent intacts et peuvent toujours être rétablis.
"""

from __future__ import annotations

import json
import logging
import re
import tomllib
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from alicia.games import profiles as registry
from alicia.games.profiles import GameProfile, builtin_text, default_user_file

log = logging.getLogger("alicia.games")

HEADER = """\
# Tes jeux pour ALICIA. Ce fichier est écrit par l'onglet « Jeux » d'ALICIA,
# mais tu peux aussi le modifier à la main (format : voir games.toml fourni avec ALICIA).
# Sous le nom d'un jeu fourni, seuls les champs écrits ici remplacent l'original.
"""


def normalize_site(text: str) -> str:
    """« https://www.Icy-Veins.com/wow-forever/?x=1 » → « icy-veins.com/wow-forever »."""
    site = text.strip()
    site = re.sub(r"^[a-z][a-z0-9+.-]*://", "", site, flags=re.IGNORECASE)
    site = re.split(r"[?#\s]", site, maxsplit=1)[0].rstrip("/")
    if not site:
        return ""
    domain, _, path = site.partition("/")
    domain = domain.lower().removeprefix("www.")
    if "." not in domain or not re.fullmatch(r"[a-z0-9.-]+(:\d+)?", domain):
        return ""
    return f"{domain}/{path}" if path else domain


def slugify(name: str) -> str:
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "jeu"


def _toml_string(value: str) -> str:
    # Les échappements JSON (\", \\, \n, \uXXXX) sont valides dans une chaîne TOML.
    return json.dumps(value, ensure_ascii=False)


def _toml_list(values: tuple[str, ...] | list[str]) -> str:
    if not values:
        return "[]"
    inner = "".join(f"    {_toml_string(v)},\n" for v in values)
    return f"[\n{inner}]"


@dataclass
class GameDraft:
    """Ce que l'onglet « Jeux » modifie."""

    name: str
    exe_names: list[str]
    title_keywords: list[str]
    sources: list[str]
    context: str
    folders: list[str] = field(default_factory=list)
    sources_off: list[str] = field(default_factory=list)  # sites désactivés (gardés)

    @classmethod
    def from_profile(cls, profile: GameProfile) -> GameDraft:
        # les sites désactivés restent dans la liste, à leur place d'origine si possible
        everything = list(profile.sources_all or profile.sources)
        return cls(
            profile.name,
            list(profile.exe_names),
            list(profile.title_keywords),
            everything,
            profile.context,
            list(profile.folders),
            list(profile.sources_off),
        )


class GameStore:
    def __init__(self, user_file: Path | None = None) -> None:
        self.user_file = user_file or default_user_file()
        self._builtin_keys = {k.lower() for k in tomllib.loads(builtin_text())}
        self.profiles: dict[str, GameProfile] = {}
        self.reload()

    # --- lecture --------------------------------------------------------------------------------

    def reload(self) -> None:
        self.profiles = registry.load_profiles(self.user_file)
        if self.user_file == default_user_file():
            registry.all_profiles(reload=True)  # l'analyse voit tout de suite les changements

    def games(self) -> list[GameProfile]:
        """Les jeux, sans le profil générique, dans l'ordre alphabétique."""
        games = [p for k, p in self.profiles.items() if k != "generic"]
        return sorted(games, key=lambda p: p.name.casefold())

    def is_builtin(self, key: str) -> bool:
        return key in self._builtin_keys

    def is_modified(self, key: str) -> bool:
        entry = self._user_entries().get(key, {})
        return self.is_builtin(key) and any(name != "hidden" for name in entry)

    def hidden_keys(self) -> list[str]:
        """Les jeux retirés de la liste (on peut les remettre)."""
        return [k for k, v in self._user_entries().items() if v.get("hidden")]

    def hide(self, key: str) -> None:
        """Retire un jeu de la liste (un jeu fourni reste rétablissable)."""
        if not self.is_builtin(key):
            self.reset(key)  # un jeu ajouté par le joueur est simplement supprimé
            return
        entries = self._user_entries()
        entries.setdefault(key, {})["hidden"] = True
        self._write(entries)
        log.info("Jeu retiré de la liste : %s", key)

    def unhide_all(self) -> None:
        entries = self._user_entries()
        for key in list(entries):
            if entries[key].pop("hidden", None) is not None and not entries[key]:
                entries.pop(key)
        self._write(entries)
        log.info("Jeux retirés remis dans la liste")

    def _user_entries(self) -> dict[str, dict]:
        if not self.user_file.is_file():
            return {}
        try:
            data = tomllib.loads(self.user_file.read_text("utf-8"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
            # On ne réécrit jamais par-dessus un fichier qu'on ne sait pas lire sans le garder.
            backup = self.user_file.with_suffix(".toml.bak")
            try:
                backup.write_bytes(self.user_file.read_bytes())
                log.error("games.toml illisible (%s) : copie gardée dans %s", exc, backup)
            except OSError:
                log.error("games.toml illisible : %s", exc)
            return {}
        return {str(k).lower(): v for k, v in data.items() if isinstance(v, dict)}

    # --- écriture -------------------------------------------------------------------------------

    def save(self, key: str | None, draft: GameDraft) -> str:
        """Enregistre un jeu (key=None : nouveau jeu). Renvoie sa clé."""
        name = draft.name.strip()
        if not name:
            raise ValueError("Donne un nom au jeu.")
        entries = self._user_entries()
        if key is None:
            base = slugify(name)
            key, n = base, 2
            while key in self.profiles or key in entries:
                key, n = f"{base}-{n}", n + 1
        sources: list[str] = []
        for site in draft.sources:
            clean = normalize_site(site)
            if clean and clean not in sources:
                sources.append(clean)
        hidden = entries.get(key, {}).get("hidden")
        entries[key] = {
            "name": name,
            "folder": [f.strip().strip("\\/").lower() for f in draft.folders if f.strip()],
            "exe": [e.strip().lower() for e in draft.exe_names if e.strip()],
            "title": [t.strip().lower() for t in draft.title_keywords if t.strip()],
            "sources": sources,
            "sources_off": [normalize_site(x) for x in draft.sources_off if normalize_site(x)],
            "context": draft.context.strip(),
        }
        if hidden:
            entries[key]["hidden"] = True
        self._write(entries)
        log.info("Jeu enregistré : %s (%d sites)", name, len(sources))
        return key

    def reset(self, key: str) -> None:
        """Rétablit un jeu fourni avec ALICIA, ou supprime un jeu ajouté par le joueur."""
        entries = self._user_entries()
        if entries.pop(key, None) is not None:
            self._write(entries)
            log.info("Jeu %s : %s", "rétabli" if self.is_builtin(key) else "supprimé", key)

    delete = reset

    def _write(self, entries: dict[str, dict]) -> None:
        parts = [HEADER]
        for key, entry in entries.items():
            lines = [f"[{key}]"]
            for name, value in entry.items():
                if isinstance(value, bool):
                    lines.append(f"{name} = {'true' if value else 'false'}")
                elif isinstance(value, list):
                    lines.append(f"{name} = {_toml_list([str(v) for v in value])}")
                else:
                    lines.append(f"{name} = {_toml_string(str(value))}")
            parts.append("\n".join(lines) + "\n")
        self.user_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.user_file.with_suffix(".toml.tmp")
        tmp.write_text("\n".join(parts), encoding="utf-8")
        tomllib.loads(tmp.read_text("utf-8"))  # jamais de fichier cassé
        tmp.replace(self.user_file)
        self.reload()
