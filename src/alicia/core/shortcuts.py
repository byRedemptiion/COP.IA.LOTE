"""Raccourcis Windows au nom et à l'icône du profil choisi (ALICIA, VIIRUS…).

Au démarrage, le raccourci du bureau et celui du menu Démarrer prennent le nom et l'icône
du profil : « VIIRUS » avec l'icône de VIIRUS chez l'un, « ALICIA » chez l'autre. Seuls les
raccourcis qui lancent COP'IA'LOTE sont renommés ; les autres fichiers ne sont jamais touchés.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import threading
from importlib import resources
from pathlib import Path

from alicia.core.persona import PERSONAS, Persona

log = logging.getLogger("alicia.app")

# Remplace ou crée le raccourci ; supprime les anciens noms qui lancent le même programme.
_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$shell = New-Object -ComObject WScript.Shell
$target = $env:COPIA_TARGET
$folders = @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))
foreach ($folder in $folders) {
  if (-not $folder -or -not (Test-Path $folder)) { continue }
  $wanted = Join-Path $folder ($env:COPIA_NAME + '.lnk')
  $found = $false
  foreach ($old in ($env:COPIA_OLD -split '\|')) {
    $path = Join-Path $folder ($old + '.lnk')
    if ((Test-Path $path) -and ($shell.CreateShortcut($path).TargetPath -ieq $target)) {
      $found = $true
      if ($path -ne $wanted) { Remove-Item -LiteralPath $path }
    }
  }
  if ($found) {  # seulement nos raccourcis : un raccourci supprimé n'est pas recréé
    $link = $shell.CreateShortcut($wanted)
    $link.TargetPath = $target
    $link.WorkingDirectory = $env:COPIA_DIR
    $link.IconLocation = $env:COPIA_ICON + ',0'
    $link.Description = $env:COPIA_NAME + " - COP'IA'LOTE"
    $link.Save()
  }
}
"""


def _icon_file(persona: Persona, root: Path, cache: Path) -> Path | None:
    """L'icône sur le disque : dans le dossier d'installation, sinon copiée dans le cache."""
    installed = root / "src" / "alicia" / "assets" / persona.icon
    if installed.is_file():
        return installed
    try:
        data = resources.files("alicia.assets").joinpath(persona.icon).read_bytes()
    except OSError:
        return None
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / persona.icon
    path.write_bytes(data)
    return path


def sync_shortcuts(persona: Persona, root: Path | None, cache: Path) -> bool:
    """Met le raccourci du bureau (et du menu Démarrer) au nom et à l'icône du profil."""
    if sys.platform != "win32" or root is None:
        return False
    target = root / ".venv" / "Scripts" / "alicia-gui.exe"
    icon = _icon_file(persona, root, cache)
    powershell = shutil.which("powershell")
    if not target.is_file() or icon is None or powershell is None:
        return False
    old = {p.title for p in PERSONAS.values()} | {"ALICIA", "Alicia", "VERIS", "COP'IA'LOTE"}
    env = dict(
        os.environ,
        COPIA_TARGET=str(target),
        COPIA_DIR=str(root),
        COPIA_ICON=str(icon),
        COPIA_NAME=persona.title,
        COPIA_OLD="|".join(sorted(old)),
    )
    try:
        result = subprocess.run(
            [powershell, "-NoProfile", "-NonInteractive", "-Command", _SCRIPT],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("Raccourci du bureau non mis à jour : %r", exc)
        return False
    if result.returncode != 0:
        log.warning("Raccourci du bureau non mis à jour : %s", result.stderr.strip()[:300])
        return False
    log.info("Raccourci du bureau : « %s » avec son icône", persona.title)
    return True


def sync_shortcuts_async(persona: Persona, root: Path | None, cache: Path) -> None:
    threading.Thread(
        target=sync_shortcuts, args=(persona, root, cache), name="alicia-shortcuts", daemon=True
    ).start()
