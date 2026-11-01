"""Le nom du personnage dans les textes de l'interface (« ALICIA » → « VIIRUS »)."""

from __future__ import annotations

import re
import sys
from importlib import resources

from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton,
    QComboBox,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QWidget,
)

from alicia.core.persona import current

_NAME = re.compile(r"(?<![\\/%])\b(d'|qu'|D'|QU'|d’|qu’)?(ALICIA|Alicia)\b(?![\\/])")
_ELISION = {"d'": "de ", "qu'": "que ", "D'": "DE ", "QU'": "QUE ", "d’": "de ", "qu’": "que "}


_MASCULINE = [
    (re.compile(r"\bqu'elle\b"), "qu'il"),
    (re.compile(r"\bQu'elle\b"), "Qu'il"),
    (re.compile(r"\belle\b"), "il"),
    (re.compile(r"\bElle\b"), "Il"),
    (re.compile(r"\btoute seule\b"), "tout seul"),
    (re.compile(r"\bseule\b"), "seul"),
]


def spaced(title: str, sep: str = " ") -> str:
    return sep.join(title)


def named(text: str) -> str:
    """Texte avec le nom du personnage choisi (sans toucher aux dossiers « …\\Alicia\\ »)."""
    persona = current()
    if persona.key == "alicia" or not text:
        return text
    text = text.replace("A · L · I · C · I · A", spaced(persona.title, " · "))
    text = text.replace("A L I C I A", spaced(persona.title))

    def swap(match: re.Match[str]) -> str:
        prefix, word = match.group(1), match.group(2)
        name = persona.title if word.isupper() else persona.name
        if prefix and persona.name[0].lower() not in "aeiouyh":
            prefix = _ELISION[prefix]
        return (prefix or "") + name

    text = _NAME.sub(swap, text)
    if not persona.feminine:  # VIIRUS : « il se réveille tout seul »
        for pattern, value in _MASCULINE:
            text = pattern.sub(value, text)
    return text


def rename_widgets(root: QWidget) -> None:
    """Applique le nom du personnage à tous les textes déjà affichés sous ``root``."""
    if current().key == "alicia":
        return
    for widget in [root, *root.findChildren(QWidget)]:
        if widget.property("keep_names"):
            continue  # texte qui cite déjà les deux robots (duo)
        if isinstance(widget, QComboBox):
            for index in range(widget.count()):
                if widget.itemData(index) in ("veris", "voixc"):
                    continue  # voix de VIIRUS / voix C d'ALICIA : leur vrai nom
                widget.setItemText(index, named(widget.itemText(index)))
        if widget.windowTitle():
            widget.setWindowTitle(named(widget.windowTitle()))
        if widget.toolTip():
            widget.setToolTip(named(widget.toolTip()))
        if isinstance(widget, QLabel | QAbstractButton) and widget.text():
            widget.setText(named(widget.text()))
        elif isinstance(widget, QGroupBox) and widget.title():
            widget.setTitle(named(widget.title()))
        if isinstance(widget, QLineEdit | QPlainTextEdit) and widget.placeholderText():
            widget.setPlaceholderText(named(widget.placeholderText()))


def app_icon() -> QIcon:
    """Icône du personnage (fenêtres et barre des tâches), tirée de son .ico multi-tailles."""
    persona = current()
    icon = QIcon()
    for name in (persona.icon, persona.portrait):
        try:
            data = resources.files("alicia.assets").joinpath(name).read_bytes()
        except (OSError, ModuleNotFoundError):
            continue
        pixmap = QPixmap()
        if name.endswith(".ico"):
            from PySide6.QtCore import QBuffer, QByteArray
            from PySide6.QtGui import QImageReader

            buffer = QBuffer()
            buffer.setData(QByteArray(data))
            reader = QImageReader(buffer, b"ico")
            while True:
                image = reader.read()
                if image.isNull():
                    break
                icon.addPixmap(QPixmap.fromImage(image))
                if not reader.jumpToNextImage():
                    break
        elif pixmap.loadFromData(data):
            icon.addPixmap(pixmap)
        if not icon.isNull():
            break
    return icon


def set_taskbar_identity() -> None:
    """Windows : ALICIA / VIIRUS a sa propre icône dans la barre des tâches (pas celle de
    Python), et ses fenêtres y sont regroupées."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        app_id = f"byRedemptiion.Alicia.{current().key}"
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        pass


def persona_avatar(persona, size: int = 52) -> QPixmap:  # type: ignore[no-untyped-def]
    """Tête ronde d'un personnage (pour la bulle du duo)."""
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QPainter, QPainterPath

    source = QPixmap()
    try:
        source.loadFromData(
            resources.files("alicia.assets").joinpath(persona.portrait).read_bytes()
        )
    except OSError:
        return QPixmap()
    if source.isNull():
        return source
    fx, fy, fw, fh = persona.face_crop
    crop = QRectF(
        fx * source.width(), fy * source.height(), fw * source.width(), fh * source.height()
    )
    out = QPixmap(size, size)
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    clip = QPainterPath()
    clip.addEllipse(QRectF(0, 0, size, size))
    painter.setClipPath(clip)
    painter.drawPixmap(QRectF(0, 0, size, size), source, crop)
    painter.end()
    return out
