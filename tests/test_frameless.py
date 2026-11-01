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


def test_update_channel_switches_branch(qt_app, tmp_path, monkeypatch):
    import tomllib

    from alicia.core.config import data_dir
    from alicia.ui.main_window import MainWindow

    monkeypatch.chdir(tmp_path)
    window = MainWindow(
        build_services(load_settings(environ={"ALICE_AI_PROVIDER": "fake"}), demo=True)
    )
    try:
        box = window.settings_page.channel_box
        assert box.currentData() == "alice-v0.3"
        box.setCurrentIndex(box.findData("alice-test"))
        assert window.services.settings.update.branch == "alice-test"
        saved = tomllib.loads((data_dir() / "alicia.toml").read_text("utf-8"))
        assert saved["update"]["branch"] == "alice-test"
    finally:
        window.close()
