import logging

import pytest

from alicia.app import build_services
from alicia.core.ai.providers.fake import FakeModel
from alicia.core.capture.backends import DEMO_WINDOW
from alicia.core.capture.models import WindowInfo
from alicia.core.config import load_settings
from alicia.core.errors import ProviderError, ProviderErrorKind
from alicia.core.logging_setup import setup_logging
from alicia.games.profiles import resolve_profile


@pytest.fixture
def settings(tmp_path):
    # Pas de vraie voix ni de vrai micro dans les tests : doubles injectés au besoin.
    (tmp_path / "alicia.toml").write_text("[voice]\nspeak_answers = false\n", encoding="utf-8")
    return load_settings(
        cwd=tmp_path, environ={"ALICE_AI_PROVIDER": "fake"}, user_dir=tmp_path / "u"
    )


def test_analysis_uses_capture_history_and_profile(settings):
    model = FakeModel()
    services = build_services(settings, demo=True, model=model)
    deltas, frames = [], []
    first = services.analysis.analyze(
        DEMO_WINDOW, "Quel objet ?", on_delta=deltas.append, on_frame=frames.append
    )
    assert "Image reçue : 1280x720" in first.result.text
    assert "".join(deltas) == first.result.text
    assert frames and frames[0].backend == "demo"

    services.analysis.analyze(DEMO_WINDOW, "Et le deuxième ?")
    second_request = model.requests[-1]
    assert second_request.history[0].question == "Quel objet ?"
    assert second_request.images[0].mime_type == "image/jpeg"


def test_empty_question_gets_a_default(settings):
    model = FakeModel()
    services = build_services(settings, demo=True, model=model)
    services.analysis.analyze(DEMO_WINDOW, "   ")
    assert model.requests[0].question


def test_overwatch_profile_is_detected():
    window = WindowInfo(1, "Overwatch", 2, exe_name="Overwatch.exe")
    profile = resolve_profile(window)
    assert profile.key == "overwatch"
    assert "Stadium" in profile.context
    assert resolve_profile(DEMO_WINDOW).key == "generic"
    assert resolve_profile(window, "generic").key == "generic"


def test_logs_are_written_with_operation_id(settings, tmp_path):
    log_file = setup_logging(tmp_path / "logs", "INFO", console=False)
    services = build_services(settings, demo=True, model=FakeModel())
    outcome = services.analysis.analyze(DEMO_WINDOW, "Quel objet ?")
    for handler in logging.getLogger("alicia").handlers:
        handler.flush()
    text = log_file.read_text(encoding="utf-8")
    assert f"[{outcome.operation_id}] Capture ok via demo" in text
    assert "Appel IA fake/fake-1" in text
    assert "Quel objet ?" not in text  # question visible seulement en DEBUG


def run_until(app, window, timeout_ms=5000):
    from PySide6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    result = {}
    window.analysis_done.connect(lambda value: (result.setdefault("value", value), loop.quit()))
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    return result.get("value")


def test_ui_full_flow_streams_answer(qt_app, settings):
    from alicia.ui.main_window import MainWindow

    window = MainWindow(build_services(settings, demo=True, model=FakeModel()))
    window.window_list.setCurrentRow(0)
    window.question.setText("Quel objet ?")
    window.analyze_or_cancel()
    assert window.busy and window.analyze_button.text() == "Annuler"
    outcome = run_until(qt_app, window)
    assert not isinstance(outcome, Exception)
    assert "Image reçue" in window.answer.toPlainText()
    assert "demo" in window.preview_info.text()
    assert window.analyze_button.text() == "Analyser"
    window.close()


def test_ui_shows_provider_error_clearly(qt_app, settings):
    from alicia.ui.main_window import MainWindow

    failing = FakeModel(
        fail_with=ProviderError(ProviderErrorKind.RATE_LIMIT, "Quota Gemini atteint.")
    )
    window = MainWindow(build_services(settings, demo=True, model=failing))
    window.window_list.setCurrentRow(0)
    window.analyze_or_cancel()
    run_until(qt_app, window)
    assert "Quota Gemini atteint." in window.status.text()
    assert not window.busy
    window.close()


