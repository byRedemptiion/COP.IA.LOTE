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


def test_name_is_not_repeated_every_sentence():
    from alicia.core import persona

    persona.set_player("Redem")
    persona._name_said_at["t"] = -1e9
    try:
        assert "rarement" in build_system_prompt()
        persona.pronounce("Bien joué Redem, continue !")  # il vient de le dire
        assert "ne l'écris PAS" in build_system_prompt()
        persona._name_said_at["t"] -= persona.NAME_PAUSE_S + 1  # 10 min plus tard
        assert "ne l'écris PAS" not in build_system_prompt()
    finally:
        persona.set_player("")
        persona._name_said_at["t"] = -1e9


def test_cut_answers_are_finished_or_explained():
    from alicia.core.analysis.service import finish_cut

    long = "Voici des idées. Prends un nom court et facile. Vise un truc qui"
    assert finish_cut(long, "MAX_TOKENS") == "Voici des idées. Prends un nom court et facile."
    assert finish_cut("Si tu veux, vise un truc qui", "SAFETY").endswith("filtre de Google)")
    assert finish_cut("Tout va bien.", "STOP") == "Tout va bien."


def test_opinion_questions_get_a_real_opinion():
    from alicia.core.ai.factory import deep_reason

    assert deep_reason("t'en penses quoi de mes stats ?")
    assert deep_reason("qu'en penses-tu ?")
    assert not deep_reason("il est quelle heure ?")
    assert "tu as un vrai avis" in build_system_prompt()


def test_purge_cleans_files_but_keeps_settings(qt_app, tmp_path, monkeypatch):
    from alicia.app import build_services
    from alicia.core.config import load_settings
    from alicia.ui.main_window import MainWindow

    monkeypatch.chdir(tmp_path)
    log_file = tmp_path / "logs" / "alicia.log"
    log_file.parent.mkdir()
    log_file.write_text("en cours")
    (tmp_path / "logs" / "alicia.log.1").write_text("x" * 1000)
    window = MainWindow(
        build_services(load_settings(environ={"ALICE_AI_PROVIDER": "fake"}), demo=True),
        log_file=log_file,
    )
    try:
        window.change_setting("purge", True)
        assert log_file.exists() and not (tmp_path / "logs" / "alicia.log.1").exists()
    finally:
        window.close()


def test_depleted_credits_are_named_clearly():
    from alicia.core.ai.providers.gemini import CREDITS_HINT, credits_depleted

    body = '{"error": {"code": 429, "message": "Your prepayment credits are depleted."}}'
    assert credits_depleted(body) and not credits_depleted("Quota exceeded per minute")
    assert "Facturation" in CREDITS_HINT
