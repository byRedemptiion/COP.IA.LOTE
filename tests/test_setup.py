import logging

from alicia.core.config import load_settings
from alicia.core.user_config import set_env


def test_api_key_is_written_without_being_logged(tmp_path, caplog):
    path = tmp_path / ".env"
    path.write_text("# mes clés\nALICE_LOG_LEVEL=INFO\nGEMINI_API_KEY=ancienne\n", "utf-8")
    with caplog.at_level(logging.INFO):
        set_env("GEMINI_API_KEY", "AQ.nouvelle-cle", path)
    text = path.read_text("utf-8")
    assert "GEMINI_API_KEY=AQ.nouvelle-cle" in text and "ancienne" not in text
    assert "ALICE_LOG_LEVEL=INFO" in text and "# mes clés" in text
    assert "AQ.nouvelle-cle" not in caplog.text


def test_key_chosen_in_alicia_is_used_right_away(qt_app, tmp_path, monkeypatch):
    from alicia.app import build_services
    from alicia.core.ai.providers.fake import FakeModel
    from alicia.ui.main_window import MainWindow

    monkeypatch.chdir(tmp_path)
    settings = load_settings(environ={})
    assert not settings.ai.gemini.api_key
    window = MainWindow(build_services(settings, demo=True, model=FakeModel()))
    assert window._needs_key()
    window.apply_ai_choice("gemini", "AQ.cle-de-test")
    assert window.services.model.provider == "gemini"
    assert window.services.model.check() is None  # clé présente
    assert not window._needs_key()
    assert load_settings().ai.gemini.api_key.get() == "AQ.cle-de-test"  # relue au lancement
    assert "gemini" in window.provider_label.text()
    window.close()


def test_dialog_asks_for_a_key_before_saving(qt_app):
    from alicia.ui.setup_dialog import SetupDialog

    dialog = SetupDialog("gemini", has_key=False)
    dialog.save()
    assert dialog.choice is None and "Colle" in dialog.status.text()
    dialog.key_input.setText("  AQ.cle  ")
    dialog.save()
    assert dialog.choice == ("gemini", "AQ.cle")
    other = SetupDialog("gemini", has_key=True)
    other.ollama.setChecked(True)
    assert not other.gemini_box.isVisibleTo(other) and other.ollama_box.isVisibleTo(other)
    other.save()
    assert other.choice == ("ollama", "")


def test_chatgpt_key_is_saved_under_its_own_name(qt_app, tmp_path, monkeypatch):
    from alicia.app import build_services
    from alicia.core.ai.providers.fake import FakeModel
    from alicia.ui.main_window import MainWindow
    from alicia.ui.setup_dialog import SetupDialog

    dialog = SetupDialog("gemini", {"gemini": True, "openai": False})
    dialog.openai.setChecked(True)
    assert "OpenAI" in dialog.open_page.text()
    dialog.save()
    assert dialog.choice is None and "OpenAI" in dialog.status.text()
    dialog.key_input.setText("sk-test")
    dialog.save()
    assert dialog.choice == ("openai", "sk-test")

    monkeypatch.chdir(tmp_path)
    window = MainWindow(build_services(load_settings(environ={}), demo=True, model=FakeModel()))
    window.apply_ai_choice("openai", "sk-test")
    settings = load_settings()
    assert settings.ai.provider == "openai" and settings.ai.openai.api_key.get() == "sk-test"
    assert window.services.model.provider == "openai" and not window._needs_key()
    window.close()
