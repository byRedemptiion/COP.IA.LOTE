import numpy as np
import pytest

from alicia.core.capture.backends import DEMO_WINDOW, DemoBackend
from alicia.core.capture.models import Rect, WindowInfo, image_from_bgra, is_black
from alicia.core.capture.service import CaptureService
from alicia.core.errors import CaptureError


def bgra(color, size=(40, 60)):
    b, g, r = color
    pixels = np.zeros(size + (4,), dtype=np.uint8)
    pixels[:, :] = (b, g, r, 255)
    return pixels


class StubBackend:
    def __init__(self, name, result):
        self.name = name
        self.result = result
        self.calls = 0

    def grab(self, window):
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def service(*backends):
    return CaptureService(lambda: [DEMO_WINDOW], lambda w: w, lambda w: list(backends))


def test_black_detection():
    assert is_black(bgra((0, 0, 0)))
    assert is_black(bgra((3, 3, 3)))
    assert not is_black(bgra((0, 0, 200)))


def test_bgra_is_converted_to_rgb():
    image = image_from_bgra(bgra((10, 20, 200)))
    assert image.mode == "RGB"
    assert image.getpixel((0, 0)) == (200, 20, 10)


def test_first_working_backend_is_used():
    first = StubBackend("wgc-window", bgra((0, 0, 255)))
    second = StubBackend("printwindow", bgra((255, 0, 0)))
    frame = service(first, second).capture(DEMO_WINDOW)
    assert frame.backend == "wgc-window"
    assert frame.notes == ()
    assert second.calls == 0


def test_black_image_falls_back_and_says_so():
    black = StubBackend("wgc-window", bgra((0, 0, 0)))
    monitor = StubBackend("wgc-monitor", bgra((0, 255, 0)))
    frame = service(black, monitor).capture(DEMO_WINDOW)
    assert frame.backend == "wgc-monitor"
    assert "image noire" in frame.notes[0]


def test_error_falls_back_then_reports_every_attempt():
    failing = StubBackend("wgc-window", CaptureError("refus", detail="E_ACCESSDENIED"))
    black = StubBackend("printwindow", bgra((0, 0, 0)))
    with pytest.raises(CaptureError) as info:
        service(failing, black).capture(DEMO_WINDOW)
    assert "E_ACCESSDENIED" in info.value.detail
    assert "printwindow: image noire" in info.value.detail


def test_recent_frames_are_bounded():
    svc = CaptureService(lambda: [], lambda w: w, lambda w: [DemoBackend()], keep_last=2)
    for _ in range(3):
        svc.capture(DEMO_WINDOW)
    assert len(svc.recent) == 2
    assert svc.last is svc.recent[-1]


def test_fullscreen_detection():
    monitor = Rect(0, 0, 1920, 1080)
    full = WindowInfo(1, "Overwatch", 2, rect=Rect(0, 0, 1920, 1080), monitor_rect=monitor)
    windowed = WindowInfo(1, "Overwatch", 2, rect=Rect(100, 100, 1380, 820), monitor_rect=monitor)
    assert full.fullscreen
    assert not windowed.fullscreen


def test_windows_capture_refuses_other_platforms(monkeypatch):
    import sys

    from alicia.core.capture.win32 import Win32
    from alicia.core.errors import UnsupportedPlatformError

    if sys.platform == "win32":
        pytest.skip("test des plateformes non Windows")
    with pytest.raises(UnsupportedPlatformError):
        Win32()


def test_screen_and_cursor_vision_modes():
    from alicia.core.capture.models import Rect

    screen = Rect(0, 0, 1280, 720)
    svc = CaptureService(
        lambda: [DEMO_WINDOW],
        lambda w: w,
        lambda w: [DemoBackend()],
        cursor=lambda: (1200, 50, 1, screen),
        screen_chain=lambda w: [DemoBackend()],
    )
    whole = svc.capture(None, "screen")
    assert whole.mode == "screen"
    assert (whole.width, whole.height) == (1280, 720) and whole.cursor == (1200, 50)

    zone = svc.capture(None, "cursor", (400, 300))
    assert (zone.width, zone.height) == (400, 300)
    # Zone collée au bord : le curseur reste dedans, marqué en rose
    assert zone.cursor == (400 - (1280 - 1200), 50)
    r, g, b = zone.image.getpixel((zone.cursor[0] + 2, zone.cursor[1]))
    assert r > 200 and g < 120  # trait rose du marqueur
    assert svc.last is zone


