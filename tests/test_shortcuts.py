import tomllib

import pytest
from PySide6.QtCore import Qt

from alicia.core.user_config import set_value
from alicia.ui.hotkey import hotkey_label, parse_hotkey
from alicia.ui.shortcuts_page import key_to_hotkey


def test_player_settings_are_edited_in_place(tmp_path):
    path = tmp_path / "alicia.toml"
    path.write_text(
        '# mes réglages\n[voice]\nspeak_answers = false  # garde ce commentaire\n\n[hotkeys]\ntalk = "F10"\n',
        "utf-8",
    )
    set_value("hotkeys", "talk", "mouse4", path)
    set_value("hotkeys", "analyze", "ctrl+f9", path)
    set_value("ui", "orb_size", 240, path)
    text = path.read_text("utf-8")
    assert "# garde ce commentaire" in text and "# mes réglages" in text
    data = tomllib.loads(text)
    assert data["hotkeys"] == {"talk": "mouse4", "analyze": "ctrl+f9"}
    assert data["voice"]["speak_answers"] is False
    assert data["ui"]["orb_size"] == 240


def test_new_file_is_created(tmp_path):
    path = set_value("hotkeys", "talk", "f8", tmp_path / "sub" / "alicia.toml")
    assert tomllib.loads(path.read_text("utf-8")) == {"hotkeys": {"talk": "f8"}}


@pytest.mark.parametrize(
    ("text", "vk"),
    [
        ("F10", 0x79),
        ("ctrl+f9", 0x78),
        ("mouse4", 0x05),
        ("mouse5", 0x06),
        ("num5", 0x65),
        ("v", 0x56),
    ],
)
def test_supported_keys(text, vk):
    assert parse_hotkey(text)[1] == vk


def test_labels_are_readable():
    assert hotkey_label("ctrl+mouse4") == "Ctrl + Souris 4"
    assert hotkey_label("f10") == "F10"


def test_qt_keys_become_hotkeys():
    none = Qt.KeyboardModifier.NoModifier
    assert key_to_hotkey(Qt.Key.Key_F7, none) == "f7"
    assert key_to_hotkey(Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier) == "ctrl+v"
    assert key_to_hotkey(Qt.Key.Key_5, Qt.KeyboardModifier.KeypadModifier) == "num5"
    assert key_to_hotkey(Qt.Key.Key_Insert, none) == "insert"
    assert key_to_hotkey(Qt.Key.Key_Eacute, none) is None


def test_changing_the_talk_key_is_saved_and_checked(qt_app, tmp_path, monkeypatch):
    from alicia.app import build_services
    from alicia.core.ai.providers.fake import FakeModel
    from alicia.core.config import data_dir, load_settings
    from alicia.ui.main_window import MainWindow

    settings = load_settings(cwd=tmp_path, environ={"ALICE_AI_PROVIDER": "fake"})
    window = MainWindow(build_services(settings, demo=True, model=FakeModel()))
    window.show_page(2)
    assert window.pages.currentWidget() is window.settings_page
    window.change_hotkey("talk", "mouse4")
    assert window.hotkey_texts["talk"] == "mouse4"
    saved = tomllib.loads((data_dir() / "alicia.toml").read_text("utf-8"))
    assert saved["hotkeys"]["talk"] == "mouse4"
    window.change_hotkey("analyze", "mouse4")  # déjà prise par « parler »
    assert window.hotkey_texts["analyze"] == "F9"
    assert "déjà" in window.shortcuts_page.states["analyze"].text()
    assert load_settings(cwd=tmp_path).hotkey_talk == "mouse4"  # relu au prochain lancement
    window.close()


def test_french_keyboard_keys_are_supported():
    none = Qt.KeyboardModifier.NoModifier
    assert key_to_hotkey(Qt.Key.Key_Less, none, native_vk=0xE2) == "vk226"
    assert key_to_hotkey(Qt.Key.Key_Ampersand, none, native_vk=0x31) == "vk49"  # touche 1/&
    assert parse_hotkey("vk226")[1] == 0xE2
    assert parse_hotkey("<")[1] == 0xE2
    assert hotkey_label("vk226") == "Touche <"
    assert hotkey_label("ctrl+vk49") == "Ctrl + Touche 1"
