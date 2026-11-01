"""Données de capture, indépendantes de Windows et de Qt."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
from PIL import Image


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    def covers(self, other: Rect, tolerance: int = 2) -> bool:
        return (
            self.left <= other.left + tolerance
            and self.top <= other.top + tolerance
            and self.right >= other.right - tolerance
            and self.bottom >= other.bottom - tolerance
        )


@dataclass(frozen=True)
class WindowInfo:
    handle: int
    title: str
    process_id: int
    exe_name: str = ""
    rect: Rect | None = None
    monitor_index: int | None = None  # 1 = premier écran (ordre Windows)
    monitor_rect: Rect | None = None
    minimized: bool = False
    exe_path: str = ""  # chemin complet du programme (distingue les versions d'un même jeu)

    @property
    def fullscreen(self) -> bool:
        if self.rect is None or self.monitor_rect is None:
            return False
        return self.rect.covers(self.monitor_rect)

    @property
    def label(self) -> str:
        exe = f" — {self.exe_name}" if self.exe_name else ""
        return f"{self.title}{exe}"


@dataclass(frozen=True)
class Frame:
    image: Image.Image  # RGB
    window: WindowInfo
    backend: str  # ex. « wgc-window », « wgc-monitor », « printwindow », « demo »
    captured_at: datetime
    duration_ms: int
    capture_id: str
    notes: tuple[str, ...] = field(default_factory=tuple)
    cursor: tuple[int, int] | None = None  # position du curseur dans l'image (mode curseur)
    mode: str = "window"

    @property
    def width(self) -> int:
        return self.image.width

    @property
    def height(self) -> int:
        return self.image.height


def is_black(pixels: np.ndarray, threshold: int = 8) -> bool:
    """Vrai si l'image (H×W×C, uint8) est quasiment noire : capture invalide."""
    if pixels.size == 0:
        return True
    sample = pixels[::4, ::4, :3]
    return int(sample.max()) < threshold


def image_from_bgra(pixels: np.ndarray) -> Image.Image:
    """Convertit un tableau BGRA (H×W×4) en image RGB indépendante du tampon d'origine."""
    if pixels.ndim != 3 or pixels.shape[2] < 3:
        raise ValueError("Tableau de pixels BGRA attendu (hauteur × largeur × 4).")
    rgb = np.ascontiguousarray(pixels[:, :, 2::-1])
    return Image.fromarray(rgb, "RGB")
