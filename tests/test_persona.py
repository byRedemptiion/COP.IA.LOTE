import subprocess
import sys

import numpy as np
import pytest

from alicia.core import persona
from alicia.core.ai.prompts import build_system_prompt
from alicia.core.audio.speaker import robot_voice
from alicia.core.audio.wake import find_wake, strip_wake_word


@pytest.fixture
def veris():
    persona.set_current("veris")
    yield persona.current()
    persona.set_current("alicia")


def test_default_is_alicia():
    assert persona.current().key == "alicia"
    assert persona.set_current("inconnu").key == "alicia"
    assert "Tu es Alicia" in build_system_prompt()


def test_veris_identity_and_wake_word(veris):
    assert "Tu es VIIRUS" in build_system_prompt()
    assert find_wake("Véris, lance Discord") == (True, "lance discord")
    assert find_wake("Ok Verisse quel objet") == (True, "quel objet")
    assert find_wake("Alicia, lance Discord")[0] is False
    assert strip_wake_word("Veris, monte le son") == "monte le son"


def test_names_in_interface(veris, qt_app):
    from alicia.ui.naming import named

    assert named("Mettre à jour ALICIA") == "Mettre à jour VIIRUS"
    assert named("CE QU'ALICIA SAIT DU JEU") == "CE QUE VIIRUS SAIT DU JEU"
    assert named("le rond d'ALICIA") == "le rond de VIIRUS"
    assert named("A · L · I · C · I · A") == "V · I · I · R · U · S"
    assert named(r"%APPDATA%\Alicia\.env") == r"%APPDATA%\Alicia\.env"


def test_robot_voice_raises_pitch_and_keeps_format():
    rate = 24000
    t = np.arange(rate) / rate
    ratio = 2 ** (450 / 1200)
    samples = (0.3 * np.sin(2 * np.pi * 400 * t) * 32767).astype(np.int16)
    out = robot_voice(samples, ratio)
    assert out.dtype == np.int16
    assert len(out) == round(rate / ratio)
    peak = np.argmax(np.abs(np.fft.rfft(out))) * rate / len(out)
    assert abs(peak - 400 * ratio) < 3


