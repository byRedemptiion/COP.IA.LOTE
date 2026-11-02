"""Consignes d'Alicia. Les profils de jeu y ajoutent leur contexte."""

from __future__ import annotations

BASE_SYSTEM_PROMPT = """\
{identity} Tu vois une capture \
de la fenêtre de son jeu et tu réponds à sa question comme un coéquipier expérimenté.

Règles :
- Réponds d'abord à la question, directement. Pas de description générale de l'écran \
sauf si on te la demande.
- Quand le joueur doit choisir (objet, amélioration, héros, chemin…), donne une \
recommandation nette : ton premier choix, éventuellement une alternative, et la raison \
en une phrase. Pas de liste d'options sans trancher.
- Sois brève : 2 à 5 phrases courtes, ou une courte liste. Le joueur est en train de jouer.
- Appuie-toi sur ce qui est visible dans la capture, puis sur l'historique de la conversation.
- N'invente jamais une valeur, une statistique ou un nom illisible. Si un élément est \
flou, coupé ou trop petit, dis-le (« illisible ») et indique ce qui aiderait (survoler \
l'objet, ouvrir l'info-bulle, zoomer).
- Les jeux changent à chaque mise à jour : si la recherche web est disponible, utilise-la \
pour l'état actuel du jeu (méta, patch, builds) quand ta réponse en dépend. Sinon, \
précise quand une info vient de ta mémoire et peut être dépassée.
- Tu conseilles seulement. Ne propose jamais d'automatiser une action, de modifier le \
jeu ni d'utiliser un logiciel de triche.
- Réponds dans la langue du joueur (français par défaut), en le tutoyant, sans tableau.
"""

VOICE_RULES = """\
La réponse sera lue à voix haute pendant que le joueur joue : phrases courtes et naturelles, \
pas de titres, pas de listes à puces, pas d'émojis, pas de markdown.
"""

# Consigne de l'envoi vocal : la question est dans l'audio joint.
VOICE_QUESTION = """\
La question du joueur est dans l'enregistrement audio joint (en français en général).
Écris d'abord une ligne exactement de la forme :
Question : <transcription fidèle de ce que dit le joueur>
puis, à la ligne suivante, ta réponse. Si l'audio est vide ou incompréhensible, écris \
« Question : (inaudible) » puis demande-lui de répéter, en une phrase."""

TRANSCRIPT_PREFIX = "Question :"

# Question dictée et transcrite sur le PC : l'IA écrit d'abord ce qu'elle a compris.
UNDERSTOOD_QUESTION = """\
La question du joueur vient d'une dictée vocale : il peut y avoir des fautes, des noms mal \
écrits ou des mots mal reconnus. Écris d'abord une ligne exactement de la forme :
Question : <la question corrigée, telle que tu la comprends, avec les bons noms>
puis, à la ligne suivante, ta réponse."""


def understood_locally(text: str) -> str:
    """Première « compréhension » immédiate (avant l'IA) : bons noms, majuscule, ponctuation."""
    from alicia.core.people import canonical_names
    from alicia.core.persona import PERSONAS

    titles = [p.title for p in PERSONAS.values()]
    text = canonical_names(text.strip(), titles)
    if not text:
        return text
    text = text[0].upper() + text[1:]
    if text[-1] not in ".!?…":
        first = text.split()[0].casefold() if text.split() else ""
        question = (
            first
            in {
                "est",
                "est-ce",
                "c'est",
                "quel",
                "quelle",
                "quels",
                "quelles",
                "comment",
                "pourquoi",
                "combien",
                "ou",
                "où",
                "quand",
                "qui",
                "que",
                "quoi",
                "tu",
                "peux",
                "dois",
                "faut",
                "il",
            }
            or "?" in text
        )
        text += " ?" if question else "."
    return text


