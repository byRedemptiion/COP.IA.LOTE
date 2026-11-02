"""Socle commun aux fournisseurs HTTP : streaming, annulation, erreurs, un réessai borné."""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import httpx

from alicia.core.ai.base import AnalysisRequest, AnalysisResult, DeltaCallback, Source
from alicia.core.errors import ProviderError, ProviderErrorKind

log = logging.getLogger("alicia.ai")


@dataclass
class Chunk:
    text: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    finish_reason: str | None = None
    sources: tuple[Source, ...] = ()
    search_queries: tuple[str, ...] = ()


class HttpVisionModel:
    provider = "http"
    model = ""

    def __init__(self, timeout_s: float, client: httpx.Client | None = None) -> None:
        self.timeout_s = timeout_s
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(timeout_s, connect=min(5.0, timeout_s)),
            headers={"User-Agent": "Alicia-Copilot/0.1"},
        )

    # --- à fournir par chaque fournisseur ---------------------------------------------------

    def _request(self, request: AnalysisRequest) -> tuple[str, dict[str, str], dict[str, Any]]:
        raise NotImplementedError

    def _parse_lines(self, lines: Iterator[str]) -> Iterator[Chunk]:
        raise NotImplementedError

    def _http_error(self, status: int, body: str) -> ProviderError:
        raise NotImplementedError

    def check(self) -> str | None:
        return None

    # --- logique commune --------------------------------------------------------------------

    def analyze(
        self,
        request: AnalysisRequest,
        on_delta: DeltaCallback | None = None,
        cancel: threading.Event | None = None,
    ) -> AnalysisResult:
        problem = self.check()
        if problem:
            raise ProviderError(ProviderErrorKind.AUTH, problem)
        emitted = [False]
        try:
            return self._run(request, on_delta, cancel, emitted)
        except ProviderError as exc:
            if (
                not exc.retryable
                or emitted[0]
                or getattr(exc, "no_retry", False)
                or (cancel and cancel.is_set())
            ):
                raise
            log.warning("Appel %s échoué (%s), unique nouvel essai", self.provider, exc.kind)
            return self._run(request, on_delta, cancel, emitted)

    def _run(
        self,
        request: AnalysisRequest,
        on_delta: DeltaCallback | None,
        cancel: threading.Event | None,
        emitted: list[bool],
    ) -> AnalysisResult:
        url, headers, body = self._request(request)
        started = time.perf_counter()
        first_token_ms: int | None = None
        parts: list[str] = []
        last = Chunk()
        # Étape atteinte, pour savoir où un délai dépassé s'est produit.
        phase = "connexion et envoi"
        events = 0
        try:
            with self._client.stream("POST", url, headers=headers, json=body) as response:
                headers_ms = _ms(started)
                log.info(
                    "%s : réponse HTTP %d reçue en %d ms, attente du flux",
                    self.label,
                    response.status_code,
                    headers_ms,
                )
                if response.status_code >= 400:
                    response.read()
                    raise self._http_error(response.status_code, response.text[:2000])
                phase = f"attente du premier mot (en-têtes reçus en {headers_ms} ms)"
                for chunk in self._parse_lines(response.iter_lines()):
                    events += 1
                    if events == 1:
                        log.debug(
                            "%s : premier événement du flux à %d ms", self.label, _ms(started)
                        )
                    if cancel is not None and cancel.is_set():
                        raise ProviderError(ProviderErrorKind.CANCELLED, "Analyse annulée.")
                    if chunk.text:
                        if first_token_ms is None:
                            first_token_ms = _ms(started)
                        parts.append(chunk.text)
                        emitted[0] = True
                        if on_delta is not None:
                            on_delta(chunk.text)
                    last = Chunk(
                        input_tokens=chunk.input_tokens or last.input_tokens,
                        output_tokens=chunk.output_tokens or last.output_tokens,
                        finish_reason=chunk.finish_reason or last.finish_reason,
                        sources=chunk.sources or last.sources,
                        search_queries=chunk.search_queries or last.search_queries,
                    )
        except httpx.TimeoutException as exc:
            if first_token_ms is not None:
                phase = "pendant la réponse"
            error = ProviderError(
                ProviderErrorKind.TIMEOUT,
                f"{self.label} n'a pas répondu à temps ({self.timeout_s:.0f} s, étape : {phase}).",
                detail=f"{exc!r} — étape : {phase}, événements reçus : {events}, "
                f"écoulé {_ms(started)} ms",
            )
            # Serveur joint mais modèle muet : un nouvel essai identique ne servirait à rien.
            error.no_retry = phase != "connexion et envoi"  # type: ignore[attr-defined]
            raise error from exc
        except httpx.TransportError as exc:
            raise ProviderError(
                ProviderErrorKind.UNAVAILABLE,
                f"Impossible de joindre {self.label}. Vérifie ta connexion.",
                detail=repr(exc),
            ) from exc

        text = "".join(parts).strip()
        if not text:
            raise self._empty_answer(last.finish_reason)
        return AnalysisResult(
            text=text,
            provider=self.provider,
            model=self.model,
            latency_ms=_ms(started),
            first_token_ms=first_token_ms,
            input_tokens=last.input_tokens,
            output_tokens=last.output_tokens,
            finish_reason=last.finish_reason,
            sources=list(dict.fromkeys(last.sources)),
            search_queries=list(last.search_queries),
        )

    @property
    def label(self) -> str:
        return self.provider

    def _empty_answer(self, finish_reason: str | None) -> ProviderError:
        return ProviderError(
            ProviderErrorKind.BAD_REQUEST,
            f"{self.label} a renvoyé une réponse vide.",
            detail=f"finish_reason={finish_reason}",
        )


def json_lines(lines: Iterator[str], prefix: str = "") -> Iterator[dict[str, Any]]:
    """Décode des lignes JSON (NDJSON) ou des événements SSE ``data: {...}``."""
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if prefix:
            if not line.startswith(prefix):
                continue
            line = line[len(prefix) :].strip()
            if line == "[DONE]":
                return
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            log.debug("Ligne de flux ignorée (JSON invalide) : %.120s", line)
            continue
        if isinstance(value, dict):
            yield value


def error_message(body: str) -> str:
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return body.strip()[:300]
    error = data.get("error", data) if isinstance(data, dict) else data
    if isinstance(error, dict):
        return str(error.get("message") or error.get("status") or error)[:300]
    return str(error)[:300]


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
