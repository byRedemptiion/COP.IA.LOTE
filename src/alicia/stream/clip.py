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
import re
import unicodedata

from alicia.stream.ws import WebSocket as _WebSocket

log = logging.getLogger("alicia.stream")

PORTS = {"obs": 4455, "streamlabs": 59650}


class ClipError(Exception):
    """Message lisible pour l'interface."""


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
