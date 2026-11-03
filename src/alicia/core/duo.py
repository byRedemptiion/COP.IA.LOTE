"""Duo : deux robots COP'IA'LOTE (ALICIA chez l'un, VIIRUS chez l'autre) qui se parlent.

Les deux PC échangent de courts messages par un relais public gratuit (ntfy.sh), sans
compte ni serveur à installer. Tout est **chiffré et signé avec le code de duo** que vous
êtes seuls à connaître : le relais ne voit que du charabia, et un message qui ne vient pas
de l'autre robot est rejeté.

Screens : une capture d'écran part en pièce jointe du relais, chiffrée et signée elle aussi
(le relais la garde 3 h au plus, illisible) ; l'autre PC la télécharge, vérifie sa signature
et son empreinte, puis l'affiche. Seulement une image JPEG, jamais un fichier à ouvrir.

Sécurité : un message reçu n'est que du texte de conversation. Il ne passe jamais par les
actions du PC (éteindre, lancer une appli…) et l'IA a pour consigne de ne suivre aucune
instruction qu'il contiendrait.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import threading
import time
import unicodedata
from collections.abc import Callable
from pathlib import Path

import httpx

log = logging.getLogger("alicia.duo")

DEFAULT_RELAY = "https://ntfy.sh"
MAX_TEXT = 600
MAX_AGE_S = 180  # message trop vieux (rejoué) : ignoré
MAX_FILE = 8 * 1024 * 1024  # screen chiffré : 8 Mo au plus (le relais en accepte 15)


# --- chiffrement (bibliothèque standard : HMAC-SHA256 en mode compteur + signature) ----------


class DuoKeys:
    def __init__(self, code: str) -> None:
        material = hashlib.pbkdf2_hmac(
            "sha256", code.strip().encode(), b"copialote-duo-v1", 200_000, dklen=96
        )
        self._topic, self._enc, self._mac = material[:32], material[32:64], material[64:]
        self.topic = "copialote-" + hmac.new(self._topic, b"topic", "sha256").hexdigest()[:32]

    def _stream(self, nonce: bytes, size: int) -> bytes:
        out = bytearray()
        counter = 0
        while len(out) < size:
            out += hmac.new(self._enc, nonce + counter.to_bytes(8, "big"), "sha256").digest()
            counter += 1
        return bytes(out[:size])

    def seal(self, data: dict) -> str:  # type: ignore[type-arg]
        plain = json.dumps(data, ensure_ascii=False).encode()
        nonce = os.urandom(16)
        cipher = bytes(a ^ b for a, b in zip(plain, self._stream(nonce, len(plain)), strict=True))
        tag = hmac.new(self._mac, nonce + cipher, "sha256").digest()[:16]
        return base64.urlsafe_b64encode(nonce + cipher + tag).decode()

    def seal_bytes(self, plain: bytes) -> bytes:
        nonce = os.urandom(16)
        stream = self._stream(nonce, len(plain))
        cipher = (int.from_bytes(plain, "big") ^ int.from_bytes(stream, "big")).to_bytes(
            len(plain), "big"
        )
        tag = hmac.new(self._mac, b"file" + nonce + cipher, "sha256").digest()[:16]
        return nonce + cipher + tag

    def open_bytes(self, raw: bytes) -> bytes | None:
        if len(raw) < 33:
            return None
        nonce, cipher, tag = raw[:16], raw[16:-16], raw[-16:]
        expected = hmac.new(self._mac, b"file" + nonce + cipher, "sha256").digest()[:16]
        if not hmac.compare_digest(tag, expected):
            return None
        stream = self._stream(nonce, len(cipher))
        return (int.from_bytes(cipher, "big") ^ int.from_bytes(stream, "big")).to_bytes(
            len(cipher), "big"
        )

    def open(self, payload: str) -> dict | None:  # type: ignore[type-arg]
        try:
            raw = base64.urlsafe_b64decode(payload.strip().encode())
        except (ValueError, TypeError):
            return None
        if len(raw) < 33:
            return None
        nonce, cipher, tag = raw[:16], raw[16:-16], raw[-16:]
        expected = hmac.new(self._mac, nonce + cipher, "sha256").digest()[:16]
        if not hmac.compare_digest(tag, expected):
            return None  # pas signé avec notre code : ignoré
        plain = bytes(a ^ b for a, b in zip(cipher, self._stream(nonce, len(cipher)), strict=True))
        try:
            data = json.loads(plain)
        except ValueError:
            return None
        return data if isinstance(data, dict) else None


def new_code() -> str:
    """Code de duo à partager avec ton pote (une seule fois)."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(4))


