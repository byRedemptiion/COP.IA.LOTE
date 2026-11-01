"""Voix sur mesure Gemini (Voice design, modèle Gemini 3.8 Flash TTS).

On décrit une voix en une ou deux phrases (« petit garçon d'environ 9 ans… »), Gemini la crée
une fois et renvoie un extrait à écouter. Elle est gardée dans ton projet Google (identifiant
``voice_…``, valable un an après la dernière utilisation) et se choisit ensuite comme les
autres voix Gemini. La clé Gemini ne quitte jamais le PC autrement que vers Google, et n'est
jamais journalisée.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from alicia.core.audio.devices import AudioError

log = logging.getLogger("alicia.voice")

API = "https://generativelanguage.googleapis.com/v1beta"
VOICES_URL = f"{API}/voices"
INTERACTIONS_URL = f"{API}/interactions"
DESIGN_MODEL = "gemini-3.8-flash-tts"
RATE = 24000  # fréquence attendue par le lecteur

# Modèles proposés (on peut tout réécrire) : traits permanents seulement (âge, timbre…).
PRESETS = {
    "VIIRUS — petit robot": (
        "Un petit robot de dessin animé, voix aiguë, claire et pétillante, débit rapide, "
        "espiègle et toujours enjoué ; français de France, sans accent."
    ),
    "ALICIA — robote pétillante": (
        "Une jeune femme robot de dessin animé, voix aiguë, douce et vive, curieuse et "
        "malicieuse ; français de France, sans accent."
    ),
}


@dataclass(frozen=True)
class DesignedVoice:
    id: str  # voice_…
    name: str
    description: str


def is_designed(voice: str) -> bool:
    return voice.startswith("voice_")


# --- liste locale des voix créées -------------------------------------------------------------


def _store_path() -> Path:
    from alicia.core.config import state_dir

    return state_dir() / "voix_gemini.json"


def load_voices(path: Path | None = None) -> list[DesignedVoice]:
    path = path or _store_path()
    try:
        items = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and is_designed(str(item.get("id", ""))):
            out.append(
                DesignedVoice(
                    str(item["id"]),
                    str(item.get("name") or item["id"])[:60],
                    str(item.get("description", ""))[:600],
                )
            )
    return out


def save_voice(voice: DesignedVoice, path: Path | None = None) -> None:
    path = path or _store_path()
    voices = [v for v in load_voices(path) if v.id != voice.id] + [voice]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([v.__dict__ for v in voices], ensure_ascii=False, indent=2), encoding="utf-8"
    )


def voice_name(voice_id: str, path: Path | None = None) -> str:
    return next((v.name for v in load_voices(path) if v.id == voice_id), voice_id)


# --- audio ----------------------------------------------------------------------------------


def decode_audio(data: bytes) -> np.ndarray:
    """WAV (ou PCM 16 bits brut à 24 kHz) → int16 mono à 24 kHz."""
    if data[:4] == b"RIFF":
        with wave.open(io.BytesIO(data)) as wav:
            rate, channels, width = wav.getframerate(), wav.getnchannels(), wav.getsampwidth()
            frames = wav.readframes(wav.getnframes())
        if width != 2:
            raise AudioError("Voix Gemini : format audio inattendu.", detail=f"{width * 8} bits")
        samples = np.frombuffer(frames[: len(frames) - len(frames) % 2], dtype=np.int16)
        if channels > 1:
            samples = samples[: len(samples) - len(samples) % channels]
            samples = samples.reshape(-1, channels).mean(axis=1).astype(np.int16)
    else:
        rate = RATE
        samples = np.frombuffer(data[: len(data) - len(data) % 2], dtype=np.int16)
    if rate != RATE and len(samples):
        count = int(len(samples) * RATE / rate)
        x = np.linspace(0, len(samples) - 1, count)
        samples = np.interp(x, np.arange(len(samples)), samples).astype(np.int16)
    return samples


def find_audio(payload: Any) -> str | None:
    """Cherche les données audio (base64) dans la réponse, quelle que soit sa forme exacte."""
    if isinstance(payload, dict):
        output = payload.get("output_audio") or payload.get("outputAudio")
        if isinstance(output, dict) and isinstance(output.get("data"), str):
            return output["data"]
        mime = str(payload.get("mime_type") or payload.get("mimeType") or "")
        if (payload.get("type") == "audio" or mime.startswith("audio")) and isinstance(
            payload.get("data"), str
        ):
            return payload["data"]
        inline = payload.get("inlineData") or payload.get("inline_data")
        if isinstance(inline, dict) and isinstance(inline.get("data"), str):
            return inline["data"]
        for value in payload.values():
            found = find_audio(value)
            if found:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = find_audio(value)
            if found:
                return found
    return None


def _check(response: Any, what: str) -> dict[str, Any]:
    if response.status_code in (401, 403):
        raise AudioError(
            f"{what} : la clé Gemini est refusée (ou n'a pas accès à Gemini 3.8 TTS).",
            detail=response.text[:300],
        )
    if response.status_code == 429:
        raise AudioError(f"{what} : quota Gemini atteint, réessaie plus tard.", detail="429")
    if response.status_code >= 400 and "safety" in response.text.casefold():
        raise AudioError(
            f"{what} : Google refuse cette description (règles de sécurité), sans doute "
            "parce qu'elle décrit un enfant. Décris plutôt un personnage (petit robot…).",
            detail=response.text[:400],
        )
    if response.status_code >= 400:
        raise AudioError(f"{what} : erreur {response.status_code}.", detail=response.text[:400])
    try:
        data = response.json()
    except ValueError as exc:
        raise AudioError(f"{what} : réponse illisible.", detail=response.text[:300]) from exc
    return data if isinstance(data, dict) else {}


# --- création et synthèse -------------------------------------------------------------------


def create_voice(
    key: str, name: str, description: str, language: str = "fr-FR"
) -> tuple[DesignedVoice, np.ndarray]:
    """Crée la voix chez Google et renvoie (voix, extrait)."""
    import httpx

    description = " ".join(description.split())[:600]
    if len(description) < 10:
        raise AudioError("Décris la voix en une ou deux phrases.", detail="description vide")
    body = {
        "store": True,
        "voice": {
            "model": DESIGN_MODEL,
            "type": "prompted",
            "display_name": (name or "Voix sur mesure")[:60],
            "language_code": language,
            "prompted": {"input": description},
        },
    }
    try:
        response = httpx.post(VOICES_URL, headers={"x-goog-api-key": key}, json=body, timeout=90)
    except httpx.HTTPError as exc:
        raise AudioError("Création de voix : Gemini injoignable.", detail=repr(exc)) from exc
    data = _check(response, "Création de voix")
    voice = data.get("voice") if isinstance(data.get("voice"), dict) else data
    voice_id = str(voice.get("id") or voice.get("name") or "").rsplit("/", 1)[-1]
    if not is_designed(voice_id):
        raise AudioError("Création de voix : pas d'identifiant reçu.", detail=str(data)[:300])
    designed = DesignedVoice(voice_id, (name or "Voix sur mesure")[:60], description)
    audio = find_audio(voice.get("sample_audio") or voice.get("sampleAudio") or {})
    sample = decode_audio(base64.b64decode(audio)) if audio else np.zeros(0, dtype=np.int16)
    log.info("Voix sur mesure créée : %s (%s)", designed.name, voice_id)
    return designed, sample


def designed_synthesizer(key: str, voice_id: str, style: str = ""):  # type: ignore[no-untyped-def]
    """Synthèse avec une voix sur mesure (API Interactions, Gemini 3.8 Flash TTS)."""
    import httpx

    def synthesize(text: str) -> np.ndarray:
        content: dict[str, Any] = {"type": "text", "text": text}
        if style:
            content["annotations"] = [{"type": "speech_metadata", "style": style}]
        body = {
            "model": DESIGN_MODEL,
            "input": [{"type": "user_input", "content": [content]}],
            "response_format": {"type": "audio"},
            "generation_config": {"speech_config": [{"voice": voice_id}]},
        }
        try:
            response = httpx.post(
                INTERACTIONS_URL, headers={"x-goog-api-key": key}, json=body, timeout=40
            )
        except httpx.HTTPError as exc:
            raise AudioError("Voix sur mesure : Gemini injoignable.", detail=repr(exc)) from exc
        audio = find_audio(_check(response, "Voix sur mesure"))
        if not audio:
            body = " ".join(response.text.split())
            if any(w in body for w in ("blockReason", "PROHIBITED", "SAFETY", "blocked")):
                raise VoiceBlocked("Voix sur mesure : phrase refusée.", detail=body[:200])
            raise AudioError("Voix sur mesure : réponse sans audio.", detail=body[:300])
        return decode_audio(base64.b64decode(audio))

    return synthesize


class VoiceBlocked(AudioError):
    """Google refuse de dire une phrase précise (filtre de contenu) : seulement celle-là."""


def with_fallback(primary, fallback, pause_s: float = 300.0):  # type: ignore[no-untyped-def]
    """Si la voix sur mesure échoue, la voix de secours prend le relais (5 min)."""
    state = {"until": 0.0}

    def synthesize(text: str) -> np.ndarray:
        if time.monotonic() >= state["until"]:
            try:
                return primary(text)
            except VoiceBlocked as exc:
                log.warning("Voix en ligne : %s — voix de secours pour cette phrase", exc.detail)
                return fallback(text)
            except AudioError as exc:
                state["until"] = time.monotonic() + pause_s
                log.warning("Voix en ligne indisponible, voix de secours 5 min : %s", exc.detail)
        return fallback(text)

    return synthesize
