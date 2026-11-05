import time

from alicia.core.ai.base import Turn, ago
from alicia.core.ai.prompts import build_system_prompt
from alicia.core.copilot import CopilotGate
from alicia.core.session.context import SessionContext


def test_history_carries_its_age():
    now = time.time()
    assert ago(now - 20, now) == "à l'instant"
    assert ago(now - 6 * 60, now) == "il y a 6 min"
    assert ago(now - 80 * 60, now) == "il y a 1 h 20"
    turn = Turn("on tape le kobold ?", "oui", now - 5 * 60)
    assert turn.dated_question(now) == "[il y a 5 min] on tape le kobold ?"
    assert Turn("vieux", "x").dated_question() == "vieux"  # sans heure : inchangé
    session = SessionContext()
    session.record("question", "réponse")
    assert session.history()[0].at > 0


def test_copilot_memory_and_prompt_know_the_time():
    gate = CopilotGate()
    gate.spoke("Attention au kobold à gauche !")
    note = gate.recent_note()
    assert "[à l'instant] Attention au kobold" in note and "PASSÉ" in note
    prompt = build_system_prompt()
    assert time.strftime("%H:%M") in prompt and "TERMINÉ" in prompt


def test_copilot_remark_is_remembered_as_its_own(qt_app, tmp_path, monkeypatch):
    from alicia.app import build_services
    from alicia.core.config import load_settings
    from alicia.ui.main_window import COPILOT_TURN, MainWindow

    monkeypatch.chdir(tmp_path)
    window = MainWindow(
        build_services(load_settings(environ={"ALICE_AI_PROVIDER": "fake"}), demo=True)
    )
    window._say = lambda text: True
    try:
        window._copilot_speak("Attention au niveau 7 !", 8)
        last = window.services.session.history()[-1]
        assert last.question == COPILOT_TURN and last.answer == "Attention au niveau 7 !"
        assert "TOI tu as dit" in build_system_prompt()
    finally:
        window.close()
