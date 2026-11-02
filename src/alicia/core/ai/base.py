"""Contrat du « cerveau » d'Alicia. Aucun SDK de fournisseur n'est importé ici."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class PreparedImage:
    data: bytes
    mime_type: str
    width: int
    height: int


@dataclass(frozen=True)
class PreparedAudio:
    data: bytes
    mime_type: str  # ex. « audio/wav »
    duration_s: float


@dataclass(frozen=True)
class Source:
    title: str
    url: str


@dataclass(frozen=True)
class Turn:
    question: str
    answer: str


@dataclass(frozen=True)
class AnalysisRequest:
    question: str
    images: tuple[PreparedImage, ...]
    system_prompt: str
    history: tuple[Turn, ...] = ()
    max_output_tokens: int = 1024
    temperature: float = 0.4
    audio: PreparedAudio | None = None  # question orale du joueur (V0.3)
    web_search: bool = False  # autoriser une recherche web si le fournisseur sait le faire
    quick: bool = False  # réponse réflexe (Copilote) : réflexion minimale, pour répondre vite


@dataclass
class AnalysisResult:
    text: str
    provider: str
    model: str
    latency_ms: int
    first_token_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    finish_reason: str | None = None
    extra: dict[str, str] = field(default_factory=dict)
    sources: list[Source] = field(default_factory=list)
    search_queries: list[str] = field(default_factory=list)


DeltaCallback = Callable[[str], None]


class VisionModel(Protocol):
    """Modèle multimodal (texte + images) capable de diffuser sa réponse."""

    provider: str
    model: str

    def analyze(
        self,
        request: AnalysisRequest,
        on_delta: DeltaCallback | None = None,
        cancel: threading.Event | None = None,
    ) -> AnalysisResult:
        """Renvoie la réponse complète ; ``on_delta`` reçoit les morceaux au fil de l'eau.

        Lève ``ProviderError`` (type normalisé) en cas d'échec ou d'annulation.
        """
        ...

    def check(self) -> str | None:
        """Vérification locale rapide (clé, URL) : message d'erreur lisible, ou None."""
        ...
