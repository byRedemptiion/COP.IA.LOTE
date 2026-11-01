"""Diagnostic sans interface : ``alicia-diag list-windows | capture | ask | models``.

Pratique pour isoler un problème (capture ou IA) et l'envoyer avec le log.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image

from alicia.core.config import load_settings, migrate_legacy_dirs
from alicia.core.errors import AliciaError
from alicia.core.logging_setup import setup_logging


def _find_window(capture, needle: str):  # type: ignore[no-untyped-def]
    windows = capture.list_windows()
    if needle.isdigit():
        matches = [w for w in windows if w.handle == int(needle)]
    else:
        matches = [w for w in windows if needle.casefold() in w.label.casefold()]
    if not matches:
        raise AliciaError(
            f"Aucune fenêtre ne correspond à « {needle} ». Voir : alicia-diag list-windows"
        )
    return matches[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="alicia-diag")
    parser.add_argument("--debug", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list-windows", help="fenêtres détectées")
    cap = sub.add_parser("capture", help="capture une fenêtre en PNG")
    cap.add_argument("window", help="HWND ou partie du titre / de l'exécutable")
    cap.add_argument("--out", default="capture.png")
    cap.add_argument("--backend", choices=["auto", "wgc", "printwindow"])
    ask = sub.add_parser("ask", help="envoie une image et une question à l'IA")
    ask.add_argument("image")
    ask.add_argument("question")
    sub.add_parser("models", help="modèles Gemini accessibles avec ta clé")
    sub.add_parser("devices", help="micros et sorties audio détectés")
    sub.add_parser("voices", help="voix françaises disponibles pour la réponse vocale")
    sub.add_parser("prepare-voice", help="télécharge Whisper et la voix Kokoro (installation)")
    hear = sub.add_parser("transcribe", help="transcrit un fichier WAV avec faster-whisper")
    hear.add_argument("wav")
    say = sub.add_parser("say", help="teste la réponse vocale")
    say.add_argument("--engine", choices=["edge", "kokoro"], help="moteur à tester")
    say.add_argument("text", nargs="?", default="Bonjour, je suis Alicia. Je t'entends bien ?")
    rec = sub.add_parser("record", help="teste le micro : enregistre N secondes en WAV")
    rec.add_argument("--seconds", type=float, default=4.0)
    rec.add_argument("--out", default="micro.wav")
    sub.add_parser(
        "setup-ai",
        help="installateur : enregistre l'IA choisie (ALICIA_SETUP_PROVIDER, ALICIA_SETUP_KEY)",
    )
    sub.add_parser("games", help="profils de jeu et sites de référence ; crée ton games.toml")
    sub.add_parser("ping", help="question texte minimale à l'IA (sans image) : teste clé et réseau")
    args = parser.parse_args(argv)

    migrate_legacy_dirs()
    settings = load_settings()
    setup_logging(settings.log_dir, "DEBUG" if args.debug else settings.log_level)

    if args.command == "games":
        return _games_command()
    if args.command == "setup-ai":
        return _setup_ai_command()

    try:
        if args.command in ("devices", "voices", "say", "record", "prepare-voice", "transcribe"):
            return _audio_command(args, settings)
        if args.command in ("list-windows", "capture"):
            from dataclasses import replace

            from alicia.core.capture.service import CaptureService
            from alicia.core.capture.win32 import enable_dpi_awareness

            enable_dpi_awareness()
            capture_settings = settings.capture
            if getattr(args, "backend", None):
                capture_settings = replace(capture_settings, backend=args.backend)
            capture = CaptureService.for_windows(capture_settings)
            if args.command == "list-windows":
                for w in capture.list_windows():
                    size = f"{w.rect.width}x{w.rect.height}" if w.rect else "?"
                    full = " plein-écran" if w.fullscreen else ""
                    print(f"{w.handle:>10}  {size:>10}  écran {w.monitor_index}{full}  {w.label}")
                return 0
            frame = capture.capture(_find_window(capture, args.window))
            frame.image.save(args.out)
            print(
                f"OK {frame.width}x{frame.height} via {frame.backend} en {frame.duration_ms} ms -> {args.out}"
            )
            for note in frame.notes:
                print("  ", note)
            return 0

        from alicia.core.ai.factory import create_model

        model = create_model(settings.ai)
        if args.command == "models":
            from alicia.core.ai.providers.gemini import GeminiModel

            if not isinstance(model, GeminiModel):
                print(
                    f"La commande models concerne Gemini (fournisseur actuel : {model.provider})."
                )
                return 1
            for name in model.list_models():
                print(name)
            return 0

        from alicia.core.ai.base import AnalysisRequest
        from alicia.core.ai.image_prep import prepare_image
        from alicia.core.ai.prompts import build_system_prompt

        if args.command == "ping":
            print(f"Test de {model.provider}/{model.model} (texte seul)...")
            request = AnalysisRequest(
                question="Réponds seulement : OK",
                images=(),
                system_prompt="Réponds très brièvement.",
                max_output_tokens=256,
                temperature=0,
            )
            result = model.analyze(request, on_delta=lambda t: print(t, end="", flush=True))
            print(f"\n[1er mot {result.first_token_ms} ms, total {result.latency_ms} ms]")
            return 0

        image = prepare_image(
            Image.open(Path(args.image)),
            settings.capture.max_image_side,
            settings.capture.jpeg_quality,
        )
        request = AnalysisRequest(
            question=args.question,
            images=(image,),
            system_prompt=build_system_prompt(),
            max_output_tokens=settings.ai.max_output_tokens,
            temperature=settings.ai.temperature,
        )
        result = model.analyze(request, on_delta=lambda t: print(t, end="", flush=True))
        print(
            f"\n\n[{result.provider}/{result.model} — 1er mot {result.first_token_ms} ms, "
            f"total {result.latency_ms} ms, jetons {result.input_tokens}/{result.output_tokens}]"
        )
        return 0
    except AliciaError as exc:
        print(f"ERREUR : {exc.user_message}", file=sys.stderr)
        print(f"Détail : {exc.detail}", file=sys.stderr)
        return 1


def _setup_ai_command() -> int:
    """Appelé par l'installateur. La clé arrive par variable d'environnement (jamais sur la
    ligne de commande, visible des autres programmes) et n'est jamais affichée."""
    import os

    from alicia.core.ai.providers.gemini import check_gemini_key
    from alicia.core.user_config import set_env, set_value

    provider = os.environ.get("ALICIA_SETUP_PROVIDER", "").strip().lower()
    key = os.environ.get("ALICIA_SETUP_KEY", "").strip()
    if provider not in ("gemini", "openai", "ollama"):
        print("IA : à choisir au premier lancement d'ALICIA.")
        return 0
    set_value("ai", "provider", provider)
    if provider == "ollama":
        print(
            "IA : Ollama (locale). ALICIA le démarre toute seule et télécharge son modèle "
            "au premier lancement (installe Ollama : https://ollama.com/download)."
        )
        return 0
    name = "OpenAI" if provider == "openai" else "Gemini"
    if not key:
        print(f"IA : {name}, clé à coller au premier lancement d'ALICIA.")
        return 0
    path = set_env("OPENAI_API_KEY" if provider == "openai" else "GEMINI_API_KEY", key)
    print(f"Clé {name} enregistrée sur ce PC ({path}).")
    if provider == "openai":
        from alicia.core.ai.providers.openai import check_openai_key

        problem = check_openai_key(key)
    else:
        problem = check_gemini_key(key)
    print("Clé vérifiée : OK." if problem is None else f"Attention : {problem}")
    return 0


