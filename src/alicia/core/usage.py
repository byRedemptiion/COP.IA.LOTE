"""Compteur de consommation du jour : combien d'appels à chaque service.

Utile pour voir venir les quotas (les voix Gemini sont limitées à 100 par jour au niveau 1
de Google). Compté sur ce PC seulement, remis à zéro chaque jour à minuit (heure locale).
Aucun contenu n'est gardé : juste des nombres.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import date
from pathlib import Path

log = logging.getLogger("alicia.app")

# (clé, libellé, limite par jour connue ou None)
COUNTERS: tuple[tuple[str, str, int | None], ...] = (
    ("questions", "Questions à l'IA", None),
    ("copilot", "Coups d'œil du Copilote", None),
    ("chat", "Réponses au chat Twitch", None),
    ("stt", "Transcriptions de ta voix", None),
    ("tts_gemini_38", "Voix sur mesure (Gemini 3.8 TTS)", 100),
    ("tts_gemini_31", "Voix Gemini (3.1 TTS)", 100),
    ("tts_openai", "Voix ChatGPT", None),
    ("tts_edge", "Voix Edge (gratuites)", None),
    ("tts_backup", "Phrases dites par la voix de secours", None),
)

_lock = threading.Lock()
_state: dict[str, object] = {"day": "", "counts": {}}
_path: Path | None = None


def _file() -> Path:
    global _path
    if _path is None:
        from alicia.core.config import state_dir

        _path = state_dir() / "consommation.json"
    return _path


def use_file(path: Path | None) -> None:
    """Tests : autre fichier (None = celui par défaut)."""
    global _path
    with _lock:
        _path = path
        _state.update(day="", counts={})


def _load() -> None:
    today = date.today().isoformat()
    if _state["day"] == today:
        return
    counts: dict[str, int] = {}
    try:
        data = json.loads(_file().read_text("utf-8"))
        if data.get("day") == today and isinstance(data.get("counts"), dict):
            counts = {str(k): int(v) for k, v in data["counts"].items()}
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    _state.update(day=today, counts=counts)


def add(key: str, amount: int = 1) -> None:
    """+1 pour ce service (appelable depuis n'importe quel fil ; ne lève jamais)."""
    try:
        with _lock:
            _load()
            counts = _state["counts"]
            assert isinstance(counts, dict)
            counts[key] = int(counts.get(key, 0)) + amount
            path = _file()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(_state), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - un compteur ne casse jamais la voix ni l'IA
        log.debug("Compteur de consommation : %r", exc)


def today() -> dict[str, int]:
    with _lock:
        _load()
        counts = _state["counts"]
        return dict(counts) if isinstance(counts, dict) else {}


def report() -> list[tuple[str, int, int | None]]:
    """[(libellé, nombre, limite)] pour l'affichage."""
    counts = today()
    return [(label, counts.get(key, 0), limit) for key, label, limit in COUNTERS]
