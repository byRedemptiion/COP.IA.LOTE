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
        assert "gemini|voice_xyz" in page.gallery_buttons
        window.change_setting("voice_choose", "gemini|voice_xyz")
        assert window.services.settings.voice.gemini_voice == "voice_xyz"
        assert window.services.settings.voice.tts_engine == "gemini"
    finally:
        window.close()
