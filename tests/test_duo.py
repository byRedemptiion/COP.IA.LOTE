import time

import httpx
import pytest

from alicia.core.duo import DuoKeys, DuoLink, new_code, parse_duo_request


def test_messages_are_encrypted_and_signed():
    keys = DuoKeys("ABCD-EFGH-JKLM-NPQR")
    sealed = keys.seal({"text": "Salut Alicia !"})
    assert "Salut" not in sealed
    assert keys.open(sealed) == {"text": "Salut Alicia !"}
    assert DuoKeys("AUTRE-CODE").open(sealed) is None  # mauvais code : rejeté
    tampered = sealed[:-6] + ("A" if sealed[-6] != "A" else "B") + sealed[-5:]
    assert keys.open(tampered) is None
    assert keys.topic == DuoKeys("ABCD-EFGH-JKLM-NPQR").topic != DuoKeys("x").topic


def test_new_code_format():
    code = new_code()
    assert len(code) == 19 and code.count("-") == 3


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("dis bonjour à Alicia", ("relay", "dis bonjour à Alicia")),
        ("demande à alicia ce qu'elle fait", ("relay", "demande à alicia ce qu'elle fait")),
        ("réponds-lui que j'arrive", ("relay", "réponds-lui que j'arrive")),
        ("Discute avec Alicia de World of Warcraft", ("chat", "de world of warcraft")),
        ("parle avec alicia", ("chat", "")),
        ("quel objet pour Ashe ?", None),
        ("dis-moi quoi acheter", None),
    ],
)
def test_parse_duo_request(text, expected):
    assert parse_duo_request(text, ["ALICIA"]) == expected


def test_link_sends_sealed_messages_and_ignores_its_own():
    posted = []

    def handler(request):
        posted.append(request.content.decode())
        return httpx.Response(200, json={})

    received = []
    link = DuoLink("code", "moi", "VERIS", received.append, transport=httpx.MockTransport(handler))
    assert link.send("say", text="Coucou", conv="c1", turn=1, max=6)
    assert link.keys.open(posted[0])["text"] == "Coucou"
    link.handle(posted[0])
    assert received == []  # notre propre message
    other = DuoKeys("code").seal(
        {"kind": "say", "sender": "lui", "name": "ALICIA", "ts": int(time.time()), "text": "Yo"}
    )
    link.handle(other)
    assert received[0]["name"] == "ALICIA" and received[0]["text"] == "Yo"
    old = DuoKeys("code").seal({"kind": "say", "sender": "lui", "ts": 0, "text": "vieux"})
    link.handle(old)
    assert len(received) == 1  # message rejoué trop vieux : ignoré


def test_robots_take_turns(qt_app, tmp_path, monkeypatch):
    from alicia.app import build_services
    from alicia.core.ai.providers.fake import FakeModel
    from alicia.core.config import load_settings
    from alicia.ui.main_window import MainWindow

    monkeypatch.chdir(tmp_path)
    settings = load_settings(environ={"ALICE_AI_PROVIDER": "fake"})
    window = MainWindow(build_services(settings, demo=True, model=FakeModel()))
    sent = []

    class Link:
        def send(self, kind, **data):
            sent.append((kind, data))
            return True

        def stop(self):
            pass

    window.duo_link = Link()
    window.voice_box.setChecked(False)  # pas de voix : envoi immédiat
    from dataclasses import replace

    duo = replace(window.services.settings.duo, allow_chat=True, max_turns=6)
    window.services.settings = replace(window.services.settings, duo=duo)
    window._duo_received({"kind": "hello", "name": "VERIS", "sender": "lui"})
    assert window.duo_peer == "VERIS"
    window._duo_received(
        {"kind": "say", "name": "VERIS", "conv": "c1", "turn": 1, "max": 3, "text": "Salut !"}
    )
    deadline = time.monotonic() + 5
    while not any(kind == "say" for kind, _ in sent) and time.monotonic() < deadline:
        qt_app.processEvents()
        time.sleep(0.02)
    says = [data for kind, data in sent if kind == "say"]
    assert says and says[0]["turn"] == 2 and says[0]["conv"] == "c1"
    # 3e et dernière réplique de l'autre : on ne répond plus
    window._duo_received(
        {"kind": "say", "name": "VERIS", "conv": "c1", "turn": 3, "max": 3, "text": "Ciao"}
    )
    assert window.duo_conv["ended"]
    # « Alicia, demande à Veris… » passe par le routeur, sans IA
    reply = window.services.analysis.router("demande à VERIS ce qu'il fait")
    assert reply.intent == "duo_relay"
    assert window.services.analysis.router("discute avec VERIS de WoW").intent == "duo_chat"
    window.duo_link = None
    window.close()


