import pytest

from alicia.app import build_services
from alicia.core.actions.controller import ActionController
from alicia.core.actions.intents import parse_confirmation, parse_intent
from alicia.core.ai.providers.fake import FakeModel
from alicia.core.capture.backends import DEMO_WINDOW
from alicia.core.config import DEFAULT_APPS, ActionSettings, load_settings
from alicia.core.errors import AliciaError


class FakeSystem:
    def __init__(self):
        self.calls, self.level = [], 40

    def shutdown(self, delay_s, restart=False):
        self.calls.append(("restart" if restart else "shutdown", delay_s))

    def cancel_shutdown(self):
        self.calls.append(("cancel",))

    def sleep(self):
        self.calls.append(("sleep",))

    def lock(self):
        self.calls.append(("lock",))

    def volume(self):
        return self.level

    def set_volume(self, percent):
        self.level = percent
        self.calls.append(("volume", percent))

    def set_mute(self, muted):
        self.calls.append(("mute", muted))

    def launch(self, target):
        self.calls.append(("launch", target))

    def close(self, process):
        self.calls.append(("close", process))
        return 1


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


@pytest.mark.parametrize(
    ("phrase", "name", "params"),
    [
        ("Éteins le PC", "shutdown", {}),
        ("Alicia, tu peux éteindre l'ordi ?", "shutdown", {}),
        ("Redémarre le PC", "restart", {}),
        ("Mets le PC en veille", "sleep", {}),
        ("Verrouille le PC", "lock", {}),
        ("Monte le son", "volume_up", {"step": 10}),
        ("Baisse le volume de 20", "volume_down", {"step": 20}),
        ("Mets le volume à 30 %", "volume_set", {"percent": 30}),
        ("volume à cinquante", "volume_set", {"percent": 50}),
        ("Coupe le son", "mute", {}),
        ("Rappelle-moi dans 20 minutes de manger", "timer", {"seconds": 1200, "label": "manger"}),
        ("Mets un minuteur de cinq minutes", "timer", {"seconds": 300, "label": ""}),
        ("Lance Discord", "launch", {"app": "discord"}),
        ("Ferme Spotify", "close", {"app": "spotify"}),
        ("Annule l'extinction", "cancel_shutdown", {}),
    ],
)
def test_actions_are_recognized(phrase, name, params):
    intent = parse_intent(phrase, DEFAULT_APPS)
    assert intent is not None and intent.name == name and intent.params == params


@pytest.mark.parametrize(
    "phrase",
    [
        "Quel objet j'achète pour Ashe ?",
        "Ouvre l'inventaire, je prends quoi ?",
        "Est-ce que je dois arrêter de push ?",
        "Comment je ferme la porte dans ce niveau ?",
        "Le son du jeu est bizarre non ?",
    ],
)
def test_game_questions_are_not_actions(phrase):
    assert parse_intent(phrase, DEFAULT_APPS) is None


def test_negation_always_wins():
    assert parse_confirmation("oui") is True
    assert parse_confirmation("oui enfin non attends") is False
    assert parse_confirmation("euh") is None


def controller(clock=None):
    system = FakeSystem()
    return ActionController(ActionSettings(), system, clock=clock or Clock()), system


def test_shutdown_needs_confirmation_then_can_be_cancelled():
    actions, system = controller()
    reply = actions.route("Éteins le PC")
    assert reply.awaiting_confirmation and "confirmes" in reply.text
    assert system.calls == []
    reply = actions.route("oui")
    assert system.calls == [("shutdown", 20)] and "annule" in reply.text
    assert reply.expects_reply  # ALICIA écoute « annule » sans redire son nom
    reply = actions.route("non non annule")
    assert system.calls[-1] == ("cancel",) and "reste allumé" in reply.text


def test_refused_or_expired_confirmation_does_nothing():
    clock = Clock()
    actions, system = controller(clock)
    actions.route("Verrouille le PC")
    assert actions.route("non").text == "D'accord, j'annule."
    actions.route("Redémarre le PC")
    clock.now = 25  # au-delà de 20 s
    assert actions.route("oui") is None  # plus rien en attente : « oui » part à l'IA
    assert system.calls == []


def test_direct_actions_run_immediately():
    actions, system = controller()
    assert actions.route("Monte le son").text == "Volume à 50 %."
    assert actions.route("Lance Discord").text == "J'ouvre discord."
    assert ("launch", "discord://") in system.calls
    assert actions.route("Quel objet pour Ashe ?") is None


def test_timer_fires_reminder(monkeypatch):
    fired = []
    actions, _ = controller()
    actions.on_reminder = fired.append
    started = []

    class InstantTimer:
        def __init__(self, seconds, fn):
            started.append(seconds)
            self.fn, self.daemon = fn, False

        def start(self):
            self.fn()

        def cancel(self):
            pass

    monkeypatch.setattr("alicia.core.actions.controller.threading.Timer", InstantTimer)
    reply = actions.route("Rappelle-moi dans 20 minutes de manger")
    assert "20 minutes" in reply.text and started == [1200]
    assert fired == ["Rappel : manger."]


def test_windows_error_is_reported_not_raised():
    actions, system = controller()

    def broken(percent):
        raise AliciaError("Volume indisponible.", detail="COM error")

    system.set_volume = broken
    assert actions.route("Coupe le son").text == "Son coupé."
    assert actions.route("Mets le volume à 30").text == "Volume indisponible."


def test_actions_skip_capture_and_ai(tmp_path):
    settings = load_settings(cwd=tmp_path, environ={"ALICE_AI_PROVIDER": "fake"}, user_dir=tmp_path)
    actions, system = controller()
    model = FakeModel()
    services = build_services(settings, demo=True, model=model, actions=actions)
    outcome = services.analysis.analyze(DEMO_WINDOW, "Mets le volume à 25")
    assert outcome.action is not None and outcome.frame is None
    assert model.requests == [] and system.level == 25


def test_custom_apps_from_config(tmp_path):
    (tmp_path / "alicia.toml").write_text(
        '[actions.apps]\nobs = { launch = "C:/OBS/obs64.exe", process = "obs64.exe" }\n',
        encoding="utf-8",
    )
    settings = load_settings(cwd=tmp_path, environ={}, user_dir=tmp_path / "u")
    assert settings.actions.apps["obs"].process == "obs64.exe"
    assert "discord" in settings.actions.apps  # les applis par défaut restent
    assert parse_intent("Lance OBS", settings.actions.apps).params == {"app": "obs"}
