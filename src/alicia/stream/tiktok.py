"""Mode Stream sur TikTok : le robot lit le chat d'un live TikTok (et les cadeaux, follows,
partages), comme pour Twitch.

TikTok n'a pas d'API officielle pour les lives : on passe par la bibliothèque TikTokLive
(non officielle, licence AGPL modifiée qui autorise explicitement les « TikTok LIVE Stream
Bots », §18). Aucun compte ni mot de passe : seulement le @pseudo du live, comme un
spectateur. La connexion passe par un service de signature gratuit (Euler Stream).

Comme pour Twitch, les messages sont des DONNÉES écrites par des inconnus : ils ne
déclenchent jamais d'action sur le PC, et le robot n'écrit jamais dans le chat.
"""

from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
from collections.abc import Callable
from dataclasses import replace

from alicia.stream.chat import ChatMessage
from alicia.stream.twitch_events import TwitchEvent

log = logging.getLogger("alicia.stream")


def tiktok_user(text: str) -> str:
    """« @Nova.Jagger », « https://www.tiktok.com/@nova.jagger/live » → « nova.jagger »."""
    text = text.strip().rstrip("/")
    match = re.search(r"tiktok\.com/@([A-Za-z0-9._]{2,24})", text)
    name = match.group(1) if match else text.lstrip("@")
    return name.lower() if re.fullmatch(r"[A-Za-z0-9._]{2,24}", name) else ""


def _who(user: object) -> str:
    """Le pseudo affiché d'un spectateur TikTok (nickname, sinon @identifiant)."""
    for field in ("nickname", "unique_id", "display_id"):
        value = str(getattr(user, field, "") or "").strip()
        if value:
            return value[:40]
    return "quelqu'un"


def gift_event(event: object) -> TwitchEvent | None:
    """Un cadeau TikTok, une seule fois par série (à la fin d'un combo)."""
    if bool(getattr(event, "streaking", False)):
        return None  # combo en cours : on remercie à la fin
    gift = getattr(event, "gift", None)
    name = str(getattr(gift, "name", "") or "cadeau")[:40]
    count = int(getattr(event, "repeat_count", 1) or 1)
    return TwitchEvent("tiktok_gift", _who(getattr(event, "user", None)), max(1, count), name)


class TikTokChat:
    """Lecture d'un live TikTok dans un fil à part (sa propre boucle asyncio) ;
    reconnexion automatique, et nouvel essai régulier tant que le live n'a pas commencé."""

    def __init__(
        self,
        user: str,
        on_message: Callable[[ChatMessage], None],
        on_event: Callable[[TwitchEvent], None] = lambda _e: None,
    ) -> None:
        self.user = tiktok_user(user)
        self.on_message = on_message
        self.on_event = on_event
        self.on_status: Callable[[str], None] = lambda _s: None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._client = None

    def start(self) -> None:
        if not self.user or (self._thread and self._thread.is_alive()):
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="alicia-tiktok", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        loop, client = self._loop, self._client
        if loop is not None and client is not None and loop.is_running():
            try:
                asyncio.run_coroutine_threadsafe(client.disconnect(), loop)
            except RuntimeError:
                pass

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        delay = 5.0
        try:
            while not self._stop.is_set():
                try:
                    loop.run_until_complete(self._session())
                    delay = 5.0
                except Exception as exc:  # noqa: BLE001 - la bibliothèque lève des erreurs variées
                    if self._stop.is_set():
                        break
                    kind = type(exc).__name__
                    if kind == "UserNotFoundError":
                        self.on_status(f"⚠ compte @{self.user} introuvable (vérifie le pseudo)")
                        log.warning("TikTok : compte @%s introuvable", self.user)
                        delay = 300.0
                    elif kind == "UserOfflineError":
                        self.on_status("pas en live pour l'instant (nouvel essai dans 1 min)")
                        log.info(
                            "TikTok : @%s n'est pas en live, nouvel essai dans 60 s", self.user
                        )
                        delay = 60.0
                    else:
                        self.on_status("reconnexion…")
                        log.warning(
                            "TikTok : connexion perdue (%s), nouvel essai dans %.0f s",
                            type(exc).__name__,
                            delay,
                        )
                if self._stop.wait(delay):
                    break
                delay = min(120.0, delay * 2)
        finally:
            self._client = None
            loop.close()

    async def _session(self) -> None:
        from TikTokLive import TikTokLiveClient
        from TikTokLive.events import (
            CommentEvent,
            ConnectEvent,
            DisconnectEvent,
            FollowEvent,
            GiftEvent,
            LiveEndEvent,
            ShareEvent,
        )

        client = TikTokLiveClient(unique_id=f"@{self.user}")
        self._client = client

        async def connected(_event: ConnectEvent) -> None:
            log.info("TikTok : connecté au live de @%s (lecture seule)", self.user)
            self.on_status("connecté")

        async def comment(event: CommentEvent) -> None:
            text = str(getattr(event, "comment", "") or getattr(event, "content", "") or "")
            if text.strip():
                user = getattr(event, "user", None)
                message = ChatMessage(_who(user), text.strip()[:400], time.monotonic())
                self.on_message(replace(message, platform="tiktok"))

        async def gift(event: GiftEvent) -> None:
            found = gift_event(event)
            if found is not None:
                self.on_event(found)

        async def follow(event: FollowEvent) -> None:
            self.on_event(TwitchEvent("follow", _who(getattr(event, "user", None))))

        async def share(event: ShareEvent) -> None:
            self.on_event(TwitchEvent("share", _who(getattr(event, "user", None))))

        async def ended(_event: LiveEndEvent) -> None:
            self.on_status("live terminé")
            log.info("TikTok : le live de @%s est terminé", self.user)

        async def disconnected(_event: DisconnectEvent) -> None:
            if not self._stop.is_set():
                self.on_status("déconnecté")

        client.add_listener(ConnectEvent, connected)
        client.add_listener(CommentEvent, comment)
        client.add_listener(GiftEvent, gift)
        client.add_listener(FollowEvent, follow)
        client.add_listener(ShareEvent, share)
        client.add_listener(LiveEndEvent, ended)
        client.add_listener(DisconnectEvent, disconnected)
        self.on_status("connexion…")
        if self._stop.is_set():
            return
        await client.connect(fetch_live_check=True)
        if not self._stop.is_set():
            raise ConnectionError("live interrompu")
