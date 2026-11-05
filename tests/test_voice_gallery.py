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
        page.voice_panel.refresh_library()
        buttons = page.voice_panel.main_buttons
        assert len(buttons) == 13 + 30 + 13 + 2  # Edge, Gemini, ChatGPT, intégrées
        before = window.services.settings.voice.tts_engine
        window.change_setting("voice_preview", "edge|fr-FR-EloiseNeural")
        assert speaker.said and callable(speaker.said[-1][1])  # voix d'essai, pas la sienne
        assert window.services.settings.voice.tts_engine == before  # rien n'est changé

        buttons["gemini|Leda"].click()
        voice = window.services.settings.voice
        assert voice.tts_engine == "gemini" and voice.gemini_voice == "Leda"
        assert buttons["gemini|Leda"].text() == "✓ Principale"
        saved = tomllib.loads((data_dir() / "alicia.toml").read_text("utf-8"))
        assert saved["voice"]["tts_engine"] == "gemini" and saved["voice"]["gemini_voice"] == "Leda"

        buttons["edge|fr-FR-HenriNeural"].click()
        assert window.services.settings.voice.tts_voice == "fr-FR-HenriNeural"
        assert buttons["gemini|Leda"].text() == "Principale"
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
    assert rates[0] == "-29%"  # 2^(6/12) ≈ 1,41 → ralentie de 29 % (puis le secours)


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
        panel = window.settings_page.voice_panel
        panel.open_editor("main")
        panel.editor.rows["volume"][0].setValue(140)
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
        panel = window.settings_page.voice_panel
        panel.refresh_library()
        panel.main_buttons["openai|onyx"].click()
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


def test_bottom_voice_list_follows_the_catalogue(qt_app, tmp_path, monkeypatch):
    from alicia.app import build_services
    from alicia.core.config import load_settings
    from alicia.ui.main_window import MainWindow

    monkeypatch.chdir(tmp_path)
    window = MainWindow(
        build_services(load_settings(environ={"ALICE_AI_PROVIDER": "fake"}), demo=True)
    )
    try:
        window.change_setting("voice_choose", "gemini|Puck")
        assert window.engine_box.currentData() == "gemini"
    finally:
        window.close()


def test_main_and_backup_voices_each_keep_their_own_settings(qt_app, tmp_path, monkeypatch):
    from alicia.ui.main_window import MainWindow

    monkeypatch.chdir(tmp_path)
    settings = load_settings(environ={"ALICE_AI_PROVIDER": "fake", "GEMINI_API_KEY": "k"})
    speaker = RecordingSpeaker(settings.voice)
    window = MainWindow(build_services(settings, demo=True, speaker=speaker))
    panel = window.settings_page.voice_panel
    try:
        window.show_page(2, "profile")
        panel.refresh_library()
        panel.main_buttons["gemini|Kore"].click()
        panel.backup_buttons["edge|fr-FR-HenriNeural"].click()
        voice = window.services.settings.voice
        assert (voice.tts_engine, voice.gemini_voice) == ("gemini", "Kore")
        assert voice.backup_voice == "edge:fr-FR-HenriNeural"
        assert panel.backup_buttons["edge|fr-FR-HenriNeural"].text() == "✓ Secours"
        assert panel.main_buttons["gemini|Kore"].text() == "✓ Principale"
        assert "Kore" in panel.cards["main"].name.text()
        assert "Henri" in panel.cards["backup"].name.text()
        # ✎ Modifier la voix de secours : la principale ne bouge pas
        panel.cards["backup"].edit.click()
        assert panel.editing == "backup"
        rows = panel.editor.rows
        assert not rows["style"][0].isEnabled()  # Edge : pas de jeu de voix (et c'est dit)
        assert "Edge" in rows["style"][3].text()
        rows["pitch"][0].setValue(-4)
        rows["reverb"][0].setValue(30)
        rows["volume"][0].setValue(80)
        rows["rate"][0].setValue(10)
        voice = window.services.settings.voice
        assert (voice.backup_pitch, voice.backup_reverb, voice.backup_volume) == (-2.0, 30, 80)
        assert voice.backup_rate == "+10%"
        assert (voice.fx_pitch, voice.fx_reverb, voice.volume) == (0.0, 0, 100)
        # ✎ Modifier la principale : le secours ne bouge pas
        panel.cards["main"].edit.click()
        assert panel.editing == "main" and rows["style"][0].isEnabled()  # Gemini : natif
        rows["metal"][0].setValue(40)
        rows["style"][0].setText("petit robot espiègle")
        rows["style"][0].editingFinished.emit()
        voice = window.services.settings.voice
        assert voice.fx_metal == 40 and voice.voice_style == "petit robot espiègle"
        assert voice.backup_metal == 0 and voice.backup_style == ""
        # gardé au prochain lancement
        reloaded = load_settings(environ={"ALICE_AI_PROVIDER": "fake"}).voice
        assert (reloaded.backup_pitch, reloaded.backup_volume, reloaded.fx_metal) == (-2.0, 80, 40)
        # ▶ Écouter de chaque carte : sa propre voix
        window.change_setting("slot_preview", "backup")
        window.change_setting("slot_preview", "main")
        assert len(speaker.said) == 2 and all(callable(s) for _t, s in speaker.said)
        # Secours désactivé
        panel.cards["backup"].enabled.setChecked(False)
        assert window.services.settings.voice.backup_enabled is False
        assert "Désactivée" in panel.cards["backup"].status.text()
        # Garder la principale dans Mes voix
        window.change_setting("slot_to_library", "main")
        from alicia.core.audio.custom_voices import load_custom

        (kept,) = load_custom()
        assert kept.engine == "gemini" and kept.metal == 40 and kept.style == "petit robot espiègle"
    finally:
        window.close()