def test_ui_stop_discards_late_result(qt_app, settings):
    from PySide6.QtCore import QEventLoop, QThreadPool, QTimer

    from alicia.ui.main_window import MainWindow

    window = MainWindow(build_services(settings, demo=True, model=FakeModel(delay_s=0.05)))
    window.window_list.setCurrentRow(0)
    window.analyze_or_cancel()
    window.stop_observation()
    QThreadPool.globalInstance().waitForDone(5000)
    loop = QEventLoop()
    QTimer.singleShot(100, loop.quit)
    loop.exec()
    assert window.answer.toPlainText() in ("",) or "Image reçue" not in window.answer.toPlainText()
    assert window.start_button.text() == "Démarrer"
    window.close()


def test_parse_hotkey():
    from alicia.core.errors import ConfigError
    from alicia.ui.hotkey import MOD_ALT, MOD_CONTROL, MOD_SHIFT, parse_hotkey

    assert parse_hotkey("F9") == (0, 0x78)
    assert parse_hotkey("ctrl+F9") == (MOD_CONTROL, 0x78)
    assert parse_hotkey("Alt + Shift + a") == (MOD_ALT | MOD_SHIFT, ord("A"))
    for bad in ("", "hyper+F9", "F99", "ctrl+Entrée"):
        with pytest.raises(ConfigError):
            parse_hotkey(bad)


def test_hotkey_analyzes_observed_window_with_default_question(qt_app, settings):
    from alicia.ui.main_window import DEFAULT_HOTKEY_QUESTION, MainWindow

    model = FakeModel()
    window = MainWindow(build_services(settings, demo=True, model=model))
    window.hotkey_analyze()  # aucune fenêtre active ni choisie
    assert "premier plan" in window.status.text()
    window.window_list.setCurrentRow(0)
    window.start_observation()
    window.hotkey_analyze()
    outcome = run_until(qt_app, window)
    assert not isinstance(outcome, Exception)
    assert model.requests[-1].question == DEFAULT_HOTKEY_QUESTION
    window.close()


def test_minimized_window_error_points_to_hotkey(tmp_path):
    from alicia.core.capture.service import CaptureService
    from alicia.core.errors import CaptureError

    def refuse(window):
        raise CaptureError("La fenêtre du jeu est réduite … F9", detail="IsIconic")

    service = CaptureService(lambda: [], refuse, lambda w: [])
    with pytest.raises(CaptureError) as info:
        service.capture(DEMO_WINDOW)
    assert "F9" in info.value.user_message


class FakeRecorder:
    def __init__(self, audio=None, error=None):
        self.audio, self.error, self.recording, self.started = audio, error, False, 0

    def start(self):
        self.recording, self.started = True, self.started + 1

    def stop(self):
        self.recording = False
        if self.error:
            raise self.error
        return self.audio

    def cancel(self):
        self.recording = False


class FakeSpeaker:
    def __init__(self):
        self.spoken, self.stopped, self.speaking = [], 0, False
        self.on_state = lambda state, msg: None

    def speak(self, text):
        self.spoken.append(text)
        return True

    def stop(self):
        self.stopped += 1


def test_voice_question_transcript_is_shown_and_answer_spoken(qt_app, settings):
    from alicia.core.ai.base import PreparedAudio
    from alicia.ui.main_window import MainWindow

    audio = PreparedAudio(b"RIFF....", "audio/wav", 2.5)
    recorder, speaker, model = FakeRecorder(audio), FakeSpeaker(), FakeModel()
    services = build_services(settings, demo=True, model=model, speaker=speaker, recorder=recorder)
    window = MainWindow(services)
    window.voice_box.setChecked(True)
    window.window_list.setCurrentRow(0)
    window.start_observation()
    window.talk_pressed()
    assert recorder.recording and "écoute" in window.status.text()
    window.talk_released()
    outcome = run_until(qt_app, window)
    assert not isinstance(outcome, Exception)
    assert outcome.transcript == "question orale factice"
    assert window.question.text() == "🎙 question orale factice"
    assert not window.answer.toPlainText().startswith("Question :")
    assert model.requests[-1].audio is audio
    assert speaker.spoken and "Réponse factice" in speaker.spoken[0]
    assert services.session.last.question == "question orale factice"
    window.close()


