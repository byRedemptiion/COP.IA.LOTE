"""Google Gemini (API REST, réponse en streaming SSE). Aucun SDK requis."""

from __future__ import annotations

import base64
import json
import logging
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from alicia.core.ai.base import AnalysisRequest, Source
from alicia.core.ai.providers.http_base import Chunk, HttpVisionModel, error_message, json_lines
from alicia.core.config import GeminiSettings, Secret
from alicia.core.errors import ProviderError, ProviderErrorKind

log = logging.getLogger("alicia.ai")
OVERLOAD_PAUSE_S = 120  # un modèle saturé est évité pendant ce délai

KEY_URL = "https://aistudio.google.com/apikey"
KEY_HELP = (
    "Clique sur « IA » en haut du panneau (ou clic droit sur le rond → Choisir l'IA) : "
    f"crée ta clé gratuite sur {KEY_URL} et colle-la."
)


def quota_details(body: str) -> tuple[str, int | None]:
    """Extrait l'identifiant du quota dépassé et le délai conseillé d'une erreur 429."""
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return "", None
    quota, retry = "", None
    for detail in (data.get("error") or {}).get("details") or []:
        kind = str(detail.get("@type", ""))
        if kind.endswith("QuotaFailure"):
            for violation in detail.get("violations") or []:
                quota = quota or str(violation.get("quotaId") or violation.get("quotaMetric") or "")
        elif kind.endswith("RetryInfo"):
            delay = str(detail.get("retryDelay", "")).rstrip("s")
            try:
                retry = int(float(delay))
            except ValueError:
                pass
    return quota, retry


def seconds_until_utc_midnight() -> int:
    now = datetime.now(UTC)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=5, microsecond=0)
    return int((tomorrow - now).total_seconds())


