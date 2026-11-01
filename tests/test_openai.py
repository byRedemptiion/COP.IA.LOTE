import json

import httpx
import pytest

from alicia.core.ai.base import AnalysisRequest, PreparedImage, Turn
from alicia.core.ai.providers.openai import OpenAIModel
from alicia.core.config import OpenAISettings, Secret
from alicia.core.errors import ProviderError, ProviderErrorKind


def sse(*events):
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()


def model(handler, key="sk-test"):
    settings = OpenAISettings(api_key=Secret(key))
    return OpenAIModel(settings, 10, client=httpx.Client(transport=httpx.MockTransport(handler)))


def request(web=True):
    return AnalysisRequest(
        question="Quel objet ?",
        images=(PreparedImage(b"jpeg", "image/jpeg", 10, 10),),
        system_prompt="Tu es Alicia.",
        history=(Turn("avant ?", "réponse"),),
        max_output_tokens=300,
        temperature=0.4,
        web_search=web,
    )


def test_streams_answer_with_image_search_and_sources():
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content)
        seen["auth"] = req.headers["Authorization"]
        seen["url"] = str(req.url)
        return httpx.Response(
            200,
            content=sse(
                {"type": "response.output_text.delta", "delta": "Prends "},
                {
                    "type": "response.output_text.annotation.added",
                    "annotation": {"type": "url_citation", "url": "https://wiki", "title": "Wiki"},
                },
                {"type": "response.output_text.delta", "delta": "la lame."},
                {
                    "type": "response.completed",
                    "response": {"usage": {"input_tokens": 900, "output_tokens": 12}},
                },
            ),
        )

    deltas = []
    result = model(handler).analyze(request(), on_delta=deltas.append)
    assert result.text == "Prends la lame." and deltas == ["Prends ", "la lame."]
    assert [s.url for s in result.sources] == ["https://wiki"]
    assert result.input_tokens == 900
    body = seen["body"]
    assert seen["url"].endswith("/v1/responses") and seen["auth"] == "Bearer sk-test"
    assert body["model"] == "gpt-6-luna" and body["stream"] is True and body["store"] is False
    assert body["instructions"] == "Tu es Alicia."
    assert body["tools"] == [{"type": "web_search"}]
    assert body["reasoning"] == {"effort": "low"}
    last = body["input"][-1]["content"]
    assert last[0] == {"type": "input_text", "text": "Quel objet ?"}
    assert last[1]["image_url"].startswith("data:image/jpeg;base64,")
    assert body["input"][1]["role"] == "assistant"


def test_missing_credit_is_explained():
    def handler(req):
        return httpx.Response(
            429, json={"error": {"message": "You exceeded your current quota, check billing"}}
        )

    with pytest.raises(ProviderError) as info:
        model(handler).analyze(request())
    assert info.value.kind is ProviderErrorKind.RATE_LIMIT
    assert "crédit" in info.value.user_message


def test_model_without_reasoning_option_is_retried_without_it():
    bodies = []

    def handler(req):
        body = json.loads(req.content)
        bodies.append(body)
        if "reasoning" in body:
            return httpx.Response(
                400, json={"error": {"message": "Unsupported parameter: 'reasoning.effort'"}}
            )
        return httpx.Response(
            200, content=sse({"type": "response.output_text.delta", "delta": "ok"})
        )

    assert model(handler).analyze(request(web=False)).text == "ok"
    assert "reasoning" not in bodies[-1] and "tools" not in bodies[-1]


def test_missing_key_is_reported_before_calling():
    with pytest.raises(ProviderError) as info:
        model(lambda r: httpx.Response(500), key=None).analyze(request())
    assert "Clé OpenAI manquante" in info.value.user_message
