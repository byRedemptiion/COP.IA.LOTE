"""Exécution Windows des actions du catalogue. Aucune commande libre, aucune entrée clavier."""

from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys
from typing import Protocol

from alicia.core.errors import AliciaError, UnsupportedPlatformError

log = logging.getLogger("alicia.actions")

_NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW


class SystemControl(Protocol):
    def shutdown(self, delay_s: int, restart: bool = False) -> None: ...
    def cancel_shutdown(self) -> None: ...
    def sleep(self) -> None: ...
    def lock(self) -> None: ...
    def volume(self) -> int: ...
    def set_volume(self, percent: int) -> None: ...
    def set_mute(self, muted: bool) -> None: ...
    def launch(self, target: str) -> None: ...
    def close(self, process: str) -> int: ...


class WindowsSystem:
    def __init__(self) -> None:
        if sys.platform != "win32":
            raise UnsupportedPlatformError("Les actions sur le PC nécessitent Windows.")

    @staticmethod
    def _run(args: list[str]) -> None:
        result = subprocess.run(  # liste d'arguments fixe, jamais de shell
            args, capture_output=True, text=True, timeout=10, creationflags=_NO_WINDOW
        )
        if result.returncode != 0:
            raise AliciaError(
                f"Windows a refusé l'action ({args[0]}).",
                detail=f"{args} → code {result.returncode} : {result.stderr.strip()[:200]}",
            )

    def shutdown(self, delay_s: int, restart: bool = False) -> None:
        self._run(["shutdown", "/r" if restart else "/s", "/t", str(int(delay_s))])

    def cancel_shutdown(self) -> None:
        self._run(["shutdown", "/a"])

    def sleep(self) -> None:
        # SetSuspendState(hibernate=False, force=False, wakeupEventsDisabled=False)
        if not ctypes.windll.powrprof.SetSuspendState(False, False, False):
            raise AliciaError("Windows a refusé la mise en veille.")

    def lock(self) -> None:
        if not ctypes.windll.user32.LockWorkStation():
            raise AliciaError("Windows a refusé le verrouillage.")

    @staticmethod
    def _endpoint():  # type: ignore[no-untyped-def]
        try:
            from pycaw.pycaw import AudioUtilities
        except ImportError as exc:
            raise AliciaError("Module de volume (pycaw) absent.", detail=repr(exc)) from exc
        return AudioUtilities.GetSpeakers().EndpointVolume

    def volume(self) -> int:
        return round(self._endpoint().GetMasterVolumeLevelScalar() * 100)

    def set_volume(self, percent: int) -> None:
        endpoint = self._endpoint()
        endpoint.SetMute(0, None)
        endpoint.SetMasterVolumeLevelScalar(max(0, min(100, percent)) / 100, None)

    def set_mute(self, muted: bool) -> None:
        self._endpoint().SetMute(1 if muted else 0, None)

    def launch(self, target: str) -> None:
        try:
            os.startfile(target)  # type: ignore[attr-defined]  # chemin ou lien (discord://…)
        except OSError as exc:
            raise AliciaError(
                f"Impossible de lancer « {target} ». Vérifie le chemin dans alicia.toml.",
                detail=repr(exc),
            ) from exc

    def close(self, process: str) -> int:
        result = subprocess.run(
            ["taskkill", "/IM", process],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=_NO_WINDOW,
        )
        if result.returncode == 128:  # processus introuvable
            return 0
        if result.returncode != 0:
            raise AliciaError(
                f"Impossible de fermer {process}.", detail=result.stderr.strip()[:200]
            )
        return 1
