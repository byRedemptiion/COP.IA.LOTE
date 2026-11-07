import time
from types import SimpleNamespace

from alicia.stream.tiktok import TikTokChat, gift_event, tiktok_user
from alicia.stream.twitch_events import thank_line


def test_tiktok_user_is_cleaned():
    assert tiktok_user("@Nova.Jagger") == "nova.jagger"
    assert tiktok_user("https://www.tiktok.com/@redem_tv/live") == "redem_tv"
    assert tiktok_user("pas un pseudo !") == ""


def test_gifts_are_thanked_once_per_combo():
    user = SimpleNamespace(nickname="Bob", unique_id="bob")
    rose = SimpleNamespace(name="Rose")
    combo = SimpleNamespace(streaking=True, gift=rose, repeat_count=3, user=user)
    assert gift_event(combo) is None  # combo en cours : pas encore
    done = SimpleNamespace(streaking=False, gift=rose, repeat_count=5, user=user)
    event = gift_event(done)
    assert (event.kind, event.user, event.amount, event.message) == (
        "tiktok_gift",
        "Bob",
        5,
        "Rose",
    )
    line = thank_line(event)
    assert "Bob" in line and "5 × Rose" in line
    assert "Rose" in thank_line(gift_event(SimpleNamespace(gift=rose, repeat_count=1, user=user)))


def test_live_events_reach_the_robot(monkeypatch):
    import TikTokLive
    from TikTokLive.events import CommentEvent, ConnectEvent, FollowEvent, GiftEvent

    class FakeClient:
        def __init__(self, unique_id):
            assert unique_id == "@redem_tv"
            self.handlers = {}

        def add_listener(self, kind, f):
            self.handlers[kind] = f

        async def connect(self, **_kw):
            bob = SimpleNamespace(nickname="Bob")
            await self.handlers[ConnectEvent](None)
            await self.handlers[CommentEvent](SimpleNamespace(comment="viirus salut !", user=bob))
            await self.handlers[FollowEvent](SimpleNamespace(user=bob))
            gift = SimpleNamespace(
                streaking=False, gift=SimpleNamespace(name="Lion"), repeat_count=1
            )
            await self.handlers[GiftEvent](SimpleNamespace(**vars(gift), user=bob))
            chat.stop()

        async def disconnect(self):
            pass

    monkeypatch.setattr(TikTokLive, "TikTokLiveClient", FakeClient)
    messages, events, states = [], [], []
    chat = TikTokChat("@Redem_TV", messages.append, events.append)
    chat.on_status = states.append
    chat.start()
    deadline = time.monotonic() + 5
    while chat._thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert [(m.user, m.text, m.platform) for m in messages] == [("Bob", "viirus salut !", "tiktok")]
    assert [(e.kind, e.message) for e in events] == [("follow", ""), ("tiktok_gift", "Lion")]
    assert "connecté" in states


def test_stream_mode_reads_tiktok_without_twitch(qt_app, tmp_path, monkeypatch):
    from alicia.app import build_services
    from alicia.core.config import load_settings
    from alicia.stream import tiktok
    from alicia.ui.main_window import MainWindow

    monkeypatch.chdir(tmp_path)
    started = []
    monkeypatch.setattr(tiktok.TikTokChat, "start", lambda self: started.append(self.user))
    monkeypatch.setattr(tiktok.TikTokChat, "stop", lambda self: None)
    window = MainWindow(
        build_services(load_settings(environ={"ALICE_AI_PROVIDER": "fake"}), demo=True)
    )
    try:
        window.change_setting("tiktok_user", "@Redem_TV")
        assert window.services.settings.stream.tiktok_user == "redem_tv"
        assert load_settings().stream.tiktok_user == "redem_tv"  # gardé
        window.set_stream_mode(True, save=False)
        assert window.stream_mode.enabled and started == ["redem_tv"]
        assert window.stream_mode.chat is None  # pas de chaîne Twitch : TikTok seul
        from alicia.stream.chat import ChatMessage

        name = window.stream_mode.gate.names[0]
        window.stream_mode._received(
            ChatMessage("Bob", f"{name} salut", time.monotonic(), platform="tiktok")
        )
        assert window.stream_mode.gate.kept == 1
        window.set_stream_mode(False, save=False)
        assert not window.stream_mode.enabled
    finally:
        window.close()


def test_viewer_names_are_readable_and_never_the_message():
    from alicia.stream.chat import ChatMessage, chat_question
    from alicia.stream.tiktok import _who

    assert _who(SimpleNamespace(nickname="𝓝𝓸𝓿𝓪 ✨", unique_id="nova.j")) == "Nova"
    assert _who(SimpleNamespace(nickname="🔥🔥", unique_id="redem.tv")) == "redem.tv"
    question = chat_question(ChatMessage("Bob", "viirus tu joues à quoi", 0.0), True)
    assert "Pseudo du spectateur : Bob" in question and "PAS un pseudo" in question
    unnamed = chat_question(ChatMessage("🔥", "salut", 0.0), True)
    assert "ne dis aucun pseudo" in unnamed
