import json
import threading

import httpx
import pytest
from PIL import Image

from alicia.core.ai.base import AnalysisRequest, PreparedImage, Turn
from alicia.core.ai.image_prep import prepare_image
from alicia.core.ai.providers.gemini import GeminiModel
from alicia.core.ai.providers.ollama import OllamaModel
from alicia.core.config import GeminiSettings, OllamaSettings, Secret
from alicia.core.errors import ProviderError, ProviderErrorKind

IMAGE = PreparedImage(b"\xff\xd8fakejpeg", "image/jpeg", 64, 32)
REQUEST = AnalysisRequest(
    question="Quel objet ?",
    images=(IMAGE,),
    system_prompt="Tu es Alicia.",
    history=(Turn("Bonjour ?", "Salut !"),),
    max_output_tokens=200,
)


def gemini(handler, key="test-key", **extra):
    settings = GeminiSettings(
        model="gemini-test", base_url="https://gemini.invalid/v1beta", api_key=Secret(key), **extra
    )
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return GeminiModel(settings, timeout_s=5, client=client)


def sse(*events):
    return "".join(f"data: {json.dumps(e)}\r\n\r\n" for e in events)


def text_event(text, **extra):
    event = {"candidates": [{"content": {"role": "model", "parts": [{"text": text}]}}]}
    event.update(extra)
    return event


def test_gemini_streams_and_builds_expected_request():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["key"] = request.headers.get("x-goog-api-key")
        seen["body"] = json.loads(request.content)
        body = sse(
            text_event("Prends "),
            {"candidates": [{"content": {"parts": [{"text": "réflexion", "thought": True}]}}]},
            text_event(
                "la lame.", usageMetadata={"promptTokenCount": 300, "candidatesTokenCount": 5}
            ),
        )
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    deltas = []
    result = gemini(handler, thinking_budget=0).analyze(REQUEST, on_delta=deltas.append)

    assert result.text == "Prends la lame."
    assert deltas == ["Prends ", "la lame."]
    assert result.input_tokens == 300 and result.output_tokens == 5
    assert result.first_token_ms is not None
    assert seen["url"].endswith("/models/gemini-test:streamGenerateContent?alt=sse")
    assert seen["key"] == "test-key"
    body = seen["body"]
    assert body["systemInstruction"]["parts"][0]["text"] == "Tu es Alicia."
    assert [c["role"] for c in body["contents"]] == ["user", "model", "user"]
    last = body["contents"][-1]["parts"]
    assert last[0]["inline_data"]["mime_type"] == "image/jpeg"
    assert last[1]["text"] == "Quel objet ?"
    assert body["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 0}


def test_gemini_without_key_explains_how_to_get_one():
    model = gemini(lambda r: httpx.Response(500), key="")
    with pytest.raises(ProviderError) as info:
        model.analyze(REQUEST)
    assert info.value.kind is ProviderErrorKind.AUTH
    assert "aistudio.google.com" in info.value.user_message


@pytest.mark.parametrize(
    ("status", "message", "kind"),
    [
        (400, "API key not valid. Please pass a valid API key.", ProviderErrorKind.AUTH),
        (403, "Permission denied", ProviderErrorKind.AUTH),
        (429, "Resource has been exhausted", ProviderErrorKind.RATE_LIMIT),
        (404, "models/gemini-test is not found", ProviderErrorKind.BAD_REQUEST),
        (503, "The model is overloaded", ProviderErrorKind.UNAVAILABLE),
    ],
)
def test_gemini_http_errors_are_normalized(status, message, kind):
    payload = {"error": {"code": status, "message": message}}
    model = gemini(lambda r: httpx.Response(status, json=payload))
    with pytest.raises(ProviderError) as info:
        model.analyze(REQUEST)
    assert info.value.kind is kind
    assert info.value.status_code == status
    assert "test-key" not in info.value.user_message + info.value.detail


def test_unavailable_is_retried_once_then_succeeds():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, json={"error": {"message": "overloaded"}})
        return httpx.Response(200, text=sse(text_event("OK")))

    assert gemini(handler).analyze(REQUEST).text == "OK"
    assert calls["n"] == 2


def test_rate_limit_is_not_retried():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(429, json={"error": {"message": "quota"}})

    with pytest.raises(ProviderError):
        gemini(handler).analyze(REQUEST)
    assert calls["n"] == 1


def test_network_failure_is_explained():
    def handler(request):
        raise httpx.ConnectError("no route", request=request)

    with pytest.raises(ProviderError) as info:
        gemini(handler).analyze(REQUEST)
    assert info.value.kind is ProviderErrorKind.UNAVAILABLE
    assert "connexion" in info.value.user_message


