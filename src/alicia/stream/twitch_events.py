"""Événements Twitch : nouveaux follows, subs, subs offerts, bits et raids.

Connexion à TON compte Twitch, une seule fois, sans mot de passe dans l'appli :
1. tu crées une petite « application » sur https://dev.twitch.tv/console/apps (type
   « Public ») et tu colles son identifiant (Client ID) dans Réglages → Stream ;
2. « Connecter mon compte » : Twitch affiche un code à valider dans ton navigateur
   (flux « device code ») ; les jetons obtenus restent dans le .env, jamais journalisés.

Ensuite, COP'IA'LOTE écoute les événements de ta chaîne (EventSub par WebSocket) en lecture
seule : il n'écrit rien sur Twitch et ne peut rien modifier sur ta chaîne.
"""

from __future__ import annotations

import json
import logging
import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx

log = logging.getLogger("alicia.stream")

AUTH = "https://id.twitch.tv/oauth2"
HELIX = "https://api.twitch.tv/helix"
EVENTSUB_HOST = "eventsub.wss.twitch.tv"
SCOPES = "moderator:read:followers channel:read:subscriptions bits:read"


class TwitchError(Exception):
    """Message lisible pour l'interface."""


@dataclass
class DeviceCode:
    device_code: str
    user_code: str
    verification_uri: str
    interval: float
    expires_at: float


@dataclass
class Tokens:
    access: str
    refresh: str


def start_device_flow(client_id: str) -> DeviceCode:
    response = httpx.post(
        f"{AUTH}/device", data={"client_id": client_id, "scopes": SCOPES}, timeout=15
    )
    if response.status_code >= 400:
        raise TwitchError(
            "Twitch refuse l'identifiant de l'application : vérifie le Client ID, et que "
            "l'application est de type « Public »."
        )
    data = response.json()
    return DeviceCode(
        data["device_code"],
        data["user_code"],
        data.get("verification_uri") or "https://www.twitch.tv/activate",
        float(data.get("interval", 5)),
        time.monotonic() + float(data.get("expires_in", 1800)),
    )