def test_veris_theme_is_violet():
    code = (
        "from alicia.core.persona import set_current; set_current('veris');"
        "from alicia.ui import theme; print(theme.PINK, theme.STATE_COLORS['idle'].name())"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.split() == ["#7c4dff", "#7c4dff"]


def test_stream_visibility_setting(qt_app, tmp_path, monkeypatch):
    import tomllib

    from alicia.app import build_services
    from alicia.core.config import data_dir, load_settings
    from alicia.ui import orb
    from alicia.ui.main_window import MainWindow

    monkeypatch.chdir(tmp_path)
    settings = load_settings(environ={"ALICE_AI_PROVIDER": "fake"})
    assert settings.stream_visible is False
    window = MainWindow(build_services(settings, demo=True))
    window.settings_page.stream_box.setChecked(True)
    assert orb.stream_visible is True
    saved = tomllib.loads((data_dir() / "alicia.toml").read_text("utf-8"))
    assert saved["ui"]["stream_visible"] is True
    window.orb.stream_toggled.emit(False)
    assert orb.stream_visible is False
    assert window.settings_page.stream_box.isChecked() is False
    window.close()


def test_veris_is_masculine_in_the_interface(veris, qt_app):
    from alicia.ui.naming import named

    assert named("ALICIA se réveille toute seule quand elle t'entend") == (
        "VIIRUS se réveille tout seul quand il t'entend"
    )


def test_player_name_and_pronunciation():
    from alicia.core.persona import pronounce, set_player

    try:
        set_player("Redemptiion", "Rédemm-chionne")
        assert "Ton joueur s'appelle Redemptiion" in build_system_prompt()
        assert pronounce("Salut Redemptiion !") == "Salut Rédemm-chionne !"
        assert pronounce("Redemptiions") == "Redemptiions"  # mot entier seulement
    finally:
        set_player("", "")
    assert "Ton joueur s'appelle" not in build_system_prompt()


def test_player_settings_are_saved(qt_app, tmp_path, monkeypatch):
    import tomllib

    from alicia.app import build_services
    from alicia.core.config import data_dir, load_settings
    from alicia.core.persona import player, set_player
    from alicia.ui.main_window import MainWindow

    monkeypatch.chdir(tmp_path)
    window = MainWindow(
        build_services(load_settings(environ={"ALICE_AI_PROVIDER": "fake"}), demo=True)
    )
    try:
        page = window.settings_page
        page.player_name.setText("Yannick")
        page.player_name.editingFinished.emit()
        page.player_phonetic.setText("Ya-nik")
        page.player_phonetic.editingFinished.emit()
        assert player().name == "Yannick" and player().phonetic == "Ya-nik"
        saved = tomllib.loads((data_dir() / "alicia.toml").read_text("utf-8"))
        assert saved["player"] == {"name": "Yannick", "phonetic": "Ya-nik"}
        assert load_settings().player.name == "Yannick"
    finally:
        set_player("", "")
        window.close()


def test_personality_file_is_added_to_the_prompt(tmp_path, monkeypatch):
    from alicia.core import personality

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    source = tmp_path / "Alic.ia_profil.md"
    source.write_text(
        "# Alic.ia\n\nTu es malicieuse et tu parles simplement.\n\n"
        "## À régler séparément\n\nNotes pour les humains.\n",
        encoding="utf-8",
    )
    personality.install("alicia", source)
    prompt = build_system_prompt()
    assert "Tu es malicieuse" in prompt and "Notes pour les humains" not in prompt
    assert "sans jamais jouer à sa place" in prompt
    personality.remove("alicia")
    assert "<personnalite>" not in build_system_prompt()


def test_alicia_voice_c_is_available():
    from dataclasses import replace

    from alicia.core.audio.speaker import make_synthesizer
    from alicia.core.config import VoiceSettings
    from alicia.core.persona import ALICIA

    assert ALICIA.voice_engine == "voixc"
    synth = make_synthesizer(replace(VoiceSettings(), tts_engine="voixc"))
    assert callable(synth) and hasattr(synth, "warm_up")


def test_profile_list_shows_alicia_and_veris(veris, qt_app, tmp_path, monkeypatch):
    """La liste des profils montre ALICIA et VERIS, même quand VERIS est actif."""
    from alicia.app import build_services
    from alicia.core.config import load_settings
    from alicia.ui.main_window import MainWindow

    monkeypatch.chdir(tmp_path)
    window = MainWindow(
        build_services(load_settings(environ={"ALICE_AI_PROVIDER": "fake"}), demo=True)
    )
    box = window.settings_page.persona_box
    assert [box.itemText(i) for i in range(box.count())] == ["ALICIA", "VIIRUS"]
    assert box.currentData() == "veris"
    window.close()


@pytest.mark.parametrize(
    ("key", "identity", "wake"),
    [("alicia", "Tu es Alicia", "alicia"), ("veris", "Tu es VIIRUS", "viirus")],
)
def test_each_profile_loads_its_own_identity(key, identity, wake, tmp_path, monkeypatch):
    from alicia.core import personality

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    persona.set_current(key)
    try:
        (tmp_path / "Alicia").mkdir(exist_ok=True)
        personality.personality_file(key).write_text(f"Caractère propre à {key}.", "utf-8")
        prompt = build_system_prompt()
        assert identity in prompt and f"Caractère propre à {key}." in prompt
        other = "veris" if key == "alicia" else "alicia"
        assert f"Caractère propre à {other}." not in prompt
        assert persona.current().wake_name == wake
    finally:
        persona.set_current("alicia")


def test_viirus_replaces_veris(veris):
    from alicia.core.audio.wake import find_wake

    assert persona.current().title == "VIIRUS"
    assert find_wake("Virus, dis à Nova de garder l'objet")[0]
    assert find_wake("Viirus, monte le son") == (True, "monte le son")
    assert persona.set_current("viirus").key == "veris"  # ancien réglage « veris » gardé