def test_empty_answer_due_to_max_tokens_gives_a_hint():
    event = {"candidates": [{"content": {"parts": []}, "finishReason": "MAX_TOKENS"}]}
    model = gemini(lambda r: httpx.Response(200, text=sse(event)))
    with pytest.raises(ProviderError) as info:
        model.analyze(REQUEST)
    assert "max_output_tokens" in info.value.user_message


def test_cancel_stops_the_stream():
    cancel = threading.Event()
    model = gemini(lambda r: httpx.Response(200, text=sse(text_event("a"), text_event("b"))))
    with pytest.raises(ProviderError) as info:
        model.analyze(REQUEST, on_delta=lambda t: cancel.set(), cancel=cancel)
    assert info.value.kind is ProviderErrorKind.CANCELLED


def test_gemini_list_models_keeps_generate_content_models():
    payload = {
        "models": [
            {
                "name": "models/gemini-flash-latest",
                "supportedGenerationMethods": ["generateContent"],
            },
            {"name": "models/text-embedding", "supportedGenerationMethods": ["embedContent"]},
        ]
    }
    model = gemini(lambda r: httpx.Response(200, json=payload))
    assert model.list_models() == ["gemini-flash-latest"]


def ollama(handler):
    settings = OllamaSettings(
        model="qwen2.5vl:7b", base_url="http://ollama.invalid", keep_alive="5m"
    )
    return OllamaModel(
        settings, timeout_s=5, client=httpx.Client(transport=httpx.MockTransport(handler))
    )


def test_ollama_streams_ndjson():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        lines = [
            {"message": {"content": "Le "}, "done": False},
            {"message": {"content": "bouclier."}, "done": False},
            {
                "message": {"content": ""},
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 50,
                "eval_count": 3,
            },
        ]
        return httpx.Response(200, text="\n".join(json.dumps(x) for x in lines))

    result = ollama(handler).analyze(REQUEST)
    assert result.text == "Le bouclier."
    assert result.output_tokens == 3
    messages = seen["body"]["messages"]
    assert messages[0]["role"] == "system"
    assert messages[-1]["images"]
    assert seen["body"]["stream"] is True


def test_ollama_not_running_is_explained():
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(ProviderError) as info:
        ollama(handler).analyze(REQUEST)
    assert "Ollama ne répond pas" in info.value.user_message


def test_image_is_resized_and_jpeg_encoded():
    prepared = prepare_image(Image.new("RGB", (3840, 2160), (10, 20, 30)), max_side=1568)
    assert (prepared.width, prepared.height) == (1568, 882)
    assert prepared.mime_type == "image/jpeg"
    assert prepared.data[:2] == b"\xff\xd8"


def test_small_image_is_not_upscaled():
    prepared = prepare_image(Image.new("RGB", (800, 600)), max_side=1568)
    assert (prepared.width, prepared.height) == (800, 600)


def test_thinking_config_rejected_is_dropped_once_and_logged():
    bodies = []

    def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        if "thinkingConfig" in body["generationConfig"]:
            return httpx.Response(
                400, json={"error": {"message": "thinking_level is not supported by this model"}}
            )
        return httpx.Response(200, text=sse(text_event("OK")))

    model = gemini(handler, thinking_level="low")
    assert model.analyze(REQUEST).text == "OK"
    assert model.analyze(REQUEST).text == "OK"
    assert len(bodies) == 3  # un refus, puis deux appels sans réglage


def test_silent_model_timeout_is_not_retried_and_says_where():
    calls = {"n": 0}

    class Silent(httpx.SyncByteStream):
        def __iter__(self):
            raise httpx.ReadTimeout("The read operation timed out")
            yield b""

    def handler(request):
        calls["n"] += 1
        return httpx.Response(200, stream=Silent())

    with pytest.raises(ProviderError) as info:
        gemini(handler).analyze(REQUEST)
    assert info.value.kind is ProviderErrorKind.TIMEOUT
    assert "premier mot" in info.value.user_message
    assert calls["n"] == 1


def test_overloaded_model_falls_back_to_next_and_says_so():
    seen = []

    def handler(request):
        seen.append(request.url.path)
        if "gemini-test:" in request.url.path:
            return httpx.Response(503, json={"error": {"message": "high demand"}})
        return httpx.Response(200, text=sse(text_event("Prends la lame.")))

    model = gemini(handler, fallback_models=("gemini-lite",))
    result = model.analyze(REQUEST)
    assert result.text == "Prends la lame."
    assert result.model == "gemini-lite"
    assert result.extra["fallback_from"] == "gemini-test"
    assert model.model == "gemini-test"  # le modèle principal reste la référence
    assert len(seen) == 2  # pas de nouvel essai sur le modèle saturé


def test_auth_error_does_not_fall_back():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(403, json={"error": {"message": "Permission denied"}})

    with pytest.raises(ProviderError) as info:
        gemini(handler, fallback_models=("gemini-lite",)).analyze(REQUEST)
    assert info.value.kind is ProviderErrorKind.AUTH
    assert calls["n"] == 1


