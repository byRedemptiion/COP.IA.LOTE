from datetime import datetime

from PIL import Image

from alicia.app import build_services
from alicia.core.ai.base import AnalysisResult, PreparedImage
from alicia.core.capture.models import Frame, WindowInfo
from alicia.core.config import load_settings
from alicia.core.copilot import (
    Copilot,
    CopilotGate,
    Decision,
    parse_copilot_command,
    parse_decision,
)


class JsonModel:
    provider, model = "fake", "copilote-1"

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.requests = []

    def check(self):
        return None

    def analyze(self, request, on_delta=None, cancel=None):
        self.requests.append(request)
        return AnalysisResult(self.reply, self.provider, self.model, 5)


def test_parse_decision_tolerates_fences_and_junk():
    found = parse_decision(
        '```json\n{"speak": true, "importance": 8, "message": "Recule, ta vie est basse.", '
        '"reason": "PV 10 %"}\n```'
    )
    assert found == Decision(True, 8, "Recule, ta vie est basse.", "PV 10 %")
    assert parse_decision("pas de json") is None
    assert parse_decision('{"speak": "true", "importance": "12", "message": ""}').speak is False
    assert parse_decision('{"speak": true, "importance": 99, "message": "x"}').importance == 10


def test_gate_threshold_cooldown_and_repeats():
    gate = CopilotGate(threshold=7, cooldown_s=60)
    ok = Decision(True, 8, "Achète une potion avant de repartir.")
    assert gate.allow(Decision(False, 9, ""), now=0)[0] is False
    assert gate.allow(Decision(True, 6, "bof"), now=0) == (False, "importance 6 < seuil 7")
    assert gate.allow(ok, now=0) == (True, "conseil")
    gate.spoke(ok.message, now=0)
    allowed, why = gate.allow(Decision(True, 8, "Pense à ton ultime."), now=30)
    assert not allowed and "délai de silence" in why
    assert gate.allow(Decision(True, 9, "Le boss charge, esquive !"), now=30)[0]  # urgence
    assert gate.allow(Decision(True, 8, "Achète une potion avant de repartir !"), now=90) == (
        False,
        "déjà dit",
    )
    assert gate.allow(Decision(True, 8, "Pense à ton ultime."), now=90)[0]


def test_observe_sends_one_small_request_with_rules():
    model = JsonModel('{"speak": true, "importance": 9, "message": "Esquive !", "reason": "AoE"}')
    copilot = Copilot(CopilotGate(7, 60))
    image = PreparedImage(b"jpg", "image/jpeg", 10, 10)
    decision, speak, why = copilot.observe(model, image, "Jeu : Elden Ring")
    assert speak and decision.message == "Esquive !" and why == "urgent"
    request = model.requests[0]
    assert "MODE COPILOTE" in request.system_prompt and "Elden Ring" in request.system_prompt
    assert request.max_output_tokens <= 200 and len(request.images) == 1
    copilot.observe(model, image)  # 2e fois : redite, et le prompt rappelle ce qui a été dit
    assert "Esquive !" in model.requests[1].system_prompt


def _frame():
    from alicia.core.capture.models import Rect

    screen = Rect(0, 0, 1920, 1080)
    window = WindowInfo(
        1, "Elden Ring", 42, exe_name="eldenring.exe", rect=screen, monitor_rect=screen
    )
    return Frame(Image.new("RGB", (64, 48)), window, "demo", datetime.now(), 1, "c1")


