import pytest

from alicia.core import personality
from alicia.core.ai.prompts import build_system_prompt


@pytest.mark.parametrize(
    ("text", "mode"),
    [
        ("Viirus, mode déchaîné", "dechaine"),
        ("lâche-toi !", "dechaine"),
        ("passe en mode déchaîné", "dechaine"),
        ("mode normal", "normal"),
        ("calme-toi", "normal"),
        ("désactive le mode déchaîné", "normal"),
        ("c'est quoi le meilleur build pour Ashe ?", None),
    ],
)
def test_mode_commands(text, mode):
    assert personality.parse_mode_command(text) == mode


def test_wild_mode_changes_the_prompt_and_is_kept():
    assert personality.mode() == "normal"
    assert "MODE DÉCHAÎNÉ" not in build_system_prompt()
    personality.set_mode("dechaine")
    assert personality.mode() == "dechaine"  # gardé (fichier)
    prompt = build_system_prompt()
    assert "MODE DÉCHAÎNÉ" in prompt and personality.DECHAINE_DEFAULT in prompt
    assert "aucune insulte" in prompt  # les limites restent
    # Son propre fichier, pour le profil en cours
    from alicia.core.persona import current

    path = personality.personality_file(current().key, "dechaine")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("Hurle de joie à chaque kill.", "utf-8")
    assert "Hurle de joie" in build_system_prompt()
    personality.set_mode("normal")
    assert "MODE DÉCHAÎNÉ" not in build_system_prompt()


def test_voice_command_switches_mode(qt_app, tmp_path, monkeypatch):
    from alicia.app import build_services
    from alicia.core.config import load_settings
    from alicia.ui.main_window import MainWindow

    monkeypatch.chdir(tmp_path)
    window = MainWindow(
        build_services(load_settings(environ={"ALICE_AI_PROVIDER": "fake"}), demo=True)
    )
    try:
        reply = window._duo_router("Viirus, lâche-toi")
        assert reply.intent == "personality_mode:dechaine"
        text = window.set_personality_mode("dechaine")
        assert "déchaîné" in text and personality.mode() == "dechaine"
        page = window.settings_page
        assert page.personality_mode.currentData() == "dechaine"
        page.personality_mode.setCurrentIndex(page.personality_mode.findData("normal"))
        assert personality.mode() == "normal"
    finally:
        window.close()