def test_all_models_overloaded_reports_last_error():
    model = gemini(
        lambda r: httpx.Response(503, json={"error": {"message": "high demand"}}),
        fallback_models=("gemini-lite",),
    )
    with pytest.raises(ProviderError) as info:
        model.analyze(REQUEST)
    assert "gemini-lite" in info.value.user_message


def test_overloaded_model_is_skipped_for_a_while():
    seen = []

    def handler(request):
        seen.append(request.url.path)
        if "gemini-test:" in request.url.path:
            return httpx.Response(503, json={"error": {"message": "high demand"}})
        return httpx.Response(200, text=sse(text_event("OK")))

    model = gemini(handler, fallback_models=("gemini-lite",))
    model.analyze(REQUEST)
    second = model.analyze(REQUEST)
    assert second.extra["fallback_from"] == "gemini-test"
    assert [p.split("/")[-1].split(":")[0] for p in seen] == [
        "gemini-test",
        "gemini-lite",
        "gemini-lite",
    ]


def test_gemini_sends_search_tool_audio_and_parses_sources():
    from alicia.core.ai.base import PreparedAudio

    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        final = text_event("Prends la lame.")
        final["candidates"][0]["groundingMetadata"] = {
            "webSearchQueries": ["ashe stadium build"],
            "groundingChunks": [{"web": {"uri": "https://example.com/a", "title": "Guide"}}],
        }
        return httpx.Response(200, text=sse(final))

    audio = PreparedAudio(b"RIFFdata", "audio/wav", 1.5)
    request = AnalysisRequest(
        question="voir audio", images=(IMAGE,), system_prompt="s", audio=audio, web_search=True
    )
    result = gemini(handler).analyze(request)
    body = seen["body"]
    assert body["tools"] == [{"google_search": {}}]
    mimes = [p["inline_data"]["mime_type"] for p in body["contents"][-1]["parts"][:-1]]
    assert mimes == ["image/jpeg", "audio/wav"]
    assert result.sources[0].title == "Guide"
    assert result.search_queries == ["ashe stadium build"]


def test_search_refused_answers_without_and_says_so():
    bodies = []

    def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        if "tools" in body:
            return httpx.Response(
                400, json={"error": {"message": "Search Grounding is not supported."}}
            )
        return httpx.Response(200, text=sse(text_event("OK")))

    request = AnalysisRequest(question="q", images=(IMAGE,), system_prompt="s", web_search=True)
    result = gemini(handler).analyze(request)
    assert result.text == "OK" and "search_disabled" in result.extra
    assert len(bodies) == 2


def test_ollama_refuses_voice_questions_clearly():
    from alicia.core.ai.base import PreparedAudio

    request = AnalysisRequest(
        question="q",
        images=(IMAGE,),
        system_prompt="s",
        audio=PreparedAudio(b"x", "audio/wav", 1.0),
    )
    with pytest.raises(ProviderError) as info:
        ollama(lambda r: httpx.Response(200)).analyze(request)
    assert "Gemini" in info.value.user_message


def test_daily_quota_is_explained_and_model_skipped_until_reset():
    body = {
        "error": {
            "code": 429,
            "message": "You exceeded your current quota, please check your plan and billing details.",
            "details": [
                {
                    "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                    "violations": [
                        {"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}
                    ],
                },
                {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "17999s"},
            ],
        }
    }
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(429, json=body)

    model = gemini(handler, fallback_models=("gemini-lite",))
    with pytest.raises(ProviderError) as info:
        model.analyze(REQUEST)
    assert "Quota du jour épuisé" in info.value.user_message
    assert "PerDay" in info.value.detail
    remaining = model._overloaded_until["gemini-test"] - __import__("time").monotonic()
    assert remaining > 3600 or remaining > 0  # jusqu'à minuit UTC


def test_per_minute_quota_gives_retry_delay():
    from alicia.core.ai.providers.gemini import quota_details

    body = json.dumps(
        {
            "error": {
                "details": [
                    {
                        "@type": "x.QuotaFailure",
                        "violations": [
                            {"quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"}
                        ],
                    },
                    {"@type": "x.RetryInfo", "retryDelay": "46s"},
                ]
            }
        }
    )
    assert quota_details(body) == ("GenerateRequestsPerMinutePerProjectPerModel-FreeTier", 46)


def test_gemini_quick_request_asks_for_minimal_thinking():
    from dataclasses import replace

    model = gemini(lambda r: httpx.Response(500))
    _url, _headers, body = model._request(replace(REQUEST, quick=True))
    assert body["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "minimal"}
    model.model = "gemini-2.5-flash"
    _url, _headers, body = model._request(replace(REQUEST, quick=True))
    assert body["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 0}