def test_peer_line_shows_its_head_in_the_bubble(qt_app, tmp_path, monkeypatch):
    from alicia.app import build_services
    from alicia.core.ai.providers.fake import FakeModel
    from alicia.core.config import load_settings
    from alicia.ui.main_window import MainWindow

    monkeypatch.chdir(tmp_path)
    window = MainWindow(
        build_services(
            load_settings(environ={"ALICE_AI_PROVIDER": "fake"}), demo=True, model=FakeModel()
        )
    )
    window.orb.show()
    window.duo_link = None
    window._duo_received(
        {"kind": "say", "name": "VERIS", "conv": "c9", "turn": 1, "max": 2, "text": "Bip boup !"}
    )
    assert window.bubble.avatar.isVisibleTo(window.bubble)
    assert "Bip boup" in window.bubble.text.text()
    window.bubble.ask("question normale")
    assert not window.bubble.avatar.isVisibleTo(window.bubble)
    window.close()


def test_talk_key_works_without_a_game_window(qt_app, tmp_path, monkeypatch):
    """Touche pour parler sans jeu au premier plan : la demande part quand même (avant, rien)."""
    from alicia.app import build_services
    from alicia.core.ai.base import PreparedAudio
    from alicia.core.ai.providers.fake import FakeModel
    from alicia.core.config import load_settings
    from alicia.ui.main_window import MainWindow

    class Recorder:
        recording = True
        level = 0.0
        device = ""

        def stop(self):
            self.recording = False
            return PreparedAudio(b"RIFF", "audio/wav", 1.0)

        def cancel(self):
            pass

    monkeypatch.chdir(tmp_path)
    services = build_services(
        load_settings(environ={"ALICE_AI_PROVIDER": "fake"}), demo=True, model=FakeModel()
    )
    services.recorder = Recorder()
    window = MainWindow(services)
    monkeypatch.setattr(window.services.capture, "foreground_window", lambda: None)
    window.observed = None
    started = []
    monkeypatch.setattr(window, "_start_analysis", lambda *args: started.append(args))
    window.talk_released()
    assert started  # la question part à l'analyse (actions, duo ou message d'erreur)
    window.close()


def _window(qt_app, tmp_path, monkeypatch, **duo_changes):
    from dataclasses import replace

    from alicia.app import build_services
    from alicia.core.ai.providers.fake import FakeModel
    from alicia.core.config import load_settings
    from alicia.ui.main_window import MainWindow

    monkeypatch.chdir(tmp_path)
    window = MainWindow(
        build_services(
            load_settings(environ={"ALICE_AI_PROVIDER": "fake"}), demo=True, model=FakeModel()
        )
    )
    duo = replace(window.services.settings.duo, **duo_changes)
    window.services.settings = replace(window.services.settings, duo=duo)
    sent = []

    class Link:
        def send(self, kind, **data):
            sent.append((kind, data))
            return True

        def stop(self):
            pass

    window.duo_link = Link()
    window.voice_box.setChecked(False)
    return window, sent


def _wait(qt_app, condition, seconds=5):
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        qt_app.processEvents()
        time.sleep(0.02)