def test_my_voices_any_engine_with_fine_tuning(qt_app, tmp_path, monkeypatch):
    from alicia.core.audio.custom_voices import load_custom
    from alicia.ui.main_window import MainWindow

    monkeypatch.chdir(tmp_path)
    settings = load_settings(environ={"ALICE_AI_PROVIDER": "fake"})
    speaker = RecordingSpeaker(settings.voice)
    window = MainWindow(build_services(settings, demo=True, speaker=speaker))
    panel = window.settings_page.voice_panel
    try:
        window.show_page(2)
        panel.create_button.setChecked(True)  # Bibliothèque → Créer une voix
        panel.cv_engine.setCurrentIndex(panel.cv_engine.findData("edge"))
        panel.cv_voice.setCurrentIndex(panel.cv_voice.findData("fr-FR-HenriNeural"))
        rows = panel.cv_editor.rows
        rows["pitch"][0].setValue(-4)
        rows["metal"][0].setValue(30)
        rows["reverb"][0].setValue(40)
        rows["rate"][0].setValue(-10)
        panel.cv_name.setText("Henri caverne")
        window.change_setting("custom_preview", panel.custom_draft())
        assert speaker.said and callable(speaker.said[-1][1])  # écoute d'essai
        assert window.services.settings.voice.fx_reverb == 0  # rien n'est changé
        panel._cv_save("backup")  # 💾 + Voix de secours
        (saved,) = load_custom()
        assert (saved.name, saved.engine, saved.voice) == (
            "Henri caverne",
            "edge",
            "fr-FR-HenriNeural",
        )
        assert (saved.pitch, saved.metal, saved.reverb, saved.rate) == (-2.0, 30, 40, -10)
        voice = window.services.settings.voice
        assert (
            voice.backup_voice == "edge:fr-FR-HenriNeural" and voice.backup_name == "Henri caverne"
        )
        assert (voice.backup_pitch, voice.backup_reverb, voice.backup_rate) == (-2.0, 40, "-10%")
        assert voice.fx_pitch == 0.0  # la principale ne bouge pas
        key = f"custom|{saved.id}"
        panel.refresh_library()
        assert panel.backup_buttons[key].text() == "✓ Secours"
        panel.main_buttons[key].click()
        voice = window.services.settings.voice
        assert voice.tts_engine == "edge" and voice.tts_voice == "fr-FR-HenriNeural"
        assert (voice.fx_pitch, voice.fx_metal, voice.fx_reverb) == (-2.0, 30, 40)
        assert panel.cards["main"].name.text() == "Henri caverne"
        # Retouche dans Mes voix : les voix déjà choisies gardent leurs réglages (copies)
        panel.edit_custom(saved.id)
        rows["reverb"][0].setValue(10)
        panel._cv_save("")
        assert len(load_custom()) == 1 and load_custom()[0].reverb == 10
        assert window.services.settings.voice.fx_reverb == 40
        # Une voix de la bibliothèque telle quelle : sans réglages
        panel.main_buttons["edge|fr-FR-DeniseNeural"].click()
        voice = window.services.settings.voice
        assert voice.fx_pitch == 0 and voice.fx_reverb == 0 and voice.fx_metal == 0
        window.change_setting("custom_delete", saved.id)
        assert not load_custom()
    finally:
        window.close()


