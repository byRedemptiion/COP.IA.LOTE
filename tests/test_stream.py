import json
import socket
import urllib.error
import urllib.request

import pytest

from alicia.core.config import twitch_channel, twitch_chat_url
from alicia.stream.overlay import OverlayServer


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.mark.parametrize(
    ("text", "channel"),
    [
        ("Nova_Jagger", "nova_jagger"),
        ("https://www.twitch.tv/nova_jagger", "nova_jagger"),
        ("https://www.twitch.tv/popout/nova_jagger/chat?popout=", "nova_jagger"),
        ("@nova_jagger", "nova_jagger"),
        ("ab", ""),
        ("nova jagger", ""),
        ("", ""),
    ],
)
def test_twitch_channel(text, channel):
    assert twitch_channel(text) == channel


def test_twitch_chat_url():
    assert twitch_chat_url("nova_jagger") == "https://www.twitch.tv/popout/nova_jagger/chat?popout="


def _events(server, count, timeout=3.0):
    """Lit ``count`` messages du flux /events."""
    response = urllib.request.urlopen(server.url.replace("/overlay", "/events"), timeout=timeout)
    messages = []
    while len(messages) < count:
        line = response.readline().decode().strip()
        if line.startswith("data: "):
            messages.append(json.loads(line[6:]))
    response.close()
    return messages


def test_overlay_serves_page_portrait_and_events(tmp_path):
    (tmp_path / "idle.webm").write_bytes(b"webm")
    (tmp_path.parent / "secret.txt").write_text("non")
    server = OverlayServer(
        _free_port(),
        lambda: {"name": "VERIS", "anims": ["idle.webm"]},
        lambda: b"\x89PNG",
        tmp_path,
    )
    assert server.start()
    try:
        page = urllib.request.urlopen(server.url, timeout=3).read().decode()
        assert '"name": "VERIS"' in page and "EventSource" in page
        base = server.url.removesuffix("/overlay")
        assert urllib.request.urlopen(base + "/portrait", timeout=3).read() == b"\x89PNG"
        assert urllib.request.urlopen(base + "/anim/idle.webm", timeout=3).read() == b"webm"
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(base + "/anim/..%2Fsecret.txt", timeout=3)

        server.publish("state", state="thinking")
        server.publish("text", question="quel objet ?", text="Prends l'épée.")
        server.publish("level", value=0.5)  # pas rejoué aux nouvelles pages
        replay = _events(server, 2)
        assert replay[0] == {"type": "state", "state": "thinking"}
        assert replay[1]["text"] == "Prends l'épée."
    finally:
        server.stop()
    assert not server.running


def test_overlay_uses_next_port_when_busy():
    port = _free_port()
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", port))
        busy.listen()
        server = OverlayServer(port)
        assert server.start()
        try:
            assert server.port != port
        finally:
            server.stop()


def test_main_window_mirrors_bubble_and_state_to_overlay(qt_app, tmp_path, monkeypatch):
    from alicia.app import build_services
    from alicia.core.config import load_settings
    from alicia.ui.main_window import MainWindow

    monkeypatch.chdir(tmp_path)
    settings = load_settings(environ={"ALICE_AI_PROVIDER": "fake"})
    window = MainWindow(build_services(settings, demo=True))
    from dataclasses import replace

    stream = replace(settings.stream, overlay_port=_free_port())
    window.services.settings = replace(window.services.settings, stream=stream)
    window.set_overlay(True, save=False)
    try:
        assert window.overlay is not None and window.overlay.running
        assert window.settings_page.overlay_url.text() == window.overlay.url
        sent = []
        window.overlay.publish = lambda kind, **data: sent.append((kind, data))
        window.bubble.mirror = window.overlay.publish
        window.bubble.ask("salut")
        assert sent[-1] == ("text", {"question": "salut", "text": "…"})
        window.overlay._clients.append(object())  # une page OBS est connectée
        window._core("thinking")
        window._pump_overlay()
        assert ("state", {"state": "thinking"}) in sent
        window.overlay._clients.clear()
    finally:
        window.set_overlay(False, save=False)
        window.close()
    assert window.overlay is None


def test_twitch_channel_setting_is_saved(qt_app, tmp_path, monkeypatch):
    import tomllib

    from alicia.app import build_services
    from alicia.core.config import data_dir, load_settings
    from alicia.ui.main_window import MainWindow

    monkeypatch.chdir(tmp_path)
    window = MainWindow(
        build_services(load_settings(environ={"ALICE_AI_PROVIDER": "fake"}), demo=True)
    )
    opened = []
    monkeypatch.setattr(
        "PySide6.QtGui.QDesktopServices.openUrl", lambda url: opened.append(url.toString())
    )
    window.settings_page.twitch_input.setText("https://www.twitch.tv/Nova_Jagger")
    window.settings_page.twitch_input.editingFinished.emit()
    assert window.services.settings.stream.twitch_channel == "nova_jagger"
    saved = tomllib.loads((data_dir() / "alicia.toml").read_text("utf-8"))
    assert saved["stream"]["twitch_channel"] == "nova_jagger"
    window.orb.twitch_requested.emit()
    assert opened == ["https://www.twitch.tv/popout/nova_jagger/chat?popout="]
    window.close()


def test_overlay_serves_the_voice_for_obs():
    import numpy as np

    server = OverlayServer(_free_port())
    assert server.start()
    try:
        clip = server.publish_audio(np.zeros(2400, np.int16))
        base = server.url.removesuffix("/overlay")
        data = urllib.request.urlopen(f"{base}/audio/{clip}.wav", timeout=3).read()
        assert data[:4] == b"RIFF" and len(data) == 44 + 4800
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(f"{base}/audio/999.wav", timeout=3)
        page = urllib.request.urlopen(server.url, timeout=3).read().decode()
        assert "queueVoice" in page
    finally:
        server.stop()


def test_speaker_copies_each_sentence_for_obs_except_headset_only():
    import time

    import numpy as np

    from alicia.core.audio.speaker import Speaker
    from alicia.core.config import VoiceSettings
    from tests.test_voice import FakePlayer

    copies = []
    speaker = Speaker(
        VoiceSettings(), synthesizer=lambda t: np.zeros(50, np.int16), player=FakePlayer()
    )
    speaker.on_audio = lambda samples: copies.append(len(samples))
    speaker.speak("Première phrase assez longue. Deuxième phrase assez longue.")
    speaker._thread.join(3)
    assert copies == [50, 50]

    class DevicePlayer(FakePlayer):
        def open(self, device=None):
            return object()

    speaker.player = DevicePlayer()
    speaker.speak("Une phrase pour le casque seulement.", device="Casque")
    speaker._thread.join(3)
    time.sleep(0.05)
    assert copies == [50, 50]  # « casque seul » : pas envoyé à OBS
