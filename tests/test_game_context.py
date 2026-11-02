import httpx

from alicia.app import build_services
from alicia.core.ai.local_search import best_passages, page_text, search_sources
from alicia.core.capture.models import Rect, WindowInfo
from alicia.core.config import load_settings

SCREEN = Rect(0, 0, 2560, 1440)


def _window(title, exe, fullscreen=True):
    rect = SCREEN if fullscreen else Rect(10, 10, 800, 600)
    return WindowInfo(5, title, 9, exe_name=exe, rect=rect, monitor_index=1, monitor_rect=SCREEN)


def test_game_is_remembered_when_asking_from_the_desktop():
    services = build_services(load_settings(environ={"ALICE_AI_PROVIDER": "fake"}), demo=True)
    analysis = services.analysis
    profile, note = analysis.game_for(None)
    assert profile.key == "generic" and "Aucun jeu" in note

    analysis.note_window(_window("Overwatch", "Overwatch.exe"))
    profile, note = analysis.game_for(None)  # question posée depuis COP'IA'LOTE
    assert profile.key == "overwatch" and "il jouait à ce jeu" in note

    # Jeu sans profil, en plein écran : l'IA reçoit son titre pour le reconnaître
    profile, note = analysis.game_for(_window("Rainbow Six", "RainbowSix.exe"))
    assert profile.key == "generic" and "Rainbow Six" in note and "RainbowSix.exe" in note
    profile, note = analysis.game_for(None)
    assert "Rainbow Six" in note

    # Une fenêtre ordinaire (navigateur) ne remplace pas le jeu en cours
    analysis.note_window(_window("Firefox", "firefox.exe", fullscreen=False))
    assert analysis.last_game[1].exe_name == "RainbowSix.exe"


def test_local_search_only_reads_reference_sites():
    fetched = []

    def handler(request):
        url = str(request.url)
        if "duckduckgo" in url:
            assert b"site%3Amobalytics.gg%2Foverwatch" in request.content
            links = (
                '<a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg='
                'https%3A%2F%2Fmobalytics.gg%2Foverwatch%2Fheroes%2Fana">Ana build</a>'
                '<a class="result__a" href="https://evil.example.com/ana">Pub</a>'
            )
            return httpx.Response(200, text=links)
        fetched.append(url)
        body = (
            "<html><title>Ana — build Stadium</title><script>x()</script><nav>Menu</nav>"
            "<p>Ana soigne à distance avec son fusil biotique et sa grenade.</p>"
            "<p>Pour le Stadium, le meilleur build Ana prend Grenade biotique améliorée.</p>"
            "</html>"
        )
        return httpx.Response(200, text=body, headers={"content-type": "text/html"})

    pages = search_sources(
        "meilleur build Ana Stadium",
        ("mobalytics.gg/overwatch",),
        "Overwatch",
        transport=httpx.MockTransport(handler),
    )
    assert fetched == ["https://mobalytics.gg/overwatch/heroes/ana"]
    assert len(pages) == 1 and "meilleur build Ana" in pages[0].text
    assert "Menu" not in pages[0].text and "x()" not in pages[0].text


def test_local_search_never_raises():
    def down(request):
        raise httpx.ConnectError("hors ligne")

    assert search_sources("build", ("wowhead.com",), transport=httpx.MockTransport(down)) == []
    assert search_sources("build", ()) == []


def test_page_text_and_passages():
    title, text = page_text(
        "<title>T</title><p>Ligne sans intérêt pour la question posée.</p>"
        "<p>La grenade biotique de Ana bloque les soins adverses.</p>"
    )
    assert title == "T"
    assert best_passages(text, ["grenade"], limit=60).startswith("La grenade")


def test_ollama_gets_reference_site_extracts(monkeypatch):
    from alicia.core.ai import local_search
    from alicia.core.ai.local_search import Page
    from alicia.core.capture.backends import DEMO_WINDOW

    class OllamaLike:
        provider, model = "ollama", "qwen2.5vl:7b"

        def __init__(self):
            self.requests = []

        def check(self):
            return None

        def analyze(self, request, on_delta=None, cancel=None):
            from alicia.core.ai.base import AnalysisResult

            self.requests.append(request)
            return AnalysisResult("Prends la grenade.", self.provider, self.model, 1)

    monkeypatch.setattr(
        local_search,
        "search_sources",
        lambda q, sources, game: [Page("https://mobalytics.gg/overwatch/ana", "Ana", "Grenade.")],
    )
    model = OllamaLike()
    services = build_services(
        load_settings(environ={"ALICE_AI_PROVIDER": "fake"}), demo=True, model=model
    )
    services.analysis.game_profile = "overwatch"
    outcome = services.analysis.analyze(DEMO_WINDOW, "Meilleur build Ana ?", web_search=True)
    assert "<extraits>" in model.requests[0].system_prompt
    assert outcome.result.sources[0].url == "https://mobalytics.gg/overwatch/ana"
