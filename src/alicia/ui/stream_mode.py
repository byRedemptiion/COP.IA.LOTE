"""Mode Stream (fenêtre principale) : lit le chat Twitch et répond à voix haute.

Le chat arrive dans un fil à part ; un minuteur (1 s) choisit un message quand personne ne
parle, demande une réponse courte au cerveau rapide, puis la dit (bulle + overlay OBS).
Les messages du chat ne passent JAMAIS par les commandes (actions PC, duo, réglages).
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QTimer, Signal

from alicia.core.persona import current as current_persona
from alicia.stream.chat import IGNORE, ChatGate, ChatMessage, TwitchChat, chat_question

if TYPE_CHECKING:
    from alicia.ui.main_window import MainWindow

log = logging.getLogger("alicia.stream")


class _Bridge(QObject):
    message = Signal(object)  # ChatMessage, depuis le fil du chat
    status = Signal(str)


class StreamMode(QObject):
    def __init__(self, window: MainWindow) -> None:
        super().__init__(window)
        self.window = window
        self.chat: TwitchChat | None = None
        self.gate = ChatGate()
        self.running = False  # une réponse est en préparation
        self.status = "coupé"
        self.bridge = _Bridge()
        self.bridge.message.connect(self._received)
        self.bridge.status.connect(self._set_status)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)

    @property
    def enabled(self) -> bool:
        return self.chat is not None

    def configure(self) -> None:
        stream = self.window.services.settings.stream
        names = (current_persona().title, current_persona().name)
        self.gate.names = tuple(n.casefold() for n in names if n)
        self.gate.trigger = stream.chat_trigger
        self.gate.cooldown_s = stream.chat_cooldown_s
        self.gate.ignored = {
            n.strip().casefold().lstrip("@") for n in stream.chat_ignored.split(",") if n.strip()
        }

    def start(self) -> str | None:
        """Démarre la lecture du chat ; renvoie un message d'erreur sinon."""
        channel = self.window.services.settings.stream.twitch_channel
        if not channel:
            return "Indique d'abord ta chaîne Twitch : Réglages → Stream."
        self.stop()
        self.configure()
        self.chat = TwitchChat(channel, self.bridge.message.emit)
        self.chat.on_status = self.bridge.status.emit
        self.chat.start()
        self.timer.start(1000)
        self._set_status("connexion…")
        log.info("Mode Stream : lecture du chat de #%s", channel)
        return None

    def stop(self) -> None:
        if self.chat is not None:
            self.chat.stop()
            log.info("Mode Stream : coupé")
        self.chat = None
        self.timer.stop()
        self.gate.queue.clear()
        self._set_status("coupé")

    def _set_status(self, text: str) -> None:
        self.status = text
        label = getattr(self.window.settings_page, "chat_state", None)
        if label is not None:
            label.setText(f"Chat : {text}")

    def _received(self, message: ChatMessage) -> None:
        if self.chat is None:
            return
        if self.gate.offer(message):
            log.info("Chat : message de %s retenu", message.user)

    def _busy(self) -> str | None:
        window = self.window
        speaker = window.services.speaker
        if self.running:
            return "réponse en cours"
        if window.busy or window._wake_paused():
            return "tu parles ou une question est en cours"
        if (speaker is not None and speaker.speaking) or window._peer_talking():
            return "quelqu'un parle déjà"
        return None

    def tick(self) -> None:
        if self.chat is None or self._busy():
            return
        message = self.gate.next()
        if message is None:
            return
        self.running = True
        window = self.window
        say_names = window.services.settings.stream.chat_say_names
        frame = window._live_frame(3.0)
        model = window.services.model
        rules = self.gate.rules(say_names)

        def answer() -> str:
            from alicia.core.ai.base import AnalysisRequest
            from alicia.core.ai.image_prep import prepare_image
            from alicia.core.ai.prompts import build_system_prompt

            images = ()
            context = ""
            if frame is not None and frame.window is not None:
                if window.services.analysis.playing(frame.window):
                    capture = window.services.settings.capture
                    images = (prepare_image(frame.image, 768, capture.jpeg_quality),)
                    profile, note = window.services.analysis.game_for(frame.window)
                    context = profile.prompt_context(False) + note
            request = AnalysisRequest(
                question=chat_question(message, say_names),
                images=images,
                system_prompt=build_system_prompt(context + rules, spoken=True, brain="rapide"),
                max_output_tokens=300,
                temperature=0.6,
                quick=True,
            )
            started = time.perf_counter()
            result = model.analyze(request)
            log.info(
                "[%s] [Mode Stream] réponse au chat en %d ms",
                current_persona().title,
                (time.perf_counter() - started) * 1000,
            )
            return result.text.strip()

        def done(text: str) -> None:
            self.running = False
            self.gate.answered(message)
            if not text or IGNORE in text.upper() or self.chat is None:
                log.info("Chat : message de %s ignoré par l'IA", message.user)
                return
            if self._busy():
                log.info("Chat : réponse annulée, quelqu'un a pris la parole")
                return
            self._speak(message, text)

        def failed(exc: Exception) -> None:
            self.running = False
            self.gate.answered(message)  # pas de rafale d'appels si l'IA ne répond pas
            log.warning("Mode Stream : réponse impossible (%r)", getattr(exc, "detail", exc))

        window._background(answer, done, failed)

    def _speak(self, message: ChatMessage, text: str) -> None:
        window = self.window
        text = text.replace(IGNORE, "").strip()
        title = current_persona().title.upper()
        window.asked_label.setText(f"💬 {message.user}  ›  {message.text[:80]}")
        window.answer.setPlainText(text)
        window._set_status(f"💬 {title} répond au chat")
        if window._bubble_active():
            window.bubble.ask(f"💬 {message.user} : {message.text[:120]}")
        window._core("speaking")
        speaker, device = window.services.speaker, window.services.settings.stream.chat_output
        spoken = False
        if window.voice_box.isChecked() and speaker is not None:
            spoken = speaker.speak(text, device=device or None)  # casque seul : pas sur le live
            window.stop_voice_button.setEnabled(spoken)
        window._bubble_finish(text, spoken)
