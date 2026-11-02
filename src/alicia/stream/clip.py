"""« VIIRUS, clip ça ! » : sauvegarde les dernières secondes dans OBS ou Streamlabs.

Rien n'est envoyé au jeu : on demande seulement au logiciel de stream d'enregistrer sa
« relecture instantanée » (replay buffer), qui doit être activée dans le logiciel.

- OBS Studio 28+ : obs-websocket (Outils → Paramètres du serveur WebSocket), port 4455,
  avec le mot de passe affiché dans cette fenêtre.
- Streamlabs Desktop : Paramètres → Contrôle à distance → jeton d'API, port 59650.

Le mot de passe / jeton reste dans le .env (CLIP_TOKEN), jamais dans les journaux.
Petit client WebSocket intégré (bibliothèque standard) : aucune dépendance en plus.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import socket
import struct
import unicodedata

log = logging.getLogger("alicia.stream")

PORTS = {"obs": 4455, "streamlabs": 59650}


class ClipError(Exception):
    """Message lisible pour l'interface."""


class _WebSocket:
    """Client WebSocket minimal (texte seulement), suffisant pour OBS et Streamlabs."""

    def __init__(self, host: str, port: int, path: str = "/", timeout: float = 5.0) -> None:
        self.sock = socket.create_connection((host, port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        request = (
            f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        self.sock.sendall(request.encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(1024)
            if not chunk:
                raise ConnectionError("connexion fermée pendant la poignée de main")
            head += chunk
        header, _, self.buffer = head.partition(b"\r\n\r\n")
        if b" 101 " not in header.split(b"\r\n", 1)[0]:
            raise ConnectionError(header.split(b"\r\n", 1)[0].decode(errors="replace"))

    def _read(self, n: int) -> bytes:
        while len(self.buffer) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("connexion fermée")
            self.buffer += chunk
        data, self.buffer = self.buffer[:n], self.buffer[n:]
        return data

    def send(self, text: str) -> None:
        payload = text.encode()
        mask = os.urandom(4)
        size = len(payload)
        if size < 126:
            header = struct.pack("!BB", 0x81, 0x80 | size)
        elif size < 65536:
            header = struct.pack("!BBH", 0x81, 0x80 | 126, size)
        else:
            header = struct.pack("!BBQ", 0x81, 0x80 | 127, size)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(header + mask + masked)

    def recv(self) -> str:
        while True:
            first, second = self._read(2)
            opcode, size = first & 0x0F, second & 0x7F
            if size == 126:
                (size,) = struct.unpack("!H", self._read(2))
            elif size == 127:
                (size,) = struct.unpack("!Q", self._read(8))
            mask = self._read(4) if second & 0x80 else b""
            data = self._read(size)
            if mask:
                data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
            if opcode == 0x8:
                raise ConnectionError("fermé par le logiciel de stream")
            if opcode == 0x9:  # ping → pong
                self.sock.sendall(struct.pack("!BB", 0x8A, 0x80 | len(data)) + b"\0" * 4 + data)
                continue
            if opcode in (0x1, 0x0):
                return data.decode("utf-8", "replace")

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


def _obs_clip(port: int, password: str) -> None:
    ws = _WebSocket("127.0.0.1", port)
    try:
        hello = json.loads(ws.recv())
        auth = (hello.get("d") or {}).get("authentication")
        identify: dict = {"rpcVersion": 1}  # type: ignore[type-arg]
        if auth:
            if not password:
                raise ClipError("OBS demande un mot de passe : colle-le dans Réglages → Stream.")
            secret = base64.b64encode(
                hashlib.sha256((password + auth["salt"]).encode()).digest()
            ).decode()
            identify["authentication"] = base64.b64encode(
                hashlib.sha256((secret + auth["challenge"]).encode()).digest()
            ).decode()
        ws.send(json.dumps({"op": 1, "d": identify}))
        try:
            identified = json.loads(ws.recv())
        except ConnectionError as exc:
            raise ClipError("OBS refuse le mot de passe (Réglages → Stream).") from exc
        if identified.get("op") != 2:
            raise ClipError("OBS refuse la connexion.")
        ws.send(
            json.dumps({"op": 6, "d": {"requestType": "SaveReplayBuffer", "requestId": "clip"}})
        )
        while True:
            answer = json.loads(ws.recv())
            if answer.get("op") == 7:
                status = (answer.get("d") or {}).get("requestStatus") or {}
                if not status.get("result"):
                    raise ClipError(
                        "OBS n'a pas pu garder le clip : démarre la « relecture instantanée » "
                        "(replay buffer) dans OBS."
                        if status.get("code") in (500, 501, 604)
                        else f"OBS : {status.get('comment') or 'clip refusé'}."
                    )
                return
    finally:
        ws.close()


def _streamlabs_clip(port: int, token: str) -> None:
    if not token:
        raise ClipError(
            "Streamlabs demande un jeton : Paramètres → Contrôle à distance → afficher les "
            "détails, puis colle le jeton dans Réglages → Stream."
        )
    ws = _WebSocket("127.0.0.1", port, "/api/websocket")
    try:

        def call(call_id: int, method: str, resource: str, args: list) -> dict:  # type: ignore[type-arg]
            ws.send(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": call_id,
                        "method": method,
                        "params": {"resource": resource, "args": args},
                    }
                )
            )
            while True:
                message = json.loads(ws.recv())
                if message.get("id") == call_id:
                    return message

        if "error" in call(1, "auth", "TcpServerService", [token]):
            raise ClipError("Streamlabs refuse le jeton (Réglages → Stream).")
        answer = call(2, "saveReplay", "StreamingService", [])
        if "error" in answer:
            raise ClipError(
                "Streamlabs n'a pas pu garder le clip : active la « relecture instantanée » "
                "(replay buffer) dans Streamlabs."
            )
    finally:
        ws.close()


def save_clip(app: str, port: int, token: str) -> None:
    """Demande au logiciel de stream de garder les dernières secondes. Lève ClipError."""
    try:
        if app == "streamlabs":
            _streamlabs_clip(port, token)
        else:
            _obs_clip(port, token)
    except ClipError:
        raise
    except (OSError, ValueError, KeyError) as exc:
        name = "Streamlabs" if app == "streamlabs" else "OBS"
        log.warning("Clip : %s injoignable (%r)", name, exc)
        raise ClipError(
            f"{name} ne répond pas : est-il ouvert, avec le contrôle à distance activé "
            f"(port {port}) ?"
        ) from exc
    log.info("Clip : relecture sauvegardée (%s)", app)


_CLIP = re.compile(
    r"\b(?:clip(?:pe|pes|per)? (?:ca|ce moment)|clippe|clipper|fais (?:un|le|moi un) clip|"
    r"sauvegarde (?:le )?(?:replay|clip)|garde ce moment)\b|^(?:\w+ )?clip$"
)


def parse_clip_command(text: str) -> bool:
    plain = unicodedata.normalize("NFKD", text.casefold())
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    plain = " ".join(re.sub(r"[^\w\s]", " ", plain).split())
    return len(plain.split()) <= 8 and bool(_CLIP.search(plain))
