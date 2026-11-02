"""Réveil vocal : dire « Alicia… » suffit, sans toucher au clavier.

Le micro reste ouvert, mais tout se passe sur le PC :
1. Un détecteur d'énergie repère le début d'une phrase (rien n'est analysé dans le silence).
2. Le début de la phrase (2,5 s au plus) est transcrit par un petit modèle Whisper local.
3. Si la phrase commence par « Alicia », la phrase entière devient une question ou une
   demande, exactement comme avec F10. Sinon elle est oubliée aussitôt.
   « Alicia » seul : elle attend la suite quelques secondes.

Aucun son n'est envoyé à l'IA ni enregistré tant que le mot de réveil n'a pas été dit.
L'écoute est suspendue pendant qu'ALICIA parle, analyse, ou que F10 est maintenue.
"""

from __future__ import annotations

import collections
import difflib
import logging
import queue
import re
import threading
import time
import unicodedata
from collections.abc import Callable

import numpy as np

from alicia.core.ai.base import PreparedAudio
from alicia.core.audio.devices import AudioError, device_name, find_device, sounddevice
from alicia.core.audio.recorder import to_prepared_audio
from alicia.core.persona import PERSONAS, current

log = logging.getLogger("alicia.audio")

WAKE_NAME = "alicia"
# Graphies que Whisper produit pour « Alicia » (et l'ancien nom « Alice »).
WAKE_FORMS = {
    "alicia",
    "alissia",
    "alicya",
    "alisia",
    "alysia",
    "alycia",
    "allicia",
    "aliciaa",
    "elicia",
    "alice",
    "alisa",
}

BLOCK_S = 0.03
PREROLL_S = 0.35
START_BLOCKS = 3  # ~90 ms au-dessus du seuil = début de phrase
CHECK_AFTER_S = 1.4  # on vérifie le mot de réveil après 1,4 s de parole…
CHECK_MAX_S = 2.5  # …sur 2,5 s au plus
END_SILENCE_S = 0.8  # fin de phrase
IGNORE_SILENCE_S = 0.5
FOLLOW_UP_S = 6.0  # « Alicia » seul : temps laissé pour dire la suite
MAX_COMMAND_S = 15.0
MIN_LEVEL = 0.012
# Sensibilité du réveil (réglages) → volume minimal d'une phrase.
SENSITIVITY_LEVELS = {1: 0.03, 2: 0.02, 3: 0.012, 4: 0.008, 5: 0.005}


def _normalize(text: str) -> list[str]:
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.findall(r"[a-z]+", plain)


def _wake_forms(name: str) -> set[str] | frozenset[str]:
    for persona in PERSONAS.values():
        if persona.wake_name == name:
            return persona.wake_forms
    return WAKE_FORMS if name == WAKE_NAME else {name}


def _is_name(word: str, name: str | None = None) -> bool:
    name = name or current().wake_name
    if word in _wake_forms(name) or word == name:
        return True
    return len(word) >= 5 and difflib.SequenceMatcher(None, word, name).ratio() >= 0.8


def find_wake(text: str, name: str | None = None) -> tuple[bool, str]:
    """(mot de réveil dit au début ?, ce qui suit). Tolère « Ok Alicia », « A licia »."""
    words = _normalize(text)
    for i, word in enumerate(words[:3]):
        if _is_name(word, name):
            return True, " ".join(words[i + 1 :])
        if i + 1 < len(words) and _is_name(word + words[i + 1], name):
            return True, " ".join(words[i + 2 :])
    return False, ""


STOP_WORDS = {"stop", "stoppe", "stopp", "arrete", "arretes", "chut", "silence", "tais", "suffit"}


def is_stop(rest: str) -> bool:
    """« stop », « arrête », « tais-toi », « chut », « ça suffit » juste après le nom."""
    words = rest.split()[:3]
    return any(word in STOP_WORDS for word in words)


def strip_wake_word(text: str, name: str | None = None) -> str:
    """« Alicia, lance Discord » → « lance Discord » (texte d'origine conservé)."""
    tokens = list(re.finditer(r"\S+", text))
    for i, token in enumerate(tokens[:3]):
        word = "".join(_normalize(token.group()))
        joined = word + "".join(_normalize(tokens[i + 1].group())) if i + 1 < len(tokens) else ""
        if word and _is_name(word, name):
            end = token.end()
        elif joined and _is_name(joined, name):
            end = tokens[i + 1].end()
        else:
            continue
        return text[end:].lstrip(" ,.;:!?-—").strip()
    return text.strip()