class GeminiModel(HttpVisionModel):
    provider = "gemini"

    def __init__(
        self, settings: GeminiSettings, timeout_s: float, client: httpx.Client | None = None
    ) -> None:
        super().__init__(timeout_s, client)
        self._overloaded_until = {}
        self.settings = settings
        self.model = settings.model

    @property
    def label(self) -> str:
        return "Gemini"

    def check(self) -> str | None:
        if not self.settings.api_key:
            return "Clé Gemini manquante. " + KEY_HELP
        if not self.model:
            return "Aucun modèle Gemini configuré (section [ai.gemini] model)."
        return None

    _thinking_rejected = False
    _search_rejected = False
    _overloaded_until: dict[str, float]

    def analyze(self, request, on_delta=None, cancel=None):  # type: ignore[no-untyped-def]
        """Essaie le modèle principal puis les modèles de secours, en le journalisant."""
        all_models = [self.settings.model, *self.settings.fallback_models]
        if len(all_models) == 1:
            return super().analyze(request, on_delta, cancel)
        now = time.monotonic()
        models = [m for m in all_models if self._overloaded_until.get(m, 0) <= now]
        skipped = [m for m in all_models if m not in models]
        if not models:  # tous récemment saturés : on retente quand même dans l'ordre
            models, skipped = all_models, []
        if skipped:
            log.info(
                "Modèle(s) saturé(s) récemment, ignoré(s) %d s : %s",
                OVERLOAD_PAUSE_S,
                ", ".join(skipped),
            )
        problem = self.check()
        if problem:
            raise ProviderError(ProviderErrorKind.AUTH, problem)
        try:
            for index, model in enumerate(models):
                self.model = model
                emitted = [False]
                try:
                    result = self._run(request, on_delta, cancel, emitted)
                except ProviderError as exc:
                    switchable = (
                        not emitted[0]
                        and not (cancel is not None and cancel.is_set())
                        and (
                            exc.kind
                            in (
                                ProviderErrorKind.UNAVAILABLE,
                                ProviderErrorKind.RATE_LIMIT,
                                ProviderErrorKind.TIMEOUT,
                            )
                            or exc.status_code == 404
                        )
                    )
                    if exc.kind in (ProviderErrorKind.UNAVAILABLE, ProviderErrorKind.RATE_LIMIT):
                        pause = OVERLOAD_PAUSE_S
                        if getattr(exc, "daily", False):
                            pause = seconds_until_utc_midnight()
                        elif getattr(exc, "retry_after_s", None):
                            pause = max(int(exc.retry_after_s), 5)  # type: ignore[attr-defined]
                        self._overloaded_until[model] = time.monotonic() + pause
                    if not switchable or index == len(models) - 1:
                        raise
                    log.warning(
                        "Modèle %s indisponible [%s] : bascule sur %s — %s",
                        model,
                        exc.kind,
                        models[index + 1],
                        exc.detail,
                    )
                    continue
                if model != all_models[0]:
                    result.extra["fallback_from"] = all_models[0]
                self._overloaded_until.pop(model, None)
                return result
        finally:
            self.model = all_models[0]
        raise AssertionError("inatteignable")

    def _run(self, request, on_delta, cancel, emitted):  # type: ignore[no-untyped-def]
        try:
            return super()._run(request, on_delta, cancel, emitted)
        except ProviderError as exc:
            # Le réglage de réflexion dépend de la génération du modèle (2.5 : budget, 3.x : niveau).
            # Si le modèle le refuse, on le retire une fois pour toutes, et on le journalise.
            if (
                exc.status_code == 400
                and "thinking" in exc.detail.lower()
                and not self._thinking_rejected
            ):
                log.warning(
                    "Réglage de réflexion refusé par %s, envoi sans : %s", self.model, exc.detail
                )
                self._thinking_rejected = True
                return self._run(request, on_delta, cancel, emitted)
            # Recherche Google refusée (modèle sans « grounding » ou quota dédié épuisé) :
            # on répond sans recherche, et on le dit dans le journal et sous la réponse.
            if (
                request.web_search
                and not self._search_rejected
                and exc.status_code in (400, 429)
                and any(w in exc.detail.lower() for w in ("search", "grounding", "tool"))
            ):
                log.warning(
                    "Recherche Google refusée par %s, réponse sans : %s", self.model, exc.detail
                )
                self._search_rejected = True
                try:
                    result = self._run(request, on_delta, cancel, emitted)
                finally:
                    self._search_rejected = False
                result.extra["search_disabled"] = exc.detail[:200]
                return result
            raise

    def _headers(self) -> dict[str, str]:
        return {"x-goog-api-key": self.settings.api_key.get()}

    def _request(self, request: AnalysisRequest) -> tuple[str, dict[str, str], dict[str, Any]]:
        contents: list[dict[str, Any]] = []
        for turn in request.history:
            contents.append({"role": "user", "parts": [{"text": turn.question}]})
            contents.append({"role": "model", "parts": [{"text": turn.answer}]})
        parts: list[dict[str, Any]] = [
            {
                "inline_data": {
                    "mime_type": image.mime_type,
                    "data": base64.b64encode(image.data).decode(),
                }
            }
            for image in request.images
        ]
        if request.audio is not None:
            parts.append(
                {
                    "inline_data": {
                        "mime_type": request.audio.mime_type,
                        "data": base64.b64encode(request.audio.data).decode(),
                    }
                }
            )
        parts.append({"text": request.question})
        contents.append({"role": "user", "parts": parts})

        generation: dict[str, Any] = {
            "maxOutputTokens": request.max_output_tokens,
            "temperature": request.temperature,
        }
        thinking: dict[str, Any] = {}
        if self.settings.thinking_budget is not None:
            thinking["thinkingBudget"] = self.settings.thinking_budget
        if self.settings.thinking_level:
            thinking["thinkingLevel"] = self.settings.thinking_level
        if request.quick:  # Copilote : pas le temps de réfléchir longuement
            thinking = (
                {"thinkingBudget": 0} if "2.5" in self.model else {"thinkingLevel": "minimal"}
            )
        if thinking and not self._thinking_rejected:
            generation["thinkingConfig"] = thinking

        body: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": request.system_prompt}]},
            "contents": contents,
            "generationConfig": generation,
        }
        if request.web_search and not self._search_rejected:
            body["tools"] = [{"google_search": {}}]
        url = f"{self.settings.base_url}/models/{self.model}:streamGenerateContent?alt=sse"
        return url, self._headers(), body

    def _parse_lines(self, lines: Iterator[str]) -> Iterator[Chunk]:
        for event in json_lines(lines, prefix="data:"):
            feedback = event.get("promptFeedback") or {}
            if feedback.get("blockReason"):
                raise ProviderError(
                    ProviderErrorKind.BAD_REQUEST,
                    "Gemini a refusé la demande (filtre de contenu).",
                    detail=f"blockReason={feedback['blockReason']}",
                )
            usage = event.get("usageMetadata") or {}
            text_parts: list[str] = []
            finish = None
            sources: list[Source] = []
            queries: list[str] = []
            for candidate in event.get("candidates") or []:
                finish = candidate.get("finishReason") or finish
                grounding = candidate.get("groundingMetadata") or {}
                queries.extend(str(q) for q in grounding.get("webSearchQueries") or [])
                for item in grounding.get("groundingChunks") or []:
                    web = item.get("web") or {}
                    if web.get("uri"):
                        sources.append(Source(str(web.get("title") or web["uri"]), str(web["uri"])))
                for part in (candidate.get("content") or {}).get("parts") or []:
                    if part.get("thought"):
                        continue  # résumé de réflexion interne : pas pour le joueur
                    if isinstance(part.get("text"), str):
                        text_parts.append(part["text"])
            yield Chunk(
                text="".join(text_parts),
                input_tokens=usage.get("promptTokenCount"),
                output_tokens=usage.get("candidatesTokenCount"),
                finish_reason=finish,
                sources=tuple(sources),
                search_queries=tuple(queries),
            )

    def _http_error(self, status: int, body: str) -> ProviderError:
        message = error_message(body)
        lowered = message.lower()
        if status in (401, 403) or "api key" in lowered or "api_key" in lowered:
            return ProviderError(
                ProviderErrorKind.AUTH,
                "Clé Gemini refusée. " + KEY_HELP,
                detail=f"HTTP {status}: {message}",
                status_code=status,
            )
        if status == 429:
            quota, retry_s = quota_details(body)
            if "PerDay" in quota:
                hint = (
                    f"Quota du jour épuisé pour « {self.model} » (offre gratuite : une vingtaine "
                    "de questions par jour et par modèle). Il revient à 1 h du matin "
                    "(minuit UTC)."
                )
            elif "PerMinute" in quota:
                hint = (
                    f"Trop de questions en une minute pour « {self.model} ». "
                    f"Réessaie dans {retry_s or 60} s."
                )
            else:
                hint = "Quota Gemini atteint. Réessaie dans une minute."
            error = ProviderError(
                ProviderErrorKind.RATE_LIMIT,
                hint,
                detail=f"HTTP 429 [{quota or 'quota inconnu'}, réessai {retry_s} s]: {message}",
                status_code=status,
            )
            error.retry_after_s = retry_s  # type: ignore[attr-defined]
            error.daily = "PerDay" in quota  # type: ignore[attr-defined]
            return error
        if status == 404:
            return ProviderError(
                ProviderErrorKind.BAD_REQUEST,
                f"Modèle Gemini « {self.model} » introuvable. Liste les modèles disponibles "
                "avec : alicia-diag models",
                detail=f"HTTP 404: {message}",
                status_code=status,
            )
        if status >= 500:
            return ProviderError(
                ProviderErrorKind.UNAVAILABLE,
                f"Le modèle Gemini « {self.model} » est saturé (forte demande). "
                "Réessaie dans un moment.",
                detail=f"HTTP {status}: {message}",
                status_code=status,
            )
        return ProviderError(
            ProviderErrorKind.BAD_REQUEST,
            f"Requête refusée par Gemini : {message}",
            detail=f"HTTP {status}: {message}",
            status_code=status,
        )

    def _empty_answer(self, finish_reason: str | None) -> ProviderError:
        if finish_reason == "MAX_TOKENS":
            hint = " Augmente [ai] max_output_tokens ou réduis la réflexion (thinking_budget)."
        elif finish_reason in ("SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST"):
            hint = " La réponse a été bloquée par le filtre de contenu."
        else:
            hint = ""
        return ProviderError(
            ProviderErrorKind.BAD_REQUEST,
            "Gemini a renvoyé une réponse vide." + hint,
            detail=f"finishReason={finish_reason}",
        )

    def list_models(self) -> list[str]:
        """Modèles utilisables avec ``generateContent`` pour cette clé."""
        problem = self.check()
        if problem:
            raise ProviderError(ProviderErrorKind.AUTH, problem)
        try:
            response = self._client.get(
                f"{self.settings.base_url}/models",
                params={"pageSize": 1000},
                headers=self._headers(),
            )
        except httpx.HTTPError as exc:
            raise ProviderError(
                ProviderErrorKind.UNAVAILABLE, "Impossible de joindre Gemini.", detail=repr(exc)
            ) from exc
        if response.status_code >= 400:
            raise self._http_error(response.status_code, response.text[:2000])
        names = []
        for item in response.json().get("models", []):
            if "generateContent" in item.get("supportedGenerationMethods", []):
                names.append(str(item.get("name", "")).removeprefix("models/"))
        return sorted(names)


DEFAULT_GEMINI = GeminiSettings(
    "gemini-flash-latest", "https://generativelanguage.googleapis.com/v1beta", Secret(None)
)


def check_gemini_key(key: str, base: GeminiSettings | None = None) -> str | None:
    """None si la clé fonctionne, sinon un message clair."""
    from dataclasses import replace

    from alicia.core.errors import AliciaError

    settings = replace(base or DEFAULT_GEMINI, api_key=Secret(key))
    if not settings.base_url:
        settings = replace(settings, base_url=DEFAULT_GEMINI.base_url)
    try:
        models = GeminiModel(settings, 15).list_models()
    except AliciaError as exc:
        return exc.user_message
    except Exception as exc:  # noqa: BLE001 - réseau, réponse inattendue
        return f"Vérification impossible : {exc!r}"
    return None if models else "La clé fonctionne, mais aucun modèle Gemini n'est accessible."
