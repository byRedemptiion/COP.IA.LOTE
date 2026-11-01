from dataclasses import replace

import pytest

from alicia.core.ai.factory import create_deep_model, wants_deep_thinking
from alicia.core.ai.providers.fake import FakeModel
from alicia.core.config import load_settings


@pytest.mark.parametrize(
    ("question", "deep"),
    [
        ("Analyse ma partie et dis-moi la meilleure stratégie", True),
        ("Réfléchis bien : quel build pour Ashe ?", True),
        ("Que dois-je faire les 5 prochaines minutes ?", True),
        ("C'est quoi cet objet ?", False),
        ("Je vois un ennemi à droite ?", False),
    ],
)
def test_deep_questions(question, deep):
    assert wants_deep_thinking(question) is deep


def test_create_deep_model():
    settings = load_settings(environ={"ALICE_AI_PROVIDER": "fake"})
    assert create_deep_model(settings.ai) is None
    ai = replace(settings.ai, deep_provider="ollama", deep_model="")
    model = create_deep_model(ai)
    assert model.provider == "ollama" and model.model == "qwen3.8:27b"


def test_deep_questions_go_to_the_second_brain(tmp_path):
    from alicia.app import build_services
    from alicia.core.capture.models import WindowInfo

    settings = load_settings(environ={"ALICE_AI_PROVIDER": "fake"})
    fast, deep = FakeModel(), FakeModel()
    fast.model, deep.model = "rapide", "reflechi"
    services = build_services(settings, demo=True, model=fast)
    services.analysis.deep_model = deep
    window = WindowInfo(1, "Démo — inventaire fictif", 1, "demo.exe")
    simple = services.analysis.analyze(window, "C'est quoi cet objet ?")
    hard = services.analysis.analyze(window, "Analyse ma partie et donne la meilleure stratégie")
    assert simple.result.model == "rapide"
    assert hard.result.model == "reflechi"


def test_brain_settings_are_saved(qt_app, tmp_path, monkeypatch):
    import tomllib

    from alicia.app import build_services
    from alicia.core.config import data_dir
    from alicia.ui.main_window import MainWindow

    monkeypatch.chdir(tmp_path)
    window = MainWindow(
        build_services(load_settings(environ={"ALICE_AI_PROVIDER": "fake"}), demo=True)
    )
    page = window.settings_page
    page.deep_box.setCurrentIndex(page.deep_box.findData("gemini"))
    page.ollama_model.setCurrentIndex(page.ollama_model.findData("lfm3-omni:2b"))
    page.ollama_model.activated.emit(page.ollama_model.currentIndex())
    saved = tomllib.loads((data_dir() / "alicia.toml").read_text("utf-8"))
    assert saved["ai"]["deep_provider"] == "gemini"
    assert saved["ai"]["ollama"]["model"] == "lfm3-omni:2b"
    assert window.services.settings.ai.deep_provider == "gemini"
    assert not page.deep_model.isHidden()  # modèle en ligne optionnel

    page.deep_box.setCurrentIndex(page.deep_box.findData("ollama"))
    page.ollama_deep_model.setEditText("qwen3-vl:8b")
    page.ollama_deep_model.lineEdit().editingFinished.emit()
    saved = tomllib.loads((data_dir() / "alicia.toml").read_text("utf-8"))
    assert saved["ai"]["ollama"]["deep_model"] == "qwen3-vl:8b"
    assert window.services.settings.ai.ollama.deep_model == "qwen3-vl:8b"
    assert page.deep_model.isHidden()
    assert page.ollama_states["reflechi"].text() == "● utilisé"

    page.fast_box.setCurrentIndex(page.fast_box.findData("ollama"))
    saved = tomllib.loads((data_dir() / "alicia.toml").read_text("utf-8"))
    assert saved["ai"]["provider"] == "ollama"
    window.close()


def test_old_ollama_deep_model_moves_to_the_ollama_section(tmp_path):
    path = tmp_path / "alicia.toml"
    path.write_text(
        '[ai]\nprovider = "gemini"\ndeep_provider = "ollama"\ndeep_model = "qwen3-vl:8b"\n',
        encoding="utf-8",
    )
    ai = load_settings(cwd=tmp_path, user_dir=tmp_path, environ={}).ai
    assert ai.ollama.deep_model == "qwen3-vl:8b" and ai.deep_model == ""
    assert create_deep_model(ai).model == "qwen3-vl:8b"


def test_tester_makes_a_real_call(qt_app, tmp_path, monkeypatch):
    from alicia.app import build_services
    from alicia.core.ai.providers.fake import FakeModel
    from alicia.core.errors import ProviderError, ProviderErrorKind
    from alicia.ui.main_window import MainWindow
    from tests.test_duo import _wait

    monkeypatch.chdir(tmp_path)
    model = FakeModel()
    window = MainWindow(
        build_services(load_settings(environ={"ALICE_AI_PROVIDER": "fake"}), demo=True, model=model)
    )
    state = window.settings_page.brain_labels["rapide"]["state"]
    try:
        window.test_brain("rapide")
        _wait(qt_app, lambda: "✓" in state.text())
        assert "la clé marche" in state.text() and model.requests[-1].images == ()
        model.fail_with = ProviderError(ProviderErrorKind.AUTH, "Clé refusée par Gemini.")
        window.test_brain("rapide")
        _wait(qt_app, lambda: "⚠" in state.text())
        assert "refusée" in state.text()
    finally:
        window.close()
