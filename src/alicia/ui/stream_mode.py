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
    event = Signal(object)  # TwitchEvent (follow, sub, raid…), depuis le fil des événements
    event_status = Signal(str)
    tokens = Signal(object)  # jetons Twitch rafraîchis : à enregistrer


class StreamMode(QObject):
    def __init__(self, window: MainWindow) -> None:
        super().__init__(window)
        self.window = window
        self.chat: TwitchChat | None = None
        self.gate = ChatGate()
        self.gate.seen = self.gate.kept = 0
        from alicia.stream.viewers import ViewerBook

        self.viewers = ViewerBook()  # habitués du chat (sur ce PC)
        self.running = False  # une réponse est en préparation
        self.status = "coupé"
        self.bridge = _Bridge()
        self.bridge.message.connect(self._received)
        self.bridge.status.connect(self._set_status)
        self.bridge.event.connect(self._event_received)
        self.bridge.event_status.connect(self._set_event_status)
        self.bridge.tokens.connect(self._save_tokens)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.events = None  # TwitchEvents : follows, subs, raids… (compte connecté)
        from collections import deque

        self.event_queue: deque = deque(maxlen=10)  # type: ignore[type-arg]

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
        self.gate.seen = self.gate.kept = 0
        self.chat = TwitchChat(channel, self.bridge.message.emit)
        self.chat.on_status = self.bridge.status.emit
        self.chat.start()
        self.timer.start(1000)
        self._set_status("connexion…")
        log.info("Mode Stream : lecture du chat de #%s", channel)
        return None

    # --- événements Twitch (follows, subs, raids, bits) -------------------------------------

    def start_events(self) -> str | None:
        from alicia.stream.twitch_events import Tokens, TwitchEvents

        stream = self.window.services.settings.stream
        access, refresh = stream.twitch_access.get(), stream.twitch_refresh.get()
        if not stream.twitch_client_id or not access:
            return "Connecte d'abord ton compte Twitch (Réglages → Stream → Événements)."
        self.stop_events()
        self.events = TwitchEvents(
            stream.twitch_client_id,
            Tokens(access, refresh or ""),
            self.bridge.event.emit,
            self.bridge.tokens.emit,
        )
        self.events.on_status = self.bridge.event_status.emit
        self.events.start()
        self.timer.start(1000)
        self._set_event_status("connexion…")
        return None

    def stop_events(self) -> None:
        if self.events is not None:
            self.events.stop()
        self.events = None
        self.event_queue.clear()
        self._set_event_status("coupés")
        if self.chat is None:
            self.timer.stop()

    def _set_event_status(self, text: str) -> None:
        label = getattr(self.window.settings_page, "twitch_events_state", None)
        if label is not None:
            label.setText(f"Événements : {text}")

    def _save_tokens(self, tokens) -> None:  # type: ignore[no-untyped-def]
        self.window.save_twitch_tokens(tokens.access, tokens.refresh)

    def _event_received(self, event) -> None:  # type: ignore[no-untyped-def]
        from alicia.stream.twitch_events import GESTURES

        gesture, emoji = GESTURES.get(event.kind, ("nod", "💜"))
        overlay = self.window.overlay
        if overlay is not None:  # réaction immédiate sur l'overlay
            overlay.publish("gesture", name=gesture)
            overlay.publish("react", emoji=emoji)
        self.event_queue.append(event)

    def _thank(self) -> bool:
        """Dit le remerciement le plus ancien (prioritaire sur le chat)."""
        if not self.event_queue:
            return False
        from alicia.stream.twitch_events import thank_line

        event = self.event_queue.popleft()
        text = thank_line(event)
        window = self.window
        icons = {"follow": "💜", "sub": "⭐", "resub": "⭐", "gift": "🎁", "cheer": "💎"}
        window.asked_label.setText(f"{icons.get(event.kind, '🚀')} TWITCH  ›  {event.user}")
        window.answer.setPlainText(text)
        if window._bubble_active():
            window.bubble.ask(f"{icons.get(event.kind, '🚀')} {event.user}")
        window._core("speaking")
        speaker, device = window.services.speaker, window.services.settings.stream.chat_output
        spoken = False
        window._follow_up = False  # pas une réponse à ta question : pas d'écoute de la suite
        if window.voice_box.isChecked() and speaker is not None:
            spoken = speaker.speak(text, device=device or None)
        window._bubble_finish(text, spoken)
        return True

    def stop(self) -> None:
        if self.chat is not None:
            self.chat.stop()
            log.info("Mode Stream : coupé")
        self.chat = None
        if self.events is None:
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
        if self.window.services.settings.stream.chat_regulars:
            self.viewers.seen(message.user)
        self.window.chat_reaction(message.text)  # petites réactions sur l'overlay
        if self.gate.seen == 0:
            log.info("Chat Twitch : 1er message reçu (le chat est bien lu)")
        if self.gate.offer(message):
            log.info("Chat : message de %s retenu", message.user)
        self._show_counts()

    def _show_counts(self) -> None:
        """« Chat : connecté · 12 lus · 1 pour lui » : on voit tout de suite s'il lit le chat."""
        gate = self.gate
        if self.chat is None:
            return
        text = f"connecté · {gate.seen} message{'s' if gate.seen > 1 else ''} lu"
        text += "s" if gate.seen > 1 else ""
        text += f" · {gate.kept} pour lui"
        if gate.seen and not gate.kept and gate.last_skip == "pas pour lui":
            text += f" (il ne répond que si on écrit « {current_persona().title} »)"
        elif gate.seen and not gate.kept and gate.last_skip == "pas une question":
            text += " (il ne répond qu'aux questions et quand on le nomme)"
        self._set_status(text)

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
        busy = self._busy()
        if busy:
            if self.gate.queue and busy != getattr(self, "_told_busy", ""):
                self._told_busy = busy  # une seule ligne au journal, pas une par seconde
                log.info("Chat : réponse en attente (%s)", busy)
            return
        self._told_busy = ""
        if self._thank() or self.chat is None:
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
                question=chat_question(message, say_names)
                + (
                    "\n" + self.viewers.note_for(message.user)
                    if window.services.settings.stream.chat_regulars
                    else ""
                ),
                images=images,
                system_prompt=build_system_prompt(context + rules, spoken=True, brain="rapide"),
                max_output_tokens=300,
                temperature=0.6,
                quick=True,
            )
            started = time.perf_counter()
            from alicia.core import usage

            usage.add("chat")
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
            if window.services.settings.stream.chat_regulars:
                self.viewers.topic(message.user, message.text)
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
        window._follow_up = False  # pas une réponse à ta question : pas d'écoute de la suite
        if window.voice_box.isChecked() and speaker is not None:
            spoken = speaker.speak(text, device=device or None)  # casque seul : pas sur le live
            window.stop_voice_button.setEnabled(spoken)
        window._bubble_finish(text, spoken)
