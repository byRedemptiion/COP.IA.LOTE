import numpy as np
import pytest

from alicia.core.audio.wake import WakeListener, find_wake, strip_wake_word

RATE = 16000
BLOCK = int(RATE * 0.03)


@pytest.mark.parametrize(
    ("text", "woke", "rest"),
    [
        ("Alicia, lance Discord.", True, "lance discord"),
        ("Ok Alicia monte le son", True, "monte le son"),
        ("Alissia ?", True, ""),
        ("A licia, quelle heure", True, "quelle heure"),
        ("Alice, éteins le PC", True, "eteins le pc"),
        ("On va au point A, il y a Alicia là-bas", False, ""),
        ("C'est délicieux", False, ""),
        ("", False, ""),
    ],
)
def test_wake_word_detection(text, woke, rest):
    assert find_wake(text) == (woke, rest)


def test_wake_word_is_removed_from_the_request():
    assert strip_wake_word("Alicia, lance Discord.") == "lance Discord."
    assert strip_wake_word("Ok Alicia monte le son") == "monte le son"
    assert strip_wake_word("Alicia") == ""
    assert strip_wake_word("Quel objet pour Ashe ?") == "Quel objet pour Ashe ?"


def tone(seconds, amplitude=6000):
    t = np.arange(int(RATE * seconds)) / RATE
    return (np.sin(2 * np.pi * 220 * t) * amplitude).astype(np.int16)


def silence(seconds):
    return np.zeros(int(RATE * seconds), np.int16)


def feed(listener, samples):
    for i in range(0, len(samples), BLOCK):
        listener.process(samples[i : i + BLOCK])


def make(text, paused=lambda: False):
    events = {"wake": 0, "commands": [], "cancel": []}
    listener = WakeListener(
        lambda _samples: text,
        on_wake=lambda: events.__setitem__("wake", events["wake"] + 1),
        on_command=events["commands"].append,
        on_cancel=events["cancel"].append,
        paused=paused,
    )
    return listener, events


def test_sentence_starting_with_alicia_becomes_a_request():
    listener, events = make("Alicia, lance Discord")
    feed(listener, np.concatenate([silence(1), tone(2.5), silence(1.2)]))
    assert events["wake"] == 1
    assert len(events["commands"]) == 1
    assert 2.4 <= events["commands"][0].duration_s <= 3.4  # toute la phrase, sans le silence


def test_other_speech_is_ignored():
    listener, events = make("on push le point B")
    feed(listener, np.concatenate([silence(1), tone(2.5), silence(1.2)]))
    assert events == {"wake": 0, "commands": [], "cancel": []}


def test_alicia_alone_waits_for_the_request():
    listener, events = make("Alicia ?")
    feed(listener, np.concatenate([silence(1), tone(0.7), silence(1)]))
    assert events["wake"] == 1 and not events["commands"]
    feed(listener, np.concatenate([tone(1.5), silence(1.2)]))
    assert len(events["commands"]) == 1


def test_alicia_alone_then_nothing_cancels():
    listener, events = make("Alicia")
    feed(listener, np.concatenate([silence(1), tone(0.7), silence(7)]))
    assert events["wake"] == 1 and not events["commands"] and events["cancel"]


def test_nothing_is_heard_while_paused():
    calls = []
    listener = WakeListener(
        lambda s: calls.append(s) or "Alicia",
        on_wake=lambda: None,
        on_command=lambda a: None,
        paused=lambda: True,
    )
    feed(listener, np.concatenate([silence(1), tone(2.5), silence(1.2)]))
    assert not calls


@pytest.mark.parametrize(
    "text", ["Alicia stop", "Alicia, tais-toi !", "Alicia arrête", "Ok Alicia, chut"]
)
def test_alicia_stop_interrupts_even_while_she_talks(text):
    stops = []
    listener = WakeListener(
        lambda _s: text,
        on_wake=lambda: pytest.fail("pas de nouvelle demande"),
        on_command=lambda a: pytest.fail("pas de nouvelle demande"),
        stop_only=lambda: True,
        on_stop=lambda: stops.append(1),
    )
    feed(listener, np.concatenate([silence(1), tone(1.0), silence(1)]))
    assert stops == [1]


def test_other_requests_wait_while_she_talks():
    listener, events = make("Alicia, lance Discord")
    listener.stop_only = lambda: True
    feed(listener, np.concatenate([silence(1), tone(2.5), silence(1.2)]))
    assert events == {"wake": 0, "commands": [], "cancel": []}


def test_reply_is_heard_without_saying_alicia():
    listener, events = make("oui")
    listener.listen_now(5)
    feed(listener, np.concatenate([silence(0.5), tone(0.8), silence(1.2)]))
    assert events["wake"] == 0 and len(events["commands"]) == 1


def test_no_reply_cancels_after_the_window():
    listener, events = make("oui")
    listener.listen_now(2)
    feed(listener, silence(3))
    assert not events["commands"] and events["cancel"]
