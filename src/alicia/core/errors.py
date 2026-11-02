"""Erreurs d'Alicia : chaque erreur porte un message lisible par le joueur."""

from __future__ import annotations

from enum import StrEnum


class AliciaError(Exception):
    """Erreur prévue, avec un message destiné à l'interface."""

    def __init__(self, user_message: str, *, detail: str | None = None) -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.detail = detail or user_message


class ConfigError(AliciaError):
    pass


class UnsupportedPlatformError(AliciaError):
    pass


class CaptureError(AliciaError):
    pass


class ProviderErrorKind(StrEnum):
    AUTH = "auth"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    BAD_REQUEST = "bad_request"
    CANCELLED = "cancelled"


class ProviderError(AliciaError):
    def __init__(
        self,
        kind: ProviderErrorKind,
        user_message: str,
        *,
        detail: str | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(user_message, detail=detail)
        self.kind = kind
        self.status_code = status_code

    @property
    def retryable(self) -> bool:
        return self.kind in (ProviderErrorKind.TIMEOUT, ProviderErrorKind.UNAVAILABLE)
