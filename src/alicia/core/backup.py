"""Sauvegarde et restauration de COP'IA'LOTE en un seul fichier .zip.

Contenu : réglages (alicia.toml), jeux, personnes, personnalités, carnet de partie, voix sur
mesure, habitués du chat, réglages du rond et animations. **Jamais les clés d'API** (.env) :
le fichier peut être partagé (ex. copier sa config chez Nova) sans rien divulguer.

Une sauvegarde automatique est faite chaque jour dans Documents\\COPIALOTE\\sauvegardes
(les 3 plus récentes sont gardées) : si le dossier de l'appli est effacé, tout se restaure.
"""

from __future__ import annotations

import json
import logging
import time
import zipfile
from datetime import datetime
from pathlib import Path

log = logging.getLogger("alicia.app")

# Fichiers d'état (%LOCALAPPDATA%\Alicia) à garder ; le reste (journaux, modèles, mémoire
# de partie) se recrée tout seul ou est trop volumineux.
STATE_FILES = ("voix_gemini.json", "orb.json", "habitues.json")
STATE_DIRS = ("anims",)
SKIP = (".env", ".tmp", "backups")
AUTO_KEEP = 3


def _dirs() -> tuple[Path, Path]:
    from alicia.core.config import data_dir, state_dir

    return data_dir(), state_dir()


def _secret(name: str) -> bool:
    low = name.casefold()
    return low.startswith(".env") or low.endswith(".tmp")


def create_backup(dest: Path, include_anims: bool = True) -> int:
    """Écrit le .zip ; renvoie le nombre de fichiers sauvegardés."""
    config, state = _dirs()
    count = 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as archive:
        if config.is_dir():
            for path in sorted(config.rglob("*")):
                rel = path.relative_to(config)
                if not path.is_file() or rel.parts[0] in SKIP or _secret(path.name):
                    continue
                archive.write(path, f"config/{rel.as_posix()}")
                count += 1
        for name in STATE_FILES:
            path = state / name
            if path.is_file():
                archive.write(path, f"state/{name}")
                count += 1
        if include_anims:
            for folder in STATE_DIRS:
                base = state / folder
                for path in sorted(base.rglob("*")) if base.is_dir() else ():
                    if path.is_file():
                        archive.write(path, f"state/{path.relative_to(state).as_posix()}")
                        count += 1
        from alicia import __version__

        archive.writestr(
            "copialote.json",
            json.dumps(
                {"app": "COP'IA'LOTE", "version": __version__, "date": datetime.now().isoformat()}
            ),
        )
    tmp.replace(dest)
    log.info("Sauvegarde : %d fichier(s) dans %s (sans les clés)", count, dest)
    return count


def restore_backup(source: Path) -> int:
    """Remet les fichiers de la sauvegarde ; renvoie leur nombre. Ne touche pas aux clés."""
    config, state = _dirs()
    count = 0
    with zipfile.ZipFile(source) as archive:
        names = archive.namelist()
        if "copialote.json" not in names:
            raise ValueError("Ce fichier n'est pas une sauvegarde de COP'IA'LOTE.")
        for name in names:
            parts = Path(name).parts
            if (
                len(parts) < 2
                or parts[0] not in ("config", "state")
                or ".." in parts
                or name.endswith("/")
                or _secret(parts[-1])
            ):
                continue
            base = config if parts[0] == "config" else state
            target = base.joinpath(*parts[1:])
            if base.resolve() not in target.resolve().parents:
                continue  # chemin bizarre : ignoré
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(name))
            count += 1
    log.info("Restauration : %d fichier(s) depuis %s", count, source)
    return count


def auto_folder() -> Path:
    documents = Path.home() / "Documents"
    return (documents if documents.is_dir() else Path.home()) / "COPIALOTE" / "sauvegardes"


def auto_backup(folder: Path | None = None, every_s: float = 86400.0) -> Path | None:
    """Sauvegarde du jour (si la dernière a plus d'un jour) ; garde les 3 plus récentes."""
    folder = folder or auto_folder()
    try:
        existing = sorted(folder.glob("copialote-*.zip"), key=lambda p: p.stat().st_mtime)
        if existing and time.time() - existing[-1].stat().st_mtime < every_s:
            return None
        dest = folder / f"copialote-{datetime.now():%Y-%m-%d_%H%M}.zip"
        create_backup(dest)
        for old in sorted(folder.glob("copialote-*.zip"), key=lambda p: p.stat().st_mtime)[
            :-AUTO_KEEP
        ]:
            old.unlink(missing_ok=True)
        return dest
    except OSError as exc:
        log.warning("Sauvegarde automatique impossible : %r", exc)
        return None
