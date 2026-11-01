"""CaptureService : seul point d'entrée de la capture pour le reste d'Alicia."""

from __future__ import annotations

import contextlib
import logging
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime

from alicia.core.capture.backends import (
    DEMO_WINDOW,
    CaptureBackend,
    DemoBackend,
    PrintWindowBackend,
    WgcBackend,
)
from alicia.core.capture.models import Frame, Rect, WindowInfo, image_from_bgra, is_black
from alicia.core.config import CaptureSettings
from alicia.core.errors import AliciaError, CaptureError

log = logging.getLogger("alicia.capture")
_quiet = threading.local()


@contextlib.contextmanager
def quiet_logs():
    """Captures de fond (vision en direct) : réussites au niveau DEBUG, pour ne pas écrire
    une ligne de journal par seconde sur le disque."""
    _quiet.on = True
    try:
        yield
    finally:
        _quiet.on = False


def _ok_level() -> int:
    return logging.DEBUG if getattr(_quiet, "on", False) else logging.INFO


def _problem_level(level: int) -> int:
    """Captures de fond : leurs échecs sont résumés par la vision en direct (pas une ligne
    d'erreur par seconde dans le journal)."""
    return logging.DEBUG if getattr(_quiet, "on", False) else level


class CaptureService:
    """Liste les fenêtres et capture celle choisie en essayant les backends dans l'ordre.

    Chaque repli est journalisé et noté dans la ``Frame`` : rien n'est silencieux.
    """

    def __init__(
        self,
        lister: Callable[[], list[WindowInfo]],
        refresher: Callable[[WindowInfo], WindowInfo],
        chain: Callable[[WindowInfo], Sequence[CaptureBackend]],
        keep_last: int = 5,
        foreground: Callable[[], WindowInfo | None] | None = None,
        cursor: Callable[[], tuple[int, int, int | None, Rect | None]] | None = None,
        screen_chain: Callable[[WindowInfo], Sequence[CaptureBackend]] | None = None,
    ) -> None:
        self._foreground = foreground
        self._cursor = cursor
        self._screen_chain = screen_chain
        self._lister = lister
        self._refresher = refresher
        self._chain = chain
        self.recent: deque[Frame] = deque(maxlen=keep_last)

    # --- fabriques ----------------------------------------------------------------------------

    @classmethod
    def for_windows(cls, settings: CaptureSettings) -> CaptureService:
        from alicia.core.capture.win32 import Win32

        win32 = Win32()

        def chain(window: WindowInfo) -> list[CaptureBackend]:
            if settings.backend == "printwindow":
                return [PrintWindowBackend(win32)]
            backends: list[CaptureBackend] = [WgcBackend("window", settings.timeout_s)]
            if settings.monitor_fallback and window.fullscreen:
                backends.append(WgcBackend("monitor", settings.timeout_s))
            if settings.backend == "auto":
                backends.append(PrintWindowBackend(win32))
            return backends

        def screen_chain(_screen: WindowInfo) -> list[CaptureBackend]:
            return [WgcBackend("monitor", settings.timeout_s)]

        return cls(
            win32.list_windows,
            win32.check_still_valid,
            chain,
            settings.keep_last_frames,
            foreground=win32.foreground_window,
            cursor=win32.cursor,
            screen_chain=screen_chain,
        )

    @classmethod
    def demo(cls, keep_last: int = 5) -> CaptureService:
        screen = Rect(0, 0, 1280, 720)
        return cls(
            lambda: [DEMO_WINDOW],
            lambda w: w,
            lambda w: [DemoBackend()],
            keep_last,
            cursor=lambda: (900, 300, 1, screen),
            screen_chain=lambda w: [DemoBackend()],
        )

    # --- opérations ---------------------------------------------------------------------------

    def list_windows(self) -> list[WindowInfo]:
        started = time.perf_counter()
        windows = self._lister()
        log.debug("%d fenêtres listées en %d ms", len(windows), _ms(started))
        return windows

    def foreground_window(self) -> WindowInfo | None:
        """Fenêtre active (hors Alicia), ou None si inconnue."""
        if self._foreground is None:
            return None
        try:
            return self._foreground()
        except Exception as exc:  # noqa: BLE001
            log.warning("Fenêtre active introuvable : %r", exc)
            return None

    def capture(
        self,
        window: WindowInfo | None,
        mode: str = "window",
        cursor_box: tuple[int, int] = (1280, 800),
    ) -> Frame:
        """« window » : l'application ; « screen » : l'écran entier ; « cursor » : une zone
        autour du curseur, avec le curseur marqué pour que l'IA voie ce que tu montres."""
        if mode in ("screen", "cursor"):
            return self._capture_screen(window, mode, cursor_box)
        if window is None:
            raise CaptureError(
                "Aucune application à regarder : mets le jeu au premier plan.",
                detail="mode application sans fenêtre",
            )
        return self._capture_window(window)

    def _screen_target(
        self, window: WindowInfo | None, mode: str
    ) -> tuple[WindowInfo, tuple[int, int] | None]:
        cursor = None
        if self._cursor is not None:
            try:
                cursor = self._cursor()
            except AliciaError as exc:
                log.warning("Curseur introuvable : %s", exc.detail)
        if mode == "screen" and window is not None and window.monitor_index is not None:
            index, rect = window.monitor_index, window.monitor_rect
        elif cursor is not None and cursor[2] is not None:
            index, rect = cursor[2], cursor[3]
        elif window is not None and window.monitor_index is not None:
            index, rect = window.monitor_index, window.monitor_rect
        else:
            raise CaptureError(
                "Impossible de savoir quel écran capturer.", detail=f"curseur {cursor}"
            )
        screen = WindowInfo(
            handle=0,
            title=f"Écran {index}",
            process_id=0,
            exe_name=window.exe_name if window else "",
            exe_path=window.exe_path if window else "",
            rect=rect,
            monitor_index=index,
            monitor_rect=rect,
        )
        point = None
        if cursor is not None and rect is not None and cursor[2] == index:
            point = (cursor[0] - rect.left, cursor[1] - rect.top)
        return screen, point

    def _capture_screen(
        self, window: WindowInfo | None, mode: str, cursor_box: tuple[int, int]
    ) -> Frame:
        if self._screen_chain is None:
            raise CaptureError("Capture d'écran indisponible.", detail="pas de backend écran")
        screen, point = self._screen_target(window, mode)
        frame = self._capture_window(screen, chain=self._screen_chain(screen), refresh=False)
        image = frame.image
        if mode == "cursor":
            if point is None:
                point = (image.width // 2, image.height // 2)
            # L'écran peut être capturé à une autre échelle que ses coordonnées Windows.
            if screen.monitor_rect is not None and screen.monitor_rect.width:
                scale = image.width / screen.monitor_rect.width
                point = (int(point[0] * scale), int(point[1] * scale))
            width, height = min(cursor_box[0], image.width), min(cursor_box[1], image.height)
            left = max(0, min(point[0] - width // 2, image.width - width))
            top = max(0, min(point[1] - height // 2, image.height - height))
            image = image.crop((left, top, left + width, top + height))
            point = (point[0] - left, point[1] - top)
        if point is not None:
            image = mark_cursor(image, point)
        frame = replace(frame, image=image, window=window or screen, cursor=point, mode=mode)
        self.recent[-1] = frame
        log.log(
            _ok_level(),
            "Vision %s : %dx%d%s",
            "autour du curseur" if mode == "cursor" else "écran entier",
            frame.width,
            frame.height,
            f", curseur en {point}" if point else "",
        )
        return frame

    def _capture_window(
        self,
        window: WindowInfo,
        chain: Sequence[CaptureBackend] | None = None,
        refresh: bool = True,
    ) -> Frame:
        started = time.perf_counter()
        try:
            if refresh:
                window = self._refresher(window)
        except AliciaError as exc:
            log.log(
                _problem_level(logging.ERROR),
                "Capture refusée pour « %s » : %s",
                window.title,
                exc.detail,
            )
            raise
        attempts: list[str] = []
        notes: list[str] = []
        for backend in chain if chain is not None else self._chain(window):
            step = time.perf_counter()
            try:
                pixels = backend.grab(window)
            except AliciaError as exc:
                attempts.append(f"{backend.name}: {exc.detail}")
                log.log(
                    _problem_level(logging.WARNING),
                    "Capture %s échouée : %s",
                    backend.name,
                    exc.detail,
                )
                continue
            except Exception as exc:  # noqa: BLE001 - erreur native inattendue
                attempts.append(f"{backend.name}: {exc!r}")
                log.warning("Capture %s : erreur inattendue %r", backend.name, exc)
                continue
            if is_black(pixels):
                attempts.append(f"{backend.name}: image noire")
                log.log(
                    _problem_level(logging.WARNING),
                    "Capture %s : image entièrement noire, essai suivant",
                    backend.name,
                )
                continue
            if attempts:
                notes.append("Repli après : " + " ; ".join(attempts))
            frame = Frame(
                image=image_from_bgra(pixels),
                window=window,
                backend=backend.name,
                captured_at=datetime.now(UTC),
                duration_ms=_ms(started),
                capture_id=uuid.uuid4().hex[:6],
                notes=tuple(notes),
            )
            self.recent.append(frame)
            log.log(
                _ok_level(),
                "Capture ok via %s : %dx%d en %d ms (grab %d ms)%s",
                backend.name,
                frame.width,
                frame.height,
                frame.duration_ms,
                _ms(step),
                " — " + notes[0] if notes else "",
            )
            return frame

        log.log(
            _problem_level(logging.ERROR),
            "Capture impossible de « %s » : %s",
            window.title,
            " | ".join(attempts),
        )
        hint = (
            " Le jeu est en plein écran : vérifie qu'il est bien sur l'écran affiché."
            if window.fullscreen
            else " Essaie le mode plein écran fenêtré du jeu."
        )
        raise CaptureError(
            "Impossible de capturer cette fenêtre (image noire ou refusée)." + hint,
            detail=" | ".join(attempts) or "aucun backend disponible",
        )

    @property
    def last(self) -> Frame | None:
        return self.recent[-1] if self.recent else None


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def mark_cursor(image, point: tuple[int, int]):  # type: ignore[no-untyped-def]
    """Cercle rose autour du curseur : l'IA voit ce que le joueur montre."""
    from PIL import ImageDraw

    marked = image.copy()
    draw = ImageDraw.Draw(marked)
    x, y = point
    radius = max(14, image.width // 60)
    for width, color in ((6, (0, 0, 0)), (3, (255, 61, 139))):
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), outline=color, width=width)
    draw.line((x - radius // 3, y, x + radius // 3, y), fill=(255, 61, 139), width=2)
    draw.line((x, y - radius // 3, x, y + radius // 3), fill=(255, 61, 139), width=2)
    return marked
