"""Réponse vocale interruptible, phrase par phrase.

Inspiré de RealtimeTTS (EdgeEngine, MIT) et de huburton/jarvis (lecture phrase par phrase
interruptible, MIT) : la phrase suivante est synthétisée pendant que la précédente est lue,
pour que la voix démarre vite. Voix Microsoft Edge (``edge-tts``) décodée par ``miniaudio`` :
aucun lecteur externe (mpv, ffmpeg) à installer sous Windows.
"""

from __future__ import annotations

import asyncio
import logging
import queue
import re
import threading
import time
from collections import deque
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace

import numpy as np

from alicia.core.audio.devices import AudioError, device_name, find_device, sounddevice
from alicia.core.audio.text import split_sentences
from alicia.core.config import VoiceSettings

log = logging.getLogger("alicia.audio")

TTS_SAMPLE_RATE = 24000
Synthesizer = Callable[[str], np.ndarray]  # phrase → échantillons int16 mono à 24 kHz


def edge_synthesizer(voice: str, rate: str) -> Synthesizer:
    def synthesize(text: str) -> np.ndarray:
        try:
            import edge_tts
            import miniaudio
        except ImportError as exc:
            raise AudioError(
                "Modules de voix absents (edge-tts, miniaudio).", detail=repr(exc)
            ) from exc

        async def fetch() -> bytes:
            communicate = edge_tts.Communicate(text, voice, rate=rate)
            data = bytearray()
            async for chunk in communicate.stream():
                if chunk.get("type") == "audio":
                    data.extend(chunk["data"])
            return bytes(data)

        from alicia.core import usage

        usage.add("tts_edge")
        try:
            mp3 = asyncio.run(fetch())
        except Exception as exc:  # noqa: BLE001 - réseau, voix inconnue, service changé
            raise AudioError(
                "La voix en ligne (Microsoft Edge) ne répond pas. Vérifie ta connexion ou "
                "le nom de la voix ([voice] tts_voice).",
                detail=repr(exc),
            ) from exc
        if not mp3:
            raise AudioError("La voix en ligne n'a renvoyé aucun son.", detail=f"voix {voice}")
        decoded = miniaudio.decode(
            mp3,
            output_format=miniaudio.SampleFormat.SIGNED16,
            nchannels=1,
            sample_rate=TTS_SAMPLE_RATE,
        )
        return np.frombuffer(decoded.samples, dtype=np.int16)

    return synthesize


def kokoro_synthesizer(voice: str, speed: float, lang: str = "fr-fr") -> Synthesizer:
    """Voix Kokoro locale (ONNX, processeur) : gratuite, hors ligne, ne prend pas le GPU."""
    state: dict[str, object] = {}
    lock = threading.Lock()

    def engine():  # type: ignore[no-untyped-def]
        with lock:
            if "kokoro" not in state:
                from alicia.core.audio.models import kokoro_paths, kokoro_ready

                if not kokoro_ready():
                    raise AudioError(
                        "La voix Kokoro n'est pas installée. Relance Installer_COPIALOTE.bat ou "
                        "lance : alicia-diag prepare-voice",
                        detail="fichiers Kokoro absents",
                    )
                try:
                    from kokoro_onnx import Kokoro
                except ImportError as exc:
                    raise AudioError("Module kokoro-onnx absent.", detail=repr(exc)) from exc
                started = time.perf_counter()
                model, voices = kokoro_paths()
                state["kokoro"] = Kokoro(str(model), str(voices))
                log.info("Kokoro chargé en %.1f s", time.perf_counter() - started)
            return state["kokoro"]

    def synthesize(text: str) -> np.ndarray:
        kokoro = engine()
        with lock:  # une synthèse à la fois : la session ONNX utilise déjà tous les cœurs prévus
            try:
                audio, rate = kokoro.create(text, voice=voice, speed=speed, lang=lang)  # type: ignore[attr-defined]
            except Exception as exc:  # noqa: BLE001
                raise AudioError("La voix Kokoro a échoué.", detail=repr(exc)) from exc
        if rate != TTS_SAMPLE_RATE:
            raise AudioError("Fréquence inattendue pour Kokoro.", detail=f"{rate} Hz")
        return (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)

    synthesize.warm_up = engine  # type: ignore[attr-defined]
    return synthesize


OPENAI_VOICE_STYLE = (
    "Parle en français naturel, comme une coéquipière de jeu vidéo : ton chaleureux, "
    "vif et complice, phrases courtes, sans lire la ponctuation ni les symboles."
)


