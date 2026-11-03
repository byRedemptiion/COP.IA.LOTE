from alicia.app import build_services
from alicia.core.config import load_settings
from alicia.core.copilot import CopilotGate, Decision
from alicia.core.rules import Rules, parse_rule_command


def test_rule_commands():
    assert parse_rule_command("VIIRUS, arrête de me dire de surveiller mes PV") == (
        "add",
        "arrête de me dire de surveiller mes PV",
    )
    assert parse_rule_command("Ne parle plus de mon build")[0] == "add"
    assert parse_rule_command("Évite les blagues sur ma visée")[0] == "add"
    assert parse_rule_command("Tu peux de nouveau parler de mes PV")[0] == "lift"
    assert parse_rule_command("Annule tes consignes") == ("lift", "tout")
    for not_a_rule in ("VIIRUS, stop", "Arrête", "arrête de parler", "Quel build ?"):
        assert parse_rule_command(not_a_rule) is None


def test_rules_are_in_every_prompt_and_block_the_copilot():
    from alicia.core.ai.prompts import build_system_prompt

    Rules().add("arrête de me dire de surveiller mes PV")
    assert "CONSIGNES DU JOUEUR" in build_system_prompt("x", brain="rapide")
    gate = CopilotGate(threshold=5)
    blocked = Decision(True, 8, "Attention, surveille tes PV !", category="alerte")
    assert gate.allow(blocked) == (False, "consigne du joueur")
    assert gate.allow(Decision(True, 8, "Le boss charge à gauche !", category="alerte"))[0]
    assert Rules().lift("mes PV") == 1 and Rules().all() == []


def test_window_saves_a_rule_said_out_loud(qt_app, tmp_path, monkeypatch):
    from alicia.ui.main_window import MainWindow

    monkeypatch.chdir(tmp_path)
    window = MainWindow(
        build_services(load_settings(environ={"ALICE_AI_PROVIDER": "fake"}), demo=True)
    )
    try:
        reply = window._duo_router("Ne parle plus de mon build")
        assert reply.intent.startswith("rule_add")
        assert "consigne" in window.rule_action(reply.intent)
        assert Rules().all() == ["Ne parle plus de mon build"]
    finally:
        window.close()


def test_conversation_continues_without_the_wake_word(qt_app, tmp_path, monkeypatch):
    from alicia.ui.main_window import MainWindow

    monkeypatch.chdir(tmp_path)
    window = MainWindow(
        build_services(load_settings(environ={"ALICE_AI_PROVIDER": "fake"}), demo=True)
    )

    class Wake:
        running, level, state = True, 0.0, 0
        listened = []

        def listen_now(self, seconds):
            self.listened.append(seconds)

        def stop(self):
            pass

    try:
        window.wake = Wake()
        window._follow_up = True  # il vient de répondre à voix haute
        window._voice_state("idle", None)
        assert Wake.listened == [8.0] and window.core.state == "listening"
        window._wake_cancel("silence")  # tu ne dis rien : fin, sans message
        assert not window._awaiting_answer
    finally:
        window.wake = None
        window.close()