def install_id(folder: Path) -> str:
    """Identifiant de ce PC (pour ignorer ses propres messages)."""
    path = folder / "duo_id.txt"
    try:
        value = path.read_text("utf-8").strip()
        if re.fullmatch(r"[0-9a-f]{16}", value):
            return value
    except OSError:
        pass
    value = secrets.token_hex(8)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
    except OSError:
        pass
    return value


# --- liaison ----------------------------------------------------------------------------------


class DuoLink:
    """Écoute le relais en continu (un seul flux HTTP) et envoie des messages chiffrés."""

    def __init__(
        self,
        code: str,
        sender: str,
        name: str,
        on_message: Callable[[dict], None],  # type: ignore[type-arg]
        relay: str = DEFAULT_RELAY,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.keys = DuoKeys(code)
        self.sender = sender
        self.name = name
        self.on_message = on_message
        self.relay = relay.rstrip("/")
        self._transport = transport
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.connected = False
        self._since = str(int(time.time()))

    @property
    def url(self) -> str:
        return f"{self.relay}/{self.keys.topic}"

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._listen, name="alicia-duo", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.connected = False

    limited_until = 0.0  # relais saturé (429) : pas de ping avant cette heure

    def send(self, kind: str, **data: object) -> bool:
        if kind == "ping" and time.time() < self.limited_until:
            return False
        message = {
            "v": 1,
            "kind": kind,
            "sender": self.sender,
            "name": self.name,
            "ts": int(time.time()),
            **data,
        }
        if isinstance(message.get("text"), str):
            message["text"] = str(message["text"])[:MAX_TEXT]
        try:
            with httpx.Client(timeout=10.0, transport=self._transport) as client:
                response = client.post(self.url, content=self.keys.seal(message).encode())
            response.raise_for_status()
        except httpx.HTTPError as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status == 429:
                # Quota du relais atteint : plus de pings pendant 1 h, pour garder la place
                # aux vrais messages (questions, transmissions).
                self.limited_until = time.time() + 3600
                log.warning("Duo : relais saturé (429), pings suspendus 1 h")
            else:
                log.warning("Duo : message non envoyé (%r)", exc)
            return False
        log.info("Duo : message « %s » envoyé", kind)
        return True

    def send_file(self, kind: str, content: bytes, **data: object) -> bool:
        """Un screen (JPEG) en pièce jointe chiffrée, avec un petit message chiffré."""
        if not content or len(content) > MAX_FILE:
            return False
        message = {
            "v": 1,
            "kind": kind,
            "sender": self.sender,
            "name": self.name,
            "ts": int(time.time()),
            "sha": hashlib.sha256(content).hexdigest(),
            "size": len(content),
            **data,
        }
        try:
            with httpx.Client(timeout=60.0, transport=self._transport) as client:
                response = client.put(
                    self.url,
                    content=self.keys.seal_bytes(content),
                    headers={"Filename": "copialote.bin", "Message": self.keys.seal(message)},
                )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("Duo : screen non envoyé (%r)", exc)
            return False
        log.info("Duo : screen envoyé (%d ko)", len(content) // 1024)
        return True

    def fetch_file(self, url: str, sha: str) -> bytes | None:
        """Télécharge la pièce jointe (seulement sur le relais), vérifie signature et empreinte."""
        if not url.startswith(f"{self.relay}/file/"):
            return None
        raw = bytearray()
        try:
            with httpx.Client(timeout=60.0, transport=self._transport) as client:
                with client.stream("GET", url) as response:
                    response.raise_for_status()
                    for chunk in response.iter_bytes():
                        raw += chunk
                        if len(raw) > MAX_FILE + 64:
                            log.warning("Duo : pièce jointe trop grosse, ignorée")
                            return None
        except httpx.HTTPError as exc:
            log.warning("Duo : screen non téléchargé (%r)", exc)
            return None
        content = self.keys.open_bytes(bytes(raw))
        if content is None or hashlib.sha256(content).hexdigest() != sha:
            log.warning("Duo : screen illisible ou modifié, ignoré")
            return None
        return content

    def handle(self, payload: str, attachment: str = "") -> None:
        data = self.keys.open(payload)
        if data is None:
            log.debug("Duo : message illisible ignoré")
            return
        if data.get("sender") == self.sender:
            return  # notre propre message
        if abs(time.time() - float(data.get("ts") or 0)) > MAX_AGE_S:
            return
        data["text"] = str(data.get("text") or "")[:MAX_TEXT]
        data["name"] = re.sub(r"[^\w' -]", "", str(data.get("name") or "l'autre robot"))[:24]
        data.pop("_file_url", None)
        if attachment and data.get("kind") == "screen":
            data["_file_url"] = attachment
        self.on_message(data)

    def _listen(self) -> None:
        delay = 2.0
        timeout = httpx.Timeout(10.0, read=90.0)  # ntfy envoie un « keepalive » toutes les 45 s
        while not self._stop.is_set():
            try:
                with httpx.Client(timeout=timeout, transport=self._transport) as client:
                    with client.stream(
                        "GET", f"{self.url}/json", params={"since": self._since}
                    ) as r:
                        r.raise_for_status()
                        self.connected, delay = True, 2.0
                        for line in r.iter_lines():
                            if self._stop.is_set():
                                return
                            self._line(line)
            except httpx.HTTPError as exc:
                if self._stop.is_set():
                    return
                log.debug("Duo : relais injoignable (%r), nouvel essai dans %.0f s", exc, delay)
            self.connected = False
            self._stop.wait(delay)
            delay = min(30.0, delay * 2)

    def _line(self, line: str) -> None:
        try:
            event = json.loads(line)
        except ValueError:
            return
        if event.get("id"):
            self._since = str(event["id"])
        if event.get("event") == "message" and event.get("message"):
            attachment = event.get("attachment")
            url = str(attachment.get("url") or "") if isinstance(attachment, dict) else ""
            try:
                self.handle(str(event["message"]), url)
            except Exception:  # noqa: BLE001 - un message ne doit jamais couper l'écoute
                log.exception("Duo : message reçu inexploitable")


# --- « Viirus, dis bonjour à Alicia » ----------------------------------------------------------


def _plain(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in text if not unicodedata.combining(c)).replace("’", "'")


def parse_duo_request(text: str, others: list[str]) -> tuple[str, str] | None:
    """Ce que le joueur demande à son robot vis-à-vis de l'autre robot, ou None.

    - ("relay", demande) : porte-parole vers l'autre joueur (« demande à Alicia ce qu'elle
      fait », « dis bonjour à Alicia », « réponds-lui que j'arrive ») ;
    - ("chat", sujet) : les deux robots discutent entre eux (« discute avec Alicia de WoW »)."""
    plain = _plain(text)
    names = [re.escape(_plain(n)) for n in others if n] + [r"l'autre robot", r"ton pote"]
    who = "(?:" + "|".join(names) + ")"
    # « envoie un screen à Alicia », « envoie-lui mon écran » (pas « montre-moi l'écran »)
    if (
        re.search(r"\b(?:screen|screenshot|capture d'ecran|capture|ecran)s?\b", plain)
        and re.search(
            r"\b(?:envoie|envoies|envoyer|montre|montrer|partage|partager|balance)", plain
        )
        and re.search(r"[- ](?:lui|leur)\b|\b" + who + r"\b", plain)
    ):
        return "screen", ""
    chat = re.search(
        r"\b(?:discute|discutez|papote|parle|bavarde|debattez|debats)\b\s+(?:un peu\s+)?avec\s+"
        + who
        + r"\b(?P<after>.*)$",
        plain,
    )
    if chat:
        return "chat", re.sub(r"\s+", " ", chat.group("after")).strip(" ,.!?")
    if re.search(r"\b(?:reponds|repond|dis|demande)[- ]?(?:lui|leur)\b", plain):
        return "relay", text.strip()
    relay = re.search(
        r"\b(?:dis|dites|dire|demande|demander|raconte|raconter|reponds|repondre|explique|"
        r"expliquer|previens|prevenir|transmets|transmet|transmettre|transmettez|salue|saluer|"
        r"souhaite|souhaiter|envoie|envoyer|passe|passer|fais passer|faire passer)\b"
        r".{0,80}?\b(?:a|au|aupres de)?\s*" + who + r"\b",
        plain,
    )
    if relay:
        return "relay", text.strip()
    return None
