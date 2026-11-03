"""Consignes du joueur : « arrête de dire ça », « ne parle plus de mes PV »…

Un ordre dit une fois est oublié par l'IA à la question suivante : elle ne garde rien. Ici,
c'est le logiciel qui enregistre la consigne (%APPDATA%\\Alicia\\consignes.json) et :
1. la rappelle à l'IA à CHAQUE demande (questions, Copilote, chat, débrief), en tête, comme
   règle prioritaire ;
2. fait respecter les consignes « ne plus dire… » par le Copilote lui-même : une intervention
   qui reprend les mots interdits est bloquée avant d'être dite, même si l'IA l'a proposée.
Une consigne se retire à la voix (« tu peux reparler de… », « annule tes consignes ») ou
dans Réglages → Profil.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from pathlib import Path

log = logging.getLogger("alicia.app")

MAX_RULES = 40
STOP = set(
    (
        "dire parler faire plus jamais arrete arreter stop evite eviter mon mes ton tes les "
        "des une que qui avec pour dans sur chaque fois tout temps toujours cette ces son ses "
        "est pas moi toi nous vous truc chose choses trucs genre de le la me te se un en et ou "
        "au du ne je tu il on ma ta sa ce si ca aux par qu elle lui leur commente commenter "
        "commentes rappelle rappeler repete repeter veux parle dis mentionne mentionner arretes"
    ).split()
)


def _plain(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in text if not unicodedata.combining(c)).replace("’", "'")


def keywords(text: str) -> set[str]:
    """Mots porteurs de sens (pour reconnaître une phrase qui enfreint la consigne)."""
    words = re.findall(r"[a-z0-9]+", _plain(text))
    out = set()
    for w in words:
        if len(w) < 2 or w in STOP:
            continue
        w = w[:-1] if w.endswith("s") and len(w) > 3 else w  # pluriels
        out.add(w[:6])  # racine grossière : surveille / surveiller
    return out


class Rules:
    def __init__(self, path: Path | None = None) -> None:
        if path is None:
            from alicia.core.config import data_dir

            path = data_dir() / "consignes.json"
        self.path = path

    def all(self) -> list[str]:
        try:
            data = json.loads(self.path.read_text("utf-8"))
        except (OSError, ValueError):
            return []
        return [str(r) for r in data] if isinstance(data, list) else []

    def _save(self, rules: list[str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(rules[-MAX_RULES:], ensure_ascii=False, indent=2), "utf-8")
        tmp.replace(self.path)

    def add(self, rule: str) -> bool:
        rule = " ".join(rule.split()).strip(" .!")[:200]
        if len(rule) < 4:
            return False
        rules = [r for r in self.all() if _plain(r) != _plain(rule)]
        rules.append(rule[:1].upper() + rule[1:])
        self._save(rules)
        log.info("Consigne du joueur enregistrée (%d au total)", len(rules))
        return True

    def remove(self, index: int) -> None:
        rules = self.all()
        if 0 <= index < len(rules):
            del rules[index]
            self._save(rules)

    def lift(self, words: str) -> int:
        """Retire les consignes qui parlent de ces mots ; « tout » les retire toutes."""
        rules = self.all()
        wanted = keywords(words)
        if not wanted or _plain(words).strip() in ("tout", "toutes", "tes consignes"):
            kept: list[str] = []
        else:
            kept = [r for r in rules if not (wanted & keywords(r))]
        self._save(kept)
        return len(rules) - len(kept)

    def prompt(self) -> str:
        rules = self.all()
        if not rules:
            return ""
        lines = "\n".join(f"- {r}" for r in rules)
        return (
            "\nCONSIGNES DU JOUEUR — prioritaires, à respecter à chaque réponse, même si une "
            "autre règle ou ta personnalité pousse dans l'autre sens (sauf un vrai danger "
            "immédiat pour sa partie, à dire sans enfreindre la consigne) :\n" + lines + "\n"
        )

    def blocks(self, message: str) -> str | None:
        """La consigne « ne plus dire… » que ce message enfreint (logiciel, pas l'IA)."""
        said = keywords(message)
        if not said:
            return None
        for rule in self.all():
            plain = _plain(rule)
            if not re.search(
                r"\b(?:dis|dire|parle|parler|mentionne|repete|comment|rappel|signale|previen)",
                plain,
            ):
                continue  # consigne de ton ou de style : seule l'IA peut la suivre
            wanted = keywords(rule)
            need = len(wanted) if len(wanted) <= 2 else -(-len(wanted) * 6 // 10)
            if wanted and len(wanted & said) >= need:
                return rule
        return None


_STOP_SAYING = re.compile(
    r"^(?:\w+\s*,\s*)?(?:"
    r"(?:arrete|arretez|stop|cesse)\s+(?:de\s+|d')(?P<a>.+)|"
    r"(?:ne\s+)?(?:me\s+)?(?:dis|parle|repete|mentionne)\s+plus\s+(?P<b>.+)|"
    r"(?:evite|evitez)\s+(?:de\s+|d'|les\s+|tes\s+)(?P<c>.+)|"
    r"je\s+(?:ne\s+)?veux\s+plus\s+que\s+tu\s+(?P<d>.+)|"
    r"(?:je\s+t'?ai\s+dit\s+de\s+ne\s+plus|ne\s+)(?P<e>.+?\s+plus\b.*)|"
    r"(?:a\s+partir\s+de\s+maintenant|desormais|dorenavant)\s*,?\s*(?P<f>.+)"
    r")$"
)
_LIFT = re.compile(
    r"^(?:\w+\s*,\s*)?(?:"
    r"tu\s+peux\s+(?:de\s+nouveau|a\s+nouveau|re)\s*(?P<a>.+)|"
    r"(?:annule|oublie|enleve|retire)\s+(?:la\s+|ta\s+|tes\s+|les\s+)?consignes?\s*(?P<b>.*)"
    r")$"
)


def parse_rule_command(text: str) -> tuple[str, str] | None:
    """(« add », consigne) | (« lift », mots) | None — sur le texte d'origine."""
    original = " ".join(text.split()).strip(" .!?")
    plain = _plain(original)
    if len(plain.split()) > 30:
        return None
    match = _LIFT.match(plain)
    if match:
        words = (match.group("a") or match.group("b") or "").strip()
        return "lift", words or "tout"
    match = _STOP_SAYING.match(plain)
    if not match:
        return None
    if re.match(r"^(?:\w+\s*,\s*)?(?:arrete|stop)\s*$", plain):
        return None  # « stop » seul : couper la voix, pas une consigne
    rest = next(v for v in match.groupdict().values() if v)
    if len(rest.split()) < 2 and rest.split()[0] in ("parler", "causer", "crier", "chanter"):
        return None  # « arrête de parler » : faire taire maintenant, pas une consigne
    consigne = original
    # « VIIRUS, arrête de… » : on garde la consigne sans l'appel au robot
    if re.match(r"^\w+\s*,", original):
        consigne = original.split(",", 1)[1].strip()
    return "add", consigne
