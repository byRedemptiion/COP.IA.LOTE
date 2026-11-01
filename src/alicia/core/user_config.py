"""Écrire un réglage dans le fichier du joueur (%APPDATA%\\Alicia\\alicia.toml).

Modification ciblée d'une ligne : les commentaires et les autres réglages du fichier
sont conservés. Le résultat est relu avant d'être enregistré : jamais de fichier cassé.
"""

from __future__ import annotations

import json
import logging
import re
import tomllib
from pathlib import Path

from alicia.core.config import data_dir

log = logging.getLogger("alicia.config")


def user_config_file() -> Path:
    return data_dir() / "alicia.toml"


def _value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def set_value(section: str, key: str, value: object, path: Path | None = None) -> Path:
    """Écrit `key = value` dans `[section]` (créés au besoin)."""
    path = path or user_config_file()
    text = path.read_text("utf-8") if path.is_file() else ""
    lines = text.splitlines()
    line = f"{key} = {_value(value)}"
    header = re.compile(r"^\s*\[([^\]]+)\]\s*(#.*)?$")
    start = next(
        (
            i
            for i, raw in enumerate(lines)
            if (m := header.match(raw)) and m.group(1).strip() == section
        ),
        None,
    )
    if start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines += [f"[{section}]", line]
    else:
        end = next((i for i in range(start + 1, len(lines)) if header.match(lines[i])), len(lines))
        pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
        for i in range(start + 1, end):
            if pattern.match(lines[i]):
                lines[i] = line
                break
        else:
            insert = end
            while insert > start + 1 and not lines[insert - 1].strip():
                insert -= 1
            lines.insert(insert, line)
    result = "\n".join(lines) + "\n"
    tomllib.loads(result)  # vérification avant écriture
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".toml.tmp")
    tmp.write_text(result, encoding="utf-8")
    tmp.replace(path)
    log.info("Réglage enregistré : [%s] %s = %s", section, key, _value(value))
    return path


def user_env_file() -> Path:
    return data_dir() / ".env"


def set_env(key: str, value: str, path: Path | None = None) -> Path:
    """Écrit `KEY=valeur` dans le .env du joueur (clés d'API). La valeur n'est jamais journalisée."""
    path = path or user_env_file()
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
        raise ValueError(f"Nom de variable invalide : {key}")
    if any(c in value for c in "\r\n"):
        raise ValueError("La valeur ne doit pas contenir de retour à la ligne.")
    lines = path.read_text("utf-8").splitlines() if path.is_file() else []
    lines = [line for line in lines if not re.match(rf"^\s*{key}\s*=", line)]
    lines.append(f"{key}={value.strip()}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(path)
    log.info("%s enregistré dans %s (valeur masquée)", key, path)
    return path


# --- plusieurs clés d'API par fournisseur (bouton « + ») -------------------------------------
# La clé utilisée reste GEMINI_API_KEY / OPENAI_API_KEY ; les autres sont rangées dans
# GEMINI_API_KEY_2 … _9. Leur nom (facultatif) est dans alicia.toml, section [keys].

MAX_KEYS = 9


def _env_values(path: Path | None = None) -> dict[str, str]:
    from dotenv import dotenv_values

    path = path or user_env_file()
    if not path.is_file():
        return {}
    return {k: v for k, v in dotenv_values(path).items() if v}


def delete_env(key: str, path: Path | None = None) -> None:
    path = path or user_env_file()
    if not path.is_file():
        return
    lines = path.read_text("utf-8").splitlines()
    kept = [line for line in lines if not re.match(rf"^\s*{re.escape(key)}\s*=", line)]
    if kept != lines:
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
        tmp.replace(path)
        log.info("%s supprimée de %s", key, path)


def key_slots(base: str, path: Path | None = None) -> list[str]:
    """Emplacements occupés : ["GEMINI_API_KEY", "GEMINI_API_KEY_3", …] (la 1re = utilisée)."""
    values = _env_values(path)
    slots = [base] if values.get(base) else []
    return slots + [f"{base}_{n}" for n in range(2, MAX_KEYS + 1) if values.get(f"{base}_{n}")]


def key_names(config: Path | None = None) -> dict[str, str]:
    config = config or user_config_file()
    try:
        data = tomllib.loads(config.read_text("utf-8")) if config.is_file() else {}
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    keys = data.get("keys", {})
    return {k: str(v) for k, v in keys.items()} if isinstance(keys, dict) else {}


def update_keys(
    base: str,
    *,
    add: str = "",
    name: str = "",
    activate: str | None = None,
    remove: tuple[str, ...] = (),
    env: Path | None = None,
    config: Path | None = None,
) -> None:
    """Supprime, ajoute (la nouvelle clé devient la clé utilisée) et choisit la clé utilisée."""
    values = _env_values(env)
    names = key_names(config)
    for slot in remove:
        delete_env(slot, env)
        values.pop(slot, None)
        names.pop(slot, None)
    if add:
        free = next(
            (
                s
                for s in [base] + [f"{base}_{n}" for n in range(2, MAX_KEYS + 1)]
                if not values.get(s)
            ),
            None,
        )
        if free is None:
            raise ValueError(f"{MAX_KEYS} clés au maximum")
        set_env(free, add, env)
        values[free] = add
        names[free] = name.strip()
        activate = free
    if not values.get(base):  # la clé utilisée a été supprimée : la suivante prend sa place
        spare = next((s for s in key_slots(base, env) if s != base), None)
        if spare is not None and activate in (None, base):
            activate = spare
    if activate and activate != base and values.get(activate):
        current = values.get(base, "")
        set_env(base, values[activate], env)
        if current:
            set_env(activate, current, env)
        else:
            delete_env(activate, env)
        names[base], names[activate] = names.get(activate, ""), names.get(base, "")
    for slot in [base] + [f"{base}_{n}" for n in range(2, MAX_KEYS + 1)]:
        old = key_names(config).get(slot, "")
        new = names.get(slot, "") if _env_values(env).get(slot) else ""
        if new != old:
            set_value("keys", slot, new, config)