def test_robots_do_not_answer_each_other_unless_allowed(qt_app, tmp_path, monkeypatch):
    window, sent = _window(qt_app, tmp_path, monkeypatch, allow_chat=False)
    window._duo_received(
        {"kind": "say", "name": "VERIS", "conv": "c1", "turn": 1, "max": 6, "text": "Salut !"}
    )
    _wait(qt_app, lambda: bool(sent), seconds=1)
    assert not [kind for kind, _ in sent if kind == "say"]  # il écoute sans répondre
    window.duo_chat("WoW")
    assert not sent  # discussion refusée tant que ce n'est pas autorisé
    window.duo_link = None
    window.close()


def test_relay_message_goes_to_the_other_player(qt_app, tmp_path, monkeypatch):
    window, sent = _window(qt_app, tmp_path, monkeypatch, player="Redem")
    window.duo_peer = "VERIS"
    window.duo_relay("demande-lui ce qu'il fait")
    _wait(qt_app, lambda: bool(sent))
    kind, data = sent[0]
    assert kind == "relay" and data["player"] == "Redem" and data["text"]
    # Côté réception : le robot annonce le message à son joueur
    window._duo_received(
        {"kind": "relay", "name": "VERIS", "text": "Redem veut savoir ce que tu fais."}
    )
    assert (
        "Message de VERIS" in window.answer.toPlainText() or "Redem" in window.answer.toPlainText()
    )
    window.duo_link = None
    window.close()


def test_messages_wait_while_you_talk_to_your_robot(qt_app, tmp_path, monkeypatch):
    window, sent = _window(qt_app, tmp_path, monkeypatch)
    window.busy = True  # tu poses une question à ton robot
    window._duo_received({"kind": "relay", "name": "ALICIA", "text": "Nova arrive !"})
    assert len(window._duo_inbox) == 1 and "Nova arrive" not in window.answer.toPlainText()
    window.busy = False
    window._duo_flush_inbox()
    assert not window._duo_inbox and "Nova arrive" in window.answer.toPlainText()
    window.answer.clear()
    window.replay_duo_message()  # réécouter
    assert "Nova arrive" in window.answer.toPlainText()
    window.duo_link = None
    window.close()


def test_more_ways_to_ask_for_a_relay():
    from alicia.core.duo import parse_duo_request

    for text in (
        "Tu peux transmettre le message à Alicia, s'il te plaît, que je viens de te dire ?",
        "fais passer le message à Alicia",
        "passe le bonjour à Alicia",
        "tu peux dire à Alicia que j'arrive",
    ):
        assert parse_duo_request(text, ["ALICIA"])[0] == "relay", text
    assert parse_duo_request("Quel objet pour Ashe ?", ["ALICIA"]) is None


def test_the_ai_can_spot_a_relay_request_the_rules_missed():
    from alicia.app import build_services
    from alicia.core.ai.base import AnalysisResult
    from alicia.core.capture.backends import DEMO_WINDOW
    from alicia.core.config import load_settings

    class RelayModel:
        provider, model = "gemini", "flash"

        def __init__(self):
            self.requests = []

        def check(self):
            return None

        def analyze(self, request, on_delta=None, cancel=None):
            self.requests.append(request)
            return AnalysisResult("[TRANSMETTRE] Il arrive dans 5 minutes.", "gemini", "flash", 1)

    model = RelayModel()
    services = build_services(
        load_settings(environ={"ALICE_AI_PROVIDER": "fake"}), demo=True, model=model
    )
    services.analysis.duo_peer = "ALICIA"
    outcome = services.analysis.analyze(DEMO_WINDOW, "Préviens la copine de Nova pour moi")
    assert "faire passer un message à ALICIA" in model.requests[0].system_prompt
    assert outcome.result.extra["duo_relay"] == "Il arrive dans 5 minutes."
    services.analysis.duo_peer = ""
    model.requests.clear()
    services.analysis.analyze(DEMO_WINDOW, "Quel objet ?")
    assert "TRANSMETTRE" not in model.requests[0].system_prompt  # duo coupé : pas de règle
