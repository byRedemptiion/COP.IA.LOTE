import tomllib

from alicia.app import build_services
from alicia.core.ai.providers.fake import FakeModel
from alicia.core.config import data_dir, load_settings
from alicia.ui.settings_page import rate_percent


class FakeSpeaker:
    speaking = False
    level = 0.0

    def __init__(self, settings):
        self.settings = settings
        self.synthesizer = object()
        self.player = object()
        self.said = []

    def speak(self, text):
        self.said.append(text)
        return True

    def stop(self):
        pass

    def warm_up_async(self):
        pass


def test_rate_is_read_from_settings():
    assert rate_percent("+8%") == 8 and rate_percent("-10 %") == -10 and rate_percent("") == 0


def test_settings_tab_applies_and_saves_voice_and_mic(qt_app, tmp_path, monkeypatch):
    from alicia.ui.main_window import MainWindow

    monkeypatch.chdir(tmp_path)
    settings = load_settings(environ={"ALICE_AI_PROVIDER": "fake"})
    speaker = FakeSpeaker(settings.voice)
    window = MainWindow(build_services(settings, demo=True, model=FakeModel(), speaker=speaker))
    window._devices = lambda output: ["Casque G Pro"] if output else ["Microphone fifine"]
    window.settings_page._input_devices = lambda: ["Microphone fifine"]
    window.settings_page._output_devices = lambda: ["Casque G Pro"]
    window.show_page(2)
    page = window.settings_page
    assert window.pages.currentWidget() is page
    assert page.input_box.findData("Microphone fifine") > 0

    page.input_box.setCurrentIndex(page.input_box.findData("Microphone fifine"))
    page.output_box.setCurrentIndex(page.output_box.findData("Casque G Pro"))
    page.engine_box.setCurrentIndex(page.engine_box.findData("kokoro"))
    page.sensitivity.setValue(2)
    page.speed.setValue(20)
    page.speed.sliderReleased.emit()
    page.mode_box.setCurrentIndex(page.mode_box.findData("full"))

    voice = window.services.settings.voice
    assert voice.input_device == "Microphone fifine" and voice.output_device == "Casque G Pro"
    assert voice.tts_engine == "kokoro" and voice.wake_sensitivity == 2
    assert voice.tts_rate == "+20%" and voice.kokoro_speed == 1.2
    assert window.services.recorder.device == "Microphone fifine"
    assert window.engine_box.currentData() == "kokoro"
    assert speaker.settings.tts_engine == "kokoro"

    saved = tomllib.loads((data_dir() / "alicia.toml").read_text("utf-8"))
    assert saved["voice"]["input_device"] == "Microphone fifine"
    assert saved["voice"]["wake_sensitivity"] == 2
    assert saved["ui"]["mode"] == "full"
    reloaded = load_settings()
    assert reloaded.voice.tts_engine == "kokoro" and reloaded.ui_mode == "full"

    window.test_voice()
    assert speaker.said and "Alicia" in speaker.said[-1]
    window.close()