def test_silent_microphone_is_reported_without_calling_ai(qt_app, settings):
    from alicia.core.audio.devices import AudioError
    from alicia.ui.main_window import MainWindow

    recorder = FakeRecorder(error=AudioError("Aucun son capté par le micro « X »."))
    model = FakeModel()
    window = MainWindow(build_services(settings, demo=True, model=model, recorder=recorder))
    window.window_list.setCurrentRow(0)
    window.start_observation()
    window.talk_pressed()
    window.talk_released()
    assert "Aucun son" in window.status.text()
    assert model.requests == []
    window.close()


def test_talking_interrupts_alicia(qt_app, settings):
    from alicia.ui.main_window import MainWindow

    speaker = FakeSpeaker()
    speaker.speaking = True
    window = MainWindow(
        build_services(
            settings, demo=True, model=FakeModel(), speaker=speaker, recorder=FakeRecorder()
        )
    )
    window.talk_pressed()
    assert speaker.stopped >= 1
    window.close()


def test_web_search_flag_and_sources_reach_the_ui(qt_app, settings):
    from alicia.core.ai.base import Source
    from alicia.ui.main_window import MainWindow

    class SourcedModel(FakeModel):
        def analyze(self, request, on_delta=None, cancel=None):
            result = super().analyze(request, on_delta, cancel)
            result.sources = [Source("Guide Stadium", "https://example.com/stadium")]
            return result

    model = SourcedModel()
    window = MainWindow(build_services(settings, demo=True, model=model))
    window.web_box.setChecked(True)
    window.window_list.setCurrentRow(0)
    window.analyze_or_cancel()
    run_until(qt_app, window)
    assert model.requests[-1].web_search is True
    assert "Guide Stadium" in window.sources_label.text()
    window.close()


def test_voice_engine_can_be_switched_from_the_ui(qt_app, settings):
    from alicia.core.audio.speaker import Speaker
    from alicia.core.config import VoiceSettings
    from alicia.ui.main_window import MainWindow

    speaker = Speaker(VoiceSettings(), synthesizer=lambda text: None)
    window = MainWindow(build_services(settings, demo=True, model=FakeModel(), speaker=speaker))
    window.engine_box.setCurrentIndex(window.engine_box.findData("kokoro"))
    assert speaker.settings.tts_engine == "kokoro"
    assert getattr(speaker.synthesizer, "warm_up", None) is not None
    window.close()


def test_typed_action_works_without_game_or_ai(qt_app, settings):
    from alicia.core.actions.controller import ActionController
    from alicia.core.config import ActionSettings
    from alicia.ui.main_window import MainWindow
    from tests.test_actions import FakeSystem

    system = FakeSystem()
    actions = ActionController(ActionSettings(), system)
    model = FakeModel()
    window = MainWindow(build_services(settings, demo=True, model=model, actions=actions))
    window.question.setText("Éteins le PC")
    window.analyze_or_cancel()
    assert "confirmes" in window.answer.toPlainText()
    window.question.setText("oui")
    window.analyze_or_cancel()
    assert system.calls == [("shutdown", 20)]
    assert model.requests == []
    window.close()


@pytest.mark.parametrize("state", ["idle", "listening", "thinking", "speaking", "action", "error"])
def test_alicia_core_paints_every_state(qt_app, state):
    from alicia.ui.core_widget import AliciaCore

    core = AliciaCore()
    assert core.portrait is not None  # portrait d'ALICIA embarqué
    core.resize(420, 480)
    core.set_state(state, (lambda: 0.6) if state in ("listening", "speaking") else None)
    core._tick()
    image = core.grab().toImage()
    assert not image.isNull() and image.width() == 420


