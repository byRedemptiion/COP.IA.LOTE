"""Enregistrement push-to-talk du micro → WAV mono 16 bits, prêt pour l'IA."""

from __future__ import annotations

import io
import logging
import threading
import time
import wave

import numpy as np

from alicia.core.ai.base import PreparedAudio
from alicia.core.audio.devices import AudioError, device_name, find_device, sounddevice

log = logging.getLogger("alicia.audio")

MIN_DURATION_S = 0.4
SILENCE_PEAK = 400  # amplitude max (sur 32767) en dessous de laquelle on considère le micro muet


def encode_wav(samples: np.ndarray, sample_rate: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(samples.astype(np.int16).tobytes())
    return buffer.getvalue()


def to_prepared_audio(samples: np.ndarray, sample_rate: int, device: str = "") -> PreparedAudio:
    """Vérifie l'enregistrement et le convertit ; erreur claire si trop court ou muet."""
    duration = len(samples) / sample_rate
    if duration < MIN_DURATION_S:
        raise AudioError(
            "Question trop courte : maintiens la touche pendant que tu parles.",
            detail=f"enregistrement de {duration:.2f} s",
        )
    peak = int(np.abs(samples.astype(np.int32)).max()) if len(samples) else 0
    if peak < SILENCE_PEAK:
        raise AudioError(
            f"Aucun son capté par le micro « {device or 'par défaut'} ». Vérifie qu'il n'est "
            "pas coupé et que Windows autorise l'accès au micro, ou choisis-en un autre "
            "([voice] input_device).",
            detail=f"pic {peak}/32767 sur {duration:.1f} s",
        )
    log.info("Question orale : %.1f s, pic %d/32767", duration, peak)
    return PreparedAudio(encode_wav(samples, sample_rate), "audio/wav", round(duration, 2))


class Recorder:
    def __init__(self, sample_rate: int = 16000, device: str = "", max_s: float = 30.0) -> None:
        self.sample_rate = sample_rate
        self.device = device
        self.max_s = max_s
        self._chunks: list[np.ndarray] = []
        self._frames = 0
        self._stream = None
        self._lock = threading.Lock()
        self._started = 0.0
        self.device_label = ""
        self.level = 0.0  # niveau du micro (0-1), lu par l'interface

    @property
    def recording(self) -> bool:
        return self._stream is not None

    def start(self) -> None:
        if self._stream is not None:
            return
        sd = sounddevice()
        index = find_device(self.device, output=False)
        self.device_label = device_name(index, output=False)
        self._chunks, self._frames = [], 0
        max_frames = int(self.max_s * self.sample_rate)

        def callback(indata, frames, _time, status):  # type: ignore[no-untyped-def]
            if status:
                log.debug("Micro : %s", status)
            self.level = float(np.abs(indata).max()) / 32768.0  # pour l'animation
            with self._lock:
                if self._frames < max_frames:
                    self._chunks.append(indata[:, 0].copy())
                    self._frames += frames

        try:
            self._stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="int16",
                device=index,
                callback=callback,
                blocksize=int(self.sample_rate * 0.03),
            )
            self._stream.start()
        except Exception as exc:  # noqa: BLE001 - erreurs PortAudio variées
            self._stream = None
            raise AudioError(
                f"Impossible d'ouvrir le micro « {self.device_label} ». Vérifie qu'il est "
                "branché et autorisé (Paramètres Windows → Confidentialité → Microphone).",
                detail=repr(exc),
            ) from exc
        self._started = time.perf_counter()
        log.info("Micro ouvert : %s (%d Hz)", self.device_label, self.sample_rate)

    def stop(self) -> PreparedAudio:
        self.level = 0.0
        stream, self._stream = self._stream, None
        if stream is None:
            raise AudioError("Le micro n'était pas en cours d'enregistrement.")
        try:
            stream.stop()
            stream.close()
        except Exception as exc:  # noqa: BLE001
            log.warning("Fermeture du micro : %r", exc)
        with self._lock:
            samples = np.concatenate(self._chunks) if self._chunks else np.zeros(0, np.int16)
        log.debug("Micro fermé après %.2f s", time.perf_counter() - self._started)
        return to_prepared_audio(samples, self.sample_rate, self.device_label)

    def cancel(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:  # noqa: BLE001
                pass
