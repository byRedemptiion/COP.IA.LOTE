"""Mode Copilote : le robot jette un coup d'œil à l'écran et ne parle que si ça compte.

À chaque coup d'œil, le cerveau rapide répond par un petit JSON :
``{"speak": true, "importance": 8, "message": "…", "reason": "…"}``.
Le robot ne parle que si l'importance atteint le seuil, que le délai de silence
(cooldown) est passé, et que ce n'est pas une redite. Il observe et conseille :
il n'agit jamais dans le jeu.
"""

from __future__ import annotations

import difflib
import json
import logging
import re
import time
from collections import deque
from dataclasses import dataclass

from alicia.core.ai.base import AnalysisRequest, PreparedImage, VisionModel
from alicia.core.ai.prompts import build_system_prompt
from alicia.core.persona import current as current_persona

log = logging.getLogger("alicia.copilot")

COPILOT_QUESTION = "Coup d'œil du mode Copilote : faut-il dire quelque chose maintenant ?"

COPILOT_RULES = """
MODE COPILOTE — personne ne t'a posé de question. Tu regardes l'écran pour décider s'il
vaut la peine de parler MAINTENANT. Par défaut, tu te tais.
Réponds UNIQUEMENT par un objet JSON sur une seule ligne, sans texte autour :
{{"speak": true ou false, "category": "{categories}", "importance": 1 à 10, "message": "...", "reason": "..."}}
Catégories autorisées (n'en utilise AUCUNE autre) :
{allowed}
"importance" = à quel point ça vaut le coup d'être dit tout de suite :
- 9-10 : danger immédiat, erreur grave en cours, objectif perdu si rien n'est fait.
- 7-8 : vraie opportunité, conseil utile, ou moment vraiment marquant (drôle, ridicule, épique).
- 1-6 : anecdotique, rien de neuf, déjà dit → "speak": false.
- Menu, écran de chargement, pause, bureau, cinématique : "speak": false.
- "message" : une phrase courte à dire à voix haute (20 mots maximum), sans markdown, inventée
  à partir de ce que tu vois vraiment (jamais une phrase toute faite) ; vide si "speak" est
  false. "reason" : quelques mots pour le journal.
- Tu conseilles et tu réagis seulement : tu ne joues jamais à la place du joueur.
{trash}{recent}"""

CATEGORIES = {
    "conseil": "conseil : une info ou une astuce utile maintenant",
    "alerte": "alerte : un danger ou une erreur à éviter tout de suite",
    "reaction": "reaction : une réaction spontanée à un moment marquant (exploit, surprise)",
    "humour": "humour : une remarque drôle et bienveillante sur la situation",
    "trashtalk": "trashtalk : chambrer le joueur (voir les règles du trash-talk)",
    "duo": "duo : une remarque pour les coéquipiers présents (personnes de la session)",
}
# Réglage (cases de l'onglet Copilote) → catégories du JSON
KINDS = {
    "conseils": "conseil",
    "alertes": "alerte",
    "reactions": "reaction",
    "humour": "humour",
    "trashtalk": "trashtalk",
    "duo": "duo",
}
FUN = {"reaction", "humour", "trashtalk", "duo"}  # plus rares que les conseils
TRASH_LEVELS = {
    "leger": "taquinerie gentille, comme un pote qui sourit",
    "normal": "chambrer franchement, avec humour",
    "corse": "trash-talk piquant de pote de jeu, mordant mais complice",
}
TRASH_RULES = """Trash-talk ({level}) : {style}. Jamais d'insulte, jamais sur le physique, l'origine,
le genre ou quoi que ce soit de personnel, et jamais méchant gratuitement. Pas à chaque mort :
seulement sur un moment qui le mérite vraiment (erreur bête, situation ridicule), et rarement.
"""
SPONTANEITY = {"discret": 8, "normal": 7, "bavard": 5}  # importance minimale pour parler


def kinds_from(text: str | tuple[str, ...]) -> tuple[str, ...]:
    """« conseils,alertes » → ("conseils", "alertes") (seulement des types connus)."""
    items = text.split(",") if isinstance(text, str) else text
    return tuple(k.strip() for k in items if k.strip() in KINDS)


@dataclass(frozen=True)
class Decision:
    speak: bool
    importance: int
    message: str
    reason: str = ""
    category: str = "conseil"


def parse_decision(text: str) -> Decision | None:
    """Lit le JSON du modèle (tolère du texte ou des ``` autour). None si illisible."""
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if match is None:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    try:
        importance = max(0, min(10, int(float(data.get("importance", 0)))))
    except (TypeError, ValueError):
        importance = 0
    message = str(data.get("message") or "").strip()
    speak = data.get("speak")
    speak = speak.strip().lower() in ("true", "oui", "1") if isinstance(speak, str) else bool(speak)
    category = str(data.get("category") or "conseil").strip().casefold()
    category = category.replace("é", "e").replace("-", "").replace(" ", "")
    if category not in CATEGORIES:
        category = "conseil"
    return Decision(
        speak and bool(message),
        importance,
        message[:300],
        str(data.get("reason") or "")[:200],
        category,
    )


