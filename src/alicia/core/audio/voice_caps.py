"""Ce que chaque moteur de voix sait faire, réglage par réglage.

- « native » : le fournisseur le fait lui-même (vitesse Edge, jeu de voix Gemini…) ;
- « local » : appliqué sur ton PC, au son reçu (hauteur, robot, clarté, réverbération,
  volume ; vitesse pour Gemini et ChatGPT) — gratuit, sans quota ;
- « off » : impossible avec ce moteur ; l'interface grise le réglage et dit pourquoi.

Rien n'est simulé : un réglage « off » n'a aucun curseur actif.
"""

from __future__ import annotations

CONTROLS = ("pitch", "rate", "metal", "bright", "reverb", "volume", "style")

LABELS = {
    "pitch": "Hauteur",
    "rate": "Vitesse",
    "metal": "Robot / métal",
    "bright": "Clarté",
    "reverb": "Réverbération",
    "volume": "Volume",
    "style": "Jeu de voix",
}

PROVIDERS = {
    "edge": "Microsoft Edge",
    "gemini": "Gemini 3.1",
    "designed": "Gemini 3.8 (voix générée)",
    "openai": "ChatGPT (OpenAI)",
    "kokoro": "Kokoro (sur ton PC)",
    "veris": "Voix intégrée (sur ton PC)",
    "voixc": "Voix intégrée (sur ton PC)",
    "local": "Voix intégrée (sur ton PC)",
}

_LOCAL = ("local", "")
_BUILT_IN = (
    "off",
    "voix intégrée : gardée telle quelle (seuls le volume et la vitesse se règlent)",
)


def kind(engine: str, voice: str = "") -> str:
    """edge | gemini | designed | openai | kokoro | veris | voixc | local."""
    if engine == "gemini" and voice.startswith("voice_"):
        return "designed"
    return engine or "local"


def capabilities(engine: str, voice: str = "") -> dict[str, tuple[str, str]]:
    """{réglage: (« native » | « local » | « off », explication courte)}."""
    k = kind(engine, voice)
    if k in ("veris", "voixc", "local"):
        caps = {c: _BUILT_IN for c in CONTROLS}
        caps["volume"] = _LOCAL
        caps["rate"] = ("native", "")
        return caps
    caps = {c: _LOCAL for c in CONTROLS}
    if k == "edge":
        caps["rate"] = ("native", "")
        caps["style"] = ("off", "Edge lit le texte tel quel : il ne suit pas de consigne de jeu")
    elif k == "kokoro":
        caps["rate"] = ("native", "")
        caps["style"] = ("off", "Kokoro lit le texte tel quel : pas de consigne de jeu")
    else:  # gemini, designed, openai : le débit passe par la consigne donnée à la voix
        caps["style"] = ("native", "")
        caps["rate"] = (
            "native",
            "approximatif : demandé à la voix par consigne (lent, posé, vif…)",
        )
    return caps