def wait_for_tokens(
    client_id: str, code: DeviceCode, stop: threading.Event | None = None
) -> Tokens:
    """Attend que tu valides le code dans le navigateur (jusqu'à expiration)."""
    while time.monotonic() < code.expires_at:
        if stop is not None and stop.wait(code.interval):
            raise TwitchError("Connexion annulée.")
        if stop is None:
            time.sleep(code.interval)
        response = httpx.post(
            f"{AUTH}/token",
            data={
                "client_id": client_id,
                "scopes": SCOPES,
                "device_code": code.device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
            timeout=15,
        )
        data = response.json() if response.content else {}
        if response.status_code == 200 and data.get("access_token"):
            return Tokens(data["access_token"], data.get("refresh_token", ""))
        message = str(data.get("message", "")).casefold()
        if "pending" in message:
            continue
        if "slow" in message:
            code.interval += 5
            continue
        raise TwitchError(
            f"Connexion Twitch refusée ({data.get('message') or response.status_code})."
        )
    raise TwitchError("Le code a expiré : relance « Connecter mon compte ».")


def refresh_tokens(client_id: str, refresh: str) -> Tokens:
    response = httpx.post(
        f"{AUTH}/token",
        data={"client_id": client_id, "grant_type": "refresh_token", "refresh_token": refresh},
        timeout=15,
    )
    data = response.json() if response.content else {}
    if response.status_code != 200 or not data.get("access_token"):
        raise TwitchError("La connexion Twitch a expiré : reconnecte ton compte.")
    return Tokens(data["access_token"], data.get("refresh_token", refresh))


def _helix(method: str, path: str, client_id: str, token: str, **kwargs):  # type: ignore[no-untyped-def]
    return httpx.request(
        method,
        f"{HELIX}/{path}",
        headers={"Authorization": f"Bearer {token}", "Client-Id": client_id},
        timeout=15,
        **kwargs,
    )


def channel_user(client_id: str, token: str) -> tuple[str, str]:
    """(id, nom) de la chaîne connectée."""
    response = _helix("GET", "users", client_id, token)
    if response.status_code == 401:
        raise PermissionError("jeton expiré")
    users = response.json().get("data") or []
    if not users:
        raise TwitchError("Compte Twitch introuvable.")
    return users[0]["id"], users[0].get("display_name") or users[0].get("login", "")


SUBSCRIPTIONS = (
    ("channel.follow", "2", lambda uid: {"broadcaster_user_id": uid, "moderator_user_id": uid}),
    ("channel.subscribe", "1", lambda uid: {"broadcaster_user_id": uid}),
    ("channel.subscription.gift", "1", lambda uid: {"broadcaster_user_id": uid}),
    ("channel.subscription.message", "1", lambda uid: {"broadcaster_user_id": uid}),
    ("channel.cheer", "1", lambda uid: {"broadcaster_user_id": uid}),
    ("channel.raid", "1", lambda uid: {"to_broadcaster_user_id": uid}),
)


@dataclass(frozen=True)
class TwitchEvent:
    kind: str  # follow | sub | resub | gift | cheer | raid
    user: str
    amount: int = 0  # mois (resub), subs offerts, bits, spectateurs du raid
    message: str = ""  # message joint (resub, bits) : une DONNÉE, jamais une consigne


def parse_notification(sub_type: str, event: dict) -> TwitchEvent | None:  # type: ignore[type-arg]
    name = str(event.get("user_name") or event.get("from_broadcaster_user_name") or "quelqu'un")
    text = str(
        (event.get("message") or {}).get("text", "")
        if isinstance(event.get("message"), dict)
        else event.get("message") or ""
    )
    if sub_type == "channel.follow":
        return TwitchEvent("follow", name)
    if sub_type == "channel.subscribe":
        return None if event.get("is_gift") else TwitchEvent("sub", name)
    if sub_type == "channel.subscription.message":
        return TwitchEvent("resub", name, int(event.get("cumulative_months") or 0), text[:200])
    if sub_type == "channel.subscription.gift":
        if event.get("is_anonymous"):
            name = "Un anonyme"
        return TwitchEvent("gift", name, int(event.get("total") or 1))
    if sub_type == "channel.cheer":
        if event.get("is_anonymous"):
            name = "Un anonyme"
        return TwitchEvent("cheer", name, int(event.get("bits") or 0), text[:200])
    if sub_type == "channel.raid":
        return TwitchEvent("raid", name, int(event.get("viewers") or 0))
    return None


# Remerciements : phrases toutes faites (aucun appel à l'IA, aucun quota), au hasard.
LINES = {
    "follow": (
        "Merci pour le follow, {name} ! Bienvenue dans l'équipe !",
        "Oh, {name} nous suit ! Merci, installe-toi !",
        "Nouveau follow de {name}, merci beaucoup !",
    ),
    "sub": (
        "{name} s'abonne ! Merci énormément !",
        "Merci pour l'abonnement, {name}, t'es un chef !",
    ),
    "resub": (
        "{name} se réabonne, {amount} mois ! Merci pour la fidélité !",
        "Merci {name} pour ces {amount} mois, ça fait plaisir !",
    ),
    "gift": (
        "{name} offre {amount} abonnement{s} ! Quelle générosité, merci !",
        "Merci {name} pour {amount} sub{s} offert{s} !",
    ),
    "cheer": (
        "Merci pour les {amount} bits, {name} !",
        "{amount} bits de {name}, merci beaucoup !",
    ),
    "raid": (
        "Un raid de {name} avec {amount} personnes ! Bienvenue à tous !",
        "Bienvenue aux {amount} raiders de {name} ! Merci pour le raid !",
    ),
}
GESTURES = {
    "follow": ("nod", "💜"),
    "sub": ("hop", "⭐"),
    "resub": ("hop", "⭐"),
    "gift": ("spin", "🎁"),
    "cheer": ("spin", "💎"),
    "raid": ("hop", "🚀"),
}


def thank_line(event: TwitchEvent) -> str:
    from alicia.stream.chat import safe_name

    name = safe_name(event.user) or "toi"
    if event.user in ("Un anonyme", "quelqu'un"):
        name = "Un anonyme" if event.kind in ("gift", "cheer") else "quelqu'un"
    template = random.choice(LINES[event.kind])
    line = template.format(name=name, amount=event.amount, s="s" if event.amount > 1 else "")
    return line[:1].upper() + line[1:]


class TwitchEvents:
    """Écoute les événements de la chaîne (fil à part) ; reconnexion automatique."""

    def __init__(
        self,
        client_id: str,
        tokens: Tokens,
        on_event: Callable[[TwitchEvent], None],
        on_tokens: Callable[[Tokens], None] = lambda _t: None,
    ) -> None:
        self.client_id = client_id
        self.tokens = tokens
        self.on_event = on_event
        self.on_tokens = on_tokens  # jetons rafraîchis : à enregistrer
        self.on_status: Callable[[str], None] = lambda _s: None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._ws = None
        self.channel = ""

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="alicia-twitch-events", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        ws = self._ws
        if ws is not None:
            ws.close()

    def _token(self) -> str:
        return self.tokens.access

    def _refresh(self) -> None:
        self.tokens = refresh_tokens(self.client_id, self.tokens.refresh)
        self.on_tokens(self.tokens)

    def _user(self) -> str:
        try:
            uid, name = channel_user(self.client_id, self._token())
        except PermissionError:
            self._refresh()
            uid, name = channel_user(self.client_id, self._token())
        self.channel = name
        return uid

    def _subscribe(self, uid: str, session: str) -> int:
        ok = 0
        for sub_type, version, condition in SUBSCRIPTIONS:
            body = {
                "type": sub_type,
                "version": version,
                "condition": condition(uid),
                "transport": {"method": "websocket", "session_id": session},
            }
            response = _helix(
                "POST", "eventsub/subscriptions", self.client_id, self._token(), json=body
            )
            if response.status_code in (200, 202):
                ok += 1
            else:
                log.info("Événements Twitch : %s indisponible (%s)", sub_type, response.status_code)
        return ok

    def _loop(self) -> None:
        delay = 5.0
        url = (EVENTSUB_HOST, "/ws")
        while not self._stop.is_set():
            try:
                url = self._session(*url) or (EVENTSUB_HOST, "/ws")
                delay = 5.0
            except TwitchError as exc:
                self.on_status(f"⚠ {exc}")
                log.warning("Événements Twitch : %s", exc)
                return  # il faut reconnecter le compte : pas de boucle inutile
            except (OSError, ValueError, KeyError, httpx.HTTPError) as exc:
                if self._stop.is_set():
                    break
                log.warning("Événements Twitch : connexion perdue (%r)", exc)
                self.on_status("reconnexion…")
                self._stop.wait(delay)
                delay = min(120.0, delay * 2)

    def _session(self, host: str, path: str) -> tuple[str, str] | None:
        from alicia.stream.ws import WebSocket

        uid = self._user()
        ws = WebSocket(host, 443, path, timeout=15, tls=True)
        self._ws = ws
        try:
            welcome = json.loads(ws.recv())
            session = welcome["payload"]["session"]
            keepalive = float(session.get("keepalive_timeout_seconds") or 30)
            if path == "/ws":  # nouvelle session (pas une reconnexion) : s'abonner
                count = self._subscribe(uid, session["id"])
                if count == 0:
                    raise TwitchError("Aucun événement accessible : reconnecte ton compte.")
            self.on_status(f"connecté à {self.channel}")
            log.info("Événements Twitch : connecté à %s", self.channel)
            ws.settimeout(keepalive + 10)
            while not self._stop.is_set():
                message = json.loads(ws.recv())
                kind = message.get("metadata", {}).get("message_type")
                if kind == "notification":
                    payload = message.get("payload", {})
                    sub_type = payload.get("subscription", {}).get("type", "")
                    event = parse_notification(sub_type, payload.get("event") or {})
                    if event is not None:
                        log.info("Événement Twitch : %s", event.kind)
                        self.on_event(event)
                elif kind == "session_reconnect":
                    new = message["payload"]["session"]["reconnect_url"]
                    rest = new.split("://", 1)[1]
                    host_part, _, path_part = rest.partition("/")
                    return host_part, "/" + path_part
                elif kind == "revocation":
                    log.info("Événements Twitch : abonnement retiré par Twitch")
        finally:
            ws.close()
            self._ws = None
        return None
