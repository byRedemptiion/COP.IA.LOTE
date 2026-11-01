"""Configuration centralisée.

Ordre de priorité (le premier gagne) :
1. variables d'environnement (``ALICE_AI_PROVIDER``, ``ALICE_LOG_LEVEL``, clés API) ;
2. fichier ``.env`` (dossier courant, puis dossier de données d'Alicia) ;
3. ``alicia.toml`` (dossier courant, puis dossier de données d'Alicia) ;
4. ``default.toml`` livré avec le paquet.

Les clés API ne vivent que dans l'environnement ou le ``.env`` : jamais dans un TOML ni dans Git.
"""

from __future__ import annotations

import os
import re
import sys
import tomllib
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

from alicia.core.errors import ConfigError

PROVIDERS = ("gemini", "openai", "ollama", "fake")
VISION_MODES = ("window", "cursor", "screen")


def _box(value: object) -> tuple[int, int]:
    """« 1280x800 » → (1280, 800), bornes raisonnables."""
    try:
        width, height = (int(part) for part in str(value).lower().replace(" ", "").split("x"))
    except ValueError:
        return (1280, 800)
    return (max(320, min(3840, width)), max(240, min(2160, height)))


CAPTURE_BACKENDS = ("auto", "wgc", "printwindow")


class Secret:
    """Valeur secrète qui ne s'affiche jamais en clair (repr, logs, exceptions)."""

    __slots__ = ("_value",)

    def __init__(self, value: str | None) -> None:
        self._value = (value or "").strip()

    def get(self) -> str:
        return self._value

    def __bool__(self) -> bool:
        return bool(self._value)

    def __repr__(self) -> str:
        return "Secret(***)" if self._value else "Secret(<vide>)"

    __str__ = __repr__


def data_dir() -> Path:
    """Dossier des données utilisateur (config locale, .env de la version packagée)."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "Alicia"


def migrate_legacy_dirs() -> list[str]:
    """Renomme les dossiers de l'ancien nom « Alice » en « Alicia » (modèles, logs, config)."""
    moved = []
    for new in (data_dir(), state_dir()):
        old = new.with_name("Alice")
        if old.is_dir() and not new.exists():
            try:
                old.rename(new)
                moved.append(f"{old} → {new}")
            except OSError:
                pass  # dossier occupé : on repartira de zéro, sans bloquer le démarrage
    return moved


