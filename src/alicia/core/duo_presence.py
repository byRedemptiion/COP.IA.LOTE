"""Présence du Duo : savoir en un coup d'œil si l'autre robot est là.

Chaque robot envoie un petit signal (« ping ») toutes les minutes tant que le duo est actif,
et « bye » quand il s'arrête. Sans nouvelles depuis 3 minutes, l'autre est « absent ».

États (extensibles) : off, connecting, present, speaking, absent, unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass

PING_S = 60.0  # un signal par minute
ABSENT_AFTER_S = 180.0  # sans nouvelles depuis 3 min : absent

LABELS = {
    "off": "Duo désactivé",
    "connecting": "Connexion…",
    "present": "Présent",
    "speaking": "Parle…",
    "absent": "Absent",
    "unavailable": "Indisponible",
}


@dataclass
class PeerPresence:
    name: str = ""  # nom de l'autre robot (ALICIA chez toi, VIIRUS chez Nova)
    player: str = ""  # son joueur (Nova…)
    last_seen: float | None = None  # time.monotonic() du dernier signal reçu
    left: bool = False  # « bye » reçu : il est parti

    def seen(self, now: float) -> None:
        self.last_seen, self.left = now, False

    def state(
        self,
        now: float,
        *,
        enabled: bool,
        has_code: bool,
        connected: bool,
        speaking: bool = False,
    ) -> str:
        if not enabled:
            return "off"
        if not has_code:
            return "unavailable"
        if speaking:
            return "speaking"
        if self.left:
            return "absent"  # il a dit au revoir
        recent = self.last_seen is not None and now - self.last_seen < ABSENT_AFTER_S
        if recent and not self.left:
            return "present"
        if not connected:
            return "connecting" if self.last_seen is None else "unavailable"
        return "absent"


def label(state: str, feminine: bool = False) -> str:
    text = LABELS.get(state, state)
    if feminine and text in ("Présent", "Absent"):
        text += "e"
    return text
