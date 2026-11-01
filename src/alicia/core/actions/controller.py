"""Décide et exécute les actions, avec les niveaux de sécurité.

Niveaux (inspirés de huburton/jarvis, MIT) :
- direct : volume, lancer une appli de la liste, minuteur ;
- confirmation : verrouiller, mettre en veille, fermer une appli ;
- confirmation + délai annulable : éteindre, redémarrer (« annule » arrête le compte à rebours).
Une confirmation expire vite, et un « non » l'emporte toujours.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from alicia.core.actions.intents import Intent, parse_confirmation, parse_intent
from alicia.core.actions.system import SystemControl
from alicia.core.config import ActionSettings
from alicia.core.errors import AliciaError

log = logging.getLogger("alicia.actions")

CONFIRM = {"shutdown", "restart", "sleep", "lock", "close"}


@dataclass
class ActionReply:
    text: str  # affiché et lu à voix haute
    intent: str
    awaiting_confirmation: bool = False
    done: bool = False
    expects_reply: bool = False  # ALICIA écoute la réponse sans attendre « Alicia »

    def __post_init__(self) -> None:
        self.expects_reply = self.expects_reply or self.awaiting_confirmation


def _duration(seconds: int) -> str:
    if seconds >= 3600 and seconds % 3600 == 0:
        hours = seconds // 3600
        return f"{hours} heure{'s' if hours > 1 else ''}"
    if seconds >= 60 and seconds % 60 == 0:
        minutes = seconds // 60
        return f"{minutes} minute{'s' if minutes > 1 else ''}"
    return f"{seconds} secondes"


class ActionController:
    def __init__(
        self,
        settings: ActionSettings,
        system: SystemControl | None,
        on_reminder: Callable[[str], None] = lambda _text: None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings
        self.system = system
        self.on_reminder = on_reminder
        self.clock = clock
        self._pending: tuple[Intent, float] | None = None
        self._timers: list[threading.Timer] = []
        self.shutdown_scheduled = False

    @property
    def pending(self) -> Intent | None:
        if self._pending and self.clock() <= self._pending[1]:
            return self._pending[0]
        self._pending = None
        return None

    def route(self, text: str) -> ActionReply | None:
        """Point d'entrée : renvoie une réponse si le texte est une action, sinon None."""
        if not self.settings.enabled:
            return None
        pending = self.pending
        if pending is not None:
            answer = parse_confirmation(text)
            if answer is True:
                self._pending = None
                return self._execute(pending)
            if answer is False:
                self._pending = None
                log.info("Action « %s » refusée par le joueur", pending.name)
                return ActionReply("D'accord, j'annule.", pending.name, done=True)
        intent = parse_intent(text, self.settings.apps)
        if intent is None:
            if self.shutdown_scheduled and parse_confirmation(text) is False:
                intent = Intent("cancel_shutdown", {}, text)
            else:
                return None
        log.info("Action reconnue : %s %s", intent.name, intent.params or "")
        if self.system is None:
            return ActionReply(
                "Les actions sur le PC ne sont pas disponibles ici.", intent.name, done=True
            )
        if intent.name in CONFIRM:
            self._pending = (intent, self.clock() + self.settings.confirm_timeout_s)
            return ActionReply(self._question(intent), intent.name, awaiting_confirmation=True)
        return self._execute(intent)

    def _question(self, intent: Intent) -> str:
        delay = _duration(self.settings.shutdown_delay_s)
        questions = {
            "shutdown": f"J'éteins le PC dans {delay}. Tu confirmes ?",
            "restart": f"Je redémarre le PC dans {delay}. Tu confirmes ?",
            "sleep": "Je mets le PC en veille. Tu confirmes ?",
            "lock": "Je verrouille la session. Tu confirmes ?",
            "close": f"Je ferme {intent.params.get('app')}. Tu confirmes ?",
        }
        return questions[intent.name] + " Réponds oui ou non."

    def _execute(self, intent: Intent) -> ActionReply:
        system = self.system
        assert system is not None
        name, params = intent.name, intent.params
        try:
            if name in ("shutdown", "restart"):
                delay = self.settings.shutdown_delay_s
                system.shutdown(delay, restart=name == "restart")
                self.shutdown_scheduled = True
                verb = "Redémarrage" if name == "restart" else "Extinction"
                text = f"{verb} dans {_duration(delay)}. Dis « annule » pour l'arrêter."
            elif name == "cancel_shutdown":
                system.cancel_shutdown()
                self.shutdown_scheduled = False
                text = "C'est annulé, le PC reste allumé."
            elif name == "sleep":
                text = "Mise en veille. À tout à l'heure."
                threading.Timer(2.0, system.sleep).start()  # laisse le temps de le dire
            elif name == "lock":
                text = "Session verrouillée."
                threading.Timer(1.5, system.lock).start()
            elif name == "mute":
                system.set_mute(True)
                text = "Son coupé."
            elif name == "unmute":
                system.set_mute(False)
                text = "Son remis."
            elif name == "volume_set":
                system.set_volume(int(params["percent"]))  # type: ignore[arg-type]
                text = f"Volume à {params['percent']} %."
            elif name in ("volume_up", "volume_down"):
                step = int(params["step"])  # type: ignore[arg-type]
                current = system.volume()
                target = max(0, min(100, current + (step if name == "volume_up" else -step)))
                system.set_volume(target)
                text = f"Volume à {target} %."
            elif name == "launch":
                app = str(params["app"])
                system.launch(self.settings.apps[app].launch)
                text = f"J'ouvre {app}."
            elif name == "close":
                app = str(params["app"])
                process = self.settings.apps[app].process
                if not process:
                    return ActionReply(
                        f"Je ne sais pas fermer {app} : ajoute son processus dans alicia.toml.",
                        name,
                        done=True,
                    )
                closed = system.close(process)
                text = f"{app} fermé." if closed else f"{app} n'était pas ouvert."
            elif name == "timer":
                text = self._start_timer(int(params["seconds"]), str(params.get("label") or ""))  # type: ignore[arg-type]
            else:
                return ActionReply("Je ne connais pas cette action.", name, done=True)
        except AliciaError as exc:
            log.error("Action %s échouée : %s", name, exc.detail)
            return ActionReply(exc.user_message, name, done=True)
        log.info("Action %s exécutée", name)
        # Extinction programmée : on écoute « annule » sans qu'il faille redire « Alicia ».
        return ActionReply(text, name, done=True, expects_reply=name in ("shutdown", "restart"))

    def _start_timer(self, seconds: int, label: str) -> str:
        if seconds <= 0:
            return "Je n'ai pas compris la durée."
        message = f"Rappel : {label}." if label else "C'est l'heure, ton minuteur est terminé."

        def fire() -> None:
            log.info("Rappel déclenché : %s", label or "minuteur")
            self.on_reminder(message)

        timer = threading.Timer(seconds, fire)
        timer.daemon = True
        timer.start()
        self._timers.append(timer)
        what = f" pour « {label} »" if label else ""
        return f"C'est noté, je te préviens dans {_duration(seconds)}{what}."

    def stop(self) -> None:
        for timer in self._timers:
            timer.cancel()
        self._timers.clear()
