"""Ollama local (gratuit, hors ligne). Partage le GPU avec le jeu : plus lent en partie."""

from __future__ import annotations

import base64
import logging
from collections.abc import Iterator
from typing import Any

import httpx

from alicia.core.ai.base import AnalysisRequest
from alicia.core.ai.providers.http_base import Chunk, HttpVisionModel, error_message, json_lines
from alicia.core.config import OllamaSettings
from alicia.core.errors import ProviderError, ProviderErrorKind

log = logging.getLogger("alicia.ai")


class OllamaModel(HttpVisionModel):
    provider = "ollama"

    def __init__(
        self, settings: OllamaSettings, timeout_s: float, client: httpx.Client | None = None
    ) -> None:
        # Le premier chargement du modèle en mémoire peut être long : délai plus large.
        super().__init__(max(timeout_s, 120.0), client)
        self.settings = settings
        self.model = settings.model

    @property
    def label(self) -> str:
        return "Ollama (local)"

    def check(self) -> str | None:
        return None if self.model else "Aucun modèle Ollama configuré ([ai.ollama] model)."

    def _request(self, request: AnalysisRequest) -> tuple[str, dict[str, str], dict[str, Any]]:
        if request.audio is not None:
            raise ProviderError(
                ProviderErrorKind.BAD_REQUEST,
                "Les questions orales nécessitent Gemini : Ollama ne comprend pas l'audio. "
                "Tape ta question ou repasse sur Gemini.",
            )
        if request.web_search:
            log.info(
                "Ollama ne cherche pas sur le web : COP'IA'LOTE cherche dans tes sites de référence"
            )
        messages: list[dict[str, Any]] = [{"role": "system", "content": request.system_prompt}]
        for turn in request.history:
            messages.append({"role": "user", "content": turn.question})
            messages.append({"role": "assistant", "content": turn.answer})
        messages.append(
            {
                "role": "user",
                "content": request.question,
                "images": [base64.b64encode(image.data).decode() for image in request.images],
            }
        )
        body = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "keep_alive": self.settings.keep_alive,
            "options": {
                "num_predict": request.max_output_tokens,
                "temperature": request.temperature,
                # Jamais tout le processeur : sans carte graphique, Ollama le ferait chauffer.
                "num_thread": self.settings.num_thread or default_threads(),
                "num_ctx": self.settings.num_ctx,  # 8K : assez pour ALICIA, économise la VRAM
            },
        }
        return f"{self.settings.base_url}/api/chat", {}, body

    def _parse_lines(self, lines: Iterator[str]) -> Iterator[Chunk]:
        for event in json_lines(lines):
            if event.get("error"):
                raise ProviderError(
                    ProviderErrorKind.BAD_REQUEST, f"Ollama : {event['error']}", detail=str(event)
                )
            message = event.get("message") or {}
            yield Chunk(
                text=str(message.get("content") or ""),
                input_tokens=event.get("prompt_eval_count"),
                output_tokens=event.get("eval_count"),
                finish_reason=event.get("done_reason"),
            )

    def _http_error(self, status: int, body: str) -> ProviderError:
        message = error_message(body)
        if status == 404:
            return ProviderError(
                ProviderErrorKind.BAD_REQUEST,
                f"Modèle « {self.model} » absent d'Ollama. Installe-le : ollama pull {self.model}",
                detail=f"HTTP 404: {message}",
                status_code=status,
            )
        kind = ProviderErrorKind.UNAVAILABLE if status >= 500 else ProviderErrorKind.BAD_REQUEST
        return ProviderError(
            kind, f"Ollama : {message}", detail=f"HTTP {status}: {message}", status_code=status
        )

    def _run(self, request, on_delta, cancel, emitted):  # type: ignore[no-untyped-def]
        try:
            return super()._run(request, on_delta, cancel, emitted)
        except ProviderError as exc:
            if exc.kind is ProviderErrorKind.UNAVAILABLE and isinstance(
                exc.__cause__, httpx.ConnectError
            ):
                from alicia.core.ai.providers.ollama_runtime import OllamaRuntime, is_local

                if is_local(self.settings.base_url) and not getattr(self, "_autostarted", False):
                    # Ollama éteint : ALICIA le démarre, puis repose la question une fois.
                    self._autostarted = True
                    runtime = OllamaRuntime(self.settings.base_url, self.model)
                    runtime.ensure_running()  # message clair si Ollama n'est pas installé
                    self.runtime = runtime
                    return super()._run(request, on_delta, cancel, emitted)
                raise ProviderError(
                    ProviderErrorKind.UNAVAILABLE,
                    "Ollama ne répond pas sur ce PC. Lance l'application Ollama puis réessaie.",
                    detail=exc.detail,
                ) from exc
            raise


def default_threads() -> int:
    import os

    return max(2, min(6, (os.cpu_count() or 4) // 2))