def test_window_copilot_speaks_only_when_it_matters(qt_app, tmp_path, monkeypatch):
    from alicia.core.config import data_dir
    from alicia.ui.main_window import MainWindow
    from tests.test_duo import _wait

    monkeypatch.chdir(tmp_path)
    settings = load_settings(environ={"ALICE_AI_PROVIDER": "fake"})
    model = JsonModel('{"speak": true, "importance": 8, "message": "Ta jauge est pleine."}')
    window = MainWindow(build_services(settings, demo=True, model=model))
    said = []
    window._say = lambda text: said.append(text) or True
    window._live_frame = lambda max_age_s=3.0: _frame()
    try:
        assert not window.copilot_timer.isActive()
        window.settings_page.copilot_box.setChecked(True)  # depuis les réglages
        assert window.copilot_timer.isActive() and window.orb.copilot_on
        assert window.copilot_button.isChecked()
        assert "enabled = true" in (data_dir() / "alicia.toml").read_text("utf-8")
        window._copilot_tick()
        _wait(qt_app, lambda: said)
        assert said == ["Ta jauge est pleine."]
        assert "Ta jauge est pleine." in window.answer.toPlainText()

        window._copilot_tick()  # la même chose : il se tait
        _wait(qt_app, lambda: not window._copilot_running)
        assert said == ["Ta jauge est pleine."]

        window.busy = True  # tu poses une question : pas de coup d'œil
        count = len(model.requests)
        window._copilot_tick()
        assert len(model.requests) == count and not window._copilot_running
        window.busy = False

        window.settings_page.copilot_threshold.setCurrentIndex(
            window.settings_page.copilot_threshold.findData(9)
        )
        assert (
            window.services.settings.copilot.threshold == 9 and window.copilot.gate.threshold == 9
        )
        window.copilot_button.click()  # le bouton du haut coupe aussi
        assert not window.copilot_timer.isActive() and not window.copilot_button.isChecked()
        assert not window.settings_page.copilot_box.isChecked()
    finally:
        window.close()


def test_voice_command_turns_copilot_on_and_off(qt_app, tmp_path, monkeypatch):
    from alicia.ui.main_window import MainWindow

    assert parse_copilot_command("Active le copilote") is True
    assert parse_copilot_command("désactive le mode co-pilote.") is False
    assert parse_copilot_command("pourquoi le copilote parle autant alors que je joue") is None
    assert parse_copilot_command("active la lumière") is None

    monkeypatch.chdir(tmp_path)
    settings = load_settings(environ={"ALICE_AI_PROVIDER": "fake"})
    window = MainWindow(build_services(settings, demo=True, model=JsonModel("{}")))
    window._say = lambda text: True
    try:
        outcome = window.services.analysis.analyze(None, "Active le copilote")
        assert outcome.action.intent == "copilot_on"
        window._action_done(outcome)
        assert window.copilot_timer.isActive() and window.copilot_button.isChecked()
        window._action_done(window.services.analysis.analyze(None, "coupe le copilote"))
        assert not window.copilot_timer.isActive()
    finally:
        window.close()


def test_categories_trash_talk_and_fun_spacing():
    gate = CopilotGate(7, 60, ("conseils", "alertes", "humour", "trashtalk"), trash="off")
    assert "trashtalk" not in gate.categories  # case cochée mais niveau désactivé
    joke = Decision(True, 8, "Belle chute, champion.", "", "humour")
    assert gate.allow(joke, now=0)[0]
    gate.spoke(joke.message, now=0, category="humour")
    # une autre blague trop tôt : refusée (2 × le silence), un conseil passe après 60 s
    assert not gate.allow(Decision(True, 8, "Encore une ?", "", "humour"), now=90)[0]
    assert gate.allow(Decision(True, 8, "Pense à réparer ton armure.", "", "conseil"), now=90)[0]
    assert gate.allow(Decision(True, 8, "Pas de réaction", "", "reaction"), now=500) == (
        False,
        "type « reaction » désactivé",
    )
    gate.trash = "corse"
    rules = gate.rules()
    assert "trashtalk" in rules and "Jamais d'insulte" in rules and "corse" in rules
    trash = Decision(True, 8, "Tu viens de tomber tout seul ?", "", "trashtalk")
    assert gate.allow(trash, now=1000)[0]
    gate.spoke(trash.message, now=1000, category="trashtalk")
    allowed, why = gate.allow(Decision(True, 8, "Encore toi par terre", "", "trashtalk"), now=1200)
    assert not allowed and "récent" in why


def test_parse_category():
    found = parse_decision('{"speak": true, "category": "Alerte", "importance": 9, "message": "x"}')
    assert found.category == "alerte"
    assert (
        parse_decision(
            '{"speak": true, "category": "??", "importance": 9, "message": "x"}'
        ).category
        == "conseil"
    )


