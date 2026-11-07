from PIL import Image

from alicia.core.copilot import parse_decision
from alicia.core.copilot_motion import GameState, MotionWatch, signature


def _img(value):
    return Image.new("RGB", (320, 180), (value, value, value))


def test_still_screen_costs_nothing_big_change_looks_at_once():
    watch = MotionWatch()
    calm = signature(_img(40))
    assert watch.decide(calm, 10, now=0)[0]  # premier coup d'œil
    watch.looked(calm, now=0)
    assert watch.decide(calm, 10, now=2) == (False, "trop tôt")
    ok, why = watch.decide(calm, 10, now=25)
    assert not ok and why.startswith("écran immobile")  # rien n'a bougé : pas d'IA
    assert watch.decide(calm, 10, now=130)[0]  # contrôle toutes les 2 min
    watch.looked(calm, now=130)
    boom = signature(_img(200))  # l'écran change d'un coup
    ok, why = watch.decide(boom, 10, now=134)
    assert ok and "gros changement soudain" in why


def test_interval_follows_the_action():
    watch = MotionWatch()
    watch.activity = 0.2
    assert watch.interval(10) == 7.5  # ça bouge : plus souvent
    watch.activity = 0.0
    assert watch.interval(10) == 20.0  # calme : plus rarement
    watch.decide(signature(_img(40)), 10, now=0)
    watch.decide(signature(_img(200)), 10, now=1)
    assert watch.activity > 0.01


def test_game_state_knows_what_is_over():
    state = GameState()
    state.update("combat contre un kobold, PV à moitié", now=1000)
    state.update("combat contre un kobold, PV bas", now=1030)  # même combat qui continue
    assert len(state.lines) == 1 and state.lines[0].since == 1000
    state.update("en ville, inventaire ouvert", now=1300)
    note = state.note(now=1310)
    assert "TERMINÉ] combat contre un kobold" in note
    assert "en ville, inventaire ouvert (depuis 10 s)" in note
    decision = parse_decision('{"speak": false, "importance": 2, "etat": "écran de chargement"}')
    assert decision.state == "écran de chargement"


def test_signature_is_cheap_on_big_screens():
    import time

    big = Image.new("RGB", (3840, 2160), (90, 30, 30))
    started = time.perf_counter()
    sig = signature(big)
    assert sig.shape == (18, 32) and time.perf_counter() - started < 0.2
