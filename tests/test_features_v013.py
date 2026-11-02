import base64
import hashlib
import json
import socket
import struct
import threading
import zipfile

import numpy as np
import pytest

from alicia.app import build_services
from alicia.core.config import load_settings


# --- 1. voix de secours Edge --------------------------------------------------------------
def test_backup_voice_is_edge_then_local(monkeypatch):
    from alicia.core.audio import speaker
    from alicia.core.audio.devices import AudioError
    from alicia.core.config import VoiceSettings

    calls = []

    def edge(voice, rate):
        def synth(text):
            calls.append(voice)
            raise AudioError("hors ligne")

        return synth

    monkeypatch.setattr(speaker, "edge_synthesizer", edge)
    monkeypatch.setattr(speaker, "_local_fallback", lambda s: lambda t: np.ones(2, np.int16))
    backup = speaker._profile_fallback(VoiceSettings(backup_voice="fr-FR-HenriNeural"))
    assert len(backup("x")) == 2 and calls == ["fr-FR-HenriNeural"]
    assert speaker._profile_fallback(VoiceSettings(backup_voice="")) is not None
    assert load_settings(environ={}).voice.backup_voice == "fr-FR-RemyMultilingualNeural"


# --- 2. compteur de consommation ------------------------------------------------------------
def test_usage_counter_counts_today(tmp_path):
    from alicia.core import usage

    usage.use_file(tmp_path / "c.json")
    usage.add("tts_gemini_38")
    usage.add("tts_gemini_38")
    usage.add("questions")
    report = dict((label, (n, limit)) for label, n, limit in usage.report())
    assert report["Voix sur mesure (Gemini 3.8 TTS)"] == (2, 100)
    assert report["Questions à l'IA"] == (1, None)
    usage.use_file(tmp_path / "c.json")  # relu depuis le disque
    assert usage.today()["tts_gemini_38"] == 2


# --- 3. sauvegarde / restauration ----------------------------------------------------------
def test_backup_never_contains_keys_and_restores(tmp_path):
    from alicia.core.backup import auto_backup, create_backup, restore_backup
    from alicia.core.config import data_dir, state_dir

    config, state = data_dir(), state_dir()
    config.mkdir(parents=True)
    (config / "alicia.toml").write_text('[voice]\ntts_engine = "edge"\n', "utf-8")
    (config / ".env").write_text("GEMINI_API_KEY=secret\n", "utf-8")
    (config / "carnet.json").write_text("{}", "utf-8")
    (state / "anims" / "viirus").mkdir(parents=True)
    (state / "anims" / "viirus" / "idle.webp").write_bytes(b"anim")
    (state / "voix_gemini.json").write_text("[]", "utf-8")
    dest = tmp_path / "save.zip"
    assert create_backup(dest) == 4
    names = zipfile.ZipFile(dest).namelist()
    assert not any(".env" in n for n in names)
    assert "state/anims/viirus/idle.webp" in names
    (state / "anims" / "viirus" / "idle.webp").unlink()  # tout effacé…
    (config / "alicia.toml").unlink()
    assert restore_backup(dest) == 4  # … et tout revient
    assert (state / "anims" / "viirus" / "idle.webp").read_bytes() == b"anim"
    assert (config / ".env").read_text("utf-8") == "GEMINI_API_KEY=secret\n"  # pas touchée
    auto = tmp_path / "auto"
    assert auto_backup(auto) is not None and auto_backup(auto) is None  # une par jour
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("config/x.toml", "x")
    with pytest.raises(ValueError):
        restore_backup(bad)


# --- 4. carnet de partie ---------------------------------------------------------------------
def test_notebook_commands_and_prompt(tmp_path):
    from alicia.core.notebook import Notebook, parse_debrief_command, parse_note_command

    assert parse_note_command("VIIRUS, retiens que je joue Ashe en support.") == (
        "add",
        "je joue Ashe en support",
    )
    assert parse_note_command("qu'est-ce que tu as noté ?") == ("list", "")
    assert parse_note_command("oublie que je joue Ashe") == ("forget", "je joue ashe")
    assert parse_note_command("Rappelle-moi dans 20 minutes de manger") is None
    assert parse_debrief_command("Fais-moi le débrief")
    assert not parse_debrief_command("où est le boss ?")
    book = Notebook(tmp_path / "carnet.json")
    book.add("overwatch", "Overwatch", "je joue Ashe en support")
    book.add("general", "", "mon prénom se dit Rédem")
    note = book.prompt_note("overwatch", "Overwatch")
    assert "Ashe" in note and "Rédem" in note
    assert book.forget("overwatch", "ashe") == 1 and book.notes("overwatch") == []


def test_window_notebook_by_voice(qt_app, tmp_path, monkeypatch):
    from alicia.core.notebook import Notebook
    from alicia.ui.main_window import MainWindow

    monkeypatch.chdir(tmp_path)
    window = MainWindow(
        build_services(load_settings(environ={"ALICE_AI_PROVIDER": "fake"}), demo=True)
    )
    try:
        assert window.notebook_action("note_add:le boss craint le feu") == "C'est noté."
        assert "craint le feu" in window.notebook_action("note_list:")
        assert Notebook().notes("general") == ["Le boss craint le feu"]
    finally:
        window.close()


