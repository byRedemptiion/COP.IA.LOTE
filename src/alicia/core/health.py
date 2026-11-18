"""Santé du logiciel sur la durée : mémoire, fils, poignées Windows, captures ouvertes.

Après des heures, une fuite (mémoire, poignées graphiques, sessions de capture) peut finir par
bloquer tout le PC. Toutes les 5 min, on note l'état au journal ; si ça dérape (mémoire ou
poignées qui explosent), on fait le ménage tout de suite et on prévient.
Mesures Windows par ctypes (aucune dépendance) ; ailleurs, seulement ce qui est disponible.
"""

from __future__ import annotations

import logging
import sys
import threading
from dataclasses import dataclass

log = logging.getLogger("alicia.app")

RAM_ALERT_MB = 2500  # au-delà : ménage + avertissement
HANDLES_ALERT = 15000
GDI_ALERT = 8000  # Windows plafonne à 10 000 objets GDI par programme


@dataclass(frozen=True)
class Health:
    ram_mb: float
    threads: int
    handles: int = -1  # poignées Windows (fichiers, fils, événements…)
    gdi: int = -1  # objets graphiques GDI
    user: int = -1  # objets USER (fenêtres, menus…)
    captures_open: int = 0  # sessions de capture Windows pas encore refermées

    def text(self) -> str:
        parts = [f"mémoire {self.ram_mb:.0f} Mo", f"{self.threads} fils"]
        if self.handles >= 0:
            parts.append(f"{self.handles} poignées")
        if self.gdi >= 0:
            parts.append(f"GDI {self.gdi}, USER {self.user}")
        parts.append(f"captures ouvertes {self.captures_open}")
        return ", ".join(parts)

    def problems(self) -> list[str]:
        found = []
        if self.ram_mb > RAM_ALERT_MB:
            found.append(f"mémoire {self.ram_mb:.0f} Mo")
        if self.handles > HANDLES_ALERT:
            found.append(f"{self.handles} poignées Windows")
        if self.gdi > GDI_ALERT:
            found.append(f"{self.gdi} objets graphiques")
        if self.captures_open > 3:
            found.append(f"{self.captures_open} captures restées ouvertes")
        return found


def _windows() -> tuple[float, int, int, int]:
    import ctypes
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
            ("PrivateUsage", ctypes.c_size_t),
        ]

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    process = kernel32.GetCurrentProcess()
    counters = Counters()
    counters.cb = ctypes.sizeof(Counters)
    ctypes.windll.psapi.GetProcessMemoryInfo(  # type: ignore[attr-defined]
        process, ctypes.byref(counters), counters.cb
    )
    handles = wintypes.DWORD()
    kernel32.GetProcessHandleCount(process, ctypes.byref(handles))
    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    gdi = user32.GetGuiResources(process, 0)
    user = user32.GetGuiResources(process, 1)
    return counters.PrivateUsage / 1_048_576, int(handles.value), int(gdi), int(user)


def measure() -> Health:
    from alicia.core.capture.backends import open_captures

    threads = threading.active_count()
    if sys.platform == "win32":
        try:
            ram, handles, gdi, user = _windows()
            return Health(ram, threads, handles, gdi, user, open_captures())
        except (AttributeError, OSError):
            pass
    ram = 0.0
    try:
        import resource

        ram = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024  # Ko → Mo (Linux)
    except (ImportError, OSError):
        pass
    return Health(ram, threads, captures_open=open_captures())
