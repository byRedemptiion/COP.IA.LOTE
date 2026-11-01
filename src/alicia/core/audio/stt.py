"""Transcription locale de la voix du joueur avec faster-whisper (CPU, sans PyTorch).

Réglages et filtre d'hallucinations repris de huburton/jarvis (MIT) : langue imposée,
beam_size=1 pour la vitesse, VAD intégrée, pas de conditionnement sur le texte précédent.
"""

from __future__ import annotations

import io
import logging
import os
import re
import threading
import time
import wave

import numpy as np

from alicia.core.ai.base import PreparedAudio
from alicia.core.audio.devices import AudioError

log = logging.getLogger("alicia.audio")

# Phrases typiques inventées par Whisper sur du silence ou du bruit (sous-titres de vidéos).
_HALLUCINATIONS = re.compile(
    r"sous-titr|amara\.org|merci d'avoir regard|abonnez-vous|merci de votre attention"
    r"|^\W*$",
    re.IGNORECASE,
)


def wav_to_float(audio: PreparedAudio) -> np.ndarray:
    with wave.open(io.BytesIO(audio.data)) as wav:
        if wav.getsampwidth() != 2 or wav.getnchannels() != 1:
            raise AudioError("Format audio inattendu pour la transcription.")
        rate = wav.getframerate()
        samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)
    if rate != 16000:
        raise AudioError("La transcription attend un enregistrement à 16 kHz.", detail=f"{rate} Hz")
    return samples.astype(np.float32) / 32768.0