def openai_synthesizer(settings: VoiceSettings, fallback: bool = True) -> Synthesizer:
    """Voix OpenAI (API audio/speech) : très naturelle, payante à l'usage."""
    import httpx

    # gpt-4o-mini-tts ignore son paramètre « speed » : la vitesse passe par la consigne.
    pace = pace_hint(settings.tts_rate)

    def synthesize(text: str) -> np.ndarray:
        if not settings.openai_key:
            raise AudioError(
                "Voix OpenAI : il faut une clé OpenAI (bouton IA → ChatGPT), ou choisis la voix "
                "Edge dans les réglages.",
                detail="OPENAI_API_KEY absente",
            )
        from alicia.core import usage

        usage.add("tts_openai")
        try:
            response = httpx.post(
                f"{settings.openai_base_url}/audio/speech",
                headers={"Authorization": f"Bearer {settings.openai_key.get()}"},
                json={
                    "model": settings.openai_tts_model,
                    "voice": settings.openai_voice,
                    "input": text,
                    "instructions": OPENAI_VOICE_STYLE
                    + (
                        f" Parle {VOICE_EFFECTS[settings.voice_effect][4]}."
                        if settings.voice_effect in VOICE_EFFECTS
                        else ""
                    )
                    + (f" Voix et jeu : {settings.voice_style}." if settings.voice_style else "")
                    + (f" Parle {pace}." if pace else ""),
                    "response_format": "pcm",  # 24 kHz, 16 bits, mono
                },
                timeout=30,
            )
        except httpx.HTTPError as exc:
            raise AudioError("Voix OpenAI injoignable.", detail=repr(exc)) from exc
        if response.status_code == 401:
            raise AudioError("Voix OpenAI : clé refusée.", detail="HTTP 401")
        if response.status_code == 429:
            raise AudioError(
                "Voix OpenAI : plus de crédit ou trop de demandes.", detail=response.text[:200]
            )
        if response.status_code >= 400:
            raise AudioError(
                f"Voix OpenAI : erreur {response.status_code}.", detail=response.text[:300]
            )
        data = response.content
        return np.frombuffer(data[: len(data) - len(data) % 2], dtype=np.int16)

    if not settings.openai_key or not fallback:
        return synthesize
    from alicia.core.audio import voice_design

    return voice_design.with_fallback(synthesize, _profile_fallback(settings))


VERIS_PITCH_CENTS = 450  # recette VERIS MOD : Kokoro ff_siwis, +450 cents (= voix C d'ALICIA)
VIIRUS_PITCH_CENTS = 600  # VIIRUS : petit garçon robot, voix aiguë et vive, un peu métallique
VIIRUS_METAL = 0.6