def test_orb_mode_shows_only_the_ring_and_a_bubble_while_answering(qt_app, settings):
    from alicia.ui.main_window import MainWindow

    assert settings.ui_mode == "orb"  # mode par défaut
    window = MainWindow(build_services(settings, demo=True, model=FakeModel()))
    window.start()
    assert window.orb.isVisible() and not window.isVisible()
    assert not window.bubble.isVisible()  # aucun texte tant qu'on ne parle pas
    window.window_list.setCurrentRow(0)
    window.question.setText("Quel objet ?")
    window.analyze_or_cancel()
    assert window.bubble.isVisible()
    assert "Quel objet" in window.bubble.asked.text()
    run_until(qt_app, window)
    assert "Image reçue" in window.bubble.text.text()
    assert window.bubble._hide_timer.isActive()  # la bulle s'effacera d'elle-même
    window.bubble._hide_timer.timeout.emit()
    window.bubble._fade.setCurrentTime(window.bubble._fade.duration())
    assert not window.bubble.isVisible()
    window.show_panel()
    assert window.isVisible() and not window.orb.isVisible()
    window.close()


def test_orb_warnings_go_to_the_bubble(qt_app, settings):
    from alicia.ui.main_window import MainWindow

    window = MainWindow(build_services(settings, demo=True, model=FakeModel()))
    window.start()
    window.hotkey_analyze()  # aucune fenêtre active ni choisie
    assert window.bubble.isVisible()
    assert "premier plan" in window.bubble.text.text()
    window.close()


def test_long_answers_keep_their_end_in_the_bubble():
    from alicia.ui.orb import MAX_BUBBLE_CHARS, _tail

    text = "début " + "mot " * 400 + "conclusion finale"
    short = _tail(text)
    assert short.startswith("…") and short.endswith("conclusion finale")
    assert len(short) <= MAX_BUBBLE_CHARS + 2


def test_wow_forever_profile_points_to_its_reference_sites():
    from alicia.games.profiles import load_profiles

    profiles = load_profiles()
    window = WindowInfo(
        1,
        "World of Warcraft",
        2,
        exe_name="WowClassic.exe",
        exe_path=r"D:\Jeux\World of Warcraft\_forever_\WowClassic.exe",
    )
    profile = resolve_profile(window, profiles=profiles)
    assert profile.key == "wow-forever"
    assert any("icy-veins.com/wow-forever" in s for s in profile.sources)
    with_search = profile.prompt_context(web_search=True)
    assert "site:" in with_search and "method.gg/wow-forever" in with_search
    assert "site:" not in profile.prompt_context(web_search=False)


def test_player_games_file_adds_and_overrides_profiles(tmp_path):
    from alicia.games.profiles import load_profiles

    user_file = tmp_path / "games.toml"
    user_file.write_text(
        '[overwatch]\nname = "OW"\nexe = ["overwatch.exe"]\nsources = ["mon-site.fr"]\n\n'
        '[elden-ring]\nname = "Elden Ring"\nexe = ["eldenring.exe"]\n'
        'sources = ["eldenring.wiki.fextralife.com"]\ncontext = "Souls-like."\n',
        encoding="utf-8",
    )
    profiles = load_profiles(user_file)
    assert profiles["overwatch"].sources == ("mon-site.fr",)
    assert "Stadium" in profiles["overwatch"].context  # le reste du profil fourni est gardé
    elden = resolve_profile(
        WindowInfo(1, "ELDEN RING", 3, exe_name="eldenring.exe"), profiles=profiles
    )
    assert elden.name == "Elden Ring"
    # Un fichier cassé n'empêche pas ALICIA de démarrer : on garde les profils fournis.
    user_file.write_text("[cassé", encoding="utf-8")
    assert "wow-forever" in load_profiles(user_file)


