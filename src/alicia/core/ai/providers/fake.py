"""Fournisseur factice, déterministe : tests et démo sans clé ni réseau."""

from __future__ import annotations

import threading
import time

from alicia.core.ai.base import AnalysisRequest, AnalysisResult, DeltaCallback
from alicia.core.errors import ProviderError, ProviderErrorKind


class FakeModel:
    provider = "fake"
    model = "fake-1"

    def __init__(self, delay_s: float = 0.0, fail_with: ProviderError | None = None) -> None:
        self.delay_s = delay_s
        self.fail_with = fail_with
        self.requests: list[AnalysisRequest] = []

    def check(self) -> str | None:
        return None

    def analyze(
        self,
        request: AnalysisRequest,
        on_delta: DeltaCallback | None = None,
        cancel: threading.Event | None = None,
    ) -> AnalysisResult:
        self.requests.append(request)
        started = time.perf_counter()
        if self.fail_with is not None:
            raise self.fail_with
        sizes = ", ".join(f"{i.width}x{i.height}" for i in request.images) or "aucune"
        if request.audio is not None:
            prefix = "Question : question orale factice\n"
            question = f"audio {request.audio.duration_s} s"
        else:
            prefix, question = "", request.question
        words = (
            prefix + f"[Réponse factice — aucune IA appelée] Image reçue : {sizes}. "
            f"Question : « {question} »."
        ).split(" ")
        for index, word in enumerate(words):
            if cancel is not None and cancel.is_set():
                raise ProviderError(ProviderErrorKind.CANCELLED, "Analyse annulée.")
            if self.delay_s:
                time.sleep(self.delay_s)
            if on_delta is not None:
                on_delta(word if index == 0 else " " + word)
        return AnalysisResult(
            text=" ".join(words),
            provider=self.provider,
            model=self.model,
            latency_ms=int((time.perf_counter() - started) * 1000),
            first_token_ms=0,
        )
