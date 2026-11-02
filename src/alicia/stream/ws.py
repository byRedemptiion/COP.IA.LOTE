"""Client WebSocket minimal (bibliothèque standard seulement) : texte, TLS, fragments.

Suffisant pour OBS / Streamlabs (local) et les événements Twitch (EventSub, en TLS).
"""

from __future__ import annotations

import base64
import os
import socket
import ssl
import struct


class WebSocket:
    def __init__(
        self,
        host: str,
        port: int,
        path: str = "/",
        timeout: float = 5.0,
        tls: bool = False,
    ) -> None:
        raw = socket.create_connection((host, port), timeout=timeout)
        self.sock: socket.socket = (
            ssl.create_default_context().wrap_socket(raw, server_hostname=host) if tls else raw
        )
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

    def settimeout(self, seconds: float | None) -> None:
        self.sock.settimeout(seconds)

    def _read(self, n: int) -> bytes:
        while len(self.buffer) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("connexion fermée")
            self.buffer += chunk
        data, self.buffer = self.buffer[:n], self.buffer[n:]
        return data

    def _frame(self, opcode: int, payload: bytes) -> None:
        mask = os.urandom(4)
        size = len(payload)
        if size < 126:
            header = struct.pack("!BB", 0x80 | opcode, 0x80 | size)
        elif size < 65536:
            header = struct.pack("!BBH", 0x80 | opcode, 0x80 | 126, size)
        else:
            header = struct.pack("!BBQ", 0x80 | opcode, 0x80 | 127, size)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(header + mask + masked)

    def send(self, text: str) -> None:
        self._frame(0x1, text.encode())

    def recv(self) -> str:
        """Le prochain message texte (fragments réassemblés ; ping → pong)."""
        parts: list[bytes] = []
        while True:
            first, second = self._read(2)
            fin, opcode, size = first & 0x80, first & 0x0F, second & 0x7F
            if size == 126:
                (size,) = struct.unpack("!H", self._read(2))
            elif size == 127:
                (size,) = struct.unpack("!Q", self._read(8))
            mask = self._read(4) if second & 0x80 else b""
            data = self._read(size)
            if mask:
                data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
            if opcode == 0x8:
                raise ConnectionError("fermé par le serveur")
            if opcode == 0x9:
                self._frame(0xA, data)
                continue
            if opcode == 0xA:
                continue
            parts.append(data)
            if fin:
                return b"".join(parts).decode("utf-8", "replace")

    def close(self) -> None:
        try:
            self._frame(0x8, b"")
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass
