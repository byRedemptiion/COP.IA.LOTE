import base64
import io
import wave

import numpy as np
import pytest

from alicia.app import build_services
from alicia.core.audio import voice_design
from alicia.core.audio.devices import AudioError
from alicia.core.config import load_settings


def _wav(rate=24000, seconds=0.1):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(np.full(int(rate * seconds), 1000, dtype=np.int16).tobytes())
    return buffer.getvalue()


class Response:
    def __init__(self, data, status=200):
        self.status_code, self._data, self.text = status, data, str(data)

    def json(self):
        return self._data


def test_decode_audio_resamples_wav_to_24k():
    assert len(voice_design.decode_audio(_wav(48000, 0.1))) == 2400
    assert len(voice_design.decode_audio(np.zeros(10, np.int16).tobytes())) == 10


def test_create_voice_reads_id_and_sample(monkeypatch, tmp_path):
    import httpx

    sent = {}

    def post(url, headers, json, timeout):
        sent.update(url=url, body=json, headers=headers)
        sample = {"mime_type": "audio/wav", "data": base64.b64encode(_wav()).decode()}
        return Response({"id": "voice_abc", "sample_audio": sample})

    monkeypatch.setattr(httpx, "post", post)
    voice, sample = voice_design.create_voice(
        "KEY", "VIIRUS", "Un petit garçon de 9 ans, voix aiguë."
    )
    assert voice.id == "voice_abc" and len(sample) == 2400
    assert sent["url"].endswith("/v1beta/voices")
    assert sent["body"]["voice"]["type"] == "prompted"
    assert sent["body"]["voice"]["language_code"] == "fr-FR"
    path = tmp_path / "voix.json"
    voice_design.save_voice(voice, path)
    assert voice_design.load_voices(path) == [voice]
    assert voice_design.voice_name("voice_abc", path) == "VIIRUS"


def test_designed_synthesizer_uses_interactions(monkeypatch):
    import httpx

    sent = {}

    def post(url, headers, json, timeout):
        sent.update(url=url, body=json)
        audio = base64.b64encode(_wav()).decode()
        return Response(
            {"steps": [{"type": "model_output", "content": [{"type": "audio", "data": audio}]}]}
        )

    monkeypatch.setattr(httpx, "post", post)
    samples = voice_design.designed_synthesizer("KEY", "voice_abc", "enjoué")("Salut !")
    assert len(samples) == 2400
    assert sent["url"].endswith("/v1beta/interactions")
    assert sent["body"]["generation_config"]["speech_config"] == [{"voice": "voice_abc"}]
    assert sent["body"]["input"][0]["content"][0]["text"] == "Salut !"


def test_refused_key_raises_and_fallback_takes_over(monkeypatch):
    import httpx

    monkeypatch.setattr(httpx, "post", lambda *a, **k: Response({"error": "no"}, 403))
    synth = voice_design.designed_synthesizer("KEY", "voice_abc")
    with pytest.raises(AudioError):
        synth("Salut")
    backup = voice_design.with_fallback(synth, lambda text: np.ones(5, np.int16))
    assert len(backup("Salut")) == 5


def test_window_creates_and_lists_a_designed_voice(qt_app, tmp_path, monkeypatch):
    from alicia.ui.main_window import MainWindow
    from tests.test_duo import _wait

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(voice_design, "_store_path", lambda: tmp_path / "voix.json")
    created = voice_design.DesignedVoice("voice_xyz", "VIIRUS garçon", "petit garçon")
    monkeypatch.setattr(
        voice_design, "create_voice", lambda key, name, text: (created, np.zeros(10, np.int16))
    )
    settings = load_settings(environ={"ALICE_AI_PROVIDER": "fake", "GEMINI_API_KEY": "k"})
    window = MainWindow(build_services(settings, demo=True))
    try:
        window.show_page(2)
        window.change_setting("voice_design", ("VIIRUS garçon", "petit garçon de 9 ans"))
        page = window.settings_page
        _wait(qt_app, lambda: "créée" in page.design_state.text())
        page.voice_panel.refresh_library()
        assert "gemini|voice_xyz" in page.voice_panel.main_buttons  # dans la bibliothèque
        page.voice_panel.main_buttons["gemini|voice_xyz"].click()
        assert window.services.settings.voice.gemini_voice == "voice_xyz"
        assert window.services.settings.voice.tts_engine == "gemini"
    finally:
        window.close()


def test_blocked_sentence_uses_backup_voice_without_pause(monkeypatch):
    import httpx

    from alicia.core.audio import speaker
    from alicia.core.config import Secret, VoiceSettings

    monkeypatch.setattr(
        httpx,
        "post",
        lambda *a, **k: Response({"promptFeedback": {"blockReason": "PROHIBITED_CONTENT"}}),
    )
    backup = []
    monkeypatch.setattr(
        speaker,
        "_profile_fallback",
        lambda settings: lambda text: backup.append(text) or np.ones(3, np.int16),
    )
    settings = VoiceSettings(tts_engine="gemini", gemini_voice="Puck", gemini_key=Secret("k"))
    synth = speaker.gemini_synthesizer(settings)
    assert len(synth("phrase refusée")) == 3
    calls = []
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *a, **k: (
            calls.append(1)
            or Response(
                {
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {"inlineData": {"data": base64.b64encode(b"\0\0" * 4).decode()}}
                                ]
                            }
                        }
                    ]
                }
            )
        ),
    )
    assert len(synth("phrase suivante")) == 4  # pas de pause : Gemini reprend tout de suite
    assert calls and backup == ["phrase refusée"]


def test_designed_voices_keep_their_own_settings_and_backup_its_own(monkeypatch):
    from alicia.core.audio import speaker
    from alicia.core.config import Secret, VoiceSettings

    calls = []
    real = speaker.with_fx
    monkeypatch.setattr(speaker, "with_fx", lambda *a, **k: calls.append(a[1:5]) or real(*a, **k))
    settings = VoiceSettings(
        tts_engine="gemini",
        gemini_voice="voice_abc",
        gemini_key=Secret("k"),
        backup_voice="edge:fr-FR-HenriNeural",
        backup_pitch=-2.0,
        backup_reverb=30,
    )
    speaker.make_synthesizer(settings)
    # la voix générée telle quelle (aucun réglage) ; le secours avec SES réglages
    assert (0.0, 0, 50, 0) in calls and (-2.0, 0, 50, 30) in calls
    calls.clear()
    speaker.make_synthesizer(VoiceSettings(tts_engine="gemini", gemini_voice="Puck", fx_pitch=2.5))
    assert calls[0] == (2.5, 0, 50, 0)  # les réglages de la principale


def test_rename_and_delete_designed_voices(qt_app, tmp_path, monkeypatch):
    import httpx

    from alicia.ui.main_window import MainWindow

    monkeypatch.chdir(tmp_path)
    store = tmp_path / "voix.json"
    monkeypatch.setattr(voice_design, "_store_path", lambda: store)
    voice_design.save_voice(voice_design.DesignedVoice("voice_a", "VIIRUS", "x"), store)
    voice_design.save_voice(voice_design.DesignedVoice("voice_b", "VIIRUS", "y"), store)
    deleted = []
    monkeypatch.setattr(
        httpx, "delete", lambda url, headers, timeout: deleted.append(url) or Response({}, 200)
    )
    settings = load_settings(environ={"ALICE_AI_PROVIDER": "fake", "GEMINI_API_KEY": "k"})
    window = MainWindow(build_services(settings, demo=True))
    try:
        window.show_page(2)
        window.rename_designed_voice("voice_a", "VIIRUS humain")
        assert voice_design.voice_name("voice_a", store) == "VIIRUS humain"
        window.change_setting("voice_choose", "gemini|voice_b")
        window.delete_designed_voice("voice_b", confirm=False)
        assert [v.id for v in voice_design.load_voices(store)] == ["voice_a"]
        assert window.services.settings.voice.gemini_voice == "Puck"  # c'était la voix choisie
        window.settings_page.voice_panel.refresh_library()
        assert "gemini|voice_b" not in window.settings_page.voice_panel.main_buttons
        from tests.test_duo import _wait

        _wait(qt_app, lambda: deleted)
        assert deleted[0].endswith("/v1beta/voices/voice_b")
    finally:
        window.close()


def test_old_effect_setting_becomes_slider_values(tmp_path):
    from alicia.core.config import _fx

    assert {
        "fx_pitch": 4.5,
        "fx_metal": 50,
        "fx_bright": 60,
        "fx_reverb": 0,
    }.items() <= _fx({"voice_effect": "robot_enfant"}).items()
    assert _fx({"voice_effect": "enfant", "fx_pitch": 9, "fx_metal": "x"})["fx_pitch"] == 6.0
    assert _fx({})["fx_pitch"] == 0.0


def test_presets_keep_both_names_with_viirus(qt_app, monkeypatch):
    from PySide6.QtWidgets import QComboBox, QWidget

    from alicia.core import persona
    from alicia.ui.naming import rename_widgets

    monkeypatch.setattr("alicia.ui.naming.current", lambda: persona.PERSONAS["veris"])
    root = QWidget()
    kept, renamed = QComboBox(root), QComboBox(root)
    kept.setProperty("keep_names", True)
    for box in (kept, renamed):
        box.addItem("ALICIA — robote pétillante")
    rename_widgets(root)
    assert kept.itemText(0).startswith("ALICIA")
    assert renamed.itemText(0).startswith("VIIRUS")
    root.deleteLater()
