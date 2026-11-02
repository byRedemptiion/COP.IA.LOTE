"""Composition : crée les services à partir de la configuration (sans Qt)."""

from __future__ import annotations

import logging
import platform
import sys
from dataclasses import dataclass

from alicia import __version__
from alicia.core.actions.controller import ActionController
from alicia.core.ai.base import VisionModel
from alicia.core.ai.factory import create_model
from alicia.core.analysis.service import AnalysisService
from alicia.core.audio.recorder import Recorder
from alicia.core.audio.speaker import Speaker
from alicia.core.audio.stt import LocalTranscriber
from alicia.core.capture.service import CaptureService
from alicia.core.config import Settings
from alicia.core.errors import AliciaError
from alicia.core.session.context import SessionContext

log = logging.getLogger("alicia.app")


@dataclass
class Services:
    settings: Settings
    capture: CaptureService
    model: VisionModel
    session: SessionContext
    analysis: AnalysisService
    demo: bool
    speaker: Speaker | None = None
    recorder: Recorder | None = None
    transcriber: LocalTranscriber | None = None
    actions: ActionController | None = None


def build_services(
    settings: Settings,
    *,
    demo: bool = False,
    model: VisionModel | None = None,
    speaker: Speaker | None = None,
    recorder: Recorder | None = None,
    transcriber: LocalTranscriber | None = None,
    actions: ActionController | None = None,
) -> Services:
    capture = (
        CaptureService.demo(settings.capture.keep_last_frames)
        if demo
        else CaptureService.for_windows(settings.capture)
    )
    model = model or create_model(settings.ai)
    session = SessionContext(settings.ai.history_turns)
    voice = settings.voice
    if transcriber is None and not demo:
        # gardé même avec stt = gemini : il sert si l'IA n'est pas Gemini
        transcriber = LocalTranscriber(voice.whisper_model)
    if actions is None and settings.actions.enabled:
        actions = ActionController(settings.actions, None if demo else _system())
    router = actions.route if actions is not None else None
    analysis = AnalysisService(settings, capture, model, session, transcriber, router)
    if settings.ai.deep_provider and settings.ai.provider != "fake":
        from alicia.core.ai.factory import create_deep_model

        try:
            analysis.deep_model = create_deep_model(settings.ai)
        except AliciaError as exc:
            log.warning("Cerveau réfléchi indisponible : %s", exc.detail)
    speaker = speaker or Speaker(voice)
    recorder = recorder or Recorder(voice.sample_rate, voice.input_device, voice.max_record_s)
    return Services(
        settings, capture, model, session, analysis, demo, speaker, recorder, transcriber, actions
    )


def _system():  # type: ignore[no-untyped-def]
    from alicia.core.actions.system import WindowsSystem
    from alicia.core.errors import UnsupportedPlatformError

    try:
        return WindowsSystem()
    except UnsupportedPlatformError:
        return None


def log_startup(settings: Settings, log_file: str) -> None:
    log.info(
        "Démarrage d'Alicia %s — Python %s, %s %s",
        __version__,
        platform.python_version(),
        platform.system(),
        platform.version(),
    )
    log.info("Logs : %s — configuration : %s", log_file, ", ".join(settings.sources))
    model = (
        settings.ai.gemini.model if settings.ai.provider == "gemini" else settings.ai.ollama.model
    )
    log.info(
        "IA : %s/%s — clé Gemini %s — capture : %s (repli écran %s) — voix : %s / %s",
        settings.ai.provider,
        model if settings.ai.provider != "fake" else "fake",
        "présente" if settings.ai.gemini.api_key else "absente",
        settings.capture.backend,
        "oui" if settings.capture.monitor_fallback else "non",
        f"compréhension {settings.voice.stt}"
        + (f" ({settings.voice.whisper_model})" if settings.voice.stt == "local" else ""),
        f"voix {settings.voice.tts_engine}",
    )
    if sys.platform == "win32":
        try:
            import windows_capture  # noqa: F401

            log.debug("Module windows-capture chargé")
        except ImportError as exc:
            log.error("Module windows-capture indisponible : %r", exc)
