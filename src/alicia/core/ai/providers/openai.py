"""OpenAI (API de ChatGPT) via l'API Responses : image + question, recherche web, flux SSE.

Appel REST direct avec httpx (pas de SDK), comme pour Gemini. La clé (OPENAI_API_KEY) est
facturée à part de l'abonnement ChatGPT et n'apparaît jamais dans les journaux.
"""

from __future__ import annotations

import base64
import logging
from collections.abc import Iterator
from typing import Any

import httpx

from alicia.core.ai.base import AnalysisRequest, Source
from alicia.core.ai.providers.http_base import Chunk, HttpVisionModel, error_message, json_lines
from alicia.core.config import OpenAISettings, Secret
from alicia.core.errors import ProviderError, ProviderErrorKind

log = logging.getLogger("alicia.ai")

KEY_URL = "https://platform.openai.com/api-keys"
BILLING_URL = "https://platform.openai.com/settings/organization/billing"
KEY_HELP = (
    "Bouton « IA » en haut du panneau (ou clic droit sur le rond → Choisir l'IA) : "
    f"crée une clé sur {KEY_URL} et colle-la."
)


class OpenAIModel(HttpVisionModel):
    provider = "openai"

    def __init__(
        self, settings: OpenAISettings, timeout_s: float, client: httpx.Client | None = None
    ) -> None:
        super().__init__(timeout_s, client)
        self.settings = settings
        self.model = settings.model
        self._effort_rejected = False
        self._search_rejected = False

    @property
    def label(self) -> str:
        return "OpenAI"

    def check(self) -> str | None:
        if not self.settings.api_key:
            return "Clé OpenAI manquante. " + KEY_HELP
        if not self.model:
            return "Aucun modèle OpenAI configuré (section [ai.openai] model)."
        return None

    def _request(self, request: AnalysisRequest) -> tuple[str, dict[str, str], dict[str, Any]]:
        if request.audio is not None:
            raise ProviderError(
                ProviderErrorKind.BAD_REQUEST,
                "Avec OpenAI, ta voix doit être transcrite sur ton PC : mets [voice] stt = "
                '"local" (réglage par défaut).',
            )
        items: list[dict[str, Any]] = []
        for turn in request.history:
            items.append(
                {"role": "user", "content": [{"type": "input_text", "text": turn.question}]}
            )
            items.append(
                {"role": "assistant", "content": [{"type": "output_text", "text": turn.answer}]}
            )
        content: list[dict[str, Any]] = [{"type": "input_text", "text": request.question}]
        for image in request.images:
            encoded = base64.b64encode(image.data).decode()
            content.append(
                {"type": "input_image", "image_url": f"data:{image.mime_type};base64,{encoded}"}
            )
        items.append({"role": "user", "content": content})
        body: dict[str, Any] = {
            "model": self.model,
            "instructions": request.system_prompt,
            "input": items,
            "stream": True,
            "store": False,
            "max_output_tokens": request.max_output_tokens,
        }
        effort = self.settings.reasoning_effort
        if effort and not self._effort_rejected:
            body["reasoning"] = {"effort": effort}
        if request.web_search and not self._search_rejected:
            body["tools"] = [{"type": "web_search"}]
        headers = {"Authorization": f"Bearer {self.settings.api_key.get()}"}
        return f"{self.settings.base_url}/responses", headers, body

    def _parse_lines(self, lines: Iterator[str]) -> Iterator[Chunk]:
        sources: list[Source] = []
        for event in json_lines(lines, prefix="data:"):
            kind = str(event.get("type", ""))
            if kind == "response.output_text.delta":
                yield Chunk(text=str(event.get("delta") or ""))
            elif kind == "response.output_text.annotation.added":
                annotation = event.get("annotation") or {}
                if annotation.get("type") == "url_citation" and annotation.get("url"):
                    sources.append(
                        Source(str(annotation.get("title") or annotation["url"]), annotation["url"])
                    )
                    yield Chunk(sources=tuple(dict.fromkeys(sources)))
            elif kind == "response.completed" or kind == "response.incomplete":
                response = event.get("response") or {}
                usage = response.get("usage") or {}
                reason = (
                    "stop"
                    if kind == "response.completed"
                    else str((response.get("incomplete_details") or {}).get("reason", "incomplete"))
                )
                yield Chunk(
                    input_tokens=usage.get("input_tokens"),
                    output_tokens=usage.get("output_tokens"),
                    finish_reason=reason,
                    sources=tuple(dict.fromkeys(sources)),
                )
            elif kind in ("response.failed", "error"):
                error = (event.get("response") or {}).get("error") or event.get("error") or event
                message = str(error.get("message") if isinstance(error, dict) else error)
                raise ProviderError(
                    ProviderErrorKind.BAD_REQUEST,
                    f"OpenAI : {message[:300]}",
                    detail=str(event)[:500],
                )

    def _http_error(self, status: int, body: str) -> ProviderError:
        message = error_message(body)
        if status == 401:
            return ProviderError(
                ProviderErrorKind.AUTH,
                "Clé OpenAI refusée. " + KEY_HELP,
                detail=f"HTTP 401: {message}",
                status_code=status,
            )
        if status == 429:
            low = message.lower()
            if "quota" in low or "billing" in low or "credit" in low:
                text = (
                    "Plus de crédit sur le compte OpenAI : ajoute du crédit sur "
                    f"{BILLING_URL} (l'abonnement ChatGPT ne compte pas pour l'API)."
                )
            else:
                text = "OpenAI limite le nombre de questions : réessaie dans un instant."
            return ProviderError(
                ProviderErrorKind.RATE_LIMIT,
                text,
                detail=f"HTTP 429: {message}",
                status_code=status,
            )
        if status >= 500:
            return ProviderError(
                ProviderErrorKind.UNAVAILABLE,
                "OpenAI est momentanément indisponible.",
                detail=f"HTTP {status}: {message}",
                status_code=status,
            )
        return ProviderError(
            ProviderErrorKind.BAD_REQUEST,
            f"OpenAI : {message}",
            detail=f"HTTP {status}: {message}",
            status_code=status,
        )

    def _run(self, request, on_delta, cancel, emitted):  # type: ignore[no-untyped-def]
        try:
            return super()._run(request, on_delta, cancel, emitted)
        except ProviderError as exc:
            # Modèle qui refuse le réglage de réflexion ou la recherche : on réessaie sans,
            # et on le dit dans le journal (pas de repli silencieux).
            detail = (exc.detail or "").lower()
            if exc.status_code == 400 and not emitted[0]:
                if "reasoning" in detail and not self._effort_rejected:
                    self._effort_rejected = True
                    log.warning("OpenAI : %s refuse « reasoning », nouvel essai sans", self.model)
                    return super()._run(request, on_delta, cancel, emitted)
                if ("web_search" in detail or "tool" in detail) and not self._search_rejected:
                    self._search_rejected = True
                    log.warning("OpenAI : recherche web refusée par %s, réponse sans", self.model)
                    result = super()._run(request, on_delta, cancel, emitted)
                    result.extra["search_disabled"] = "1"
                    return result
            raise


def check_openai_key(key: str, base: OpenAISettings | None = None) -> str | None:
    """None si la clé fonctionne, sinon un message clair."""
    settings = base or OpenAISettings()
    try:
        response = httpx.get(
            f"{settings.base_url}/models",
            headers={"Authorization": f"Bearer {Secret(key).get()}"},
            timeout=15,
        )
    except httpx.HTTPError as exc:
        return f"Impossible de joindre OpenAI ({type(exc).__name__})."
    if response.status_code == 401:
        return "Clé OpenAI refusée : vérifie qu'elle est complète (commence par « sk- »)."
    if response.status_code >= 400:
        return f"OpenAI a répondu HTTP {response.status_code} : {error_message(response.text)}"
    return None