def test_chosen_game_sends_its_sources_with_web_search(settings):
    model = FakeModel()
    services = build_services(settings, demo=True, model=model)
    services.analysis.game_profile = "wow-forever"
    services.analysis.analyze(DEMO_WINDOW, "Quelle quête ?", web_search=True)
    prompt = model.requests[-1].system_prompt
    assert "World of Warcraft: Forever" in prompt
    assert "site:" in prompt and "icy-veins.com/wow-forever" in prompt


def test_bubble_can_be_moved_and_remembers_its_place(qt_app, tmp_path):
    from PySide6.QtCore import QPoint

    from alicia.ui.orb import OrbWindow

    position = tmp_path / "orb.json"
    orb = OrbWindow(200, position)
    orb.show()
    orb.bubble.offset = QPoint(-300, 150)
    orb.bubble.moved.emit()
    orb.close()
    again = OrbWindow(200, position)
    again.show()
    assert again.bubble.offset == QPoint(-300, 150)
    again.bubble.reset_offset()
    assert again.bubble.offset is None
    again.close()


def test_game_can_be_chosen_from_the_orb_menu(qt_app, settings):
    from alicia.ui.main_window import MainWindow

    window = MainWindow(build_services(settings, demo=True, model=FakeModel()))
    keys = [key for key, _name in window.orb.games]
    assert keys[0] == "auto" and "wow-forever" in keys
    window.orb.game_chosen.emit("wow-forever")
    assert window.services.analysis.game_profile == "wow-forever"
    assert window.game_box.currentData() == "wow-forever"
    window.close()


def test_games_tab_updates_the_game_menus(qt_app, settings):
    from alicia.games.store import GameDraft
    from alicia.ui.main_window import MainWindow

    window = MainWindow(build_services(settings, demo=True, model=FakeModel()))
    window.show_page(1)
    assert window.pages.currentWidget() is window.settings_page
    assert window.settings_page.current_tab == "games" and window.games_page.isVisibleTo(
        window.settings_page.stack.currentWidget()
    )
    assert window.nav_keys.isChecked() and not window.nav_console.isChecked()
    window.game_store.save(
        None, GameDraft("Hades II", ["hades2.exe"], [], ["hades.fandom.com"], "")
    )
    window.games_page.games_changed.emit()
    assert window.game_box.findData("hades-ii") >= 0
    assert ("hades-ii", "Hades II") in window.orb.games
    window.games_page.use_game.emit("hades-ii")
    assert window.services.analysis.game_profile == "hades-ii"
    window.close()


def test_update_button_reports_up_to_date_and_new_version(qt_app, settings):
    from alicia.core.update import UpdateInfo
    from alicia.ui.main_window import MainWindow

    class StubUpdater:
        root = None

        def __init__(self, info):
            self.info = info

        def check(self):
            return self.info

    window = MainWindow(build_services(settings, demo=True, model=FakeModel()))
    asked = []
    window._confirm_update = asked.append
    window.updater = StubUpdater(None)
    window.check_update(interactive=True)
    for _ in range(50):
        qt_app.processEvents()
        if not window._updating:
            break
        import time

        time.sleep(0.02)
    assert "à jour" in window.status.text()
    window.updater = StubUpdater(UpdateInfo("b" * 40, "Nouvelle version", ""))
    window.check_update(interactive=False)
    for _ in range(50):
        qt_app.processEvents()
        if not window._updating:
            break
        time.sleep(0.02)
    assert window.update_button.text().endswith("MAJ dispo")
    assert not asked  # vérification discrète : on ne dérange pas le joueur
    window.update_now()
    assert asked and asked[0].short == "bbbbbbb"
    window.close()


def test_wake_word_events_drive_the_interface(qt_app, settings):
    from alicia.ui.main_window import MainWindow

    window = MainWindow(build_services(settings, demo=True, model=FakeModel()))
    window.start()  # démo : le micro n'est pas ouvert
    assert window.wake is None
    window.voice_bridge.wake.emit()
    assert window.core.state == "listening" and "écoute" in window.status.text()
    assert window.bubble.isVisible()
    window.voice_bridge.wake_cancel.emit("rien")
    assert window.core.state == "idle"
    window.orb.wake_toggled.emit(False)
    assert not window.wake_box.isChecked()
    window.close()


