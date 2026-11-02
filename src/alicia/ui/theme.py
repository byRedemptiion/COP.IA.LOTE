"""Thème HUD d'ALICIA, tiré de son portrait : bleu nuit, néons cyan et rose, armure rouge et or."""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont

from alicia.core.persona import current as current_persona

BG = "#040a24"
PANEL = "rgba(10, 18, 58, 0.72)"
BORDER = "#24307a"
CYAN = "#22e3ff"
CYAN_SOFT = "#7fefff"
PINK = "#ff3d8b"
PINK_SOFT = "#ff8cc0"
RED = "#c8143c"
GOLD = "#f5b62a"
TEXT = "#e9eeff"
MUTED = "#7f8cc4"
DANGER = "#ff3b5c"
DEEP = "#0a1240"  # fond des menus et petits panneaux
GLOW = "#12206a"  # haut du dégradé de fond

STATE_COLORS = {
    "idle": QColor(43, 140, 255),  # halo bleu du portrait
    "listening": QColor(34, 227, 255),  # cyan : elle t'écoute
    "observing": QColor(61, 220, 132),  # vert : le Copilote regarde ta partie (micro en veille)
    "thinking": QColor(155, 92, 255),  # violet : elle réfléchit
    "speaking": QColor(255, 61, 139),  # rose de ses cheveux : elle parle
    "action": QColor(245, 182, 42),  # or de son armure : action sur le PC
    "error": QColor(255, 40, 70),
}
_PERSONA = current_persona()
globals().update(_PERSONA.colors)  # VIIRUS : violet néon à la place du rose et de l'or
for _state, _rgb in _PERSONA.states.items():
    STATE_COLORS[_state] = QColor(*_rgb)

STATE_LABELS = {
    "idle": "EN VEILLE",
    "listening": "À L'ÉCOUTE",
    "observing": "OBSERVE",
    "thinking": "RÉFLÉCHIT",
    "speaking": "PARLE",
    "action": "ACTION",
    "error": "ERREUR",
}

PROJECT_NAME = "COP'IA'LOTE"  # le projet ; le personnage (ALICIA, VIIRUS…) est un profil
FONT_FAMILY = "Bahnschrift"  # police « DIN » fournie avec Windows ; repli automatique sinon


def title_font(size: float, weight: QFont.Weight = QFont.Weight.DemiBold) -> QFont:
    font = QFont([FONT_FAMILY, "Segoe UI", "Arial"])
    font.setPointSizeF(size)
    font.setWeight(weight)
    font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 118)
    return font


