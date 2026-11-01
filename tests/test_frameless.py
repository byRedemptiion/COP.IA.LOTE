from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton, QWidget

from alicia.app import build_services
from alicia.core.config import load_settings


def test_window_has_its_own_title_bar(qt_app, tmp_path, monkeypatch):
    from alicia.ui.frameless import toggle_maximized
    from alicia.ui.main_window import MainWindow

    monkeypatch.chdir(tmp_path)
    window = MainWindow(
        build_services(load_settings(environ={"ALICE_AI_PROVIDER": "fake"}), demo=True)
    )
    try:
        assert window.windowFlags() & Qt.WindowType.FramelessWindowHint
        buttons = {b.toolTip(): b for b in window.findChildren(QPushButton)}
        assert {"Réduire", "Agrandir / restaurer", "Fermer"} <= set(buttons)
        assert window.findChild(QWidget, "titleBar") is not None
        window.show()
        toggle_maximized(window)
        assert window.isMaximized()
        toggle_maximized(window)
        assert not window.isMaximized()
    finally:
        window.close()
