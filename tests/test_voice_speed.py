import pytest

from alicia.app import build_services
from alicia.core.ai.base import AnalysisResult, PreparedAudio
from alicia.core.audio.text import split_sentences
from alicia.core.capture.backends import DEMO_WINDOW
from alicia.core.config import load_settings
from alicia.core.errors import ProviderError, ProviderErrorKind

AUDIO = PreparedAudio(b"RIFF....", "audio/wav", 1.8)


class GeminiLike:
    provider, model = "gemini", "gemini-flash-latest"

    def __init__(self):
        self.requests = []

    def check(self):
        return None

    def analyze(self, request, on_delta=None, cancel=None):
        self.requests.append(request)
        return AnalysisResult("Réponse.", self.provider, self.model, 1)


class Says:
    def __init__(self, text, fail=False):
        self.text, self.fail, self.calls = text, fail, 0

    def transcribe(self, audio):
        self.calls += 1
        if self.fail:
            raise ProviderError(ProviderErrorKind.UNAVAILABLE, "réseau coupé")
        return self.text


def _services(model):
    services = build_services(
        load_settings(environ={"ALICE_AI_PROVIDER": "fake"}), demo=True, model=model
    )
    services.analysis.stt = "gemini"
    return services


def test_gemini_transcribes_then_commands_still_work():
    model = GeminiLike()
    services = _services(model)
    local = Says("ne doit pas servir")
    cloud = Says("Lance YouTube")
    services.analysis.transcriber = local
    services.analysis.cloud_transcriber = cloud
    outcome = services.analysis.analyze(DEMO_WINDOW, "", audio=AUDIO)
    assert cloud.calls == 1 and local.calls == 0
    assert outcome.action is not None and outcome.action.intent == "launch"
    assert model.requests == []  # commande : aucune réponse IA nécessaire


def test_whisper_takes_over_when_gemini_transcription_fails():
    model = GeminiLike()
    services = _services(model)
    services.analysis.transcriber = Says("Quel objet pour Ashe ?")
    services.analysis.cloud_transcriber = Says("", fail=True)
    outcome = services.analysis.analyze(DEMO_WINDOW, "", audio=AUDIO)
    assert outcome.transcript.startswith("Quel objet pour Ashe")
    assert model.requests and model.requests[0].audio is None  # la question part en texte


def test_whisper_is_used_with_other_providers():
    services = _services(None)  # IA factice (pas Gemini)
    assert services.analysis.local_stt()


def test_why_questions_stay_on_the_fast_brain():
    from alicia.core.ai.factory import deep_reason

    assert deep_reason("Pourquoi tu m'écoutes ?") is None
    assert deep_reason("Quelle est la meilleure stratégie ici ?") is not None


@pytest.mark.parametrize(
    "text",
    [
        "Garde-le pour l'instant, je veux le comparer avec ton équipement actuel avant de "
        "décider quoi en faire. Ensuite on verra.",
    ],
)
def test_first_sentence_is_short_so_the_voice_starts_sooner(text):
    parts = split_sentences(text)
    assert len(parts[0]) <= 90 and parts[0].endswith(",")
    assert " ".join(parts).replace(" ,", ",").startswith("Garde-le")


def test_openai_users_get_openai_transcription(monkeypatch):
    import httpx

    from alicia.core.ai.base import PreparedAudio
    from alicia.core.audio.stt import OpenAITranscriber
    from alicia.core.config import load_settings

    settings = load_settings(environ={"ALICE_AI_PROVIDER": "openai", "OPENAI_API_KEY": "sk-x"})
    sent = {}

    class Reply:
        status_code = 200
        text = ""

        def json(self):
            return {"text": "C'est ton incapacité à m'aider, tocard."}

    def post(url, headers, data, files, timeout):
        sent.update(url=url, data=data, auth=headers["Authorization"])
        return Reply()

    monkeypatch.setattr(httpx, "post", post)
    transcriber = OpenAITranscriber(settings.ai)
    transcriber.hint = "PRAGMATA"
    text = transcriber.transcribe(PreparedAudio(b"RIFF", "audio/wav", 1.0))
    assert text.endswith("tocard.")
    assert sent["url"].endswith("/audio/transcriptions")
    assert sent["data"]["model"] == "gpt-4o-mini-transcribe" and sent["data"]["language"] == "fr"
    assert "PRAGMATA" in sent["data"]["prompt"]
