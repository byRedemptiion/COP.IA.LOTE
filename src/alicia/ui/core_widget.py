"""Le « cœur » d'ALICIA : anneaux animés qui montrent son état et réagissent au son.

Dessiné avec QPainter (aucune image, aucune dépendance). L'animation s'arrête quand la
fenêtre est cachée ou réduite, pour ne pas consommer de processeur pendant le jeu.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from importlib import resources

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QMovie, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QSizePolicy, QWidget

from alicia.core.persona import current as current_persona
from alicia.ui.theme import STATE_COLORS, STATE_LABELS, title_font

# Vitesse de rotation (tours par seconde) des anneaux, par état.
SPEED = {
    "idle": 0.05,
    "listening": 0.12,
    "thinking": 0.6,
    "speaking": 0.18,
    "action": 0.3,
    "error": 0.02,
}
BARS = 72
# Cadrage du portrait en mode bulle : le visage et le buste (fractions de l'image).
FACE_CROP = (0.2, 0.07, 0.58, 0.58)


def _round_pen(color: QColor, width: float) -> QPen:
    pen = QPen(color, width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    return pen


class AliciaCore(QWidget):
    def __init__(
        self,
        parent: QWidget | None = None,
        portrait: str | None = None,
        *,
        show_labels: bool = True,
        minimum: int = 300,
    ) -> None:
        super().__init__(parent)
        self.portrait = self._load_portrait(portrait)
        self.show_labels = show_labels
        # Animations du personnage (facultatives) : dossier anims\<nom>\, voir core/anims.py
        self._movie: QMovie | None = None
        self._still: QPixmap | None = None
        self._playing = ""
        self._gesture = ""
        self._lips: list[QPixmap] = []
        self.anim_folder = None
        self.anims_on = True  # animations du robot (préférence du mode bulle)
        self.show_hud = True  # anneaux et barres autour du robot
        self.setMinimumSize(minimum, minimum)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.state = "idle"
        self.level_source: Callable[[], float] | None = None
        self._color = QColor(STATE_COLORS["idle"])
        self._angle = 0.0
        self._level = 0.0
        self._bars = [0.0] * BARS
        self._last = time.perf_counter()
        self._timer = QTimer(self)
        self._timer.setInterval(33)  # ~30 images/s : fluide et léger
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self.load_anims()

    @staticmethod
    def _load_portrait(path: str | None) -> QPixmap | None:
        try:
            if path:
                pixmap = QPixmap(path)
            else:
                name = current_persona().portrait
                data = resources.files("alicia.assets").joinpath(name).read_bytes()
                pixmap = QPixmap()
                pixmap.loadFromData(data)
        except (OSError, ModuleNotFoundError):
            return None
        return None if pixmap.isNull() else pixmap

    # --- animations -----------------------------------------------------------------------------

    def load_anims(self, folder=None) -> None:  # type: ignore[no-untyped-def]
        """(Re)lit le dossier d'animations du personnage."""
        from alicia.core import anims

        self.anim_folder = folder or anims.anim_dir()
        custom = anims.find("portrait", self.anim_folder, (".png", ".webp", ".jpg"))
        if custom is not None:
            pixmap = QPixmap(str(custom))
            if not pixmap.isNull():
                self.portrait = pixmap
        if not self.anims_on:
            self._stop_movie()
            self._lips, self._playing = [], ""
            self.update()
            return
        self._lips = [QPixmap(str(p)) for p in anims.lip_frames(self.anim_folder)]
        self._lips = [p for p in self._lips if not p.isNull()]
        self._playing = ""
        self._play(self.state)

    def _stop_movie(self) -> None:
        if self._movie is not None:
            self._movie.stop()
            self._movie.deleteLater()
        self._movie, self._still = None, None

    def _play(self, name: str, once: bool = False) -> bool:
        from alicia.core import anims

        if self.anim_folder is None or not self.anims_on:
            return False
        path = anims.find(name, self.anim_folder)
        if path is None:
            return name != "idle" and not once and self._play("idle")
        if self._playing == path.name:
            return True
        self._stop_movie()
        self._playing = path.name
        if path.suffix == ".png":
            self._still = QPixmap(str(path))
            return True
        movie = QMovie(str(path))
        if not movie.isValid():
            self._playing = ""
            return False
        movie.setCacheMode(QMovie.CacheMode.CacheNone)  # image par image : peu de mémoire
        movie.frameChanged.connect(lambda frame: self._frame_changed(movie, frame, once))
        self._movie = movie
        movie.start()
        if not self.isVisible():
            movie.setPaused(True)
        return True

    def _frame_changed(self, movie: QMovie, frame: int, once: bool) -> None:
        if once and movie.frameCount() > 0 and frame >= movie.frameCount() - 1:
            QTimer.singleShot(movie.nextFrameDelay(), self._gesture_done)
        self.update()

    def _gesture_done(self) -> None:
        self._gesture = ""
        self._playing = ""
        self._play(self.state)

    def play_gesture(self, name: str) -> bool:
        """Geste joué une fois (wake, nod, shake, hop…), puis retour à l'état en cours."""
        from alicia.core import anims

        if self.anim_folder is None or anims.find(name, self.anim_folder) is None:
            return False
        self._gesture = name
        self._playing = ""
        return self._play(name, once=True)

    def _frame(self) -> QPixmap | None:
        """L'image à mettre dans le rond : bouche, animation, ou rien (portrait)."""
        if self.state == "speaking" and self._lips and not self._gesture:
            index = min(len(self._lips) - 1, int(self._level * len(self._lips) * 1.6))
            return self._lips[index]
        if self._movie is not None:
            pixmap = self._movie.currentPixmap()
            return None if pixmap.isNull() else pixmap
        return self._still

    # --- état -----------------------------------------------------------------------------------

    def set_state(self, state: str, level_source: Callable[[], float] | None = None) -> None:
        if state not in STATE_COLORS:
            state = "idle"
        changed = state != self.state
        self.state = state
        self.level_source = level_source
        if changed and not self._gesture:
            self._play(state)
        self.update()

    def showEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        super().showEvent(event)
        self._timer.start()
        if self._movie is not None:
            self._movie.setPaused(False)

    def hideEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        super().hideEvent(event)
        self._timer.stop()
        if self._movie is not None:
            self._movie.setPaused(True)  # rien ne tourne pendant que le rond est caché

    def _tick(self) -> None:
        window = self.window()
        if window is not None and window.isMinimized():
            return
        now = time.perf_counter()
        dt, self._last = min(now - self._last, 0.1), now
        self._angle = (self._angle + 360 * SPEED.get(self.state, 0.05) * dt) % 360
        target = 0.0
        if self.level_source is not None:
            try:
                target = max(0.0, min(1.0, float(self.level_source())))
            except Exception:  # noqa: BLE001 - une source audio qui disparaît ne doit rien casser
                target = 0.0
        elif self.state == "thinking":
            target = 0.35 + 0.25 * math.sin(now * 6)
        else:
            target = 0.12 + 0.08 * math.sin(now * 1.6)  # respiration
        self._level += (target - self._level) * 0.35
        for i in range(BARS):
            wave = 0.5 + 0.5 * math.sin(now * 5 + i * 0.55) * math.sin(now * 2.3 + i * 0.21)
            goal = self._level * (0.35 + 0.65 * wave)
            self._bars[i] += (goal - self._bars[i]) * 0.4
        target_color = STATE_COLORS.get(self.state, STATE_COLORS["idle"])
        self._color = QColor(
            int(self._color.red() + (target_color.red() - self._color.red()) * 0.15),
            int(self._color.green() + (target_color.green() - self._color.green()) * 0.15),
            int(self._color.blue() + (target_color.blue() - self._color.blue()) * 0.15),
        )
        self.update()

    # --- dessin ---------------------------------------------------------------------------------

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        label_space = 54.0 if self.show_labels else 0.0
        size = min(self.width(), self.height() - label_space) - (12 if self.show_labels else 4)
        radius = size / 2
        center = QPointF(
            self.width() / 2, (self.height() - label_space) / 2 + (6 if self.show_labels else 0)
        )
        color = self._color

        def tint(alpha: int, lighter: int = 100) -> QColor:
            c = QColor(color).lighter(lighter)
            c.setAlpha(max(0, min(255, alpha)))
            return c

        if self.show_hud:  # anneaux, arcs et barres (masquables en mode bulle)
            # Halo
            glow = QRadialGradient(center, radius * 1.05)
            glow.setColorAt(0.0, tint(int(70 + 90 * self._level)))
            glow.setColorAt(0.45, tint(28))
            glow.setColorAt(1.0, tint(0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(glow)
            painter.drawEllipse(center, radius, radius)

            # Anneau extérieur gradué (rotation lente)
            painter.save()
            painter.translate(center)
            painter.rotate(self._angle * 0.4)
            outer = radius * 0.94
            for i in range(120):
                major = i % 10 == 0
                painter.setPen(QPen(tint(170 if major else 70), 2 if major else 1))
                inner = outer - (radius * 0.05 if major else radius * 0.025)
                a = math.radians(i * 3)
                painter.drawLine(
                    QPointF(math.cos(a) * inner, math.sin(a) * inner),
                    QPointF(math.cos(a) * outer, math.sin(a) * outer),
                )
            painter.restore()

            # Arcs intermédiaires (sens inverse)
            painter.save()
            painter.translate(center)
            painter.rotate(-self._angle)
            mid = radius * 0.8
            rect = QRectF(-mid, -mid, mid * 2, mid * 2)
            for k, span in enumerate((70, 40, 100)):
                painter.setPen(_round_pen(tint(200 - k * 40), 3 - k * 0.6))
                painter.drawArc(rect, int((k * 120) * 16), int(span * 16))
            inner_mid = radius * 0.72
            rect2 = QRectF(-inner_mid, -inner_mid, inner_mid * 2, inner_mid * 2)
            painter.rotate(self._angle * 2.2)
            painter.setPen(QPen(tint(120), 1.5))
            painter.drawArc(rect2, 0, 50 * 16)
            painter.drawArc(rect2, 180 * 16, 50 * 16)
            painter.restore()

            # Barres réactives au son
            painter.save()
            painter.translate(center)
            compact = not self.show_labels
            base = radius * (0.66 if compact else 0.5)
            for i, value in enumerate(self._bars):
                a = math.radians(i * 360 / BARS - 90)
                length = radius * ((0.02 + 0.12 * value) if compact else (0.03 + 0.17 * value))
                painter.setPen(_round_pen(tint(int(90 + 160 * value), 120), 2.2))
                painter.drawLine(
                    QPointF(math.cos(a) * base, math.sin(a) * base),
                    QPointF(math.cos(a) * (base + length), math.sin(a) * (base + length)),
                )
            painter.restore()

        # Noyau : portrait d'ALICIA, qui « flotte » doucement et grossit un peu quand elle parle
        core_r = radius * ((0.63 if compact else 0.47) + 0.025 * self._level)
        bob = math.sin(time.perf_counter() * 1.4) * radius * 0.012
        core_center = QPointF(center.x(), center.y() + bob)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(6, 12, 46, 245))
        painter.drawEllipse(core_center, core_r, core_r)
        frame = self._frame()
        if frame is not None:
            # Animation : image carrée cadrée sur le robot, qui remplit le rond
            painter.save()
            clip = QPainterPath()
            clip.addEllipse(core_center, core_r, core_r)
            painter.setClipPath(clip)
            side = min(frame.width(), frame.height())
            source = QRectF((frame.width() - side) / 2, (frame.height() - side) / 2, side, side)
            target = QRectF(
                core_center.x() - core_r, core_center.y() - core_r, core_r * 2, core_r * 2
            )
            painter.drawPixmap(target, frame, source)
            painter.restore()
        elif self.portrait is not None:
            painter.save()
            clip = QPainterPath()
            clip.addEllipse(core_center, core_r, core_r)
            painter.setClipPath(clip)
            if compact or current_persona().round_portrait:  # cadré sur le visage
                w, h = self.portrait.width(), self.portrait.height()
                fx, fy, fw, fh = current_persona().face_crop
                source = QRectF(fx * w, fy * h, fw * w, fh * h)
                side = core_r * 2
                target = QRectF(core_center.x() - core_r, core_center.y() - core_r, side, side)
            else:
                source = QRectF(self.portrait.rect())
                side = core_r * 2.15  # léger zoom : le visage remplit le cercle
                target = QRectF(
                    core_center.x() - side / 2, core_center.y() - side * 0.47, side, side
                )
            painter.drawPixmap(target, self.portrait, source)
            painter.restore()
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for width, alpha in ((7, 50), (3.5, 120), (1.6, 255)):
            painter.setPen(QPen(tint(alpha, 115), width))
            painter.drawEllipse(core_center, core_r, core_r)

        if not self.show_labels:
            painter.end()
            return

        # Nom et état sous les anneaux
        text_top = center.y() + radius + 4
        painter.setPen(tint(255, 140))
        painter.setFont(title_font(17))
        painter.drawText(
            QRectF(0, text_top, self.width(), 26),
            Qt.AlignmentFlag.AlignCenter,
            " ".join(current_persona().title),
        )
        painter.setPen(tint(210, 110))
        painter.setFont(title_font(9))
        painter.drawText(
            QRectF(0, text_top + 26, self.width(), 18),
            Qt.AlignmentFlag.AlignCenter,
            STATE_LABELS.get(self.state, ""),
        )
        painter.end()
