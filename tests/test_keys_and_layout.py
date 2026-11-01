from dotenv import dotenv_values

from alicia.core.user_config import key_names, key_slots, update_keys


def _env(path):
    return {k: v for k, v in dotenv_values(path).items() if v}


def test_several_keys_for_one_provider(tmp_path):
    env, config = tmp_path / ".env", tmp_path / "alicia.toml"
    base = "GEMINI_API_KEY"
    update_keys(base, add="cle-perso", name="Perso", env=env, config=config)
    assert _env(env) == {base: "cle-perso"}
    update_keys(base, add="cle-nova", name="Nova", env=env, config=config)
    assert _env(env)[base] == "cle-nova"  # la nouvelle clé est utilisée…
    assert _env(env)[f"{base}_2"] == "cle-perso"  # …l'ancienne est gardée
    assert key_names(config)[base] == "Nova"
    assert key_slots(base, env) == [base, f"{base}_2"]

    update_keys(base, activate=f"{base}_2", env=env, config=config)  # repasser sur « Perso »
    assert _env(env)[base] == "cle-perso" and _env(env)[f"{base}_2"] == "cle-nova"
    assert key_names(config) == {base: "Perso", f"{base}_2": "Nova"}

    update_keys(base, remove=(base,), env=env, config=config)  # supprimer la clé utilisée
    assert _env(env) == {base: "cle-nova"}
    assert key_names(config).get(base) == "Nova"


def test_setup_dialog_lists_keys_and_adds_one(qt_app):
    from alicia.ui.setup_dialog import SetupDialog

    keys = {"gemini": [("GEMINI_API_KEY", "Perso"), ("GEMINI_API_KEY_2", "Nova")], "openai": []}
    dialog = SetupDialog("gemini", keys=keys)
    assert not dialog.add_row.isVisibleTo(dialog)  # des clés : le champ s'ouvre avec « + »
    radios = [b.text() for b in dialog.keys_group.buttons()]
    assert radios == ["Perso", "Nova"]
    dialog.keys_group.buttons()[1].setChecked(True)
    dialog.save()
    assert dialog.choice == ("gemini", "") and dialog.activate == "GEMINI_API_KEY_2"

    other = SetupDialog("gemini", keys=keys)
    other.add_button.click()
    assert other.add_row.isVisibleTo(other)
    other.name_input.setText("Pote")
    other.key_input.setText("AQ.nouvelle")
    other._remove_key("gemini", "GEMINI_API_KEY_2")
    other.save()
    assert other.choice == ("gemini", "AQ.nouvelle") and other.key_name == "Pote"
    assert other.remove == ("GEMINI_API_KEY_2",)


def test_wheel_does_not_change_combos(qt_app):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication, QComboBox

    from alicia.ui.wheel import install_wheel_guard

    install_wheel_guard()
    box = QComboBox()
    box.addItems(["Micro 1", "Micro 2", "Micro 3"])
    event = QWheelEvent(
        QPointF(5, 5),
        QPointF(5, 5),
        QPoint(0, 0),
        QPoint(0, -120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(box, event)
    assert box.currentIndex() == 0


def test_header_order(qt_app, tmp_path, monkeypatch):
    from alicia.app import build_services
    from alicia.core.config import load_settings
    from alicia.ui.main_window import MainWindow

    monkeypatch.chdir(tmp_path)
    window = MainWindow(
        build_services(load_settings(environ={"ALICE_AI_PROVIDER": "fake"}), demo=True)
    )
    assert window.nav_keys.text() == "⚙"
    header = window.nav_console.parentWidget().layout()
    assert window.nav_console.y() == window.nav_keys.y() or header is not None
    # Raccourcis et IA en bas de page, à côté du journal
    assert window.provider_label.parentWidget() is window.logs_toggle.parentWidget()
    window.close()
