"""« Mes voix » : une voix du catalogue (Edge, Gemini, ChatGPT) + ses réglages fins, enregistrée
sous un nom pour la choisir d'un clic en voix principale ou en voix de secours.

Rangées dans %APPDATA%\\Alicia\\voix_perso.json (sauvegardées avec le reste des réglages).
Aucune clé ici : juste le nom de la voix de base et les réglages.
"""

from __future__ import annotations

import json
import logging
import secrets
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from alicia.core.config import VoiceSettings

log = logging.getLogger("alicia.audio")

ENGINES = ("edge", "gemini", "openai")
MAX_VOICES = 60
_path: Path | None = None


@dataclass(frozen=True)
class CustomVoice:
    id: str
    name: str
    engine: str  # edge | gemini | openai
    voice: str  # nom de la voix de base (fr-FR-HenriNeural, Kore, onyx…)
    pitch: float = 0.0  # demi-tons
    metal: int = 0  # %
    bright: int = 50  # % (50 = neutre)
    reverb: int = 0  # %
    style: str = ""  # jeu de voix (Gemini, ChatGPT)

    def clamped(self) -> CustomVoice:
        return replace(
            self,
            name=" ".join(self.name.split())[:40] or "Ma voix",
            pitch=max(-6.0, min(6.0, round(float(self.pitch) * 2) / 2)),
            metal=max(0, min(100, int(self.metal))),
            bright=max(0, min(100, int(self.bright))),
            reverb=max(0, min(100, int(self.reverb))),
            style=" ".join(self.style.split())[:300],
        )


def use_file(path: Path | None) -> None:
    """Tests : fichier ailleurs (None = emplacement normal)."""
    global _path
    _path = path


def _file() -> Path:
    if _path is not None:
        return _path
    from alicia.core.config import data_dir

    return data_dir() / "voix_perso.json"


def load_custom() -> list[CustomVoice]:
    try:
        data = json.loads(_file().read_text("utf-8"))
    except (OSError, ValueError):
        return []
    voices = []
    for item in data if isinstance(data, list) else []:
        try:
            voice = CustomVoice(
                id=str(item["id"]),
                name=str(item["name"]),
                engine=str(item["engine"]),
                voice=str(item["voice"]),
                pitch=float(item.get("pitch", 0.0)),
                metal=int(item.get("metal", 0)),
                bright=int(item.get("bright", 50)),
                reverb=int(item.get("reverb", 0)),
                style=str(item.get("style", "")),
            )
        except (KeyError, TypeError, ValueError):
            continue
        if voice.engine in ENGINES and voice.voice:
            voices.append(voice.clamped())
    return voices


def _save_all(voices: list[CustomVoice]) -> None:
    path = _file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    data = [asdict(v) for v in voices[:MAX_VOICES]]
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    tmp.replace(path)


def get_custom(voice_id: str) -> CustomVoice | None:
    return next((v for v in load_custom() if v.id == voice_id), None)


def save_custom(voice: CustomVoice) -> CustomVoice:
    """Ajoute la voix, ou remplace celle qui a le même identifiant ou le même nom."""
    voice = voice.clamped()
    voices = load_custom()
    same = next(
        (v for v in voices if v.id == voice.id or v.name.casefold() == voice.name.casefold()),
        None,
    )
    if same is not None:
        voice = replace(voice, id=same.id)
        voices = [voice if v.id == same.id else v for v in voices]
    else:
        voice = replace(voice, id=voice.id or "v" + secrets.token_hex(4))
        voices.append(voice)
    _save_all(voices)
    log.info("Mes voix : « %s » enregistrée (%s)", voice.name, voice.engine)
    return voice


def delete_custom(voice_id: str) -> None:
    _save_all([v for v in load_custom() if v.id != voice_id])


def voice_settings(settings: VoiceSettings, voice: CustomVoice) -> VoiceSettings:
    """Les réglages de voix qui font parler avec ``voice`` (le reste inchangé)."""
    return replace(settings, **main_changes(voice))  # type: ignore[arg-type]


def main_changes(voice: CustomVoice) -> dict[str, object]:
    """Ce qui change dans les réglages quand on la choisit en voix principale."""
    field = {"gemini": "gemini_voice", "openai": "openai_voice"}.get(voice.engine, "tts_voice")
    return {
        "tts_engine": voice.engine,
        field: voice.voice,
        "voice_effect": "",
        "voice_style": voice.style,
        "fx_pitch": voice.pitch,
        "fx_metal": voice.metal,
        "fx_bright": voice.bright,
        "fx_reverb": voice.reverb,
    }


def matches(settings: VoiceSettings, voice: CustomVoice) -> bool:
    """Vrai si la voix principale actuelle est exactement celle-ci."""
    current = {
        "edge": settings.tts_voice,
        "gemini": settings.gemini_voice,
        "openai": settings.openai_voice,
    }.get(settings.tts_engine)
    return (
        settings.tts_engine == voice.engine
        and current == voice.voice
        and abs(settings.fx_pitch - voice.pitch) < 0.01
        and settings.fx_metal == voice.metal
        and settings.fx_bright == voice.bright
        and settings.fx_reverb == voice.reverb
        and settings.voice_style == voice.style
    )


def current_custom(settings: VoiceSettings) -> CustomVoice | None:
    return next((v for v in load_custom() if matches(settings, v)), None)


def migrate(settings: VoiceSettings) -> CustomVoice | None:
    """Ancienne version : un effet réglé directement sur sa voix devient « Ma voix (avant) »
    dans Mes voix, pour le retrouver et le reprendre (une seule fois)."""
    from alicia.core.audio.speaker import fx_neutral

    if _file().exists() or settings.tts_engine not in ENGINES:
        return None
    if fx_neutral(settings.fx_pitch, settings.fx_metal, settings.fx_bright, settings.fx_reverb):
        _save_all([])  # rien à reprendre : le fichier marque que c'est fait
        return None
    if settings.tts_engine == "gemini" and settings.gemini_voice.startswith("voice_"):
        _save_all([])
        return None
    base = {
        "edge": settings.tts_voice,
        "gemini": settings.gemini_voice,
        "openai": settings.openai_voice,
    }[settings.tts_engine]
    return save_custom(
        CustomVoice(
            id="",
            name="Ma voix (avant)",
            engine=settings.tts_engine,
            voice=base,
            pitch=settings.fx_pitch,
            metal=settings.fx_metal,
            bright=settings.fx_bright,
            reverb=settings.fx_reverb,
            style=settings.voice_style,
        )
    )
