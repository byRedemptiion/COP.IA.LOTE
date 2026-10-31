"""AnalysisService : capture + contexte + question → IA → résultat, entièrement journalisé."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

from alicia.core.actions.controller import ActionReply
from alicia.core.ai.base import (
    AnalysisRequest,
    AnalysisResult,
    DeltaCallback,
    PreparedAudio,
    VisionModel,
)
from alicia.core.ai.image_prep import prepare_image
from alicia.core.ai.prompts import (
    UNDERSTOOD_QUESTION,
    VOICE_QUESTION,
    TranscriptSplitter,
    build_system_prompt,
)
from alicia.core.capture.models import Frame, WindowInfo
from alicia.core.capture.service import CaptureService
from alicia.core.config import Settings
from alicia.core.errors import AliciaError, CaptureError, ProviderError, ProviderErrorKind
from alicia.core.logging_setup import operation
from alicia.core.persona import current as current_persona
from alicia.core.session.context import SessionContext
from alicia.games.profiles import GENERIC, GameProfile, resolve_profile

BRAIN_LABELS = {"rapide": "Cerveau rapide", "reflechi": "Cerveau réfléchi"}

log = logging.getLogger("alicia.analysis")


@dataclass
class AnalysisOutcome:
    operation_id: str
    frame: Frame | None
    result: AnalysisResult | None
    profile: str
    total_ms: int
    transcript: str | None = None  # question orale transcrite
    action: ActionReply | None = None  # demande d'action sur le PC (pas d'appel IA)


class AnalysisService:
    def __init__(
        self,
        settings: Settings,
        capture: CaptureService,
        model: VisionModel,
        session: SessionContext,
        transcriber=None,  # type: ignore[no-untyped-def]  # LocalTranscriber (voix → texte), facultatif
        router=None,  # type: ignore[no-untyped-def]  # texte → ActionReply | None (actions sur le PC)
    ) -> None:
        self.router = router
        self.transcriber = transcriber
        self.game_profile = settings.game_profile  # « auto » ou un profil choisi dans l'interface
        self.vision_mode = settings.capture.mode  # window | cursor | screen (modifiable en direct)
        self.timeline = None  # Timeline (mémoire de partie), branchée par l'interface
        self.settings = settings
        self.capture = capture
        self.model = model
        self.deep_model = None  # cerveau « réfléchi » (optionnel)
        # Dernier jeu vu au premier plan : sert quand tu poses la question depuis le bureau
        # ou depuis COP'IA'LOTE (la fenêtre du jeu n'est alors plus devant).
        self.last_game: tuple[GameProfile, WindowInfo, float] | None = None
        self.session = session

    def analyze(
        self,
        window: WindowInfo | None,
        question: str,
        *,
        frame: Frame | None = None,
        on_frame=None,  # type: ignore[no-untyped-def]  # appelé dès que la capture est prête
        on_delta: DeltaCallback | None = None,
        on_transcript=None,  # type: ignore[no-untyped-def]  # question orale transcrite
        cancel: threading.Event | None = None,
        audio: PreparedAudio | None = None,
        web_search: bool = False,
        spoken: bool = False,
    ) -> AnalysisOutcome:
        with operation() as op_id:
            started = time.perf_counter()
            local_transcript = None
            dictated = False  # question dictée : l'IA dira d'abord ce qu'elle a compris
            if audio is not None and self.transcriber is not None:
                local_transcript = self.transcriber.transcribe(audio)
                if local_transcript:
                    from alicia.core.audio.wake import strip_wake_word

                    heard = local_transcript
                    local_transcript = strip_wake_word(local_transcript)
                    if not local_transcript:
                        raise AliciaError(
                            f"Oui ? Dis ta demande juste après « {current_persona().name} ».",
                            detail=f"seulement le mot de réveil : {heard!r}",
                        )
                if not local_transcript:
                    raise AliciaError(
                        "Je n'ai rien compris : parle un peu plus fort ou plus près du micro, "
                        "puis réessaie.",
                        detail="transcription vide",
                    )
                from alicia.core.ai.prompts import understood_locally

                understood = understood_locally(local_transcript)
                log.info("Entendu : %s", heard)
                log.info("Compris (local) : %s", understood)
                if on_transcript is not None:
                    on_transcript(understood)
                question, audio = understood, None
                dictated = True
            if audio is not None:
                question = VOICE_QUESTION
            else:
                question = question.strip() or "Que vois-tu d'important sur cet écran ?"
                if self.router is not None:
                    reply = self.router(question)
                    if reply is not None:
                        total = int((time.perf_counter() - started) * 1000)
                        log.info("Demande traitée comme action « %s » (sans IA)", reply.intent)
                        return AnalysisOutcome(
                            op_id,
                            None,
                            None,
                            "",
                            total,
                            question if dictated else local_transcript,
                            action=reply,
                        )
            vision = self.vision_mode
            if window is None and frame is None and vision == "window":
                vision = "screen"  # pas de jeu (bureau, réglages…) : l'écran entier
                log.info("Aucune application au premier plan : je regarde l'écran entier")
            mode = (
                f"question orale {audio.duration_s:.1f} s"
                if audio
                else (
                    "question orale transcrite localement"
                    if local_transcript
                    else "question écrite"
                )
            )
            log.info(
                "Analyse demandée (%s%s) — fenêtre « %s »",
                mode,
                ", recherche web autorisée" if web_search else "",
                window.title if window is not None else "—",
            )
            if audio is None:
                log.debug("Question : %s", question)
            if frame is None:
                try:
                    frame = self.capture.capture(window, vision, self.settings.capture.cursor_box)
                except CaptureError as exc:
                    if vision != "window":
                        raise
                    # Fenêtre réduite ou impossible à capturer : l'écran entier à la place.
                    log.warning(
                        "Capture de l'application impossible, écran entier : %s", exc.detail
                    )
                    frame = self.capture.capture(window, "screen", self.settings.capture.cursor_box)
            if on_frame is not None:
                on_frame(frame)
            if cancel is not None and cancel.is_set():
                raise ProviderError(ProviderErrorKind.CANCELLED, "Analyse annulée.")
            self._maybe_save(frame, op_id)

            image = prepare_image(
                frame.image,
                self.settings.capture.max_image_side,
                self.settings.capture.jpeg_quality,
            )
            profile, game_note = self.game_for(frame.window)
            past_images, past_note = self._past_images(question if audio is None else "")
            # Cerveau rapide ou réfléchi : la personnalité (ALICIA / VIIRUS) reste la même.
            model, brain, reason = self.model, "rapide", ""
            if self.deep_model is not None and audio is None:
                from alicia.core.ai.factory import deep_reason

                found = deep_reason(question)
                if found:
                    model, brain, reason = self.deep_model, "reflechi", found
            found_pages: list = []  # type: ignore[type-arg]
            if web_search and model.provider == "ollama" and profile.sources and audio is None:
                # Ollama ne sait pas chercher : on cherche pour lui dans tes sites de référence
                from alicia.core.ai.local_search import search_sources

                found_pages = search_sources(question, profile.sources, profile.name)
            request = AnalysisRequest(
                question=question,
                images=(image, *past_images),
                system_prompt=build_system_prompt(
                    profile.prompt_context(web_search)
                    + game_note
                    + _pages_note(found_pages)
                    + (_guide_rules() if web_search else "")
                    + vision_note(frame)
                    + past_note
                    + ("\n" + UNDERSTOOD_QUESTION if dictated else ""),
                    spoken=spoken,
                    brain=brain,
                ),
                history=self.session.history(),
                max_output_tokens=self.settings.ai.max_output_tokens,
                temperature=self.settings.ai.temperature,
                audio=audio,
                web_search=web_search,
            )
            log.info(
                "Jeu : %s (fenêtre %s, %s)%s",
                profile.name,
                frame.window.exe_name or "?",
                "choisi" if self.game_profile != "auto" else "détecté",
                f" — sources prioritaires : {', '.join(profile.sources)}"
                if web_search and profile.sources
                else "",
            )
            brain_label = BRAIN_LABELS[brain]
            log.info(
                "[%s] [%s] %s/%s%s",
                current_persona().title,
                brain_label,
                model.provider,
                model.model,
                f" — raison du routage : « {reason} »" if reason else "",
            )
            log.info(
                "Appel IA %s/%s — image %dx%d, %d Ko, profil %s, historique %d",
                model.provider,
                model.model,
                image.width,
                image.height,
                len(image.data) // 1024,
                profile.key,
                len(request.history),
            )
            splitter = None
            sink = on_delta
            if audio is not None or dictated:
                splitter = TranscriptSplitter(
                    on_transcript or (lambda _t: None), on_delta or (lambda _t: None)
                )
                sink = splitter.feed
            try:
                result = model.analyze(request, on_delta=sink, cancel=cancel)
            except ProviderError as exc:
                level = logging.INFO if exc.kind is ProviderErrorKind.CANCELLED else logging.ERROR
                log.log(level, "Appel IA échoué [%s] : %s", exc.kind, exc.detail)
                raise
            transcript = None
            if splitter is not None:
                splitter.close()
                transcript = splitter.transcript
                from alicia.core.ai.prompts import split_transcript

                _, result.text = split_transcript(result.text)
                if dictated and transcript:
                    log.info("Compris (IA) : %s", transcript)
                else:
                    log.info("Question orale transcrite : %d caractères", len(transcript or ""))
                log.debug("Transcription : %s", transcript)
                if dictated:
                    question = transcript or question  # sinon la version comprise sur le PC
                else:
                    question = transcript or "(question orale inaudible)"
            from alicia.core.guide import take_markers

            result.text, wants_page, wants_image = take_markers(result.text)
            if wants_page:
                result.extra["open_page"] = "1"
            if wants_image:
                result.extra["show_image"] = "1"
            if request.history and repeats(result.text, request.history):
                # Petit modèle qui recopie sa réponse précédente au lieu de répondre :
                # on relance une fois sans l'historique, en lui interdisant de la répéter.
                log.warning(
                    "[%s] [%s] réponse identique à une précédente (« %s ») : relance sans "
                    "l'historique",
                    current_persona().title,
                    brain_label,
                    result.text[:60],
                )
                from dataclasses import replace

                retry = replace(
                    request,
                    history=(),
                    system_prompt=request.system_prompt + NO_REPEAT.format(previous=result.text),
                )
                try:
                    again = model.analyze(retry, cancel=cancel)
                except ProviderError as exc:
                    log.warning("Relance impossible, réponse gardée : %s", exc.detail)
                else:
                    if splitter is not None:
                        from alicia.core.ai.prompts import split_transcript

                        _, again.text = split_transcript(again.text)
                    if again.text.strip() and not repeats(again.text, request.history):
                        again.first_token_ms = result.first_token_ms
                        result = again
                    else:
                        log.warning("Toujours la même réponse : le modèle est trop petit pour ça")
            if found_pages and not result.sources:
                from alicia.core.ai.base import Source

                result.sources = [Source(p.title, p.url) for p in found_pages]
            self.session.record(question, result.text)
            if result.sources:
                log.info(
                    "Recherche web : %d source(s), requêtes %s",
                    len(result.sources),
                    result.search_queries,
                )
            if "search_disabled" in result.extra:
                log.warning("Réponse produite sans recherche web (refusée par le fournisseur)")
            total = int((time.perf_counter() - started) * 1000)
            result.extra["brain"] = brain_label
            log.info(
                "[%s] [%s] réponse en %d ms (%s/%s)",
                current_persona().title,
                brain_label,
                total,
                result.provider,
                result.model,
            )
            log.info(
                "Réponse IA : %d caractères, 1er mot %s ms, IA %d ms, total %d ms, jetons %s/%s, fin %s",
                len(result.text),
                result.first_token_ms,
                result.latency_ms,
                total,
                result.input_tokens,
                result.output_tokens,
                result.finish_reason,
            )
            log.debug("Réponse : %s", result.text)
            return AnalysisOutcome(
                op_id,
                frame,
                result,
                profile.key,
                total,
                transcript or (question if dictated else local_transcript),
            )

    def note_window(self, window: WindowInfo | None) -> None:
        """Retient le jeu au premier plan (appelé à chaque capture de la vision en direct)."""
        if window is None or not window.handle:
            return
        profile = resolve_profile(window, "auto")
        if profile is not GENERIC or window.fullscreen:
            previous = self.last_game
            self.last_game = (profile, window, time.monotonic())
            if previous is None or previous[1].exe_name != window.exe_name:
                log.info(
                    "Jeu au premier plan : %s (%s)",
                    profile.name if profile is not GENERIC else window.title,
                    window.exe_name or "?",
                )

    def game_for(self, window: WindowInfo | None) -> tuple[GameProfile, str]:
        """Le jeu de la question, et une note pour l'IA quand il n'est pas dans la liste."""
        if self.game_profile != "auto":
            return resolve_profile(window, self.game_profile), ""
        profile = resolve_profile(window, "auto")
        has_app = window is not None and bool(window.handle) and bool(window.exe_name)
        if profile is not GENERIC:
            self.note_window(window)
            return profile, ""
        if has_app and window is not None and window.fullscreen:
            self.note_window(window)
            return profile, _app_note(window)
        recent = self.last_game
        if recent is not None and time.monotonic() - recent[2] < GAME_MEMORY_S:
            last_profile, last_window, seen = recent
            minutes = int((time.monotonic() - seen) // 60)
            log.info(
                "Jeu : %s (dernier jeu vu au premier plan, il y a %d min)",
                last_profile.name if last_profile is not GENERIC else last_window.title,
                minutes,
            )
            note = (
                "\nLe joueur pose sa question hors du jeu (bureau ou fenêtre de COP'IA'LOTE), "
                f"mais il jouait à ce jeu il y a {minutes or 'moins d’une'} minute(s)."
            )
            if last_profile is GENERIC:
                return last_profile, _app_note(last_window) + note
            return last_profile, note
        if has_app and window is not None:
            return profile, _app_note(window)
        return profile, (
            "\nAucun jeu n'est reconnu au premier plan. Si la question parle d'un jeu, déduis "
            "lequel de l'image ou de la question ; si ce n'est pas clair, demande-le."
        )

    def _past_images(self, question: str) -> tuple[tuple, str]:  # type: ignore[type-arg]
        """Question sur le passé (« il y a une heure ») : images de ce moment, si gardées."""
        if self.timeline is None or not question:
            return (), ""
        from datetime import datetime

        from PIL import Image

        from alicia.core.capture.timeline import find_past_moment

        when = find_past_moment(question)
        if when is None:
            return (), ""
        found = self.timeline.near(when, count=3)
        label = when.astimezone().strftime("%H:%M")
        if not found:
            log.info("Mémoire de partie : aucune image vers %s", label)
            return (), (
                f"\n\nLe joueur parle d'un moment passé (vers {label}), mais aucune capture de "
                "ce moment n'est gardée : dis-le simplement."
            )
        images, times = [], []
        for moment, path in found:
            try:
                with Image.open(path) as picture:
                    images.append(
                        prepare_image(
                            picture.convert("RGB"),
                            self.settings.capture.max_image_side,
                            self.settings.capture.jpeg_quality,
                        )
                    )
                times.append(moment.astimezone().strftime("%H:%M:%S"))
            except OSError as exc:
                log.warning("Mémoire de partie : image illisible %s (%r)", path.name, exc)
        if not images:
            return (), ""
        now = datetime.now().astimezone().strftime("%H:%M")
        log.info(
            "Mémoire de partie : %d image(s) vers %s jointes à la question", len(images), label
        )
        return tuple(images), (
            f"\n\nLa 1re image est l'écran actuel ({now}). Les suivantes viennent de la mémoire "
            f"de partie, prises à {', '.join(times)}, parce que le joueur parle de ce moment "
            "passé : appuie-toi sur elles pour répondre."
        )

    def _maybe_save(self, frame: Frame, op_id: str) -> None:
        if not self.settings.capture.save_captures:
            return
        folder = self.settings.captures_dir
        try:
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"{frame.captured_at:%Y%m%d-%H%M%S}-{op_id}-{frame.backend}.png"
            frame.image.save(path)
            log.info("Capture enregistrée : %s", path)
        except OSError as exc:
            log.warning("Capture non enregistrée : %s", exc)


NO_REPEAT = (
    "\nATTENTION : ta réponse précédente était « {previous} ». Ne la répète surtout pas : "
    "réponds à la NOUVELLE question du joueur, avec d'autres mots.\n"
)


def _plain(text: str) -> str:
    import re

    return re.sub(r"[^\w]+", " ", text.casefold()).strip()


def repeats(answer: str, history) -> bool:  # type: ignore[no-untyped-def]
    """La réponse recopie-t-elle une réponse déjà donnée (« Non mais là… » en boucle) ?"""
    import difflib

    new = _plain(answer)
    if len(new) < 8:
        return False
    for turn in history:
        old = _plain(turn.answer)
        if old and (new == old or difflib.SequenceMatcher(None, new, old).ratio() >= 0.95):
            return True
    return False


GAME_MEMORY_S = 30 * 60  # le dernier jeu vu reste « le jeu en cours » pendant 30 min


def _app_note(window: WindowInfo) -> str:
    return (
        f"\nApplication du joueur au premier plan : « {window.title} » ({window.exe_name}). "
        "Ce jeu n'a pas de profil dans COP'IA'LOTE : déduis-le du titre et de l'image, "
        "et dis-le si tu n'es pas sûr."
    )


def _guide_rules() -> str:
    from alicia.core.guide import GUIDE_RULES

    return GUIDE_RULES


def _pages_note(pages: list) -> str:  # type: ignore[type-arg]
    if not pages:
        return ""
    from alicia.core.ai.local_search import pages_context

    return pages_context(pages)


def vision_note(frame: Frame) -> str:
    """Précise à l'IA ce qu'elle regarde (écran entier, zone du curseur)."""
    if frame.mode == "cursor":
        return (
            "\n\nL'image est une zone autour du curseur de la souris du joueur. Le cercle rose "
            "marque le curseur : c'est ce qu'il te montre (objet, sort, bouton, texte) ; "
            "réponds d'abord à propos de cet élément."
        )
    if frame.mode == "screen":
        note = "\n\nL'image montre l'écran entier du joueur, pas seulement le jeu."
        if frame.cursor is not None:
            note += " Le cercle rose marque son curseur de souris."
        return note
    return ""
