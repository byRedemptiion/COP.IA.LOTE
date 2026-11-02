import io
import threading
import time
import wave

import numpy as np
import pytest

from alicia.core.ai.prompts import TranscriptSplitter, split_transcript
from alicia.core.audio.devices import AudioError
from alicia.core.audio.recorder import to_prepared_audio
from alicia.core.audio.speaker import Speaker
from alicia.core.audio.text import clean_for_speech, split_sentences
from alicia.core.config import VoiceSettings


def test_clean_for_speech_removes_markdown_links_and_emojis():
    text = "## Conseil\n- **Prends** la [lame](https://x.y) 🔥\n- Puis `bouclier`"
    assert clean_for_speech(text) == "Conseil\nPrends la lame\nPuis bouclier"


def test_split_sentences_groups_short_and_cuts_long():
    sentences = split_sentences("Oui. Prends la lame du crépuscule, elle augmente tes dégâts. " * 1)
    assert sentences == ["Oui. Prends la lame du crépuscule, elle augmente tes dégâts."]
    long = "mot, " * 120
    assert all(len(s) <= 262 for s in split_sentences(long))


def tone(seconds, amplitude=8000, rate=16000):
    t = np.arange(int(seconds * rate)) / rate
    return (np.sin(2 * np.pi * 440 * t) * amplitude).astype(np.int16)


def test_recording_is_encoded_as_wav():
    audio = to_prepared_audio(tone(1.0), 16000, "Micro test")
    assert audio.mime_type == "audio/wav" and audio.duration_s == 1.0
    with wave.open(io.BytesIO(audio.data)) as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getnframes()) == (16000, 1, 16000)


def test_too_short_or_silent_recording_is_refused():
    with pytest.raises(AudioError, match="trop courte"):
        to_prepared_audio(tone(0.1), 16000)
    with pytest.raises(AudioError, match="Aucun son"):
        to_prepared_audio(tone(2.0, amplitude=50), 16000, "Casque")


def test_transcript_splitter_handles_streamed_pieces():
    transcripts, texts = [], []
    splitter = TranscriptSplitter(transcripts.append, texts.append)
    for piece in ["Ques", "tion : quel ob", "jet ?\nPrends ", "la lame."]:
        splitter.feed(piece)
    splitter.close()
    assert transcripts == ["quel objet ?"]
    assert "".join(texts) == "Prends la lame."


def test_transcript_splitter_passes_through_when_model_ignores_format():
    texts = []
    splitter = TranscriptSplitter(lambda t: None, texts.append)
    splitter.feed("Prends la lame.")
    splitter.close()
    assert "".join(texts) == "Prends la lame." and splitter.transcript is None
    assert split_transcript("Question : salut\nRéponse") == ("salut", "Réponse")


class FakePlayer:
    def __init__(self):
        self.played, self.closed = [], 0

    def open(self):
        return object()

    def play(self, stream, samples, stop):
        for _ in range(20):
            if stop.is_set():
                return
            time.sleep(0.005)
        self.played.append(len(samples))

    def close(self, stream):
        self.closed += 1


def wait_idle(speaker, states):
    deadline = time.monotonic() + 5
    while speaker.speaking and time.monotonic() < deadline:
        time.sleep(0.01)
    return states


def test_speaker_reads_every_sentence_in_order():
    synthesized = []

    def synth(text):
        synthesized.append(text)
        return np.zeros(240, np.int16)

    player, states = FakePlayer(), []
    speaker = Speaker(VoiceSettings(), synthesizer=synth, player=player)
    speaker.on_state = lambda state, msg: states.append(state)
    assert speaker.speak("Première phrase assez longue. Deuxième phrase assez longue. Troisième.")
    wait_idle(speaker, states)
    assert len(player.played) == len(synthesized) == 3
    assert states == ["speaking", "idle"] and player.closed == 1


def test_speaker_stop_cuts_immediately():
    gate = threading.Event()

    def synth(text):
        gate.wait(0.5)
        return np.zeros(240, np.int16)

    player = FakePlayer()
    speaker = Speaker(VoiceSettings(), synthesizer=synth, player=player)
    speaker.speak("Une première phrase bien longue. Une seconde phrase bien longue aussi.")
    gate.set()
    time.sleep(0.02)
    speaker.stop()
    assert not speaker.speaking
    assert len(player.played) < 2


def test_speaker_error_is_reported():
    def synth(text):
        raise AudioError("La voix en ligne ne répond pas.", detail="ConnectError")

    states = []
    speaker = Speaker(VoiceSettings(), synthesizer=synth, player=FakePlayer())
    speaker.on_state = lambda state, msg: states.append((state, msg))
    speaker.speak("Bonjour, ceci est un test de voix.")
    wait_idle(speaker, states)
    assert states == [("error", "La voix en ligne ne répond pas.")]


def test_openai_voice_sends_text_and_plays_pcm(monkeypatch):
    import httpx
    import numpy as np

    from alicia.core.audio.speaker import make_synthesizer
    from alicia.core.config import Secret, VoiceSettings

    seen = {}

    def fake_post(url, headers, json, timeout):
        seen.update(url=url, auth=headers["Authorization"], body=json)
        return httpx.Response(200, content=np.array([1, -1, 300], dtype=np.int16).tobytes())

    monkeypatch.setattr(httpx, "post", fake_post)
    settings = VoiceSettings(tts_engine="openai", openai_key=Secret("sk-test"), openai_voice="nova")
    samples = make_synthesizer(settings)("Salut, je suis ALICIA.")
    assert list(samples) == [1, -1, 300]
    assert seen["url"].endswith("/audio/speech") and seen["auth"] == "Bearer sk-test"
    assert seen["body"]["voice"] == "nova" and seen["body"]["response_format"] == "pcm"
    assert "français" in seen["body"]["instructions"]


def test_openai_voice_without_key_explains():
    import pytest

    from alicia.core.audio.devices import AudioError
    from alicia.core.audio.speaker import make_synthesizer
    from alicia.core.config import VoiceSettings

    with pytest.raises(AudioError) as info:
        make_synthesizer(VoiceSettings(tts_engine="openai"))("Salut")
    assert "clé OpenAI" in info.value.user_message
