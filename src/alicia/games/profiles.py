"""Profils de jeu : ce qu'ALICIA sait du jeu et les sites où elle cherche en priorité.

Les profils viennent de `games.toml` (fourni avec ALICIA), complété ou remplacé par le
fichier du joueur `%APPDATA%\\Alicia\\games.toml`. Un profil ne touche pas au moteur :
il ajoute du contexte au prompt et oriente la recherche web.
"""

from __future__ import annotations

import logging
import re
import tomllib
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

from alicia.core.capture.models import WindowInfo

log = logging.getLogger("alicia.games")

USER_FILE = "games.toml"


@dataclass(frozen=True)
class GameProfile:
    key: str
    name: str
    exe_names: tuple[str, ...] = ()
    title_keywords: tuple[str, ...] = ()
    context: str = ""
    sources: tuple[str, ...] = ()  # sites actifs, du plus fiable au moins fiable
    sources_off: tuple[str, ...] = ()  # sites gardés dans la liste mais désactivés
    sources_all: tuple[str, ...] = ()  # tous les sites, dans l'ordre (actifs et désactivés)
    folders: tuple[str, ...] = ()  # dossier d'installation (ex. « _retail_ » pour WoW)
    regions: dict[str, tuple[float, float, float, float]] = field(default_factory=dict)

    def matches(self, window: WindowInfo) -> bool:
        exe = window.exe_name.casefold()
        title = window.title.casefold()
        return exe in self.exe_names or any(k in title for k in self.title_keywords)

    def matches_folder(self, window: WindowInfo) -> bool:
        parts = {p.casefold() for p in re.split(r"[\\/]", window.exe_path) if p}
        return any(folder in parts for folder in self.folders)

    def prompt_context(self, web_search: bool = False) -> str:
        """Contexte ajouté au prompt système : le jeu, puis ses sites de référence."""
        parts = [self.context.strip()] if self.context.strip() else []
        if self.sources:
            listed = "\n".join(f"- {source}" for source in self.sources)
            if web_search:
                parts.append(
                    "Sites de référence pour ce jeu, du plus fiable au moins fiable :\n"
                    f"{listed}\n"
                    "Quand tu cherches sur le web, cible d'abord ces sites (ajoute "
                    "« site:domaine » à tes requêtes) ; élargis seulement s'ils ne disent "
                    "rien, et préfère toujours l'information la plus récente."
                )
            else:
                parts.append(f"Sites de référence du joueur pour ce jeu :\n{listed}")
        return "\n\n".join(parts)


GENERIC = GameProfile(key="generic", name="Jeu générique")


def _strings(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return ()
    return tuple(str(v).strip() for v in value if str(v).strip())


def _parse(data: dict, origin: str) -> dict[str, GameProfile]:
    profiles = {}
    for key, entry in data.items():
        if isinstance(entry, dict):
            entry = {k: v for k, v in entry.items() if k != "hidden"}
        if not isinstance(entry, dict):
            log.warning(
                "Profil de jeu « %s » ignoré dans %s : ce n'est pas une section", key, origin
            )
            continue
        key = str(key).strip().lower()
        profiles[key] = GameProfile(
            key=key,
            name=str(entry.get("name", key)).strip() or key,
            exe_names=tuple(s.casefold() for s in _strings(entry.get("exe", []))),
            title_keywords=tuple(s.casefold() for s in _strings(entry.get("title", []))),
            context=str(entry.get("context", "")).strip(),
            sources=tuple(
                site
                for site in _strings(entry.get("sources", []))
                if site not in _strings(entry.get("sources_off", []))
            ),
            sources_off=_strings(entry.get("sources_off", [])),
            sources_all=_strings(entry.get("sources", [])),
            folders=tuple(s.casefold() for s in _strings(entry.get("folder", []))),
        )
    return profiles


def builtin_text() -> str:
    return resources.files("alicia.games").joinpath("games.toml").read_text("utf-8")


def load_profiles(user_file: Path | None = None) -> dict[str, GameProfile]:
    """Profils fournis + ceux du joueur.

    Un profil du joueur qui porte le nom d'un profil fourni le complète champ par champ :
    il suffit d'écrire `sources = [...]` sous `[wow-forever]` pour changer les sites.
    """
    data = tomllib.loads(builtin_text())
    if user_file is not None and user_file.is_file():
        try:
            user = tomllib.loads(user_file.read_text("utf-8"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
            log.error("Profils de jeu illisibles dans %s : %s", user_file, exc)
        else:
            for key, entry in user.items():
                key = str(key).strip().lower()
                base = data.get(key)
                if isinstance(base, dict) and isinstance(entry, dict):
                    data[key] = {**base, **entry}
                else:
                    data[key] = entry
    # « hidden = true » : jeu retiré de la liste par le joueur (même un jeu fourni)
    data = {k: v for k, v in data.items() if not (isinstance(v, dict) and v.get("hidden"))}
    profiles = {"generic": GENERIC}
    profiles.update(_parse(data, "games.toml"))
    return profiles


def default_user_file() -> Path:
    from alicia.core.config import data_dir

    return data_dir() / USER_FILE


_CACHE: dict[str, GameProfile] | None = None


def all_profiles(reload: bool = False) -> dict[str, GameProfile]:
    global _CACHE
    if _CACHE is None or reload:
        _CACHE = load_profiles(default_user_file())
    return _CACHE


def resolve_profile(
    window: WindowInfo | None,
    setting: str = "auto",
    profiles: dict[str, GameProfile] | None = None,
) -> GameProfile:
    profiles = profiles if profiles is not None else all_profiles()
    if setting != "auto":
        return profiles.get(setting, GENERIC)
    if window is not None:
        exe = window.exe_name.casefold()
        # Du plus sûr au moins sûr : dossier d'installation (versions d'un même jeu),
        # nom du programme, puis un mot du titre.
        if window.exe_path:
            for profile in profiles.values():
                if profile is not GENERIC and profile.matches_folder(window):
                    return profile
        for profile in profiles.values():
            if profile is not GENERIC and exe and exe in profile.exe_names:
                return profile
        for profile in profiles.values():
            if profile is not GENERIC and profile.matches(window):
                return profile
    return GENERIC