def test_voice_stop_silences_and_cancels(qt_app, settings):
    from alicia.ui.main_window import MainWindow

    window = MainWindow(build_services(settings, demo=True, model=FakeModel(delay_s=0.5)))
    window.window_list.setCurrentRow(0)
    window.analyze_or_cancel()
    assert window.busy and window._wake_stop_only()
    window.voice_bridge.wake_stop.emit()
    assert not window.busy
    assert "j'arrête" in window.status.text()
    window.close()


def test_orb_edit_mode_changes_and_remembers_the_layout(qt_app, tmp_path):
    from alicia.ui.orb import OrbWindow

    position = tmp_path / "orb.json"
    orb = OrbWindow(210, position)
    orb.show()
    orb.start_editing()
    panel = orb.edit_panel
    assert orb.bubble.isVisible() and panel.isVisible()
    panel.size.setValue(300)
    panel.width_.setValue(600)
    panel.font.setValue(16)
    panel.alpha.setValue(70)
    panel.seconds.setValue(10)
    panel.side.setCurrentIndex(panel.side.findData("below"))
    assert orb.width() == 300 and orb.bubble.width() == 600
    assert orb.bubble.y() > orb.y() + orb.height() - 1  # sous le rond
    orb.bubble.hide_after(100)
    assert not orb.bubble._hide_timer.isActive()  # la bulle d'exemple reste en édition
    orb.stop_editing()
    assert not panel.isVisible() and not orb.bubble.editing
    orb.close()

    again = OrbWindow(210, position)
    assert again.size_px == 300 and again.bubble.bubble_width == 600
    assert again.bubble.font_pt == 16 and again.bubble.side == "below"
    assert again.bubble.after_voice_ms() == 10000
    again.close()


def test_cursor_vision_tells_the_ai_what_is_pointed(settings):
    model = FakeModel()
    services = build_services(settings, demo=True, model=model)
    services.analysis.vision_mode = "cursor"
    outcome = services.analysis.analyze(None, "C'est quoi ça ?")
    assert outcome.frame.mode == "cursor" and outcome.frame.cursor is not None
    assert "cercle rose" in model.requests[-1].system_prompt


def test_vision_mode_can_be_switched_and_is_remembered(qt_app, settings):
    import tomllib

    from alicia.core.config import data_dir
    from alicia.ui.main_window import MainWindow

    window = MainWindow(build_services(settings, demo=True, model=FakeModel()))
    window.orb.vision_chosen.emit("screen")
    assert window.services.analysis.vision_mode == "screen"
    assert window.vision_box.currentData() == "screen" and window.orb.vision == "screen"
    saved = tomllib.loads((data_dir() / "alicia.toml").read_text("utf-8"))
    assert saved["capture"]["mode"] == "screen"
    window.hotkey_analyze()  # écran entier : pas besoin de fenêtre au premier plan
    assert window.busy
    run_until(qt_app, window)
    window.close()


def test_speech_uses_the_screen_from_when_you_started_talking(qt_app, settings):
    from alicia.core.ai.base import PreparedAudio
    from alicia.core.capture.live import LiveCapture
    from alicia.ui.main_window import MainWindow

    audio = PreparedAudio(b"RIFF", "audio/wav", 1.0)
    services = build_services(settings, demo=True, model=FakeModel(), recorder=FakeRecorder(audio))
    window = MainWindow(services)
    window.live = LiveCapture(
        services.capture.capture, lambda: (DEMO_WINDOW, "window", (800, 500)), interval_s=30
    )
    window.live.start()
    window.live.since(0.0, wait_s=2.0)
    window.talk_pressed()  # capture demandée à l'appui
    assert window._speech_mark is not None
    pressed = window.live.since(window._speech_mark, wait_s=2.0)
    assert pressed is not None
    window.talk_released()
    outcome = run_until(qt_app, window)
    assert outcome.frame is pressed  # l'image du début de la phrase, pas une nouvelle
    window.live.stop()
    window.close()