class WakeListener:
    """Écoute le micro en continu et repère « Alicia ». Rappels appelés depuis son thread."""

    IDLE, CHECKING, IGNORING, COMMAND, FOLLOW_UP = range(5)

    def __init__(
        self,
        detector: Callable[[np.ndarray], str],
        on_wake: Callable[[], None],
        on_command: Callable[[PreparedAudio], None],
        on_cancel: Callable[[str], None] | None = None,
        *,
        paused: Callable[[], bool] | None = None,
        stop_only: Callable[[], bool] | None = None,
        on_stop: Callable[[], None] | None = None,
        on_speech: Callable[[], None] | None = None,
        device: str = "",
        sample_rate: int = 16000,
        name: str | None = None,
        sensitivity: int = 3,
    ) -> None:
        self.detector = detector
        self.on_wake = on_wake
        self.on_command = on_command
        self.on_cancel = on_cancel or (lambda _reason: None)
        self.paused = paused or (lambda: False)
        # Pendant qu'ALICIA parle ou analyse : seul « Alicia, stop » est écouté.
        self.stop_only = stop_only or (lambda: False)
        self.on_stop = on_stop or (lambda: None)
        # Début d'une phrase (avant de savoir si c'est « Alicia ») : capture de l'écran.
        self.on_speech = on_speech or (lambda: None)
        self.device = device
        self.sample_rate = sample_rate
        self.name = name or current().wake_name
        self.min_level = SENSITIVITY_LEVELS.get(sensitivity, MIN_LEVEL)
        self.level = 0.0
        self._queue: queue.Queue[np.ndarray | None] = queue.Queue(maxsize=400)
        self._stream = None
        self._thread: threading.Thread | None = None
        self.reset()

    # --- micro ----------------------------------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._stream is not None

    def start(self) -> None:
        if self._stream is not None:
            return
        sd = sounddevice()
        index = find_device(self.device, output=False)
        label = device_name(index, output=False)

        def callback(indata, _frames, _time, status):  # type: ignore[no-untyped-def]
            if status:
                log.debug("Micro (réveil) : %s", status)
            try:
                self._queue.put_nowait(indata[:, 0].copy())
            except queue.Full:
                pass  # détection en retard : on lâche des blocs plutôt que de bloquer le son

        try:
            self._stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="int16",
                device=index,
                callback=callback,
                blocksize=int(self.sample_rate * BLOCK_S),
            )
            self._stream.start()
        except Exception as exc:  # noqa: BLE001 - erreurs PortAudio variées
            self._stream = None
            raise AudioError(
                f"Réveil vocal : impossible d'ouvrir le micro « {label} ».", detail=repr(exc)
            ) from exc
        self._thread = threading.Thread(target=self._loop, name="alicia-wake", daemon=True)
        self._thread.start()
        log.info("Réveil vocal actif : dis « %s… » (micro %s)", current().name, label)

    def stop(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:  # noqa: BLE001
                pass
            self._queue.put(None)
            log.info("Réveil vocal coupé")
        self.level = 0.0

    def _loop(self) -> None:
        while True:
            block = self._queue.get()
            if block is None:
                return
            try:
                self.process(block)
            except Exception:  # noqa: BLE001 - l'écoute ne doit jamais s'arrêter sur une erreur
                log.exception("Réveil vocal : erreur de traitement")
                self.reset()

    # --- détection (testable sans micro) ----------------------------------------------------------

    def reset(self) -> None:
        self.state = self.IDLE
        self._floor = 0.01
        self._loud = 0
        self._silence = 0.0
        self._buffer: list[np.ndarray] = []
        self._preroll: collections.deque[np.ndarray] = collections.deque(
            maxlen=max(1, int(PREROLL_S / BLOCK_S))
        )
        self._waited = 0.0
        self._name_only = False
        self._spoke_after = False
        self._follow_limit = FOLLOW_UP_S

    def listen_now(self, seconds: float = FOLLOW_UP_S) -> None:
        """Écoute la prochaine phrase comme une demande, sans mot de réveil (réponse attendue :
        « oui », « non », « annule »…). Appelé quand ALICIA a fini de parler."""
        floor = self._floor
        self.reset()
        self._floor = floor
        self.state = self.FOLLOW_UP
        self._follow_limit = seconds
        log.info("Écoute de ta réponse pendant %.0f s (sans dire « Alicia »)", seconds)

    def _duration(self) -> float:
        return sum(len(b) for b in self._buffer) / self.sample_rate

    def process(self, block: np.ndarray) -> None:
        seconds = len(block) / self.sample_rate
        rms = (
            float(np.sqrt(np.mean((block.astype(np.float32) / 32768.0) ** 2)))
            if len(block)
            else 0.0
        )
        self.level = min(1.0, rms * 4)
        if self.paused():
            if self.state != self.IDLE:
                self.reset()
            return
        threshold = max(self._floor * 3.0, self.min_level)
        loud = rms > threshold

        if self.state == self.IDLE:
            self._preroll.append(block)
            if loud:
                self._loud += 1
                if self._loud >= START_BLOCKS:
                    self.state = self.CHECKING
                    self._buffer = list(self._preroll)
                    self._silence = 0.0
                    try:
                        self.on_speech()
                    except Exception:  # noqa: BLE001 - simple confort
                        log.debug("Début de phrase : rappel en erreur", exc_info=True)
            else:
                self._loud = 0
                self._floor = 0.95 * self._floor + 0.05 * rms  # bruit de fond (ventilos, jeu)
            return

        if self.state == self.FOLLOW_UP:
            self._preroll.append(block)
            self._waited += seconds
            if loud:
                self._loud += 1
                if self._loud >= START_BLOCKS:
                    self.state = self.COMMAND
                    self._buffer = list(self._preroll)
                    self._silence = 0.0
                    return
            else:
                self._loud = 0
            if self._waited >= getattr(self, "_follow_limit", FOLLOW_UP_S):
                self._finish_idle()
                self.on_cancel(f"rien entendu après « {current().name} »")
            return

        self._buffer.append(block)
        self._silence = 0.0 if loud else self._silence + seconds

        if self.state == self.IGNORING:
            if self._silence >= IGNORE_SILENCE_S:
                self._finish_idle()
            return

        if self.state == self.CHECKING:
            ended = self._silence >= IGNORE_SILENCE_S
            if self._duration() < CHECK_AFTER_S and not ended:
                return
            if self._duration() < 0.3:
                self._finish_idle()
                return
            samples = np.concatenate(self._buffer)[: int(CHECK_MAX_S * self.sample_rate)]
            started = time.perf_counter()
            text = self.detector(samples.astype(np.float32) / 32768.0)
            woke, rest = find_wake(text, self.name)
            log.debug(
                "Réveil : « %s » → %s (%.2f s)",
                text[:60],
                "oui" if woke else "non",
                time.perf_counter() - started,
            )
            if woke and is_stop(rest):
                log.info("« Alicia, stop » entendu")
                self.on_stop()
                woke = False  # rien d'autre à faire de cette phrase
            elif woke and self.stop_only():
                log.debug("Réveil ignoré : ALICIA est occupée (seul « stop » est écouté)")
                woke = False
            if not woke:
                self.state = self.IDLE if ended else self.IGNORING
                if ended:
                    self._finish_idle()
                return
            log.info("Mot de réveil entendu")
            self.on_wake()
            if ended and not rest:
                self.state = self.FOLLOW_UP  # « Alicia » seul : on attend la demande
                self._waited, self._loud = 0.0, 0
                self._preroll.clear()
                self._buffer = []
            elif ended:
                self._emit()
            else:
                self.state = self.COMMAND
                # Rien après le nom pour l'instant : si le silence suit, on attendra la suite.
                self._name_only = not rest
                self._spoke_after = False
            return

        if self.state == self.COMMAND:
            if loud:
                self._spoke_after = True
            if self._silence >= END_SILENCE_S and self._name_only and not self._spoke_after:
                self.state = self.FOLLOW_UP  # « Alicia… » puis une pause
                self._waited, self._loud = 0.0, 0
                self._preroll.clear()
                self._buffer = []
                return
            if self._silence >= END_SILENCE_S or self._duration() >= MAX_COMMAND_S:
                self._emit()

    def _emit(self) -> None:
        samples = np.concatenate(self._buffer) if self._buffer else np.zeros(0, np.int16)
        trailing = int(self._silence * self.sample_rate) - int(0.2 * self.sample_rate)
        if trailing > 0:
            samples = samples[: max(0, len(samples) - trailing)]
        self._finish_idle()
        try:
            audio = to_prepared_audio(samples, self.sample_rate, "réveil vocal")
        except AudioError as exc:
            self.on_cancel(exc.detail or exc.user_message)
            return
        self.on_command(audio)

    def _finish_idle(self) -> None:
        floor = self._floor
        self.reset()
        self._floor = floor


class WhisperWakeDetector:
    """Transcription très courte avec un petit Whisper local, réservée au mot de réveil."""

    def __init__(self, model: str = "base", threads: int = 2) -> None:
        from alicia.core.audio.stt import LocalTranscriber

        self.transcriber = LocalTranscriber(model, threads=threads)

    def warm_up_async(self) -> None:
        self.transcriber.warm_up_async()

    def __call__(self, samples: np.ndarray) -> str:
        return self.transcriber.transcribe_samples(samples, hotwords=current().name)