def test_application_mode_needs_a_window():
    with pytest.raises(CaptureError):
        service(DemoBackend()).capture(None, "window")


def test_live_capture_keeps_a_fresh_frame_in_memory():
    import time

    from alicia.core.capture.live import LiveCapture

    svc = CaptureService.demo()
    live = LiveCapture(svc.capture, lambda: (DEMO_WINDOW, "window", (800, 500)), interval_s=0.3)
    assert live.fresh() is None
    live.start()
    deadline = time.monotonic() + 3
    while live.frames < 2 and time.monotonic() < deadline:
        time.sleep(0.05)
    live.stop()
    assert live.frames >= 2 and live.fresh() is not None
    assert not live.running


def test_live_capture_waits_for_a_window_in_application_mode():
    from alicia.core.capture.live import LiveCapture

    live = LiveCapture(CaptureService.demo().capture, lambda: (None, "window", (800, 500)))
    assert live.grab_once() is None and live.latest is None


def test_game_memory_keeps_dated_images_and_cleans_up(tmp_path):
    from datetime import UTC, datetime, timedelta

    from alicia.core.capture.timeline import Timeline

    svc = CaptureService.demo()
    timeline = Timeline(tmp_path / "memoire", interval_s=30, retention_h=20, max_images=3)
    frame = svc.capture(DEMO_WINDOW)
    assert timeline.add(frame) is not None
    assert timeline.add(frame) is None  # moins de 30 s : pas de nouvelle image
    now = datetime.now(UTC)
    for hours in (1, 2, 25):  # une image trop vieille (25 h)
        old = replace_time(frame, now - timedelta(hours=hours))
        timeline.add(old, force=True)
    assert timeline.usage()[0] == 4
    assert timeline.cleanup(now) == 1  # la plus vieille (25 h), qui dépassait aussi 3 images
    times = [when for when, _ in timeline.entries()]
    assert len(times) == 3 and min(times) > now - timedelta(hours=20)
    near = timeline.near(now - timedelta(hours=1), count=1)
    assert abs((near[0][0] - (now - timedelta(hours=1))).total_seconds()) < 5
    timeline.max_bytes = 1  # place maximale dépassée : on efface les plus anciennes
    assert timeline.cleanup(now) >= 1


def replace_time(frame, when):
    from dataclasses import replace

    return replace(frame, captured_at=when)


@pytest.mark.parametrize(
    ("question", "minutes"),
    [
        ("Il y a une heure, j'avais quel objet ?", 60),
        ("c'était quoi le boss il y a 20 minutes", 20),
        ("il y a 2h on était où", 120),
        ("tout à l'heure tu as vu ma barre de sorts ?", 20),
        ("il y a une heure et demie", 90),
    ],
)
def test_past_moments_are_understood(question, minutes):
    from datetime import datetime, timedelta

    from alicia.core.capture.timeline import find_past_moment

    now = datetime(2026, 10, 30, 0, 40).astimezone()
    assert find_past_moment(question, now) == now - timedelta(minutes=minutes)


def test_clock_time_and_no_past():
    from datetime import datetime

    from alicia.core.capture.timeline import find_past_moment

    now = datetime(2026, 10, 30, 0, 40).astimezone()
    moment = find_past_moment("qu'est-ce que j'avais à 23h15 ?", now)
    assert (moment.day, moment.hour, moment.minute) == (29, 23, 15)
    assert find_past_moment("quel objet je prends ?", now) is None


def test_live_capture_on_demand_and_quiet():
    import time

    from alicia.core.capture.live import LiveCapture

    calls = []

    def capture(window, mode, box):
        from alicia.core.capture.service import _ok_level

        calls.append(_ok_level())
        from datetime import UTC, datetime

        from PIL import Image

        from alicia.core.capture.models import Frame

        return Frame(
            image=Image.new("RGB", (4, 4)),
            window=None,
            backend="test",
            captured_at=datetime.now(UTC),
            duration_ms=1,
            capture_id="x",
        )

    live = LiveCapture(capture, lambda: (None, "screen", (10, 10)), interval_s=30)
    live.start()
    try:
        assert live.since(0.0, wait_s=2.0) is not None  # 1re capture au démarrage
        first = len(calls)
        time.sleep(0.4)
        assert len(calls) == first  # pas de capture continue
        mark = live.trigger()
        assert live.since(mark, wait_s=2.0) is not None  # capture dès que tu parles
        assert len(calls) == first + 1
        assert all(level == 10 for level in calls)  # DEBUG : pas une ligne par capture
    finally:
        live.stop()