def test_question_about_the_past_sends_remembered_images(settings, tmp_path):
    from dataclasses import replace
    from datetime import UTC, datetime, timedelta

    from alicia.core.capture.timeline import Timeline

    model = FakeModel()
    services = build_services(settings, demo=True, model=model)
    timeline = Timeline(tmp_path / "memoire")
    frame = services.capture.capture(DEMO_WINDOW)
    for minutes in (58, 60, 62, 5):
        timeline.add(
            replace(frame, captured_at=datetime.now(UTC) - timedelta(minutes=minutes)), force=True
        )
    services.analysis.timeline = timeline
    services.analysis.analyze(DEMO_WINDOW, "Il y a une heure, c'était quoi mon objet ?")
    request = model.requests[-1]
    assert len(request.images) == 4  # écran actuel + 3 images d'il y a une heure
    assert "mémoire de partie" in request.system_prompt
    services.analysis.analyze(DEMO_WINDOW, "Quel objet maintenant ?")
    assert len(model.requests[-1].images) == 1


def test_confirmation_question_opens_the_mic_for_the_answer(qt_app, settings):
    from alicia.ui.main_window import MainWindow

    class FakeWake:
        running = True
        level = 0.0

        def __init__(self):
            self.listened = []

        def listen_now(self, seconds):
            self.listened.append(seconds)

        def stop(self):
            pass

    window = MainWindow(build_services(settings, demo=True, model=FakeModel()))
    window.wake = FakeWake()
    from alicia.core.actions.controller import ActionReply
    from alicia.core.analysis.service import AnalysisOutcome

    question = ActionReply("J'éteins le PC. Tu confirmes ?", "shutdown", awaiting_confirmation=True)
    window._action_done(AnalysisOutcome("action", None, None, "", 0, action=question))
    assert window.wake.listened == [8.0]
    assert window._awaiting_answer and window.core.state == "listening"
    window._wake_cancel("rien")
    assert not window._awaiting_answer
    window.close()


def test_question_from_the_desktop_looks_at_the_whole_screen(settings):
    """Pas de jeu au premier plan (bureau) : l'écran entier au lieu d'une erreur."""
    services = build_services(settings, demo=True, model=FakeModel())
    services.analysis.vision_mode = "window"
    outcome = services.analysis.analyze(None, "c'est quoi sur mon bureau ?")
    assert outcome.frame is not None and outcome.frame.mode == "screen"


class LoopingModel:
    """Petit modèle qui recopie sa réponse précédente tant qu'il a l'historique."""

    provider, model = "fake", "petit-2b"

    def __init__(self):
        self.requests = []

    def check(self):
        return None

    def analyze(self, request, on_delta=None, cancel=None):
        from alicia.core.ai.base import AnalysisResult

        self.requests.append(request)
        if request.history:
            text = request.history[-1].answer
        else:
            text = f"Réponse à : {request.question}"
        return AnalysisResult(text, self.provider, self.model, 1)


def test_a_repeated_answer_is_asked_again_without_history():
    from alicia.core.analysis.service import repeats

    model = LoopingModel()
    services = build_services(
        load_settings(environ={"ALICE_AI_PROVIDER": "fake"}), demo=True, model=model
    )
    services.analysis.analyze(DEMO_WINDOW, "Comment va le boss ?")
    second = services.analysis.analyze(DEMO_WINDOW, "Et mes potions ?")
    assert second.result.text == "Réponse à : Et mes potions ?"
    assert len(model.requests) == 3  # 1re question, 2e (recopiée), relance sans historique
    assert model.requests[2].history == () and "Ne la répète surtout pas" in (
        model.requests[2].system_prompt
    )
    assert services.session.history()[-1].answer == "Réponse à : Et mes potions ?"
    assert not repeats("Oui.", services.session.history())