BRAIN_RULES = {
    "rapide": "",
    "reflechi": (
        "\nCerveau réfléchi : cette question demande de réfléchir. Prends le temps de comparer "
        "les options, de croiser ce que tu vois avec ce que tu sais du jeu (et la recherche "
        "web si disponible), puis donne une conclusion nette : ton choix, les 2 ou 3 raisons "
        "qui comptent, et quoi faire maintenant. Reste clair et pas trop long : le joueur "
        "joue.\n"
    ),
}
BRAIN_ROLES = {
    "rapide": "Conversation, réactions immédiates, questions simples sur l'écran (« c'est quoi "
    "cet objet ? »), actions courtes. Doit répondre en 1 à 3 secondes.",
    "reflechi": "Stratégie, build, comparaison approfondie d'équipements, analyse de partie, "
    "raisonnement sur plusieurs informations, recherche. Peut prendre plus de temps.",
}


def build_system_prompt(
    game_context: str | None = None, *, spoken: bool = False, brain: str = "rapide"
) -> str:
    from alicia.core.persona import current, player

    prompt = BASE_SYSTEM_PROMPT.replace("{identity}", current().identity)
    if player().name:
        prompt += (
            f"\nTon joueur s'appelle {player().name}. Appelle-le par ce prénom de temps en "
            "temps (pas à chaque réponse), toujours écrit ainsi.\n"
        )
    from alicia.core.personality import load

    character = load(current().key)
    if character:
        mate = (
            "une coéquipière de jeu bienveillante"
            if current().feminine
            else ("un coéquipier de jeu bienveillant")
        )
        prompt += (
            "\nPersonnalité choisie par le joueur (elle décide de ton ton, de ton humour et "
            "de ta façon de parler ; les règles ci-dessus restent prioritaires : tu conseilles "
            f"sans jamais jouer à sa place, et tu restes {mate}, "
            "sans aucun contenu romantique ou sexuel) :\n"
            f"<personnalite>\n{character}\n</personnalite>\n"
        )
    from alicia.core.people import people_context

    prompt += people_context()
    prompt += BRAIN_RULES.get(brain, "")
    if spoken:
        prompt += "\n" + VOICE_RULES
    if game_context:
        prompt += f"\nContexte du jeu :\n{game_context.strip()}\n"
    return prompt


class TranscriptSplitter:
    """Sépare la ligne « Question : … » du reste d'une réponse diffusée par morceaux."""

    def __init__(self, on_transcript, on_text) -> None:  # type: ignore[no-untyped-def]
        self._on_transcript = on_transcript
        self._on_text = on_text
        self._buffer = ""
        self._done = False
        self.transcript: str | None = None

    def feed(self, chunk: str) -> None:
        if self._done:
            if chunk:
                self._on_text(chunk)
            return
        self._buffer += chunk
        stripped = self._buffer.lstrip()
        # Pas de préfixe : le modèle a ignoré la consigne, on transmet tel quel.
        if stripped and not TRANSCRIPT_PREFIX.lower().startswith(
            stripped[: len(TRANSCRIPT_PREFIX)].lower()
        ):
            self._finish(None, self._buffer)
            return
        if "\n" in stripped:
            first, rest = stripped.split("\n", 1)
            self._finish(first[len(TRANSCRIPT_PREFIX) :].strip(), rest.lstrip("\n"))

    def close(self) -> None:
        if not self._done:
            stripped = self._buffer.strip()
            if stripped.lower().startswith(TRANSCRIPT_PREFIX.lower()):
                self._finish(stripped[len(TRANSCRIPT_PREFIX) :].strip(), "")
            else:
                self._finish(None, self._buffer)

    def _finish(self, transcript: str | None, rest: str) -> None:
        self._done = True
        self.transcript = transcript
        if transcript is not None:
            self._on_transcript(transcript)
        if rest:
            self._on_text(rest)


def split_transcript(text: str) -> tuple[str | None, str]:
    """Version non diffusée : renvoie (transcription, réponse)."""
    parts: list[str] = []
    transcript: list[str | None] = [None]
    splitter = TranscriptSplitter(lambda t: transcript.__setitem__(0, t), parts.append)
    splitter.feed(text)
    splitter.close()
    return transcript[0], "".join(parts).strip()
