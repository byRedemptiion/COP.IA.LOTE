"""Vision en direct : ALICIA a toujours une capture récente de l'écran sous la main.

Économe : l'écran est capturé dès que tu commences à parler (début de voix au micro ou
appui sur F10), plus une capture de fond espacée (10 s par défaut) pour la mémoire de
partie. Ainsi l'IA voit l'écran tel qu'il était quand tu as parlé, sans capturer en
continu (une capture par seconde pendant des heures chauffe le PC pour rien).

Les images restent en mémoire (les 3 dernières) : rien n'est envoyé à l'IA ni enregistré
tant que tu ne poses pas de question.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from alicia.core.capture.models import Frame, WindowInfo
from alicia.core.capture.service import quiet_logs
from alicia.core.errors import AliciaError

log = logging.getLogger("alicia.capture")

Target = Callable[[], tuple[WindowInfo | None, str, tuple[int, int]]]


class LiveCapture:
    def __init__(
        self,
        capture: Callable[[WindowInfo | None, str, tuple[int, int]], Frame],
        target: Target,
        interval_s: float = 1.0,
        on_frame: Callable[[Frame], object] | None = None,
    ) -> None:
        self._capture = capture
        self.on_frame = on_frame  # ex. mémoire de partie
        self._target = target
        self.interval_s = max(0.3, interval_s)
        self._wake = threading.Event()  # capture demandée tout de suite
        self.latest: Frame | None = None
        self.latest_at = 0.0  # time.perf_counter() de la dernière capture réussie
        self.frames = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._errors = 0

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="alicia-live", daemon=True)
        self._thread.start()
        log.info(
            "Vision en direct : capture quand tu parles, sinon toutes les %.0f s (en mémoire)",
            self.interval_s,
        )

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(2.0)
        self._thread = None
        log.info("Vision en direct coupée")

    def trigger(self) -> float:
        """Capture dès que possible (début de phrase). Renvoie l'instant de la demande,
        à passer à ``since``. Appelable depuis n'importe quel thread."""
        self._wake.set()
        return time.perf_counter()

    def since(self, mark: float, wait_s: float = 0.0) -> Frame | None:
        """La capture faite après ``mark`` (en l'attendant au plus ``wait_s`` secondes)."""
        deadline = time.perf_counter() + wait_s
        while True:
            if self.latest is not None and self.latest_at > mark:
                return self.latest
            if time.perf_counter() >= deadline:
                return None
            time.sleep(0.02)

    def fresh(self, max_age_s: float = 3.0) -> Frame | None:
        """La dernière capture si elle a moins de ``max_age_s`` secondes."""
        if self.latest is None or time.perf_counter() - self.latest_at > max_age_s:
            return None
        return self.latest

    def grab_once(self) -> Frame | None:
        window, mode, box = self._target()
        if mode == "window" and window is None:
            return None
        try:
            frame = self._capture(window, mode, box)
        except AliciaError as exc:
            self._errors += 1
            if self._errors in (1, 10) or self._errors % 100 == 0:
                log.warning("Vision en direct : capture impossible (%s)", exc.detail)
            return None
        self._errors = 0
        self.latest, self.latest_at = frame, time.perf_counter()
        self.frames += 1
        if self.on_frame is not None:
            try:
                self.on_frame(frame)
            except Exception:  # noqa: BLE001
                log.exception("Vision en direct : traitement de l'image impossible")
        return frame

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._wake.clear()
            try:
                with quiet_logs():
                    self.grab_once()
            except Exception:  # noqa: BLE001 - la vision en direct ne doit jamais planter ALICIA
                log.exception("Vision en direct : erreur inattendue")
            self._wake.wait(self.interval_s)  # capture de fond… ou tout de suite si tu parles
            self._stop.wait(0.2)  # au plus 5 captures par seconde, même si tu parles beaucoup