def state_dir() -> Path:
    """Dossier des fichiers produits (logs)."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    else:
        base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "Alicia"


@dataclass(frozen=True)
class GeminiSettings:
    model: str
    base_url: str
    api_key: Secret
    thinking_budget: int | None = None
    thinking_level: str | None = None
    fallback_models: tuple[str, ...] = ()


@dataclass(frozen=True)
class OllamaSettings:
    model: str
    base_url: str
    keep_alive: str
    # Cœurs du processeur laissés à Ollama : sans carte graphique compatible, il calcule sur
    # le processeur et le fait chauffer. 0 = la moitié des cœurs (6 au plus).
    num_thread: int = 0
    # Taille de la mémoire de conversation du modèle : Ollama prend 32K par défaut sur une
    # grosse carte, ce qui gaspille plusieurs Go de VRAM (et peut faire échouer le chargement).
    num_ctx: int = 8192
    deep_model: str = ""  # modèle Ollama du cerveau réfléchi (vide = qwen3.8:27b)


@dataclass(frozen=True)
class OpenAISettings:
    model: str = "gpt-6-luna"
    base_url: str = "https://api.openai.com/v1"
    api_key: Secret = field(default_factory=lambda: Secret(None))
    reasoning_effort: str = "low"  # none | low | medium… (réponse plus rapide si bas)


@dataclass(frozen=True)
class AISettings:
    provider: str
    timeout_s: float
    max_output_tokens: int
    temperature: float
    history_turns: int
    gemini: GeminiSettings
    ollama: OllamaSettings
    web_search: bool = False
    openai: OpenAISettings = field(default_factory=OpenAISettings)
    # Deuxième cerveau, pour les questions qui demandent de réfléchir (stratégie, build,
    # analyse de partie) : "" = aucun, sinon gemini | openai | ollama (+ modèle au choix).
    deep_provider: str = ""
    deep_model: str = ""


@dataclass(frozen=True)
class CaptureSettings:
    backend: str
    monitor_fallback: bool
    max_image_side: int
    jpeg_quality: int
    keep_last_frames: int
    save_captures: bool
    timeout_s: float
    mode: str = "window"  # window (application) | cursor (zone autour du curseur) | screen
    cursor_box: tuple[int, int] = (1280, 800)  # taille de la zone autour du curseur (px)
    live: bool = True  # vision en direct : capture récente toujours prête (en mémoire)
    live_interval_s: float = 10.0  # capture de fond ; sinon capture au début de chaque phrase
    memory: bool = True  # mémoire de partie : petites captures datées sur le disque
    memory_interval_s: float = 30.0
    memory_hours: float = 20.0
    memory_max_images: int = 10_000
    memory_clear_on_exit: bool = False
    memory_folder: str = ""  # vide = %LOCALAPPDATA%\Alicia\memoire ; sinon un disque dédié
    memory_max_gb: float = 5.0


@dataclass(frozen=True)
class VoiceSettings:
    speak_answers: bool = True  # lire les réponses à voix haute
    stt: str = "gemini"  # gemini : Gemini transcrit (~1 s) | local : Whisper sur le PC
    whisper_model: str = "large-v3-turbo"
    tts_engine: str = "edge"  # edge | kokoro
    kokoro_voice: str = "ff_siwis"
    kokoro_speed: float = 1.05
    tts_voice: str = "fr-FR-DeniseNeural"
    tts_rate: str = "+8%"
    output_device: str = ""  # vide = sortie Windows par défaut ; sinon une partie du nom
    input_device: str = ""  # vide = micro Windows par défaut ; sinon une partie du nom
    max_record_s: float = 30.0
    sample_rate: int = 16000
    wake_word: bool = True  # dire « Alicia… » pour lui parler sans toucher au clavier
    wake_model: str = "base"  # petit Whisper dédié au mot de réveil
    wake_sensitivity: int = 3  # 1 = peu sensible (pièce bruyante) … 5 = très sensible
    openai_voice: str = "coral"  # voix OpenAI (moteur « openai »)
    openai_tts_model: str = "gpt-4o-mini-tts"
    openai_key: Secret = field(default_factory=lambda: Secret(None))  # même clé que l'IA OpenAI
    openai_base_url: str = "https://api.openai.com/v1"
    gemini_voice: str = "Leda"  # voix Gemini (moteur « gemini »)
    volume: int = 100  # volume de la voix du robot, en % (0-200)
    voice_effect: str = ""  # "" | enfant | robot | gros_robot (sur Edge, Gemini, OpenAI, Kokoro)
    gemini_tts_model: str = "gemini-3.1-flash-tts-preview"
    gemini_key: Secret = field(default_factory=lambda: Secret(None))  # même clé que l'IA Gemini


@dataclass(frozen=True)
class AppEntry:
    launch: str  # chemin d'un .exe ou lien (discord://, spotify:)
    process: str = ""  # nom du processus pour « ferme X » (ex. Discord.exe)


DEFAULT_APPS = {
    "discord": AppEntry("discord://", "Discord.exe"),
    "spotify": AppEntry("spotify:", "Spotify.exe"),
    "steam": AppEntry("steam://open/main", "steam.exe"),
    "battle.net": AppEntry("battlenet://", "Battle.net.exe"),
    "youtube": AppEntry("https://www.youtube.com", ""),  # dans le navigateur
    "twitch": AppEntry("https://www.twitch.tv", ""),
}


@dataclass(frozen=True)
class ActionSettings:
    enabled: bool = True
    shutdown_delay_s: int = 20
    confirm_timeout_s: float = 20.0
    apps: dict[str, AppEntry] = field(default_factory=lambda: dict(DEFAULT_APPS))


@dataclass(frozen=True)
class UpdateSettings:
    repo: str = "byRedemptiion/COP.IA.LOTE"
    branch: str = "alice-v0.3"
    check_on_start: bool = True
    token: Secret = field(default_factory=lambda: Secret(None))


@dataclass(frozen=True)
class StreamSettings:
    twitch_channel: str = ""  # ex. « nova_jagger » : bouton « Chat Twitch »
    overlay: bool = True  # page pour OBS (source Navigateur) sur http://127.0.0.1:<port>/overlay
    overlay_port: int = 8765


@dataclass(frozen=True)
class PlayerSettings:
    name: str = ""  # ton prénom / pseudo, écrit
    phonetic: str = ""  # comment la voix doit le dire (vide = tel quel)


@dataclass(frozen=True)
class DuoSettings:
    enabled: bool = False  # ALICIA chez l'un, VIIRUS chez l'autre : ils se parlent
    code: Secret = field(default_factory=lambda: Secret(None))  # DUO_CODE dans .env
    max_turns: int = 4  # répliques au total quand les robots discutent entre eux
    hear_peer: bool = True  # entendre aussi l'autre robot sur ce PC, avec sa voix
    allow_chat: bool = False  # les robots ne se répondent tout seuls que si c'est autorisé
    player: str = ""  # ton prénom, pour les messages transmis (« Redem veut savoir… »)
    provider: str = "main"  # IA du duo : main (la même) | gemini | openai | ollama
    key_slot: str = ""  # clé à utiliser (ex. GEMINI_API_KEY_2) ; vide = la clé utilisée
    relay: str = "https://ntfy.sh"


@dataclass(frozen=True)
class CopilotSettings:
    """Mode Copilote : le robot regarde de temps en temps et parle seulement si ça compte."""

    enabled: bool = False
    interval_s: float = (
        30.0  # coup d'œil à l'écran (8 s minimum ; 15 s et plus avec Ollama, qui chauffe)
    )
    threshold: int = 7  # importance minimale (1-10) pour parler sans qu'on lui demande
    cooldown_s: float = 60.0  # silence minimum entre deux interventions spontanées
    spontaneity: str = "normal"  # discret | normal | bavard | perso (seuil réglé à la main)
    kinds: str = "conseils,alertes,reactions,humour"  # types d'interventions permis
    trash: str = "off"  # trash-talk : off | leger | normal | corse


@dataclass(frozen=True)
class Settings:
    ai: AISettings
    capture: CaptureSettings
    log_level: str
    game_profile: str
    hotkey_analyze: str = ""
    hotkey_talk: str = ""
    voice: VoiceSettings = field(default_factory=VoiceSettings)
    actions: ActionSettings = field(default_factory=ActionSettings)
    update: UpdateSettings = field(default_factory=UpdateSettings)
    stream: StreamSettings = field(default_factory=StreamSettings)
    duo: DuoSettings = field(default_factory=DuoSettings)
    player: PlayerSettings = field(default_factory=PlayerSettings)
    copilot: CopilotSettings = field(default_factory=CopilotSettings)
    ui_mode: str = "orb"  # "orb" : seule la bulle d'ALICIA à l'écran ; "full" : le panneau
    ui_last: str = "orb"  # dernier mode utilisé (pour ui_mode = "last")
    orb_size: int = 210
    stream_visible: bool = False  # True : OBS / Discord voient le rond et la bulle
    persona: str = "alicia"  # « alicia » ou « veris » : nom, portrait, couleurs, voix
    sources: tuple[str, ...] = field(default_factory=tuple)
    log_dir: Path = field(default_factory=lambda: state_dir() / "logs")
    captures_dir: Path = field(default_factory=lambda: Path.cwd() / "captures")


def twitch_channel(text: str) -> str:
    """« Nova_Jagger », « https://www.twitch.tv/nova_jagger » → « nova_jagger » ("" si invalide)."""
    text = text.strip().rstrip("/")
    match = re.search(r"twitch\.tv/(?:popout/)?([A-Za-z0-9_]{3,25})", text)
    name = match.group(1) if match else text.lstrip("@")
    return name.lower() if re.fullmatch(r"[A-Za-z0-9_]{3,25}", name) else ""