def robot_voice(
    samples: np.ndarray,
    ratio: float,
    rate: int = TTS_SAMPLE_RATE,
    *,
    highpass_hz: float = 200.0,
    presence_hz: float = 3500.0,
    metallic: float = 0.0,
) -> np.ndarray:
    """Voix de VIIRUS à partir d'une voix générée ``ratio`` fois plus lente : on la raccourcit
    (la hauteur monte d'autant, la durée redevient normale), puis passe-haut 200 Hz,
    +3 dB vers 3,5 kHz et volume normalisé. Tout dans le domaine fréquentiel (numpy seul)."""
    audio = samples.astype(np.float32)
    if samples.dtype == np.int16:
        audio /= 32768.0
    n = len(audio)
    if n < 32:
        return (np.clip(audio, -1, 1) * 32767).astype(np.int16)
    m = max(1, round(n / ratio))
    spectrum = np.fft.rfft(audio)[: m // 2 + 1]  # coupe au-dessus de Nyquist : pas de repliement
    if len(spectrum) < m // 2 + 1:  # voix plus grave (ratio < 1) : on complète par du silence
        spectrum = np.pad(spectrum, (0, m // 2 + 1 - len(spectrum)))
    freqs = np.fft.rfftfreq(m, 1.0 / rate)
    with np.errstate(divide="ignore"):
        highpass = 1.0 / np.sqrt(1.0 + (highpass_hz / np.maximum(freqs, 1.0)) ** 4)
        octaves = np.log2(np.maximum(freqs, 1.0) / presence_hz)
    presence = 1.0 + (10 ** (3 / 20) - 1.0) * np.exp(-(octaves**2) / (2 * 0.5**2))
    out = np.fft.irfft(spectrum * highpass * presence, m) * (m / n)
    if metallic > 0:
        # Timbre de robot : écho très court (filtre en peigne, son « boîte de conserve »)
        # et légère modulation en anneau, comme un haut-parleur de petit robot.
        delay = max(1, int(rate * 0.0045))
        comb = out.copy()
        comb[delay:] += 0.55 * metallic * out[:-delay]
        t = np.arange(m, dtype=np.float32) / rate
        ring = 1.0 - 0.35 * metallic + 0.35 * metallic * np.sin(2 * np.pi * 55.0 * t)
        out = comb * ring
    rms = float(np.sqrt(np.mean(out**2))) or 1.0
    out *= 10 ** (-17 / 20) / rms
    peak = float(np.abs(out).max(initial=0))
    if peak > 0.79:
        out *= 0.79 / peak
    return (np.clip(out, -1.0, 1.0) * 32767).astype(np.int16)


def veris_synthesizer(
    speed: float = 1.0,
    ratio: float = 2 ** (VIIRUS_PITCH_CENTS / 1200),
    highpass_hz: float = 260.0,
    presence_hz: float = 4200.0,
    metallic: float = VIIRUS_METAL,
) -> Synthesizer:
    """La voix de VIIRUS (VERIS MOD) : Kokoro ff_siwis rendue plus aiguë et métallique.
    Avec d'autres réglages : la « voix C » d'ALICIA (petite fille)."""
    base = kokoro_synthesizer("ff_siwis", max(0.5, speed / ratio))
    # Sans les fichiers Kokoro : même traitement sur la voix Edge ralentie d'autant.
    fallback = edge_synthesizer("fr-FR-DeniseNeural", f"{round((1 / ratio - 1) * 100):+d}%")

    def synthesize(text: str) -> np.ndarray:
        from alicia.core.audio.models import kokoro_ready

        source = fallback(text) if not kokoro_ready() else base(text)
        return robot_voice(
            source, ratio, highpass_hz=highpass_hz, presence_hz=presence_hz, metallic=metallic
        )

    synthesize.warm_up = base.warm_up  # type: ignore[attr-defined]
    return synthesize


GEMINI_TTS_MODEL = "gemini-3.1-flash-tts-preview"
GEMINI_TTS_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_VOICE_STYLE = "Dis en français, d'un ton naturel et vivant de coéquipier de jeu : "


def looks_cut(text: str, samples: np.ndarray, rate: int = TTS_SAMPLE_RATE) -> bool:
    """Le son est-il bien trop court pour ce texte ? (Gemini s'arrête parfois en route.)
    On parle 2 à 4 mots par seconde ; moins d'1 s pour 6 mots = la fin manque."""
    words = len(re.findall(r"\w+", text))
    if words < 6:
        return False
    return len(samples) / rate < words / 6.5


def complete_or_retry(synthesize: Synthesizer, label: str) -> Synthesizer:
    """Si la phrase revient tronquée, un 2e essai ; on garde le son le plus long."""

    def run(text: str) -> np.ndarray:
        samples = synthesize(text)
        if not looks_cut(text, samples):
            return samples
        log.warning(
            "Voix %s : phrase coupée (%.1f s pour %d caractères), 2e essai",
            label,
            len(samples) / TTS_SAMPLE_RATE,
            len(text),
        )
        again = synthesize(text)
        return again if len(again) > len(samples) else samples

    warm = getattr(synthesize, "warm_up", None)
    if warm is not None:
        run.warm_up = warm  # type: ignore[attr-defined]
    return run


def pace_hint(rate: str) -> str:
    """Vitesse demandée par consigne (Gemini, ChatGPT : pas de réglage de débit chez eux)."""
    try:
        percent = int(rate.strip().rstrip("%"))
    except ValueError:
        return ""
    if percent >= 25:
        return "vite, avec un débit rapide"
    if percent >= 10:
        return "un peu plus vite que d'habitude"
    if percent <= -25:
        return "lentement, en prenant ton temps"
    if percent <= -10:
        return "posément, un peu plus lentement"
    return ""


def _gemini_style(settings: VoiceSettings) -> str:
    pace = pace_hint(settings.tts_rate)
    pace = f", {pace}" if pace else ""
    if settings.voice_style:  # consigne libre écrite par le joueur
        return f"Dis en français, {settings.voice_style}{pace} : "
    effect = VOICE_EFFECTS.get(settings.voice_effect)
    if effect is None:
        return GEMINI_VOICE_STYLE[:-3] + pace + " : " if pace else GEMINI_VOICE_STYLE
    return f"Dis en français, {effect[4]}{pace} : "


def gemini_synthesizer(settings: VoiceSettings, fallback: bool = True) -> Synthesizer:
    """Voix Gemini (30 voix, avec ta clé Gemini) : PCM 24 kHz 16 bits mono."""
    import base64

    import httpx

    from alicia.core.audio import voice_design

    if settings.gemini_voice.startswith("voice_"):  # voix générée (Gemini 3.8)
        designed = complete_or_retry(
            voice_design.designed_synthesizer(
                settings.gemini_key.get() or "", settings.gemini_voice, _designed_style(settings)
            ),
            "Gemini 3.8",
        )
        if not settings.gemini_key or not fallback:
            return designed
        return voice_design.with_fallback(designed, _profile_fallback(settings))

    def synthesize(text: str) -> np.ndarray:
        if not settings.gemini_key:
            raise AudioError(
                "Voix Gemini : il faut une clé Gemini (bouton IA → Gemini).",
                detail="GEMINI_API_KEY absente",
            )
        from alicia.core import usage

        usage.add("tts_gemini_38" if "3.8" in settings.gemini_tts_model else "tts_gemini_31")
        try:
            response = httpx.post(
                GEMINI_TTS_URL.format(model=settings.gemini_tts_model),
                headers={"x-goog-api-key": settings.gemini_key.get()},
                json={
                    "contents": [{"parts": [{"text": _gemini_style(settings) + text}]}],
                    "generationConfig": {
                        "responseModalities": ["AUDIO"],
                        "speechConfig": {
                            "voiceConfig": {
                                "prebuiltVoiceConfig": {"voiceName": settings.gemini_voice}
                            }
                        },
                    },
                },
                timeout=30,
            )
        except httpx.HTTPError as exc:
            raise AudioError("Voix Gemini injoignable.", detail=repr(exc)) from exc
        if response.status_code == 429:
            raise AudioError(
                "Voix Gemini : quota gratuit atteint pour l'instant, réessaie plus tard.",
                detail=response.text[:200],
            )
        if response.status_code >= 400:
            raise AudioError(
                f"Voix Gemini : erreur {response.status_code}.", detail=response.text[:300]
            )
        try:
            candidate = response.json()["candidates"][0]
            parts = candidate["content"]["parts"]
            # TOUS les morceaux : n'en garder qu'un coupait parfois la fin du message
            data = b"".join(
                base64.b64decode(p["inlineData"]["data"]) for p in parts if "inlineData" in p
            )
            if not data:
                raise KeyError("inlineData")
            if candidate.get("finishReason") not in (None, "STOP"):
                log.warning("Voix Gemini : fin anormale (%s)", candidate.get("finishReason"))
        except (KeyError, IndexError, StopIteration, ValueError) as exc:
            body = response.text
            if "blockReason" in body or "PROHIBITED" in body or "SAFETY" in body:
                # Google refuse de dire CETTE phrase : la voix de secours la dit à sa place.
                raise voice_design.VoiceBlocked(
                    "Voix Gemini : phrase refusée par Google.",
                    detail="phrase bloquée (" + " ".join(body.split())[:120] + ")",
                ) from exc
            raise AudioError(
                "Voix Gemini : réponse sans audio.", detail=" ".join(body.split())[:300]
            ) from exc
        return np.frombuffer(data[: len(data) - len(data) % 2], dtype=np.int16)

    def with_retry(text: str) -> np.ndarray:
        # Google coupe parfois une phrase au hasard (« SAFETY », « retry your request ») :
        # un 2e essai passe souvent ; sinon la voix de secours la dit.
        try:
            return synthesize(text)
        except voice_design.VoiceBlocked:
            return synthesize(text)

    with_retry = complete_or_retry(with_retry, "Gemini")

    if not settings.gemini_key or not fallback:
        return with_retry  # sans clé : le message « il faut une clé » reste affiché
    return voice_design.with_fallback(with_retry, _profile_fallback(settings))


def _local_fallback(settings: VoiceSettings) -> Synthesizer:
    from alicia.core.persona import current

    if current().key == "veris":
        return veris_synthesizer(settings.kokoro_speed)
    return veris_synthesizer(settings.kokoro_speed, 1.30, 220.0, 3800.0, metallic=0.0)


# « local » : la voix robot du profil ; veris / voixc : une voix intégrée précise
BACKUP_ENGINES = ("local", "edge", "gemini", "openai", "kokoro", "veris", "voixc", "custom")
LOCAL_ENGINES = ("veris", "voixc", "local")  # voix intégrées : gardées telles quelles

# Dernière phrase dite par la voix de secours (horloge monotone) : « en cours d'utilisation »
BACKUP_USED = {"t": -1e9}


def backup_in_use(window_s: float = 120.0) -> bool:
    """Vrai si la voix de secours parle en ce moment à la place de la principale."""
    from alicia.core.audio import voice_design

    now = time.monotonic()
    return now - BACKUP_USED["t"] < window_s or voice_design.online_paused()


def split_backup(value: str) -> tuple[str, str]:
    """« gemini:Puck » → ("gemini", "Puck") ; ancien format « fr-FR-… » → Edge ; "" → robot."""
    if not value:
        return "local", ""
    engine, sep, name = value.partition(":")
    if sep and engine in BACKUP_ENGINES:
        return engine, name
    return "edge", value


def _voice_field(engine: str) -> str:
    return {"gemini": "gemini_voice", "openai": "openai_voice", "kokoro": "kokoro_voice"}.get(
        engine, "tts_voice"
    )


def backup_settings(settings: VoiceSettings) -> VoiceSettings:
    """Les réglages de la voix de secours, sous la forme de réglages de voix ordinaires
    (sa voix, SA vitesse, SES effets, SON jeu de voix) : rien n'est pris à la principale."""
    engine, name = split_backup(settings.backup_voice)
    if engine == "custom":  # ancienne forme « custom:id » (v0.17) : ses réglages enregistrés
        from alicia.core.audio.custom_voices import get_custom

        custom = get_custom(name)
        if custom is None:
            return replace(settings, tts_engine="local", backup_voice="")
        engine, name = custom.engine, custom.voice
        settings = replace(
            settings,
            backup_rate=f"{custom.rate:+d}%",
            backup_pitch=custom.pitch,
            backup_metal=custom.metal,
            backup_bright=custom.bright,
            backup_reverb=custom.reverb,
            backup_style=custom.style,
            backup_volume=custom.volume,
        )
    changes: dict[str, object] = {
        "tts_engine": "local" if engine == "local" or not name else engine,
        "tts_rate": settings.backup_rate,
        "kokoro_speed": round(_speed(settings.backup_rate), 2),
        "voice_effect": "",
        "voice_style": settings.backup_style,
        "fx_pitch": settings.backup_pitch,
        "fx_metal": settings.backup_metal,
        "fx_bright": settings.backup_bright,
        "fx_reverb": settings.backup_reverb,
        "volume": settings.backup_volume,
    }
    if engine not in LOCAL_ENGINES and name:
        changes[_voice_field(engine)] = name
    return replace(settings, **changes)  # type: ignore[arg-type]


def _speed(rate: str) -> float:
    try:
        return max(0.5, min(2.0, 1 + int(rate.strip().rstrip("%")) / 100))
    except ValueError:
        return 1.0


def _designed_style(settings: VoiceSettings) -> str:
    style = settings.voice_style
    if not style:
        effect = VOICE_EFFECTS.get(settings.voice_effect)
        style = "ton naturel et vivant de coéquipier de jeu" if effect is None else effect[4]
    pace = pace_hint(settings.tts_rate)
    return f"{style}, {pace}" if pace else style


def primary_synthesizer(settings: VoiceSettings) -> Synthesizer:
    """La voix ``settings`` avec tous ses réglages (vitesse, hauteur, robot, clarté,
    réverbération, jeu de voix), SANS voix de secours derrière."""
    pitch, metal, bright = settings.fx_pitch, settings.fx_metal, settings.fx_bright
    reverb, engine = settings.fx_reverb, settings.tts_engine
    if engine == "veris" or (engine == "local" and _local_is_veris()):
        return veris_synthesizer(settings.kokoro_speed)
    if engine in ("voixc", "local"):
        return veris_synthesizer(settings.kokoro_speed, 1.30, 220.0, 3800.0, metallic=0.0)
    if engine == "edge":  # vitesse native ; la hauteur passe par une voix générée ralentie
        ratio = 2 ** (pitch / 12)
        slowed = abs(pitch) >= 0.01
        rate = _slowed_rate(settings.tts_rate, ratio) if slowed else settings.tts_rate
        base = edge_synthesizer(settings.tts_voice, rate)
        return with_fx(base, pitch, metal, bright, reverb, pre_slowed=slowed)
    if engine == "kokoro":  # vitesse native
        base = kokoro_synthesizer(settings.kokoro_voice, settings.kokoro_speed)
        return with_fx(base, pitch, metal, bright, reverb)
    if engine == "openai":  # vitesse par consigne (voir pace_hint)
        base = openai_synthesizer(settings, fallback=False)
    else:
        base = gemini_synthesizer(settings, fallback=False)
    return with_fx(base, pitch, metal, bright, reverb)


def _local_is_veris() -> bool:
    from alicia.core.persona import current

    return current().key == "veris"


def backup_synthesizer(settings: VoiceSettings) -> Synthesizer:
    """La voix de secours toute seule (pour l'écouter) : ses réglages, son volume."""
    voice = backup_settings(settings)
    base = primary_synthesizer(voice)
    gain = voice.volume / max(1, settings.volume)  # le haut-parleur applique déjà le volume
    if abs(gain - 1.0) < 0.01:  # de la principale : on corrige l'écart
        return base

    def synthesize(text: str) -> np.ndarray:
        samples = base(text).astype(np.float32) * gain
        return np.clip(samples, -32768, 32767).astype(np.int16)

    return synthesize


def _no_backup(_text: str) -> np.ndarray:
    raise AudioError(
        "Voix principale indisponible pour l'instant, et la voix de secours est désactivée "
        "(Profil → Voix).",
        detail="secours désactivé",
    )


def _profile_fallback(settings: VoiceSettings) -> Synthesizer:
    """Ce qui parle quand la voix principale échoue : la voix de secours avec ses propres
    réglages ; si elle échoue aussi, la voix robot du profil (sur le PC)."""
    if not settings.backup_enabled:
        return _no_backup
    local = _local_fallback(settings)
    backup = backup_synthesizer(settings)

    def synthesize(text: str) -> np.ndarray:
        BACKUP_USED["t"] = time.monotonic()
        try:
            return backup(text)
        except AudioError as exc:
            log.warning("Voix de secours indisponible : %s", exc.detail)
            return local(text)

    return synthesize


# Effets de voix, applicables à Edge, Gemini, OpenAI et Kokoro :
# (hauteur en cents, passe-haut, présence, métal, consigne de jeu pour Gemini / OpenAI)
VOICE_EFFECTS: dict[str, tuple[int, float, float, float, str]] = {
    "masculin": (
        -200,
        120.0,
        3000.0,
        0.0,
        "avec une voix masculine, posée et naturelle",
    ),
    "feminin": (
        200,
        220.0,
        4000.0,
        0.0,
        "avec une voix féminine, claire et naturelle",
    ),
    "enfant": (
        620,
        280.0,
        4300.0,
        0.0,
        "avec une voix aiguë, pétillante et pleine d'énergie de personnage de dessin animé",
    ),
    "robot": (
        200,
        200.0,
        3500.0,
        1.0,
        "comme un petit robot attachant : débit régulier, un peu mécanique, articulé",
    ),
    "robot_enfant": (
        600,
        260.0,
        4200.0,
        0.6,
        "comme un petit robot de dessin animé espiègle : voix aiguë, vive, rieuse, un peu "
        "mécanique",
    ),
    "robote": (
        300,
        240.0,
        4000.0,
        0.45,
        "comme une petite robote de dessin animé espiègle : voix aiguë, vive, rieuse, un peu "
        "mécanique",
    ),
    "gros_robot": (
        -350,
        90.0,
        2500.0,
        1.0,
        "comme un grand robot imposant : voix grave, lente, détachée, très mécanique",
    ),
}


def time_stretch(samples: np.ndarray, rate: float, n_fft: int = 1024) -> np.ndarray:
    """Change la durée sans changer la hauteur (vocodeur de phase, numpy seul).
    ``rate`` > 1 : plus court ; < 1 : plus long."""
    audio = samples.astype(np.float32)
    if samples.dtype == np.int16:
        audio /= 32768.0
    hop = n_fft // 4
    if len(audio) < n_fft * 2 or abs(rate - 1.0) < 1e-3:
        return audio
    window = np.hanning(n_fft).astype(np.float32)
    frames = 1 + (len(audio) - n_fft) // hop
    index = np.arange(n_fft)[None, :] + hop * np.arange(frames)[:, None]
    spectrum = np.fft.rfft(audio[index] * window, axis=1)
    steps = np.arange(0, frames - 1, rate)
    expected = 2 * np.pi * hop * np.arange(spectrum.shape[1]) / n_fft
    phase = np.angle(spectrum[0])
    out = np.zeros(len(steps) * hop + n_fft, dtype=np.float32)
    norm = np.zeros_like(out)
    for k, step in enumerate(steps):
        i = int(step)
        frac = step - i
        mag = (1 - frac) * np.abs(spectrum[i]) + frac * np.abs(spectrum[i + 1])
        frame = np.fft.irfft(mag * np.exp(1j * phase), n_fft).astype(np.float32) * window
        out[k * hop : k * hop + n_fft] += frame
        norm[k * hop : k * hop + n_fft] += window**2
        delta = np.angle(spectrum[i + 1]) - np.angle(spectrum[i]) - expected
        delta -= 2 * np.pi * np.round(delta / (2 * np.pi))
        phase += expected + delta
    return out / np.maximum(norm, 1e-3)


# Réglages de chaque effet : (hauteur en demi-tons, métal en %, clarté en %). Ce ne sont
# que des points de départ : les curseurs Hauteur / Métal / Clarté les ajustent.
# « Enfant » monte peu : au-delà de ~3 demi-tons, le calcul laisse un grain métallique.
# Décalages volontairement modérés : au-delà de ~3 demi-tons, la voix sonne trafiquée.
FX_PRESETS: dict[str, tuple[float, int, int]] = {
    "": (0.0, 0, 50),
    "masculin": (-2.0, 0, 40),
    "feminin": (2.0, 0, 60),
    "enfant": (2.5, 0, 65),  # « Jeune »
    "robot": (0.0, 70, 45),
    "robote": (2.5, 50, 55),
    "robot_enfant": (4.5, 50, 60),  # « Petit robot (VIIRUS) »
    "gros_robot": (-3.0, 90, 15),
}


def fx_neutral(pitch: float, metal: int, bright: int, reverb: int = 0) -> bool:
    return abs(pitch) < 0.01 and metal <= 0 and bright == 50 and reverb <= 0


def add_reverb(samples: np.ndarray, amount: int, rate: int = TTS_SAMPLE_RATE) -> np.ndarray:
    """Réverbération (0-100 %) : petite pièce → grande salle. Réponse impulsionnelle de bruit
    à décroissance exponentielle (douce, sans écho métallique), convoluée par FFT."""
    amount = max(0, min(100, int(amount)))
    if amount <= 0 or len(samples) < 32:
        return samples
    dry = samples.astype(np.float32)
    if samples.dtype == np.int16:
        dry /= 32768.0
    decay = 0.25 + amount / 100 * 1.2  # secondes pour -60 dB
    length = int(rate * min(2.0, decay * 1.1))
    t = np.arange(length, dtype=np.float32) / rate
    rng = np.random.default_rng(7)  # même salle à chaque phrase
    impulse = rng.standard_normal(length).astype(np.float32) * np.exp(-6.9 * t / decay)
    impulse[: int(rate * 0.012)] = 0.0  # pré-délai : la voix reste devant
    impulse /= float(np.sqrt(np.sum(impulse**2))) or 1.0
    size = len(dry) + length - 1
    n = 1 << (size - 1).bit_length()
    wet = np.fft.irfft(np.fft.rfft(dry, n) * np.fft.rfft(impulse, n), n)[:size]
    tail = int(rate * min(1.0, decay * 0.6))  # un peu de queue après la dernière syllabe
    mix = amount / 100 * 0.55
    out = np.zeros(len(dry) + tail, dtype=np.float32)
    out[: len(dry)] = dry * (1.0 - 0.35 * mix)
    out += wet[: len(out)] * mix
    peak = float(np.abs(out).max(initial=0))
    if peak > 0.89:
        out *= 0.89 / peak
    return (np.clip(out, -1.0, 1.0) * 32767).astype(np.int16)


def with_fx(
    base: Synthesizer,
    pitch: float,
    metal: int,
    bright: int,
    reverb: int = 0,
    *,
    pre_slowed: bool = False,
) -> Synthesizer:
    """Hauteur (demi-tons), métal (0-100 %), clarté (0-100 %, 50 = neutre) et réverbération
    (0-100 %) sur une voix.

    ``pre_slowed`` : la voix est déjà générée ralentie du bon facteur (Edge sait le faire,
    c'est plus propre) ; sinon on l'étire d'abord sans changer sa hauteur."""
    if fx_neutral(pitch, metal, bright, reverb):
        return base
    if fx_neutral(pitch, metal, bright):  # réverbération seule : la voix reste intacte

        def reverb_only(text: str) -> np.ndarray:
            return add_reverb(base(text), reverb)

        warm = getattr(base, "warm_up", None)
        if warm is not None:
            reverb_only.warm_up = warm  # type: ignore[attr-defined]
        return reverb_only
    ratio = 2 ** (pitch / 12)
    bright = max(0, min(100, bright))
    highpass, presence = 80.0 + bright * 3.0, 2500.0 + bright * 30.0

    def synthesize(text: str) -> np.ndarray:
        samples = base(text)
        if not pre_slowed and abs(pitch) >= 0.01:
            samples = time_stretch(samples, 1 / ratio)
        out = robot_voice(
            samples,
            ratio,
            highpass_hz=highpass,
            presence_hz=presence,
            metallic=max(0, min(100, metal)) / 100,
        )
        return add_reverb(out, reverb)

    warm = getattr(base, "warm_up", None)
    if warm is not None:
        synthesize.warm_up = warm  # type: ignore[attr-defined]
    return synthesize


def with_effect(base: Synthesizer, effect: str, *, pre_slowed: bool = False) -> Synthesizer:
    """Applique un effet tout fait (enfant, robot…) avec ses réglages de départ."""
    if effect not in FX_PRESETS or not effect:
        return base
    return with_fx(base, *FX_PRESETS[effect], pre_slowed=pre_slowed)


def _slowed_rate(rate: str, ratio: float) -> str:
    try:
        percent = int(rate.strip().rstrip("%"))
    except ValueError:
        percent = 0
    return f"{round(((1 + percent / 100) / ratio - 1) * 100):+d}%"


def make_synthesizer(settings: VoiceSettings) -> Synthesizer:
    """La voix principale avec ses réglages, et la voix de secours derrière (voix en ligne)."""
    primary = primary_synthesizer(settings)
    engine = settings.tts_engine
    if engine in ("veris", "voixc", "kokoro", "local"):
        return primary  # sur le PC : rien qui puisse tomber en panne de quota
    if (engine == "gemini" and not settings.gemini_key) or (
        engine == "openai" and not settings.openai_key
    ):
        return primary  # sans clé : le message « il faut une clé » reste affiché
    from alicia.core.audio import voice_design

    return voice_design.with_fallback(primary, _profile_fallback(settings))


class SoundDevicePlayer:
    """Lecture par blocs, arrêtable à tout moment."""

    def __init__(self, device: str = "") -> None:
        self.device = device
        self.level = 0.0  # niveau de la voix en cours (0-1), lu par l'interface

    def open(self, device: str | None = None):  # type: ignore[no-untyped-def]
        sd = sounddevice()
        index = find_device(self.device if device is None else device, output=True)
        stream = sd.OutputStream(
            samplerate=TTS_SAMPLE_RATE, channels=1, dtype="int16", device=index
        )
        stream.start()
        log.debug("Sortie audio : %s", device_name(index, output=True))
        return stream

    def play(self, stream, samples: np.ndarray, stop: threading.Event) -> None:  # type: ignore[no-untyped-def]
        block = TTS_SAMPLE_RATE // 20  # 50 ms : l'arrêt est quasi immédiat
        try:
            for start in range(0, len(samples), block):
                if stop.is_set():
                    return
                chunk = samples[start : start + block]
                self.level = float(np.abs(chunk).max()) / 32768.0 if len(chunk) else 0.0
                stream.write(chunk.reshape(-1, 1))
        finally:
            self.level = 0.0

    @staticmethod
    def close(stream) -> None:  # type: ignore[no-untyped-def]
        try:
            stream.stop()
            stream.close()
        except Exception:  # noqa: BLE001
            pass


def apply_volume(samples: np.ndarray, percent: int) -> np.ndarray:
    """Volume de la voix du robot (100 = normal, jusqu'à 200 ; écrêtage évité)."""
    if percent == 100:
        return samples
    gain = max(0, min(200, percent)) / 100
    return np.clip(samples.astype(np.float32) * gain, -32768, 32767).astype(np.int16)


class Speaker:
    """Lit une réponse ; ``stop()`` coupe la voix immédiatement."""

    def __init__(
        self,
        settings: VoiceSettings,
        synthesizer: Synthesizer | None = None,
        player: SoundDevicePlayer | None = None,
    ) -> None:
        self.settings = settings
        self.synthesizer = synthesizer or make_synthesizer(settings)
        self.player = player or SoundDevicePlayer(settings.output_device)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._queue: queue.Queue[str | None] | None = None
        # Copie de chaque phrase jouée (overlay OBS : sa voix sur sa propre source audio)
        self.on_audio: Callable[[np.ndarray], None] | None = None
        self.on_state: Callable[[str, str | None], None] = lambda _state, _msg: None

    @property
    def min_chars(self) -> int:
        return 160 if self.settings.tts_engine in ("gemini", "openai") else 25

    @property
    def level(self) -> float:
        return float(getattr(self.player, "level", 0.0)) if self.speaking else 0.0

    @property
    def speaking(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def speak(
        self, text: str, synthesizer: Synthesizer | None = None, device: str | None = None
    ) -> bool:
        """Lit ``text`` (avec une autre voix si ``synthesizer`` est donné : écoute d'essai)."""
        from alicia.core.persona import pronounce

        self.stop()
        # Voix en ligne : phrases regroupées (≈ 160 caractères) → moins d'appels, moins de quota
        sentences = split_sentences(pronounce(text), min_chars=self.min_chars)
        if not sentences:
            return False
        source: queue.Queue[str | None] = queue.Queue()
        for sentence in sentences:
            source.put(sentence)
        source.put(None)
        self._start(source, synthesizer, device)
        return True

    # --- lecture au fil de l'eau : la voix part dès la 1re phrase écrite par l'IA -----------

    def stream_begin(self) -> None:
        self.stop()
        self._queue = queue.Queue()
        self._start(self._queue, None)

    def stream_feed(self, sentence: str) -> None:
        from alicia.core.persona import pronounce

        if self._queue is not None and sentence.strip():
            self._queue.put(pronounce(sentence))

    def stream_end(self) -> None:
        if self._queue is not None:
            self._queue.put(None)
            self._queue = None

    def _start(
        self,
        source: queue.Queue[str | None],
        synthesizer: Synthesizer | None,
        device: str | None = None,
    ) -> None:
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            args=(source, self._stop, synthesizer or self.synthesizer, device),
            name="alicia-voice",
            daemon=True,
        )
        self._thread.start()

    def warm_up_async(self) -> None:
        """Charge un moteur local (Kokoro) en arrière-plan pour que la 1re réponse parte vite."""
        warm = getattr(self.synthesizer, "warm_up", None)
        if warm is None:
            return

        def run() -> None:
            try:
                warm()
            except AudioError as exc:
                log.error("Préchargement de la voix : %s", exc.detail)

        threading.Thread(target=run, name="alicia-voice-load", daemon=True).start()

    def stop(self) -> None:
        self._queue = None
        if self.speaking:
            self._stop.set()
            log.info("Voix coupée")
            self._thread.join(1.0)  # type: ignore[union-attr]

    def _run(
        self,
        source: queue.Queue[str | None],
        stop: threading.Event,
        synthesizer: Synthesizer | None = None,
        device: str | None = None,  # autre sortie (Mode Stream : seulement dans ton casque)
    ) -> None:
        synthesize = synthesizer or self.synthesizer
        started = time.perf_counter()
        stream = None
        error: str | None = None
        pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="alicia-tts")
        futures: deque[Future] = deque()
        finished = False
        played = False
        idle_since = time.monotonic()

        def pull(wait: float) -> None:
            """Prend la phrase suivante (et lance sa synthèse : 2 d'avance)."""
            nonlocal finished, idle_since
            try:
                item = source.get(timeout=wait) if wait else source.get_nowait()
            except queue.Empty:
                return
            if item is None:
                finished = True
            else:
                futures.append(pool.submit(synthesize, item))
                idle_since = time.monotonic()

        try:
            while not stop.is_set():
                while not finished and len(futures) < 2 and not source.empty():
                    pull(0)
                if not futures:
                    if finished or time.monotonic() - idle_since > 90:
                        break  # fin du texte (ou plus rien depuis 90 s)
                    pull(0.15)
                    continue
                try:
                    samples = futures.popleft().result()
                except AudioError as exc:
                    # Une phrase impossible à dire ne coupe plus tout le reste du message
                    log.error("Voix : phrase sautée (%s)", exc.detail)
                    error = exc.user_message
                    continue
                if not finished and len(futures) < 2:
                    pull(0)
                if stream is None:
                    stream = self.player.open() if device is None else self.player.open(device)
                    log.info(
                        "Voix : 1re phrase prête en %d ms",
                        (time.perf_counter() - started) * 1000,
                    )
                    self.on_state("speaking", None)
                samples = apply_volume(samples, self.settings.volume)
                if self.on_audio is not None and device is None:  # pas en « casque seul »
                    try:
                        self.on_audio(samples)
                    except Exception as exc:  # noqa: BLE001 - l'overlay ne coupe jamais la voix
                        log.debug("Copie de la voix pour OBS impossible : %r", exc)
                self.player.play(stream, samples, stop)
                played = True
        except AudioError as exc:
            log.error("Voix : %s", exc.detail)
            error = exc.user_message
        except Exception as exc:  # noqa: BLE001
            log.error("Voix : erreur inattendue %r", exc)
            error = f"Erreur de lecture vocale : {exc!r}"
        finally:
            for future in futures:
                future.cancel()
            pool.shutdown(wait=False, cancel_futures=True)
            if stream is not None:
                # Laisse finir la dernière syllabe sauf si l'on a coupé.
                if not stop.is_set():
                    time.sleep(0.15)
                self.player.close(stream)
            # Une phrase sautée au milieu d'un message dit : pas d'« erreur » affichée
            self.on_state("error" if error and not played else "idle", None if played else error)
