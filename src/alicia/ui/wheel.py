"""La molette fait défiler la page, sans changer les listes déroulantes ni les curseurs.

Sans ça, faire défiler les réglages change le micro, la voix… dès que la souris passe sur
une liste. Pour changer une valeur : un clic (la liste s'ouvre) ou glisser le curseur.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QAbstractScrollArea, QAbstractSpinBox, QComboBox, QSlider, QWidget

_GUARDED = (QComboBox, QSlider, QAbstractSpinBox)


class WheelGuard(QObject):
    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() != QEvent.Type.Wheel or not isinstance(obj, _GUARDED):
            return False
        area = _scroll_area(obj)  # type: ignore[arg-type]
        if area is not None:
            bar = area.verticalScrollBar()
            bar.setValue(bar.value() - event.angleDelta().y())  # type: ignore[attr-defined]
        return True  # la valeur ne change pas


def _scroll_area(widget: QWidget) -> QAbstractScrollArea | None:
    parent = widget.parentWidget()
    while parent is not None:
        if isinstance(parent, QAbstractScrollArea) and not isinstance(parent, _GUARDED):
            return parent
        parent = parent.parentWidget()
    return None


_installed: WheelGuard | None = None


def install_wheel_guard() -> None:
    """Une seule fois pour toute l'application."""
    global _installed
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if _installed is None and app is not None:
        _installed = WheelGuard(app)
        app.installEventFilter(_installed)
