"""Fenêtre sans la barre de titre Windows : l'en-tête de COP'IA'LOTE la remplace.

- glisser l'en-tête déplace la fenêtre (avec l'aimantation de Windows aux bords) ;
- double-clic sur l'en-tête : agrandir / restaurer ;
- les bords (quelques pixels) redimensionnent la fenêtre ;
- boutons –  ▢  ✕ dans le style de l'appli ;
- coins arrondis de Windows 11 conservés.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import QEvent, QObject, QPoint, Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QAbstractButton, QHBoxLayout, QMainWindow, QPushButton, QWidget

EDGE = 7  # largeur (px) de la zone de redimensionnement sur les bords


def _edges(widget: QWidget, pos: QPoint) -> Qt.Edge:
    edges = Qt.Edge(0)
    if pos.x() <= EDGE:
        edges |= Qt.Edge.LeftEdge
    elif pos.x() >= widget.width() - EDGE:
        edges |= Qt.Edge.RightEdge
    if pos.y() <= EDGE:
        edges |= Qt.Edge.TopEdge
    elif pos.y() >= widget.height() - EDGE:
        edges |= Qt.Edge.BottomEdge
    return edges


_CURSORS = {
    Qt.Edge.LeftEdge: Qt.CursorShape.SizeHorCursor,
    Qt.Edge.RightEdge: Qt.CursorShape.SizeHorCursor,
    Qt.Edge.TopEdge: Qt.CursorShape.SizeVerCursor,
    Qt.Edge.BottomEdge: Qt.CursorShape.SizeVerCursor,
    Qt.Edge.LeftEdge | Qt.Edge.TopEdge: Qt.CursorShape.SizeFDiagCursor,
    Qt.Edge.RightEdge | Qt.Edge.BottomEdge: Qt.CursorShape.SizeFDiagCursor,
    Qt.Edge.RightEdge | Qt.Edge.TopEdge: Qt.CursorShape.SizeBDiagCursor,
    Qt.Edge.LeftEdge | Qt.Edge.BottomEdge: Qt.CursorShape.SizeBDiagCursor,
}


_MOUSE = {
    QEvent.Type.MouseMove,
    QEvent.Type.Leave,
    QEvent.Type.MouseButtonPress,
    QEvent.Type.MouseButtonDblClick,
}


class _Frame(QObject):
    """Écoute la zone des bords (redimensionner) et l'en-tête (déplacer)."""

    def __init__(self, window: QMainWindow, title_bar: QWidget) -> None:
        super().__init__(window)
        self.window = window
        self.title_bar = title_bar

    def eventFilter(self, obj, event) -> bool:  # type: ignore[no-untyped-def]  # noqa: N802
        if event.type() not in _MOUSE:
            return False  # rien d'autre ne nous concerne (ni pendant la fermeture)
        try:
            return self._mouse(obj, event)
        except RuntimeError:  # fenêtre en cours de destruction
            return False

    def _mouse(self, obj, event) -> bool:  # type: ignore[no-untyped-def]
        kind = event.type()
        window = self.window
        if obj is window.centralWidget():
            if kind == QEvent.Type.MouseMove and not window.isMaximized():
                edges = _edges(obj, event.position().toPoint())
                if edges in _CURSORS:
                    obj.setCursor(QCursor(_CURSORS[edges]))
                else:
                    obj.unsetCursor()
            elif kind == QEvent.Type.Leave:
                obj.unsetCursor()
            elif (
                kind == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton
                and not window.isMaximized()
            ):
                edges = _edges(obj, event.position().toPoint())
                if edges in _CURSORS and window.windowHandle() is not None:
                    window.windowHandle().startSystemResize(edges)
                    return True
        if obj is self.title_bar or (
            isinstance(obj, QWidget)
            and not isinstance(obj, QAbstractButton)
            and self.title_bar.isAncestorOf(obj)
        ):
            if (
                kind == QEvent.Type.MouseButtonDblClick
                and event.button() == Qt.MouseButton.LeftButton
            ):
                toggle_maximized(window)
                return True
            if kind == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                if window.windowHandle() is not None:
                    window.windowHandle().startSystemMove()
                    return True
        return False


def toggle_maximized(window: QMainWindow) -> None:
    window.showNormal() if window.isMaximized() else window.showMaximized()


def window_buttons(window: QMainWindow) -> QWidget:
    """Les trois boutons de fenêtre : réduire, agrandir, fermer."""
    box = QWidget()
    row = QHBoxLayout(box)
    row.setContentsMargins(8, 0, 0, 0)
    row.setSpacing(2)
    for text, tip, action, name in (
        ("—", "Réduire", window.showMinimized, "winButton"),
        ("▢", "Agrandir / restaurer", lambda: toggle_maximized(window), "winButton"),
        ("✕", "Fermer", window.close, "winClose"),
    ):
        button = QPushButton(text)
        button.setObjectName(name)
        button.setToolTip(tip)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.clicked.connect(action)
        row.addWidget(button)
    return box


def make_frameless(window: QMainWindow, title_bar: QWidget) -> None:
    """Retire la barre de titre Windows ; ``title_bar`` (l'en-tête) sert à déplacer."""
    window.setWindowFlags(
        Qt.WindowType.Window
        | Qt.WindowType.FramelessWindowHint
        | Qt.WindowType.WindowMinMaxButtonsHint  # réduire depuis la barre des tâches
        | Qt.WindowType.WindowSystemMenuHint
    )
    frame = _Frame(window, title_bar)
    central = window.centralWidget()
    central.setMouseTracking(True)
    central.installEventFilter(frame)
    title_bar.installEventFilter(frame)
    for child in title_bar.findChildren(QWidget):
        if not isinstance(child, QAbstractButton):
            child.installEventFilter(frame)
    window._frame_filter = frame  # type: ignore[attr-defined]  # garde le filtre en vie


def round_corners(window: QWidget) -> None:
    """Windows 11 : coins arrondis et ombre, même sans barre de titre."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        hwnd = int(window.winId())
        preference = ctypes.c_int(2)  # DWMWCP_ROUND
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 33, ctypes.byref(preference), ctypes.sizeof(preference)
        )  # 33 = DWMWA_WINDOW_CORNER_PREFERENCE
    except (AttributeError, OSError):
        pass  # Windows 10 : coins carrés, rien de grave
