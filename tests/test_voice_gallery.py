import base64
import tomllib

import httpx
import numpy as np
import pytest

from alicia.app import build_services
from alicia.core.audio import speaker as speaker_module
from alicia.core.audio.devices import AudioError
from alicia.core.config import Secret, VoiceSettings, data_dir, load_settings


def test_gemini_voice_returns_pcm(monkeypatch):
    sent = {}
    pcm = np.array([0, 1000, -1000, 5], dtype=np.int16).tobytes()

    def post(url, headers, json, timeout):
        sent.update(url=url, headers=headers, json=json)
        body = {
            "candidates": [
                {"content": {"parts": [{"inlineData": {"data": base64.b64encode(pcm).decode()}}]}}
            ]
        }
        return httpx.Response(200, json=body)

    monkeypatch.setattr(httpx, "post", post)
    settings = VoiceSettings(tts_engine="gemini", gemini_voice="Puck", gemini_key=Secret("k"))
    samples = speaker_module.make_synthesizer(settings)("Salut !")
    assert samples.tolist() == [0, 1000, -1000, 5]
    assert (
        "gemini-3.1-flash-tts-preview" in sent["url"] and sent["headers"]["x-goog-api-key"] == "k"
    )
    voice = sent["json"]["generationConfig"]["speechConfig"]["voiceConfig"]
    assert voice["prebuiltVoiceConfig"]["voiceName"] == "Puck"
    assert sent["json"]["contents"][0]["parts"][0]["text"].endswith("Salut !")


def test_gemini_voice_needs_a_key_and_reports_quota(monkeypatch):
    with pytest.raises(AudioError):
        speaker_module.gemini_synthesizer(VoiceSettings())("x")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(429, text="quota"))
    # Quota atteint : la voix du profil prend le relais (plus de réponse muette)
    import numpy as np

    monkeypatch.setattr(
        speaker_module, "_profile_fallback", lambda s: lambda text: np.ones(2, np.int16)
    )
    synth = speaker_module.gemini_synthesizer(VoiceSettings(gemini_key=Secret("k")))
    assert len(synth("x")) == 2


class RecordingSpeaker:
    speaking = False
    level = 0.0

    def __init__(self, settings):
        self.settings = settings
        self.synthesizer = object()
        self.player = object()
        self.said = []

    def speak(self, text, synthesizer=None):
        self.said.append((text, synthesizer))
        return True

    def stop(self):
        pass

    def warm_up_async(self):
        pass


def test_gallery_previews_without_choosing_then_chooses(qt_app, tmp_path, monkeypatch):
    from alicia.ui.main_window import MainWindow

    monkeypatch.chdir(tmp_path)
    settings = load_settings(environ={"ALICE_AI_PROVIDER": "fake"})
    speaker = RecordingSpeaker(settings.voice)
    window = MainWindow(build_services(settings, demo=True, speaker=speaker))
    try:
        page = window.settings_page
        assert len(page.gallery_buttons) == 13 + 30 + 13
        before = window.services.settings.voice.tts_engine
        window.change_setting("voice_preview", "edge|fr-FR-EloiseNeural")
        assert speaker.said and callable(speaker.said[-1][1])  # voix d'essai, pas la sienne
        assert window.services.settings.voice.tts_engine == before  # rien n'est changé

        window.change_setting("voice_choose", "gemini|Leda")
        voice = window.services.settings.voice
        assert voice.tts_engine == "gemini" and voice.gemini_voice == "Leda"
        assert page.gallery_buttons["gemini|Leda"].text() == "✓ Choisie"
        saved = tomllib.loads((data_dir() / "alicia.toml").read_text("utf-8"))
        assert saved["voice"]["tts_engine"] == "gemini" and saved["voice"]["gemini_voice"] == "Leda"

        window.change_setting("voice_choose", "edge|fr-FR-HenriNeural")
        assert window.services.settings.voice.tts_voice == "fr-FR-HenriNeural"
        assert page.gallery_buttons["gemini|Leda"].text() == "Choisir"
    finally:
        window.close()


def _tone(seconds=1.0, hz=220.0):
    t = np.arange(int(24000 * seconds)) / 24000
    return (np.sin(2 * np.pi * hz * t) * 12000).astype(np.int16)


def _pitch(samples):
    spectrum = np.abs(np.fft.rfft(samples.astype(np.float32)))
    return np.argmax(spectrum) * 24000 / len(samples)


def test_effects_change_pitch_but_keep_duration():
    base = lambda text: _tone()  # noqa: E731
    for effect, higher in (("enfant", True), ("robot_enfant", True), ("gros_robot", False)):
        out = speaker_module.with_effect(base, effect)("x")
        assert abs(len(out) - 24000) < 600, effect  # même durée (± 25 ms)
        assert (_pitch(out) > 235) if higher else (_pitch(out) < 190), (effect, _pitch(out))
    assert speaker_module.with_effect(base, "") is base


