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
                        "La voix Kokoro n'est pas installée. Relance Installer_Alicia.bat ou "
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


def openai_synthesizer(settings: VoiceSettings) -> Synthesizer:
    """Voix OpenAI (API audio/speech) : très naturelle, payante à l'usage."""
    import httpx

    percent = 0
    try:
        percent = int(settings.tts_rate.strip().rstrip("%"))
    except ValueError:
        pass
    pace = (
        "" if abs(percent) < 5 else (" Parle un peu vite." if percent > 0 else " Parle posément.")
    )

    def synthesize(text: str) -> np.ndarray:
        if not settings.openai_key:
            raise AudioError(
                "Voix OpenAI : il faut une clé OpenAI (bouton IA → ChatGPT), ou choisis la voix "
                "Edge dans les réglages.",
                detail="OPENAI_API_KEY absente",
            )
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
                    + pace,
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

    return synthesize


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


def _gemini_style(settings: VoiceSettings) -> str:
    effect = VOICE_EFFECTS.get(settings.voice_effect)
    if effect is None:
        return GEMINI_VOICE_STYLE
    return f"Dis en français, {effect[4]} : "


def gemini_synthesizer(settings: VoiceSettings) -> Synthesizer:
    """Voix Gemini (30 voix, avec ta clé Gemini) : PCM 24 kHz 16 bits mono."""
    import base64

    import httpx

    if settings.gemini_voice.startswith("voice_"):  # voix sur mesure (Gemini 3.8)
        return _designed(settings)

    def synthesize(text: str) -> np.ndarray:
        if not settings.gemini_key:
            raise AudioError(
                "Voix Gemini : il faut une clé Gemini (bouton IA → Gemini).",
                detail="GEMINI_API_KEY absente",
            )
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
            parts = response.json()["candidates"][0]["content"]["parts"]
            data = base64.b64decode(
                next(p["inlineData"]["data"] for p in parts if "inlineData" in p)
            )
        except (KeyError, IndexError, StopIteration, ValueError) as exc:
            raise AudioError(
                "Voix Gemini : réponse sans audio.", detail=response.text[:300]
            ) from exc
        return np.frombuffer(data[: len(data) - len(data) % 2], dtype=np.int16)

    return synthesize


def _designed(settings: VoiceSettings) -> Synthesizer:
    """Voix sur mesure, avec la voix du profil en secours si Gemini ne répond pas."""
    from alicia.core.audio import voice_design
    from alicia.core.persona import current

    if current().key == "veris":
        fallback = veris_synthesizer(settings.kokoro_speed)
    else:
        fallback = veris_synthesizer(settings.kokoro_speed, 1.30, 220.0, 3800.0, metallic=0.0)
    if not settings.gemini_key:
        return fallback
    effect = VOICE_EFFECTS.get(settings.voice_effect)
    style = "ton naturel et vivant de coéquipier de jeu" if effect is None else effect[4]
    primary = voice_design.designed_synthesizer(
        settings.gemini_key.get() or "", settings.gemini_voice, style
    )
    return voice_design.with_fallback(primary, fallback)


# Effets de voix, applicables à Edge, Gemini, OpenAI et Kokoro :
# (hauteur en cents, passe-haut, présence, métal, consigne de jeu pour Gemini / OpenAI)
VOICE_EFFECTS: dict[str, tuple[int, float, float, float, str]] = {
    "enfant": (
        620,
        280.0,
        4300.0,
        0.0,
        "avec la petite voix aiguë, l'énergie et la spontanéité d'un enfant de 7 ans",
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
        "comme un petit garçon robot espiègle : voix aiguë, vive, rieuse, un peu mécanique",
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


def with_effect(base: Synthesizer, effect: str, *, pre_slowed: bool = False) -> Synthesizer:
    """Applique un effet (enfant, robot…) à n'importe quelle voix.

    ``pre_slowed`` : la voix est déjà générée ralentie du bon facteur (Edge sait le faire,
    c'est plus propre) ; sinon on l'étire d'abord sans changer sa hauteur."""
    if effect not in VOICE_EFFECTS:
        return base
    cents, highpass, presence, metallic, _ = VOICE_EFFECTS[effect]
    ratio = 2 ** (cents / 1200)

    def synthesize(text: str) -> np.ndarray:
        samples = base(text)
        if not pre_slowed:
            samples = time_stretch(samples, 1 / ratio)
        return robot_voice(
            samples, ratio, highpass_hz=highpass, presence_hz=presence, metallic=metallic
        )

    warm = getattr(base, "warm_up", None)
    if warm is not None:
        synthesize.warm_up = warm  # type: ignore[attr-defined]
    return synthesize


def _slowed_rate(rate: str, ratio: float) -> str:
    try:
        percent = int(rate.strip().rstrip("%"))
    except ValueError:
        percent = 0
    return f"{round(((1 + percent / 100) / ratio - 1) * 100):+d}%"


def make_synthesizer(settings: VoiceSettings) -> Synthesizer:
    effect = settings.voice_effect if settings.voice_effect in VOICE_EFFECTS else ""
    if effect and settings.tts_engine in ("edge", "gemini", "openai", "kokoro"):
        if settings.tts_engine == "edge":
            ratio = 2 ** (VOICE_EFFECTS[effect][0] / 1200)
            base = edge_synthesizer(settings.tts_voice, _slowed_rate(settings.tts_rate, ratio))
            return with_effect(base, effect, pre_slowed=True)
        if settings.tts_engine == "gemini":
            base = gemini_synthesizer(settings)  # garde l'effet : il devient une consigne de jeu
        elif settings.tts_engine == "openai":
            base = openai_synthesizer(settings)
        else:
            base = make_synthesizer(replace(settings, voice_effect=""))
        return with_effect(base, effect)
    if settings.tts_engine == "veris":
        return veris_synthesizer(settings.kokoro_speed)
    if settings.tts_engine == "voixc":
        # Voix C d'ALICIA : ff_siwis, hauteur ×1,30 (formants suivis), 220 Hz / +3 dB à 3,8 kHz
        return veris_synthesizer(settings.kokoro_speed, 1.30, 220.0, 3800.0, metallic=0.0)
    if settings.tts_engine == "openai":
        return openai_synthesizer(settings)
    if settings.tts_engine == "gemini":
        return gemini_synthesizer(settings)
    if settings.tts_engine == "kokoro":
        return kokoro_synthesizer(settings.kokoro_voice, settings.kokoro_speed)
    return edge_synthesizer(settings.tts_voice, settings.tts_rate)


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
        sentences = split_sentences(pronounce(text))  # prénoms dits comme il faut
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
                samples = futures.popleft().result()
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
            self.on_state("error" if error else "idle", error)
