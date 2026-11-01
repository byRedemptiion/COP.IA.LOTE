import time

import numpy as np

from alicia.core.audio.speaker import Speaker
from alicia.core.audio.text import LiveSentences
from alicia.core.config import load_settings
from tests.test_voice import FakePlayer


def test_live_sentences_release_complete_sentences_only():
    live = LiveSentences()
    assert live.feed("Salut ! Le boss est") == ["Salut !"]
    assert live.feed(" à gauche. Esquive") == ["Le boss est à gauche."]
    final = "Salut ! Le boss est à gauche. Esquive ses lasers.\n[IMAGE]"
    assert live.rest("Salut ! Le boss est à gauche. Esquive ses lasers.") == ["Esquive ses lasers."]
    assert live.rest("Une tout autre réponse.") is None
    assert final  # repère retiré par l'analyse avant rest()


def test_live_sentences_skip_relay_and_markers():
    live = LiveSentences()
    assert live.feed("[TRANS") == []
    assert live.feed("METTRE] Dis-lui que je gagne. ") == []
    other = LiveSentences()
    assert other.feed("Va au nord. [OUVRIR]\n") == ["Va au nord."]


def test_speaker_stream_starts_before_the_text_is_complete():
    said = []
    speaker = Speaker(
        load_settings(environ={}).voice,
        synthesizer=lambda text: said.append(text) or np.zeros(100, np.int16),
        player=FakePlayer(),
    )
    speaker.stream_begin()
    speaker.stream_feed("Première phrase.")
    deadline = time.monotonic() + 3
    while not said and time.monotonic() < deadline:
        time.sleep(0.01)
    assert said == ["Première phrase."]  # lue alors que la suite n'est pas encore là
    speaker.stream_feed("Deuxième phrase.")
    speaker.stream_end()
    speaker._thread.join(3)
    assert said == ["Première phrase.", "Deuxième phrase."] and not speaker.speaking