def test_copilot_page_presets_and_kinds(qt_app, tmp_path, monkeypatch):
    from alicia.ui.main_window import MainWindow

    monkeypatch.chdir(tmp_path)
    window = MainWindow(
        build_services(load_settings(environ={"ALICE_AI_PROVIDER": "fake"}), demo=True)
    )
    page = window.settings_page
    try:
        page.copilot_spontaneity.setCurrentIndex(page.copilot_spontaneity.findData("bavard"))
        settings = window.services.settings.copilot
        assert settings.spontaneity == "bavard" and settings.threshold == 5
        assert window.copilot.gate.threshold == 5
        page.copilot_threshold.setCurrentIndex(page.copilot_threshold.findData(9))
        assert window.services.settings.copilot.spontaneity == "perso"
        assert page.copilot_spontaneity.currentData() == "perso"

        assert not page.copilot_trash.isEnabled()
        page.copilot_kinds["trashtalk"].setChecked(True)
        assert page.copilot_trash.isEnabled() and page.copilot_trash.currentData() == "leger"
        page.copilot_kinds["humour"].setChecked(False)
        gate = window.copilot.gate
        assert "trashtalk" in gate.kinds and "humour" not in gate.kinds and gate.trash == "leger"
        reloaded = load_settings().copilot
        assert "trashtalk" in reloaded.kinds and reloaded.trash == "leger"
    finally:
        window.close()


def test_copilot_says_when_the_key_is_refused_and_pauses(qt_app, tmp_path, monkeypatch):
    from alicia.core.ai.providers.fake import FakeModel
    from alicia.core.errors import ProviderError, ProviderErrorKind
    from alicia.ui.main_window import MainWindow
    from tests.test_duo import _wait

    monkeypatch.chdir(tmp_path)
    model = FakeModel(fail_with=ProviderError(ProviderErrorKind.AUTH, "API key not valid"))
    window = MainWindow(
        build_services(load_settings(environ={"ALICE_AI_PROVIDER": "fake"}), demo=True, model=model)
    )
    notes = []
    window._notify = notes.append
    window._live_frame = lambda max_age_s=3.0: _frame()
    try:
        window.set_copilot(True, save=False)
        window._copilot_tick()
        _wait(qt_app, lambda: not window._copilot_running and notes)
        assert notes and "clé" in notes[0] and "refusée" in notes[0]
        count = len(model.requests)
        window._copilot_tick()  # en pause : pas de nouvel appel
        assert len(model.requests) == count
    finally:
        window.close()


def test_copilot_logs_why_it_stays_quiet(qt_app, tmp_path, monkeypatch, caplog):
    import logging

    from alicia.ui.main_window import MainWindow

    monkeypatch.chdir(tmp_path)
    window = MainWindow(
        build_services(load_settings(environ={"ALICE_AI_PROVIDER": "fake"}), demo=True)
    )
    try:
        with caplog.at_level(logging.INFO, logger="alicia"):
            for _ in range(10):
                window._copilot_note("importance 5 < seuil 7")
        assert "10 derniers coups d'œil — importance 5 < seuil 7 ×10" in caplog.text
    finally:
        window.close()


def test_copilot_does_not_call_the_ai_without_a_game(qt_app, tmp_path, monkeypatch):
    from alicia.ui.main_window import MainWindow
    from tests.test_duo import _wait

    monkeypatch.chdir(tmp_path)
    model = JsonModel('{"speak": true, "importance": 9, "message": "x"}')
    window = MainWindow(
        build_services(load_settings(environ={"ALICE_AI_PROVIDER": "fake"}), demo=True, model=model)
    )
    desktop = WindowInfo(0, "Écran 1", 0)
    window._live_frame = lambda max_age_s=3.0: Frame(
        Image.new("RGB", (64, 48)), desktop, "demo", datetime.now(), 1, "c2"
    )
    try:
        window.set_copilot(True, save=False)
        window._copilot_tick()
        _wait(qt_app, lambda: not window._copilot_running)
        assert model.requests == []
    finally:
        window.close()