def test_edge_effect_slows_the_voice_before_raising_it(monkeypatch):
    rates = []
    monkeypatch.setattr(
        speaker_module,
        "edge_synthesizer",
        lambda voice, rate: rates.append(rate) or (lambda t: _tone()),
    )
    settings = VoiceSettings(
        tts_engine="edge", tts_rate="+0%", voice_effect="robot_enfant", fx_pitch=6.0
    )
    speaker_module.make_synthesizer(settings)("x")
    assert rates == ["-29%"]  # 2^(6/12) ≈ 1,41 → ralentie de 29 %


def test_gemini_gets_the_style_of_the_effect(monkeypatch):
    sent = {}

    def post(url, headers, json, timeout):
        sent.update(json)
        pcm = base64.b64encode(_tone(0.2).tobytes()).decode()
        return httpx.Response(
            200, json={"candidates": [{"content": {"parts": [{"inlineData": {"data": pcm}}]}}]}
        )

    monkeypatch.setattr(httpx, "post", post)
    settings = VoiceSettings(tts_engine="gemini", gemini_key=Secret("k"), voice_effect="robot")
    speaker_module.make_synthesizer(settings)("Salut")
    assert "robot" in sent["contents"][0]["parts"][0]["text"]


def test_voice_volume(qt_app, tmp_path, monkeypatch):
    from alicia.ui.main_window import MainWindow

    loud = speaker_module.apply_volume(np.array([1000, -30000], dtype=np.int16), 150)
    assert loud.tolist() == [1500, -32768]  # pas de débordement
    assert speaker_module.apply_volume(np.array([800], dtype=np.int16), 50).tolist() == [400]

    monkeypatch.chdir(tmp_path)
    settings = load_settings(environ={"ALICE_AI_PROVIDER": "fake"})
    window = MainWindow(
        build_services(settings, demo=True, speaker=RecordingSpeaker(settings.voice))
    )
    try:
        window.settings_page.volume.setValue(140)
        assert window.services.settings.voice.volume == 140
        assert window.services.speaker.settings.volume == 140
        saved = tomllib.loads((data_dir() / "alicia.toml").read_text("utf-8"))
        assert saved["voice"]["volume"] == 140
    finally:
        window.close()


def test_openai_voices_are_in_the_catalogue_and_choosable(qt_app, tmp_path, monkeypatch):
    from alicia.app import build_services
    from alicia.core.config import load_settings
    from alicia.ui.main_window import MainWindow

    monkeypatch.chdir(tmp_path)
    window = MainWindow(
        build_services(load_settings(environ={"ALICE_AI_PROVIDER": "fake"}), demo=True)
    )
    try:
        window.show_page(2)
        assert "openai|onyx" in window.settings_page.gallery_buttons
        window.change_setting("voice_choose", "openai|onyx")
        voice = window.services.settings.voice
        assert voice.tts_engine == "openai" and voice.openai_voice == "onyx"
    finally:
        window.close()


def test_player_can_say_their_name():
    from alicia.core.persona import parse_name_command

    assert parse_name_command("Je m'appelle Yannick") == "Yannick"
    assert parse_name_command("Alicia, appelle-moi Nova.") == "Nova"
    assert parse_name_command("mon prénom c'est Jérôme") == "Jérôme"
    assert parse_name_command("comment tu t'appelles ?") is None


def test_voice_can_use_its_own_key(qt_app, tmp_path, monkeypatch, caplog):
    import logging

    from alicia.app import build_services
    from alicia.core import user_config
    from alicia.core.config import load_settings
    from alicia.ui.main_window import MainWindow

    monkeypatch.chdir(tmp_path)
    written = {}
    monkeypatch.setattr(user_config, "set_env", lambda k, v, path=None: written.update({k: v}))
    settings = load_settings(environ={"ALICE_AI_PROVIDER": "fake", "OPENAI_API_KEY": "sk-ai"})
    window = MainWindow(build_services(settings, demo=True))
    try:
        window.show_page(2)
        with caplog.at_level(logging.DEBUG):
            window.settings_page.voice_key.emit("openai", "sk-voice-secret")
        assert written == {"VOICE_OPENAI_API_KEY": "sk-voice-secret"}
        assert window.services.settings.voice.openai_key.get() == "sk-voice-secret"
        assert "sk-voice-secret" not in caplog.text  # jamais journalisée
        assert "dédiée" in window.settings_page.voice_key_state.text()
        window.settings_page.voice_key.emit("openai", "")
        assert window.services.settings.voice.openai_key.get() == "sk-ai"
    finally:
        window.close()
    env = load_settings(environ={"VOICE_GEMINI_API_KEY": "g-voice", "GEMINI_API_KEY": "g-ai"})
    assert env.voice.gemini_key.get() == "g-voice" and env.voice.own_keys == ("gemini",)
