import httpx

from alicia.app import build_services
from alicia.core.ai.base import AnalysisResult, Source
from alicia.core.capture.backends import DEMO_WINDOW
from alicia.core.config import load_settings
from alicia.core.guide import (
    fetch_preview,
    parse_guide_command,
    pick_source,
    take_markers,
)


def _png() -> bytes:
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 40, 120)).save(buffer, "PNG")
    return buffer.getvalue()


PNG = _png()


def test_markers_are_removed_from_the_answer():
    assert take_markers("Va voir le PNJ au nord.\n[OUVRIR] [image]") == (
        "Va voir le PNJ au nord.",
        True,
        True,
    )
    assert take_markers("Rien à ouvrir.") == ("Rien à ouvrir.", False, False)


def test_voice_commands():
    assert parse_guide_command("Ouvre le guide") == "open"
    assert parse_guide_command("Viirus, ouvre-moi la page") == "open"
    assert parse_guide_command("montre-moi la carte") == "image"
    assert parse_guide_command("affiche l'emplacement") == "image"
    assert parse_guide_command("ouvre l'inventaire") is None
    assert parse_guide_command("ferme l'image") == "close"
    assert parse_guide_command("Viirus, enlève-moi la carte") == "close"
    assert parse_guide_command("Pardon, je vois encore l'image que tu m'as montrée.") == "close"
    assert parse_guide_command("cache cette fenêtre") == "close"
    assert parse_guide_command("ferme la porte du fond") is None
    assert parse_guide_command("comment je fais la quête du guide de la forêt sombre ?") is None


def test_pick_source_prefers_reference_sites():
    sources = [Source("reddit.com", "https://r.example/1"), Source("wowhead.com", "https://g/2")]
    assert pick_source(sources, ("wowhead.com/classic",)).url == "https://g/2"
    assert pick_source(sources).url == "https://r.example/1"
    assert pick_source([Source("x", "javascript:alert(1)")]) is None


def test_fetch_preview_follows_redirect_and_reads_og_image():
    def handler(request):
        url = str(request.url)
        if "redirect" in url:
            return httpx.Response(302, headers={"location": "https://www.wowhead.com/quest=1"})
        if url.endswith("quest=1"):
            return httpx.Response(
                200,
                text='<title>Quête 1</title><meta property="og:image" content="/map.png">',
                headers={"content-type": "text/html"},
            )
        if url.endswith("/map.png"):
            return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})
        return httpx.Response(404)

    preview = fetch_preview(
        "https://vertexaisearch.example/redirect/abc", transport=httpx.MockTransport(handler)
    )
    assert preview is not None and preview.image == PNG
    assert preview.url == "https://www.wowhead.com/quest=1" and preview.title == "Quête 1"
    assert preview.image_url == "https://www.wowhead.com/map.png"


def test_fetch_preview_without_image_or_network():
    no_image = httpx.MockTransport(lambda r: httpx.Response(200, text="<title>x</title>"))
    assert fetch_preview("https://a.example", transport=no_image) is None

    def down(request):
        raise httpx.ConnectError("hors ligne")

    assert fetch_preview("https://a.example", transport=httpx.MockTransport(down)) is None


class GuideModel:
    provider, model = "gemini", "gemini-flash"

    def __init__(self):
        self.requests = []

    def check(self):
        return None

    def analyze(self, request, on_delta=None, cancel=None):
        self.requests.append(request)
        result = AnalysisResult("Le PNJ est au nord du camp.\n[OUVRIR]\n[IMAGE]", "gemini", "f", 1)
        result.sources = [Source("wowhead.com", "https://www.wowhead.com/quest=1")]
        return result


def test_window_opens_guide_and_image_when_the_ai_asks(qt_app, tmp_path, monkeypatch):
    from alicia.ui.main_window import MainWindow
    from tests.test_duo import _wait

    monkeypatch.chdir(tmp_path)
    model = GuideModel()
    settings = load_settings(environ={"ALICE_AI_PROVIDER": "fake"})
    window = MainWindow(build_services(settings, demo=True, model=model))
    opened, shown = [], []
    monkeypatch.setattr("alicia.core.guide.fetch_preview", lambda url: shown.append(url) or None)
    real_open = window.open_guide
    window.open_guide = lambda auto=False: opened.append(auto) or real_open(auto)
    window._say = lambda text: True
    try:
        outcome = window.services.analysis.analyze(DEMO_WINDOW, "Où est le PNJ ?", web_search=True)
        assert "Pages et images" in model.requests[0].system_prompt
        assert outcome.result.text == "Le PNJ est au nord du camp."  # repères retirés
        window._analysis_done(outcome)
        assert opened == [True] and window.guide_row.isVisibleTo(window)
        _wait(qt_app, lambda: shown)
        assert shown == ["https://www.wowhead.com/quest=1"]

        # « ouvre le guide » à la voix : la même page, sans IA
        reply = window.services.analysis.analyze(DEMO_WINDOW, "ouvre le guide")
        assert reply.action.intent == "guide_open"
        window._action_done(reply)
        assert opened == [True, False]

        # « ferme l'image » à la voix : le panneau se ferme vraiment
        from alicia.ui.image_panel import ImagePanel

        window.image_panel = ImagePanel()
        assert window.image_panel.show_image(_png(), "Carte", "https://g/1")
        reply = window.services.analysis.analyze(DEMO_WINDOW, "ferme l'image")
        assert reply.action.intent == "guide_close"
        window._action_done(reply)
        assert not window.image_panel.isVisible()
    finally:
        window.close()


def test_image_panel_shows_and_zooms(qt_app):
    from alicia.ui.image_panel import ImagePanel

    panel = ImagePanel()
    try:
        assert panel.show_image(PNG, "Carte de la quête", "https://www.wowhead.com/quest=1")
        assert panel.isVisible() and panel.title.text() == "Carte de la quête"
        assert not panel.show_image(b"pas une image", "x", "https://a")
    finally:
        panel.close()
