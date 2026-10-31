"""Panneau image flottant : la carte ou l'image du guide, par-dessus le jeu.

Simple affichage : il ne clique ni ne tape rien dans le jeu. On le déplace à la souris,
la molette l'agrandit, ✕ le ferme.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from alicia.ui.theme import DEEP, PINK, TEXT


class ImagePanel(QWidget):
    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setObjectName("imagePanel")
        self.setStyleSheet(
            f"QWidget#imagePanel {{ background:{DEEP}; border:1px solid {PINK}; "
            f"border-radius:12px; }} QLabel {{ color:{TEXT}; }}"
        )
        self.url = ""
        self.width_px = 520
        self._pixmap = QPixmap()
        self._drag: QPoint | None = None
        box = QVBoxLayout(self)
        box.setContentsMargins(10, 8, 10, 10)
        top = QHBoxLayout()
        self.title = QLabel("")
        self.title.setWordWrap(True)
        open_page = QPushButton("📖 Page")
        open_page.setToolTip("Ouvrir la page dans le navigateur")
        open_page.clicked.connect(self.open_page)
        close = QPushButton("✕")
        close.setFixedWidth(32)
        close.clicked.connect(self.hide)
        top.addWidget(self.title, 1)
        top.addWidget(open_page)
        top.addWidget(close)
        box.addLayout(top)
        self.picture = QLabel()
        self.picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(self.picture, 1)

    def show_image(self, data: bytes, title: str, url: str) -> bool:
        pixmap = QPixmap()
        if not pixmap.loadFromData(data):
            return False
        self._pixmap, self.url = pixmap, url
        self.title.setText(title[:120])
        self._render()
        if not self.isVisible():
            screen = QGuiApplication.primaryScreen().availableGeometry()
            self.move(screen.right() - self.width() - 40, screen.top() + 260)
        self.show()
        self.raise_()
        return True

    def _render(self) -> None:
        if self._pixmap.isNull():
            return
        scaled = self._pixmap.scaledToWidth(
            min(self.width_px, max(self._pixmap.width(), 320)),
            Qt.TransformationMode.SmoothTransformation,
        )
        self.picture.setPixmap(scaled)
        self.adjustSize()

    def open_page(self) -> None:
        if self.url.startswith(("http://", "https://")):
            QDesktopServices.openUrl(QUrl(self.url))

    def wheelEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        step = 60 if event.angleDelta().y() > 0 else -60
        self.width_px = max(280, min(1400, self.width_px + step))
        self._render()

    def mousePressEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        if self._drag is not None:
            self.move(event.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, _event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        self._drag = None