def test_custom_backup_voice_keeps_its_settings(monkeypatch):
    from alicia.core.audio.custom_voices import CustomVoice, save_custom

    custom = save_custom(CustomVoice("", "Grave", "edge", "fr-FR-HenriNeural", reverb=50))  # v0.17
    calls = []

    def edge(voice, rate):
        calls.append(voice)
        return lambda _text: _tone(0.5)

    monkeypatch.setattr(speaker_module, "edge_synthesizer", edge)
    settings = VoiceSettings(backup_voice=f"custom:{custom.id}")
    backup = speaker_module._profile_fallback(settings)
    out = backup("Salut")
    assert calls[-1] == "fr-FR-HenriNeural" and len(out) > len(_tone(0.5))  # queue de réverb


def test_reverb_adds_a_tail_and_stays_in_range():
    dry = _tone(0.5)
    wet = speaker_module.add_reverb(dry, 60)
    assert wet.dtype == np.int16 and len(wet) > len(dry)
    assert np.abs(wet[len(dry) :]).max() > 0  # la salle résonne après la voix
    assert speaker_module.add_reverb(dry, 0) is dry


def test_old_effect_becomes_one_of_my_voices():
    from alicia.core.audio.custom_voices import load_custom, matches, migrate

    settings = VoiceSettings(tts_engine="gemini", gemini_voice="Puck", fx_pitch=2.5, fx_metal=50)
    migrate(settings)
    (voice,) = load_custom()
    assert voice.engine == "gemini" and voice.voice == "Puck" and matches(settings, voice)
    migrate(settings)  # une seule fois
    assert len(load_custom()) == 1


def test_gemini_audio_in_several_parts_is_kept_whole(monkeypatch):
    first = np.full(24000, 100, dtype=np.int16).tobytes()
    second = np.full(24000, 200, dtype=np.int16).tobytes()

    def post(url, headers, json, timeout):
        parts = [
            {"inlineData": {"data": base64.b64encode(first).decode()}},
            {"inlineData": {"data": base64.b64encode(second).decode()}},
        ]
        return httpx.Response(200, json={"candidates": [{"content": {"parts": parts}}]})

    monkeypatch.setattr(httpx, "post", post)
    settings = VoiceSettings(tts_engine="gemini", gemini_voice="Puck", gemini_key=Secret("k"))
    samples = speaker_module.gemini_synthesizer(settings, fallback=False)("Salut toi.")
    assert len(samples) == 48000  # les deux morceaux, pas seulement le premier


def test_cut_sentence_is_tried_again():
    text = "Attention il y a un ennemi juste derrière toi sur la gauche, recule vite."
    calls = []

    def synth(t):
        calls.append(t)
        return np.zeros(2400 if len(calls) == 1 else 24000 * 4, dtype=np.int16)

    out = speaker_module.complete_or_retry(synth, "test")(text)
    assert len(calls) == 2 and len(out) == 24000 * 4
    assert not speaker_module.looks_cut("Ok !", np.zeros(100, np.int16))


def test_designed_voice_keeps_every_audio_chunk():
    from alicia.core.audio import voice_design

    a = base64.b64encode(np.full(10, 1, np.int16).tobytes()).decode()
    b = base64.b64encode(np.full(10, 2, np.int16).tobytes()).decode()
    payload = {"outputs": [{"type": "audio", "data": a}, {"type": "audio", "data": b}]}
    chunks = voice_design.find_all_audio(payload)
    assert chunks == [a, b] and len(voice_design.decode_all(chunks)) == 20


def test_one_failed_sentence_does_not_cut_the_rest():
    played = []

    class Player:
        def open(self, device=None):
            return object()

        def play(self, stream, samples, stop):
            played.append(len(samples))

        def close(self, stream):
            pass

    def synth(text):
        if "deux" in text:
            raise AudioError("non", detail="phrase refusée")
        return np.zeros(240, np.int16)

    states = []
    speaker = speaker_module.Speaker(VoiceSettings(), synthesizer=synth, player=Player())
    speaker.on_state = lambda state, message: states.append((state, message))
    speaker.speak(
        "Voici la phrase un, assez longue pour rester seule. "
        "Voilà la phrase deux, elle aussi bien assez longue. "
        "Et enfin la phrase trois, la dernière du message."
    )
    speaker._thread.join(5)
    assert len(played) == 2  # la 1re et la 3e sont dites
    assert states[-1] == ("idle", None)