class CopilotGate:
    """Seuil d'importance, délai de silence et anti-redite."""

    def __init__(
        self,
        threshold: int = 7,
        cooldown_s: float = 60.0,
        kinds: tuple[str, ...] = ("conseils", "alertes", "reactions", "humour"),
        trash: str = "off",
    ) -> None:
        self.threshold = threshold
        self.cooldown_s = cooldown_s
        self.kinds = kinds
        self.trash = trash  # off | leger | normal | corse
        self.last_spoken_at: float | None = None
        self.last_fun_at: float | None = None
        self.last_trash_at: float | None = None
        self.recent: deque[str] = deque(maxlen=5)

    @property
    def categories(self) -> list[str]:
        """Les catégories permises (trash-talk seulement s'il a un niveau)."""
        allowed = [KINDS[k] for k in self.kinds if k in KINDS]
        if self.trash == "off" and "trashtalk" in allowed:
            allowed.remove("trashtalk")
        return allowed

    def allow(self, decision: Decision, now: float | None = None) -> tuple[bool, str]:
        now = time.monotonic() if now is None else now
        if not decision.speak:
            return False, "rien d'important"
        if decision.category not in self.categories:
            return False, f"type « {decision.category} » désactivé"
        if decision.importance < self.threshold:
            return False, f"importance {decision.importance} < seuil {self.threshold}"
        if decision.importance < 9 and self.last_spoken_at is not None:
            left = self.cooldown_s - (now - self.last_spoken_at)
            if left > 0:
                return False, f"délai de silence ({left:.0f} s restantes)"
        if decision.category in FUN and decision.importance < 9 and self.last_fun_at is not None:
            left = self.cooldown_s * 2 - (now - self.last_fun_at)
            if left > 0:  # les réactions et blagues restent rares
                return False, f"réaction récente ({left:.0f} s restantes)"
        if decision.category == "trashtalk" and self.last_trash_at is not None:
            left = max(300.0, self.cooldown_s * 5) - (now - self.last_trash_at)
            if left > 0:
                return False, f"trash-talk récent ({left:.0f} s restantes)"
        said = decision.message.casefold()
        for old in self.recent:
            if difflib.SequenceMatcher(None, said, old.casefold()).ratio() >= 0.75:
                return False, "déjà dit"
        return True, "urgent" if decision.importance >= 9 else decision.category

    def spoke(self, message: str, now: float | None = None, category: str = "conseil") -> None:
        now = time.monotonic() if now is None else now
        self.last_spoken_at = now
        if category in FUN:
            self.last_fun_at = now
        if category == "trashtalk":
            self.last_trash_at = now
        self.recent.append(message)

    def rules(self) -> str:
        allowed = self.categories or ["conseil"]
        trash = ""
        if "trashtalk" in allowed and self.trash in TRASH_LEVELS:
            trash = TRASH_RULES.format(level=self.trash, style=TRASH_LEVELS[self.trash])
        return COPILOT_RULES.format(
            categories="|".join(allowed),
            allowed="\n".join(f"- {CATEGORIES[c]}" for c in allowed),
            trash=trash,
            recent=self.recent_note(),
        )

    def recent_note(self) -> str:
        if not self.recent:
            return ""
        lines = "\n".join(f"- {m}" for m in self.recent)
        return f"Déjà dit récemment (ne le répète pas) :\n{lines}"


class Copilot:
    def __init__(self, gate: CopilotGate | None = None) -> None:
        self.gate = gate or CopilotGate()

    def observe(
        self, model: VisionModel, image: PreparedImage, game_context: str = ""
    ) -> tuple[Decision | None, bool, str]:
        """Un coup d'œil : (décision, parler ?, raison). Ne lève pas pour une réponse illisible."""
        request = AnalysisRequest(
            question=COPILOT_QUESTION,
            images=(image,),
            system_prompt=build_system_prompt(
                game_context + self.gate.rules(),
                spoken=True,
                brain="rapide",
            ),
            max_output_tokens=200,
            temperature=0.3,
        )
        started = time.perf_counter()
        result = model.analyze(request)
        took = int((time.perf_counter() - started) * 1000)
        decision = parse_decision(result.text)
        title = current_persona().title
        if decision is None:
            log.info(
                "[%s] [Cerveau rapide] [Copilote] %s/%s — réponse illisible (%d ms)",
                title,
                model.provider,
                model.model,
                took,
            )
            return None, False, "réponse illisible"
        speak, why = self.gate.allow(decision)
        log.info(
            "[%s] [Cerveau rapide] [Copilote] %s/%s — %s, importance %d/10 → %s (%s) en %d ms%s",
            title,
            model.provider,
            model.model,
            decision.category,
            decision.importance,
            "parle" if speak else "se tait",
            why,
            took,
            f" — {decision.reason}" if decision.reason else "",
        )
        if speak:
            self.gate.spoke(decision.message, category=decision.category)
        return decision, speak, why


_OFF = re.compile(
    r"\b(?:desactive|desactiver|coupe|couper|arrete|arreter|eteins|eteindre|stoppe|stop|"
    r"enleve|retire|plus de)\b(?:\s+\w+){0,3}?\s+(?:le\s+|du\s+)?(?:mode\s+)?copilote?\b"
)
_ON = re.compile(
    r"\b(?:active|activer|reactive|allume|allumer|lance|lancer|demarre|demarrer|mets|mettre|"
    r"remets|enclenche)\b(?:\s+\w+){0,3}?\s+(?:le\s+|du\s+)?(?:mode\s+)?copilote?\b"
)


def parse_copilot_command(text: str) -> bool | None:
    """« Active le copilote » → True, « désactive le mode copilote » → False, sinon None."""
    import unicodedata

    plain = unicodedata.normalize("NFKD", text.casefold())
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    plain = re.sub(r"[^\w\s]", " ", plain)
    plain = re.sub(r"\bco[\s-]+pilote", "copilote", plain)
    if len(plain.split()) > 9 or "copilot" not in plain:
        return None  # une vraie question qui parle du copilote, pas un ordre
    if _OFF.search(plain):
        return False
    if _ON.search(plain):
        return True
    return None