class LocalTranscriber:
    def __init__(
        self,
        model: str = "large-v3-turbo",
        *,
        language: str = "fr",
        compute_type: str = "int8",
        threads: int | None = None,
        prompt: str = "",
    ) -> None:
        self.model_name = model
        self.language = language
        self.compute_type = compute_type
        self.threads = threads or max(2, min(8, (os.cpu_count() or 4) // 2))
        self.prompt = prompt
        self._model = None
        self._lock = threading.Lock()

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def load(self):  # type: ignore[no-untyped-def]
        with self._lock:
            if self._model is not None:
                return self._model
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise AudioError("Module faster-whisper absent.", detail=repr(exc)) from exc
            from alicia.core.audio.models import whisper_dir

            started = time.perf_counter()
            try:
                self._model = WhisperModel(
                    self.model_name,
                    device="cpu",
                    compute_type=self.compute_type,
                    cpu_threads=self.threads,
                    download_root=str(whisper_dir()),
                )
            except Exception as exc:  # noqa: BLE001 - téléchargement, fichiers corrompus…
                raise AudioError(
                    f"Impossible de charger le modèle de transcription « {self.model_name} ». "
                    "Relance Installer_Alicia.bat pour le (re)télécharger.",
                    detail=repr(exc),
                ) from exc
            log.info(
                "Whisper « %s » chargé en %.1f s (%s, %d threads)",
                self.model_name,
                time.perf_counter() - started,
                self.compute_type,
                self.threads,
            )
            return self._model

    def warm_up_async(self) -> None:
        """Charge le modèle en arrière-plan au démarrage : la 1re question n'attend pas."""

        def run() -> None:
            try:
                self.load()
            except AudioError as exc:
                log.error("Préchargement de Whisper : %s", exc.detail)

        threading.Thread(target=run, name="alicia-whisper-load", daemon=True).start()

    def transcribe_samples(self, samples: np.ndarray, *, hotwords: str | None = None) -> str:
        """Transcription brève d'échantillons float32 à 16 kHz (mot de réveil)."""
        model = self.load()
        segments, _info = model.transcribe(
            samples,
            language=self.language,
            beam_size=1,
            vad_filter=False,
            condition_on_previous_text=False,
            without_timestamps=True,
            hotwords=hotwords,
        )
        text = " ".join(segment.text.strip() for segment in segments).strip()
        return "" if _HALLUCINATIONS.search(text) else text

    def _initial_prompt(self) -> str | None:
        """Aide Whisper à bien écrire les prénoms (le joueur, le robot)."""
        from alicia.core.people import known_names
        from alicia.core.persona import current, player

        names = ", ".join(
            dict.fromkeys(n for n in (player().name, current().title, *known_names()) if n)
        )
        prompt = " ".join(p for p in (self.prompt, f"{names}." if names else "") if p)
        return prompt or None

    def transcribe(self, audio: PreparedAudio) -> str:
        model = self.load()
        samples = wav_to_float(audio)
        started = time.perf_counter()
        segments, _info = model.transcribe(
            samples,
            language=self.language,
            beam_size=1,
            vad_filter=True,
            condition_on_previous_text=False,
            initial_prompt=self._initial_prompt(),
        )
        text = " ".join(segment.text.strip() for segment in segments).strip()
        elapsed = time.perf_counter() - started
        if _HALLUCINATIONS.search(text):
            log.info("Transcription écartée (silence ou bruit) en %.2f s", elapsed)
            text = ""
        log.info(
            "Transcription locale : %d caractères en %.2f s pour %.1f s d'audio",
            len(text),
            elapsed,
            audio.duration_s,
        )
        return text


TRANSCRIBE_PROMPT = (
    "Tu es un transcripteur. Écris exactement ce que dit la personne, en français, avec la "
    "ponctuation et l'orthographe correcte. C'est un joueur qui parle à son robot copilote "
    "pendant une partie : français parlé et familier (argot, gros mots, anglicismes, termes de "
    "jeux vidéo) — écris chaque mot tel qu'il est dit, sans l'adoucir ni le corriger, et en "
    "entier (« tocard », pas « toca »). Retire seulement les hésitations (euh, hum) et les mots "
    "répétés par bégaiement. N'ajoute rien, ne réponds pas à la question, pas de guillemets. "
    "Si tu n'entends aucun mot, réponds seulement : (silence)."
)


def _hints(extra: str = "") -> str:
    from alicia.core.people import known_names
    from alicia.core.persona import current, player

    names = ", ".join(
        dict.fromkeys(n for n in (player().name, current().title, *known_names()) if n)
    )
    out = f" Noms propres possibles : {names}." if names else ""
    if extra:
        out += f" Jeu en cours : {extra}."
    return out


class CloudTranscriber:
    """Transcription par Gemini (petit modèle rapide) : ~1 s au lieu de plusieurs sur le CPU.

    Même interface que LocalTranscriber.transcribe : le texte sert ensuite aux commandes
    vocales, aux noms corrigés (« Compris ») et au choix du cerveau, comme avant."""

    # Flash (plus juste que Flash-Lite), en réflexion minimale : toujours ~1 s.
    def __init__(self, ai_settings, model: str = "gemini-flash-latest") -> None:  # type: ignore[no-untyped-def]
        from dataclasses import replace

        from alicia.core.ai.factory import create_model

        gemini = replace(
            ai_settings.gemini, model=model, fallback_models=("gemini-flash-lite-latest",)
        )
        self.model = create_model(replace(ai_settings, provider="gemini", gemini=gemini))
        self.hint = ""  # titre du jeu en cours (aide pour les noms du jeu)

    def transcribe(self, audio: PreparedAudio) -> str:
        from alicia.core.ai.base import AnalysisRequest

        started = time.perf_counter()
        result = self.model.analyze(
            AnalysisRequest(
                question="Transcris ce message vocal.",
                images=(),
                system_prompt=TRANSCRIBE_PROMPT + _hints(self.hint),
                audio=audio,
                max_output_tokens=300,
                temperature=0.0,
                quick=True,
            )
        )
        text = result.text.strip().strip('"«» ')
        if text.casefold() in ("(silence)", "silence") or _HALLUCINATIONS.search(text):
            text = ""
        log.info(
            "Transcription Gemini : %d caractères en %.2f s pour %.1f s d'audio",
            len(text),
            time.perf_counter() - started,
            audio.duration_s,
        )
        return text


class OpenAITranscriber:
    """Transcription par OpenAI (gpt-4o-mini-transcribe) pour qui utilise ChatGPT : ~1 s,
    bien plus juste que Whisper « base » sur le PC. Même interface que CloudTranscriber."""

    MODEL = "gpt-4o-mini-transcribe"

    def __init__(self, ai_settings) -> None:  # type: ignore[no-untyped-def]
        self.settings = ai_settings.openai
        self.timeout = ai_settings.timeout_s
        self.hint = ""

    def transcribe(self, audio: PreparedAudio) -> str:
        import httpx

        from alicia.core.errors import ProviderError, ProviderErrorKind

        started = time.perf_counter()
        prompt = (
            "Joueur qui parle à son robot copilote pendant une partie, français familier."
            + _hints(self.hint)
        )
        try:
            response = httpx.post(
                self.settings.base_url.rstrip("/") + "/audio/transcriptions",
                headers={"Authorization": f"Bearer {self.settings.api_key.get() or ''}"},
                data={"model": self.MODEL, "language": "fr", "prompt": prompt},
                files={"file": ("question.wav", audio.data, audio.mime_type or "audio/wav")},
                timeout=min(30.0, self.timeout),
            )
        except httpx.HTTPError as exc:
            raise ProviderError(
                ProviderErrorKind.UNAVAILABLE, "Transcription OpenAI injoignable.", detail=repr(exc)
            ) from exc
        if response.status_code >= 400:
            kind = {401: ProviderErrorKind.AUTH, 429: ProviderErrorKind.RATE_LIMIT}.get(
                response.status_code, ProviderErrorKind.UNAVAILABLE
            )
            raise ProviderError(
                kind,
                f"Transcription OpenAI : erreur {response.status_code}.",
                detail=" ".join(response.text.split())[:300],
                status_code=response.status_code,
            )
        try:
            text = str(response.json().get("text", "")).strip().strip('"«» ')
        except ValueError:
            text = ""
        if _HALLUCINATIONS.search(text):
            text = ""
        log.info(
            "Transcription OpenAI : %d caractères en %.2f s pour %.1f s d'audio",
            len(text),
            time.perf_counter() - started,
            audio.duration_s,
        )
        return text