def _games_command() -> int:
    from alicia.games.profiles import all_profiles, builtin_text, default_user_file

    user_file = default_user_file()
    if not user_file.exists():
        user_file.parent.mkdir(parents=True, exist_ok=True)
        # Copie entièrement commentée : décommente seulement ce que tu changes, pour
        # continuer de profiter des mises à jour des autres profils.
        commented = "".join(
            line if line.startswith("#") or not line.strip() else "# " + line
            for line in builtin_text().splitlines(keepends=True)
        )
        user_file.write_text(commented, encoding="utf-8")
        print(f"Fichier créé (modifie-le pour tes jeux et tes sites) : {user_file}")
    else:
        print(f"Tes profils : {user_file}")
    for profile in all_profiles().values():
        if profile.key == "generic":
            continue
        print(f"\n[{profile.key}] {profile.name}")
        print(f"  reconnu par : {', '.join(profile.exe_names + profile.title_keywords) or '—'}")
        for source in profile.sources:
            print(f"  · {source}")
    return 0


def _audio_command(args, settings) -> int:  # type: ignore[no-untyped-def]
    import time

    if args.command == "devices":
        from alicia.core.audio.devices import list_devices

        for line in list_devices():
            print(line)
        return 0
    if args.command == "voices":
        import asyncio

        import edge_tts

        voices = asyncio.run(edge_tts.list_voices())
        for voice in voices:
            if voice["Locale"].startswith("fr-"):
                print(f"{voice['ShortName']:<36} {voice['Gender']}")
        return 0
    if args.command == "prepare-voice":
        from alicia.core.audio.models import download_kokoro, download_whisper

        if settings.voice.stt == "local":
            download_whisper(settings.voice.whisper_model)
        if settings.voice.wake_word:
            download_whisper(settings.voice.wake_model)
        download_kokoro()
        print("Modèles vocaux prêts.")
        return 0
    if args.command == "transcribe":
        from alicia.core.ai.base import PreparedAudio
        from alicia.core.audio.stt import LocalTranscriber

        data = open(args.wav, "rb").read()  # noqa: SIM115
        transcriber = LocalTranscriber(settings.voice.whisper_model)
        transcriber.load()
        started = time.perf_counter()
        text = transcriber.transcribe(PreparedAudio(data, "audio/wav", 0.0))
        print(f"« {text} »  ({time.perf_counter() - started:.2f} s)")
        return 0
    if args.command == "say":
        from dataclasses import replace

        from alicia.core.audio.speaker import Speaker

        voice = replace(settings.voice, tts_engine=args.engine or settings.voice.tts_engine)
        print(f"Voix : {voice.tts_engine}")
        speaker = Speaker(voice)
        state = {}
        speaker.on_state = lambda s, m: state.update(state=s, message=m)
        started = time.perf_counter()
        speaker.speak(args.text)
        while speaker.speaking:
            time.sleep(0.05)
        if state.get("state") == "error":
            print("ERREUR :", state.get("message"))
            return 1
        print(f"Lecture terminée en {time.perf_counter() - started:.1f} s")
        return 0
    from alicia.core.audio.recorder import Recorder

    recorder = Recorder(settings.voice.sample_rate, settings.voice.input_device, args.seconds + 1)
    recorder.start()
    print(f"Parle pendant {args.seconds:.0f} s dans « {recorder.device_label} »...")
    time.sleep(args.seconds)
    audio = recorder.stop()
    with open(args.out, "wb") as handle:
        handle.write(audio.data)
    print(f"OK : {audio.duration_s} s enregistrées -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