STYLESHEET = f"""
QMainWindow, QWidget#root {{
    background: qradialgradient(cx:0.5, cy:0.4, radius:0.95, fx:0.5, fy:0.4,
        stop:0 {GLOW}, stop:0.55 {BG}, stop:1 #02041a);
}}
QWidget {{
    color: {TEXT};
    font-family: "{FONT_FAMILY}", "Segoe UI";
    font-size: 10.5pt;
}}
QFrame#panel {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
QLabel#sectionTitle {{
    color: {GOLD};
    font-size: 9pt;
    font-weight: 600;
    letter-spacing: 3px;
}}
QLabel#muted, QLabel#chip {{
    color: {MUTED};
}}
QLabel#chip {{
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 3px 10px;
    background: rgba(18, 59, 79, 0.35);
}}
QLabel#asked {{
    color: {GOLD};
    font-size: 10.5pt;
    padding: 2px 0 6px 0;
    border-bottom: 1px solid {BORDER};
}}
QLabel#status {{
    color: {CYAN_SOFT};
    font-size: 11pt;
}}
QPushButton {{
    background: rgba(34, 227, 255, 0.06);
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 7px 14px;
    color: {TEXT};
    letter-spacing: 1px;
}}
QPushButton:hover {{
    border-color: {CYAN};
    background: rgba(34, 227, 255, 0.14);
}}
QPushButton:pressed {{
    background: rgba(34, 227, 255, 0.28);
}}
QPushButton:disabled {{
    color: #35505c;
    border-color: #0d2533;
    background: transparent;
}}
QPushButton#primary {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {RED}, stop:1 {PINK});
    color: #ffffff;
    font-weight: 700;
    border: none;
    padding: 9px 22px;
}}
QPushButton#primary:hover {{
    background: {PINK_SOFT};
    color: #2a0012;
}}
QPushButton#nav {{
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    border-radius: 0;
    padding: 6px 14px;
    color: {MUTED};
    font-weight: 600;
    letter-spacing: 2px;
}}
QPushButton#nav:hover {{
    color: {TEXT};
}}
QPushButton#nav:checked {{
    color: {PINK};
    border-bottom-color: {PINK};
}}
QPushButton#winButton, QPushButton#winClose {{
    background: transparent;
    border: none;
    color: {MUTED};
    font-size: 11pt;
    min-width: 34px;
    max-width: 34px;
    min-height: 30px;
    border-radius: 8px;
    padding: 0;
}}
QPushButton#winButton:hover {{
    background: rgba(255, 255, 255, 0.08);
    color: {TEXT};
}}
QPushButton#winClose:hover {{
    background: #e5304f;
    color: #ffffff;
}}
QPushButton#navIcon {{
    font-size: 15pt;
    padding: 1px 10px 3px 10px;
    color: {MUTED};
    background: transparent;
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QPushButton#navIcon:hover {{
    color: {TEXT};
    border-color: {PINK};
}}
QPushButton#navIcon:checked {{
    color: {PINK};
    border-color: {PINK};
}}
QPushButton#copilotToggle:checked {{
    color: #ffffff;
    border: 1px solid {PINK};
    background: {PANEL};
}}
QPushButton#settingsTab {{
    background: transparent;
    color: {MUTED};
    border: 1px solid transparent;
    border-bottom: none;
    border-top-left-radius: 10px;
    border-top-right-radius: 10px;
    border-bottom-left-radius: 0;
    border-bottom-right-radius: 0;
    padding: 8px 12px;
}}
QPushButton#settingsTab:hover {{
    color: {TEXT};
}}
QPushButton#settingsTab:checked {{
    color: {TEXT};
    background: {PANEL};
    border-color: {PINK};
}}
QFrame#settingsLine {{
    background: {PINK};
    border: none;
}}
QPushButton#chipButton {{
    color: {MUTED};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 3px 10px;
    background: rgba(18, 59, 79, 0.35);
}}
QPushButton#chipButton:hover {{
    color: {TEXT};
    border-color: {CYAN};
}}
QFrame#gameCard {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 rgba(18, 28, 88, 0.85), stop:1 rgba(8, 12, 46, 0.85));
    border: 1px solid {BORDER};
    border-radius: 14px;
}}
QFrame#gameCard:hover {{
    border-color: {PINK};
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 rgba(40, 24, 96, 0.9), stop:1 rgba(12, 14, 56, 0.9));
}}
QPushButton#ghost {{
    border: none;
    background: transparent;
    color: {MUTED};
    padding: 4px 8px;
}}
QPushButton#ghost:hover {{
    color: {CYAN};
}}
QLineEdit {{
    background: rgba(2, 10, 16, 0.85);
    border: 1px solid {BORDER};
    border-bottom: 2px solid {PINK};
    border-radius: 10px;
    padding: 10px 14px;
    font-size: 11.5pt;
    selection-background-color: {CYAN};
    selection-color: #ffffff;
}}
QLineEdit:focus {{
    border-color: {PINK};
}}
QTextBrowser, QPlainTextEdit {{
    background: transparent;
    border: none;
    selection-background-color: {CYAN};
    selection-color: #ffffff;
}}
QTextBrowser {{
    font-size: 12.5pt;
}}
QPlainTextEdit {{
    font-family: "Consolas";
    font-size: 8.5pt;
    color: #7fb4c4;
}}
QPlainTextEdit#field {{
    background: rgba(2, 10, 16, 0.85);
    border: 1px solid {BORDER};
    border-bottom: 2px solid {PINK};
    border-radius: 10px;
    padding: 6px 10px;
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 11.5pt;
    color: {TEXT};
}}
QListWidget {{
    background: rgba(2, 10, 16, 0.6);
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 4px;
    outline: 0;
}}
QListWidget::item {{
    padding: 6px 8px;
    border-radius: 6px;
}}
QListWidget::item:hover {{
    background: rgba(34, 227, 255, 0.08);
}}
QListWidget::item:selected {{
    background: rgba(255, 61, 139, 0.28);
    color: #ffffff;
}}
QCheckBox {{
    spacing: 8px;
    color: {TEXT};
}}
QCheckBox::indicator {{
    width: 30px;
    height: 16px;
    border-radius: 8px;
    border: 1px solid {BORDER};
    background: rgba(2, 10, 16, 0.85);
}}
QCheckBox::indicator:checked {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {RED}, stop:1 {PINK});
    border-color: {PINK};
}}
QProgressBar {{
    background: rgba(2, 10, 16, 0.85);
    border: 1px solid {BORDER};
    border-radius: 5px;
}}
QProgressBar::chunk {{
    border-radius: 4px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {CYAN}, stop:1 {PINK});
}}
QSlider::groove:horizontal {{
    height: 6px;
    border-radius: 3px;
    background: rgba(2, 10, 16, 0.85);
    border: 1px solid {BORDER};
}}
QSlider::sub-page:horizontal {{
    border-radius: 3px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {RED}, stop:1 {PINK});
}}
QSlider::handle:horizontal {{
    width: 16px;
    margin: -6px 0;
    border-radius: 8px;
    background: {TEXT};
    border: 2px solid {PINK};
}}
QRadioButton {{
    spacing: 10px;
    color: {TEXT};
}}
QRadioButton::indicator {{
    width: 14px;
    height: 14px;
    border-radius: 8px;
    border: 2px solid {BORDER};
    background: rgba(2, 10, 16, 0.85);
}}
QRadioButton::indicator:checked {{
    border-color: {PINK};
    background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
        stop:0 {PINK}, stop:0.55 {PINK}, stop:0.6 rgba(2, 10, 16, 0.85));
}}
QComboBox {{
    background: rgba(2, 10, 16, 0.85);
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 5px 10px;
}}
QComboBox:hover {{
    border-color: {CYAN};
}}
QComboBox QAbstractItemView {{
    background: {DEEP};
    border: 1px solid {BORDER};
    selection-background-color: rgba(34, 227, 255, 0.25);
}}
QSplitter::handle {{
    background: transparent;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: {CYAN};
}}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
    background: none;
    height: 0;
}}
QToolTip {{
    background: {DEEP};
    color: {TEXT};
    border: 1px solid {CYAN};
    padding: 4px 8px;
}}
"""


def rgb(hex_color: str) -> str:
    """« #7c4dff » → « 124, 77, 255 » (pour les rgba() des feuilles de style)."""
    value = hex_color.lstrip("#")
    return ", ".join(str(int(value[i : i + 2], 16)) for i in (0, 2, 4))


if _PERSONA.colors:  # teintes écrites en rgba() dans la feuille de style
    STYLESHEET = STYLESHEET.replace("rgba(34, 227, 255,", f"rgba({rgb(CYAN)},").replace(
        "rgba(255, 61, 139,", f"rgba({rgb(PINK)},"
    )