def twitch_chat_url(channel: str) -> str:
    return f"https://www.twitch.tv/popout/{channel}/chat?popout="


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Le fichier de configuration {path} est invalide : {exc}") from exc


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name, {})
    if not isinstance(value, dict):
        raise ConfigError(f"La section [{name}] de la configuration est invalide.")
    return value


def _number(section: dict[str, Any], key: str, kind: type, minimum: float) -> Any:
    try:
        value = kind(section[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigError(f"Réglage « {key} » manquant ou invalide.") from exc
    if value < minimum:
        raise ConfigError(f"Réglage « {key} » trop petit (minimum {minimum}).")
    return value


def _actions(section: dict[str, Any]) -> ActionSettings:
    apps: dict[str, AppEntry] = {}
    raw_apps = section.get("apps", {})
    if not isinstance(raw_apps, dict):
        raise ConfigError("La section [actions.apps] est invalide.")
    for name, value in raw_apps.items():
        if isinstance(value, str):
            entry = AppEntry(value.strip())
        elif isinstance(value, dict) and value.get("launch"):
            entry = AppEntry(str(value["launch"]).strip(), str(value.get("process", "")).strip())
        else:
            raise ConfigError(f"Application « {name} » invalide dans [actions.apps].")
        apps[str(name).strip().lower()] = entry
    return ActionSettings(
        enabled=bool(section.get("enabled", True)),
        shutdown_delay_s=_number(section, "shutdown_delay_s", int, 10)
        if "shutdown_delay_s" in section
        else 60,
        confirm_timeout_s=float(section.get("confirm_timeout_s", 20)),
        apps=apps or dict(DEFAULT_APPS),
    )


def _choice(section: dict[str, Any], key: str, default: str, allowed: tuple[str, ...]) -> str:
    value = str(section.get(key, default)).strip().lower()
    if value not in allowed:
        raise ConfigError(
            f"Réglage « {key} » invalide : « {value} » (choix : {', '.join(allowed)})."
        )
    return value


def load_settings(
    *,
    cwd: Path | None = None,
    environ: dict[str, str] | None = None,
    user_dir: Path | None = None,
) -> Settings:
    cwd = cwd or Path.cwd()
    user_dir = user_dir or data_dir()
    env_os = dict(os.environ if environ is None else environ)

    sources: list[str] = ["default.toml"]
    data = tomllib.loads(resources.files("alicia").joinpath("default.toml").read_text("utf-8"))
    for candidate in (
        user_dir / "alice.toml",  # ancien nom, encore lu
        user_dir / "alicia.toml",
        cwd / "alice.toml",
        cwd / "alicia.toml",
    ):
        if candidate.is_file():
            data = _merge(data, _read_toml(candidate))
            sources.append(str(candidate))

    env: dict[str, str] = {}
    for candidate in (user_dir / ".env", cwd / ".env"):
        if candidate.is_file():
            env.update({k: v for k, v in dotenv_values(candidate).items() if v is not None})
            sources.append(str(candidate))
    env.update(env_os)

    ai = _section(data, "ai")
    gemini = _section(ai, "gemini")
    ollama = _section(ai, "ollama")
    openai = _section(ai, "openai")
    capture = _section(data, "capture")
    voice = _section(data, "voice")

    provider = str(env.get("ALICE_AI_PROVIDER") or ai.get("provider", "gemini")).strip().lower()
    if provider not in PROVIDERS:
        raise ConfigError(
            f"Fournisseur IA inconnu « {provider} » (choix : {', '.join(PROVIDERS)})."
        )
    backend = str(capture.get("backend", "auto")).strip().lower()
    if backend not in CAPTURE_BACKENDS:
        raise ConfigError(f"Backend de capture inconnu « {backend} ».")
    level = str(env.get("ALICE_LOG_LEVEL") or _section(data, "logging").get("level", "INFO"))
    level = level.strip().upper()
    if level not in ("DEBUG", "INFO", "WARNING", "ERROR"):
        raise ConfigError(f"Niveau de log inconnu « {level} ».")

    thinking_budget = gemini.get("thinking_budget")
    return Settings(
        ai=AISettings(
            deep_provider=_choice(ai, "deep_provider", "", ("", "gemini", "openai", "ollama")),
            # deep_model : modèle en ligne du cerveau réfléchi ; celui d'Ollama est dans [ai.ollama]
            deep_model=""
            if ai.get("deep_provider") == "ollama"
            else str(ai.get("deep_model", "")).strip(),
            provider=provider,
            timeout_s=_number(ai, "timeout_s", float, 1),
            max_output_tokens=_number(ai, "max_output_tokens", int, 16),
            temperature=_number(ai, "temperature", float, 0),
            history_turns=_number(ai, "history_turns", int, 0),
            gemini=GeminiSettings(
                model=str(gemini.get("model", "")).strip(),
                base_url=str(gemini.get("base_url", "")).rstrip("/"),
                api_key=Secret(env.get("GEMINI_API_KEY") or env.get("GOOGLE_API_KEY")),
                thinking_budget=int(thinking_budget) if thinking_budget is not None else None,
                thinking_level=(
                    str(gemini["thinking_level"]) if "thinking_level" in gemini else None
                ),
                fallback_models=tuple(
                    str(m).strip() for m in gemini.get("fallback_models", []) if str(m).strip()
                ),
            ),
            ollama=OllamaSettings(
                model=str(ollama.get("model", "")).strip(),
                base_url=str(ollama.get("base_url", "")).rstrip("/"),
                keep_alive=str(ollama.get("keep_alive", "2m")),
                num_thread=max(0, min(64, int(ollama.get("num_thread", 0) or 0))),
                num_ctx=max(2048, min(262144, int(ollama.get("num_ctx", 8192) or 8192))),
                deep_model=str(
                    ollama.get("deep_model")
                    or (ai.get("deep_model", "") if ai.get("deep_provider") == "ollama" else "")
                ).strip(),
            ),
            web_search=bool(ai.get("web_search", False)),
            openai=OpenAISettings(
                model=str(openai.get("model", OpenAISettings.model)).strip(),
                base_url=str(openai.get("base_url", OpenAISettings.base_url)).rstrip("/"),
                api_key=Secret(env.get("OPENAI_API_KEY")),
                reasoning_effort=str(openai.get("reasoning_effort", "low")).strip().lower(),
            ),
        ),
        capture=CaptureSettings(
            backend=backend,
            monitor_fallback=bool(capture.get("monitor_fallback", True)),
            max_image_side=_number(capture, "max_image_side", int, 256),
            jpeg_quality=min(_number(capture, "jpeg_quality", int, 30), 100),
            keep_last_frames=_number(capture, "keep_last_frames", int, 1),
            save_captures=bool(capture.get("save_captures", False)),
            timeout_s=_number(capture, "timeout_s", float, 0.2),
            mode=_choice(capture, "mode", "window", VISION_MODES),
            cursor_box=_box(capture.get("cursor_box", "1280x800")),
            live=bool(capture.get("live", True)),
            live_interval_s=max(5.0, min(60.0, float(capture.get("live_interval_s", 10.0)))),
            memory=bool(capture.get("memory", True)),
            memory_interval_s=max(5.0, float(capture.get("memory_interval_s", 30.0))),
            memory_hours=max(0.5, min(720.0, float(capture.get("memory_hours", 20.0)))),
            memory_folder=str(capture.get("memory_folder", "")).strip(),
            memory_max_gb=max(0.1, min(10_000.0, float(capture.get("memory_max_gb", 5.0)))),
            memory_max_images=max(10, int(capture.get("memory_max_images", 10_000))),
            memory_clear_on_exit=bool(capture.get("memory_clear_on_exit", False)),
        ),
        log_level=level,
        game_profile=str(_section(data, "game").get("profile", "auto")).strip().lower(),
        hotkey_analyze=str(_section(data, "hotkeys").get("analyze", "")).strip(),
        hotkey_talk=str(_section(data, "hotkeys").get("talk", "")).strip(),
        actions=_actions(_section(data, "actions")),
        ui_mode=_choice(_section(data, "ui"), "mode", "orb", ("orb", "full", "last")),
        ui_last=_choice(_section(data, "ui"), "last_mode", "orb", ("orb", "full")),
        persona=_choice(_section(data, "ui"), "persona", "alicia", ("alicia", "veris")),
        stream_visible=bool(_section(data, "ui").get("stream_visible", False)),
        stream=StreamSettings(
            twitch_channel=twitch_channel(str(_section(data, "stream").get("twitch_channel", ""))),
            overlay=bool(_section(data, "stream").get("overlay", True)),
            overlay_port=min(
                65000,
                max(1024, int(_section(data, "stream").get("overlay_port", 8765) or 8765)),
            ),
        ),
        duo=DuoSettings(
            enabled=bool(_section(data, "duo").get("enabled", False)),
            code=Secret(env.get("DUO_CODE")),
            max_turns=max(2, min(20, int(_section(data, "duo").get("max_turns", 4) or 4))),
            hear_peer=bool(_section(data, "duo").get("hear_peer", True)),
            allow_chat=bool(_section(data, "duo").get("allow_chat", False)),
            player=str(_section(data, "duo").get("player", "")).strip()[:24],
            provider=_choice(
                _section(data, "duo"), "provider", "main", ("main", "gemini", "openai", "ollama")
            ),
            key_slot=str(_section(data, "duo").get("key_slot", "")).strip(),
            relay=str(_section(data, "duo").get("relay", DuoSettings.relay)).rstrip("/"),
        ),
        player=PlayerSettings(
            name=str(
                _section(data, "player").get("name", "") or _section(data, "duo").get("player", "")
            ).strip()[:40],
            phonetic=str(_section(data, "player").get("phonetic", "")).strip()[:60],
        ),
        copilot=_copilot_settings(_section(data, "copilot")),
        update=UpdateSettings(
            repo=str(_section(data, "update").get("repo", UpdateSettings.repo)).strip(),
            branch=str(_section(data, "update").get("branch", UpdateSettings.branch)).strip(),
            check_on_start=bool(_section(data, "update").get("check_on_start", True)),
            token=Secret(env.get("ALICIA_GITHUB_TOKEN") or env.get("GITHUB_TOKEN")),
        ),
        orb_size=min(
            _number({"orb_size": _section(data, "ui").get("orb_size", 210)}, "orb_size", int, 120),
            600,
        ),
        voice=VoiceSettings(
            speak_answers=bool(voice.get("speak_answers", True)),
            stt=_choice(voice, "stt", "gemini", ("local", "gemini")),
            whisper_model=str(voice.get("whisper_model", "large-v3-turbo")).strip(),
            tts_engine=_choice(
                voice,
                "tts_engine",
                "edge",
                ("edge", "kokoro", "openai", "gemini", "veris", "voixc"),
            ),
            kokoro_voice=str(voice.get("kokoro_voice", "ff_siwis")).strip(),
            kokoro_speed=_number({"v": voice.get("kokoro_speed", 1.05)}, "v", float, 0.5),
            tts_voice=str(voice.get("tts_voice", "fr-FR-DeniseNeural")).strip(),
            tts_rate=str(voice.get("tts_rate", "+0%")).strip(),
            output_device=str(voice.get("output_device", "")).strip(),
            input_device=str(voice.get("input_device", "")).strip(),
            max_record_s=_number(voice, "max_record_s", float, 2),
            sample_rate=_number(voice, "sample_rate", int, 8000),
            wake_word=bool(voice.get("wake_word", True)),
            wake_model=str(voice.get("wake_model", "base")).strip() or "base",
            wake_sensitivity=max(1, min(5, int(voice.get("wake_sensitivity", 3)))),
            openai_voice=str(voice.get("openai_voice", "coral")).strip() or "coral",
            openai_tts_model=str(voice.get("openai_tts_model", "gpt-4o-mini-tts")).strip(),
            openai_key=Secret(env.get("OPENAI_API_KEY")),
            openai_base_url=str(openai.get("base_url", "https://api.openai.com/v1")).rstrip("/"),
            gemini_voice=str(voice.get("gemini_voice", "Leda")).strip() or "Leda",
            volume=max(0, min(200, int(voice.get("volume", 100) or 0))),
            voice_effect=_choice(
                voice, "voice_effect", "", ("", "enfant", "robot", "robot_enfant", "gros_robot")
            ),
            gemini_tts_model=str(
                voice.get("gemini_tts_model", "gemini-3.1-flash-tts-preview")
            ).strip(),
            gemini_key=Secret(env.get("GEMINI_API_KEY") or env.get("GOOGLE_API_KEY")),
        ),
        sources=tuple(sources),
        captures_dir=cwd / "captures",
    )


def _copilot_settings(section: dict) -> CopilotSettings:  # type: ignore[type-arg]
    def number(key: str, default: float, low: float, high: float) -> float:
        try:
            value = float(section.get(key, default))
        except (TypeError, ValueError):
            value = default
        return max(low, min(high, value))

    return CopilotSettings(
        enabled=bool(section.get("enabled", False)),
        interval_s=number("interval_s", 30.0, 8.0, 300.0),
        threshold=int(number("threshold", 7, 1, 10)),
        cooldown_s=number("cooldown_s", 60.0, 10.0, 900.0),
        spontaneity=_choice(
            section, "spontaneity", "normal", ("discret", "normal", "bavard", "perso")
        ),
        kinds=str(section.get("kinds", CopilotSettings.kinds)),
        trash=_choice(section, "trash", "off", ("off", "leger", "normal", "corse")),
    )