# --- 5. débrief ---------------------------------------------------------------------------
def test_debrief_needs_memory_or_moments(qt_app, tmp_path, monkeypatch):
    from alicia.core.errors import AliciaError

    monkeypatch.chdir(tmp_path)
    services = build_services(load_settings(environ={"ALICE_AI_PROVIDER": "fake"}), demo=True)
    services.analysis.timeline = None
    with pytest.raises(AliciaError):
        services.analysis.debrief(60, ())
    assert services.analysis.debrief(60, ("Attention au laser !",))


# --- 6. réglages du Copilote par jeu -------------------------------------------------------
def test_copilot_settings_per_game(qt_app, tmp_path, monkeypatch):
    from dataclasses import replace

    from alicia.ui.main_window import MainWindow

    monkeypatch.chdir(tmp_path)
    window = MainWindow(
        build_services(load_settings(environ={"ALICE_AI_PROVIDER": "fake"}), demo=True)
    )
    try:
        analysis = window.services.analysis
        monkeypatch.setattr(analysis, "game_key", lambda w=None: ("overwatch", "Overwatch"))
        strict = replace(window.services.settings.copilot, threshold=9)
        window.services.settings = replace(window.services.settings, copilot=strict)
        window.copilot_game(True)  # mémorisé pour Overwatch
        window.services.settings = replace(
            window.services.settings, copilot=replace(strict, threshold=5)
        )
        window._copilot_game_key = None
        window._apply_copilot_game()
        assert window.copilot.gate.threshold == 9  # ses réglages à lui
        monkeypatch.setattr(analysis, "game_key", lambda w=None: ("general", ""))
        window._apply_copilot_game()
        assert window.copilot.gate.threshold == 5  # hors jeu : réglages généraux
    finally:
        window.close()


# --- 7. clip : OBS (obs-websocket v5) --------------------------------------------------------
def _fake_obs(password: str, replies: list) -> int:
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]

    def send(conn, data: dict) -> None:
        payload = json.dumps(data).encode()
        conn.sendall(struct.pack("!BB", 0x81, len(payload)) + payload)

    def recv(conn) -> dict:
        first, second = conn.recv(2)
        size = second & 0x7F
        if size == 126:
            (size,) = struct.unpack("!H", conn.recv(2))
        mask = conn.recv(4)
        data = b""
        while len(data) < size:
            data += conn.recv(size - len(data))
        return json.loads(bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def run() -> None:
        conn, _ = server.accept()
        request = conn.recv(4096).decode()
        key = next(line.split(": ")[1] for line in request.split("\r\n") if line.startswith("Sec-"))
        accept = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
        ).decode()
        conn.sendall(
            (
                "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                f"Connection: Upgrade\r\nSec-WebSocket-Accept: {accept}\r\n\r\n"
            ).encode()
        )
        send(conn, {"op": 0, "d": {"authentication": {"challenge": "c", "salt": "s"}}})
        identify = recv(conn)
        secret = base64.b64encode(hashlib.sha256((password + "s").encode()).digest()).decode()
        good = base64.b64encode(hashlib.sha256((secret + "c").encode()).digest()).decode()
        replies.append(identify["d"].get("authentication") == good)
        send(conn, {"op": 2, "d": {}})
        request6 = recv(conn)
        replies.append(request6["d"]["requestType"])
        send(conn, {"op": 7, "d": {"requestStatus": {"result": True, "code": 100}}})
        conn.close()
        server.close()

    threading.Thread(target=run, daemon=True).start()
    return port


def test_clip_saves_obs_replay_with_password():
    from alicia.stream.clip import parse_clip_command, save_clip

    replies: list = []
    port = _fake_obs("secret", replies)
    save_clip("obs", port, "secret")
    assert replies == [True, "SaveReplayBuffer"]
    assert parse_clip_command("VIIRUS, clip ça !")
    assert not parse_clip_command("regarde le clip")


def test_clip_reports_when_obs_is_closed():
    from alicia.stream.clip import ClipError, save_clip

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    with pytest.raises(ClipError, match="ne répond pas"):
        save_clip("obs", port, "")


# --- 8. habitués du chat ----------------------------------------------------------------------
def test_regular_viewers_are_recognised(tmp_path):
    from alicia.stream.viewers import ViewerBook

    book = ViewerBook(tmp_path / "h.json")
    book.seen("Bob", now=1000.0)
    assert "nouveau" in book.note_for("Bob", now=1000.0)
    book.topic("Bob", "tu joues quel perso ?")
    book.seen("bob", now=1000.0 + 3 * 86400)  # revient 3 jours plus tard
    note = ViewerBook(tmp_path / "h.json").note_for("Bob", now=1000.0 + 3 * 86400)
    assert "habitué" in note and "il y a 3 jours" in note and "quel perso" in note


# --- 9. réactions sur l'overlay -----------------------------------------------------------------
def test_chat_reactions_on_overlay(qt_app, tmp_path, monkeypatch):
    from alicia.stream.chat import chat_reaction
    from alicia.ui.main_window import MainWindow

    assert chat_reaction("GG WP") == ("hop", "🏆")
    assert chat_reaction("tu joues à quoi ?") is None
    monkeypatch.chdir(tmp_path)
    window = MainWindow(
        build_services(load_settings(environ={"ALICE_AI_PROVIDER": "fake"}), demo=True)
    )
    sent = []
    try:
        window.set_overlay(True, save=False)
        monkeypatch.setattr(window.overlay, "publish", lambda kind, **d: sent.append((kind, d)))
        window.chat_reaction("lol")
        window.chat_reaction("mdr")  # moins de 4 s après : ignorée
        assert sent == [("gesture", {"name": "wiggle"}), ("react", {"emoji": "😂"})]
    finally:
        window.close()
