"""Backends de capture. Chacun renvoie des pixels BGRA (H×W×4, uint8) d'une fenêtre."""

from __future__ import annotations

import logging
import threading
import time
from typing import Protocol

import numpy as np
from PIL import Image, ImageDraw

from alicia.core.capture.models import WindowInfo, is_black
from alicia.core.errors import CaptureError

log = logging.getLogger("alicia.capture")


class CaptureBackend(Protocol):
    name: str

    def grab(self, window: WindowInfo) -> np.ndarray: ...


class WgcBackend:
    """Windows Graphics Capture via ``windows-capture`` (Rust, accéléré GPU).

    ``target="window"`` capture la fenêtre même recouverte ; ``target="monitor"`` capture
    l'écran entier où se trouve la fenêtre (utile pour un jeu en plein écran).
    Bordure jaune et curseur désactivés (Windows 11).
    """

    def __init__(self, target: str = "window", timeout_s: float = 2.0) -> None:
        if target not in ("window", "monitor"):
            raise ValueError(target)
        self.target = target
        self.name = f"wgc-{target}"
        self.timeout_s = timeout_s

    def grab(self, window: WindowInfo) -> np.ndarray:
        try:
            from windows_capture import WindowsCapture
        except ImportError as exc:  # pragma: no cover - dépend de Windows
            raise CaptureError(
                "Le module de capture Windows (windows-capture) n'est pas installé.",
                detail=repr(exc),
            ) from exc

        if self.target == "window":
            kwargs = {"window_hwnd": window.handle}
        else:
            if window.monitor_index is None:
                raise CaptureError("Impossible de déterminer l'écran du jeu.")
            kwargs = {"monitor_index": window.monitor_index}

        done = threading.Event()
        state: dict[str, object] = {"frames": 0}

        try:
            capture = WindowsCapture(cursor_capture=False, draw_border=False, **kwargs)
        except Exception as exc:  # erreur native : on garde le message pour les logs
            raise CaptureError(
                "La capture Windows (WGC) n'a pas pu démarrer.", detail=repr(exc)
            ) from exc

        def on_frame_arrived(frame, control):  # type: ignore[no-untyped-def]
            pixels = np.array(frame.frame_buffer, copy=True)  # le tampon natif est réutilisé
            state["frames"] = int(state["frames"]) + 1  # type: ignore[arg-type]
            state["pixels"] = pixels
            # Certains jeux livrent une première image noire : on en attend jusqu'à 3.
            if not is_black(pixels) or int(state["frames"]) >= 3:  # type: ignore[arg-type]
                done.set()
                control.stop()

        def on_closed():  # type: ignore[no-untyped-def]
            done.set()

        capture.event(on_frame_arrived)
        capture.event(on_closed)
        try:
            control = capture.start_free_threaded()
        except Exception as exc:
            raise CaptureError("La capture Windows (WGC) a été refusée.", detail=repr(exc)) from exc

        got_frame = done.wait(self.timeout_s)
        try:
            control.stop()
        except Exception:  # noqa: BLE001 - déjà arrêtée
            pass
        deadline = time.monotonic() + 1.0
        while not control.is_finished() and time.monotonic() < deadline:
            time.sleep(0.01)

        pixels = state.get("pixels")
        if not got_frame or pixels is None:
            raise CaptureError(
                "Aucune image reçue de Windows dans le délai imparti.",
                detail=f"{self.name}: timeout {self.timeout_s}s, frames={state['frames']}",
            )
        return pixels  # type: ignore[return-value]


class PrintWindowBackend:
    """Repli GDI : fonctionne pour les applications classiques, rarement pour les jeux 3D."""

    name = "printwindow"

    def __init__(self, win32) -> None:  # type: ignore[no-untyped-def]
        self._win32 = win32

    def grab(self, window: WindowInfo) -> np.ndarray:
        return self._win32.printwindow_pixels(window.handle)


DEMO_WINDOW = WindowInfo(handle=1, title="Démo — inventaire fictif", process_id=1, exe_name="demo")


def demo_image(width: int = 1280, height: int = 720) -> Image.Image:
    """Image synthétique clairement marquée comme démo : trois objets à comparer."""
    image = Image.new("RGB", (width, height), (24, 26, 36))
    draw = ImageDraw.Draw(image)
    draw.text((40, 30), "DÉMO ALICE — image synthétique, pas un vrai jeu", fill=(255, 200, 80))
    items = [
        ("Lame du crépuscule", "+12 dégâts", "+5 % vitesse d'attaque", (120, 80, 200)),
        ("Bouclier runique", "+150 PV", "+10 armure", (60, 140, 200)),
        ("Bottes rapides", "+15 % vitesse", "+20 PV", (80, 170, 110)),
    ]
    for index, (name, line1, line2, color) in enumerate(items):
        x = 60 + index * 400
        draw.rounded_rectangle((x, 140, x + 340, 520), radius=16, outline=color, width=4)
        draw.text((x + 24, 170), name, fill=(240, 240, 240))
        draw.text((x + 24, 220), line1, fill=(200, 230, 200))
        draw.text((x + 24, 250), line2, fill=(200, 230, 200))
    draw.text((40, height - 50), "Or disponible : 3 500", fill=(255, 215, 0))
    return image


class DemoBackend:
    name = "demo"

    def grab(self, window: WindowInfo) -> np.ndarray:
        rgb = np.asarray(demo_image())
        alpha = np.full(rgb.shape[:2] + (1,), 255, dtype=np.uint8)
        return np.concatenate([rgb[:, :, ::-1], alpha], axis=2)
