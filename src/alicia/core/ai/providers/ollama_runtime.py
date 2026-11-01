"""Démarrer Ollama tout seul quand c'est l'IA choisie, et télécharger son modèle au besoin.

ALICIA ne lance que le programme Ollama officiel déjà installé (jamais une commande libre),
et seulement pour une adresse locale (127.0.0.1 / localhost). Si c'est elle qui l'a
démarré, elle l'arrête en se fermant pour libérer la mémoire de la carte graphique.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

import httpx

from alicia.core.errors import AliciaError

log = logging.getLogger("alicia.ai")

DOWNLOAD_URL = "https://ollama.com/download"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def is_local(base_url: str) -> bool:
    return (urlparse(base_url).hostname or "") in ("127.0.0.1", "localhost", "::1")


def find_ollama() -> Path | None:
    """ollama.exe : dans le PATH, sinon à l'emplacement d'installation par défaut."""
    found = shutil.which("ollama")
    if found:
        return Path(found)
    candidates = []
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA", "")
        candidates += [
            Path(local) / "Programs" / "Ollama" / "ollama.exe",
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Ollama" / "ollama.exe",
        ]
    for path in candidates:
        if path.is_file():
            return path
    return None


class OllamaRuntime:
    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        transport: httpx.BaseTransport | None = None,
        launcher: Callable[[Path], subprocess.Popen] | None = None,
        finder: Callable[[], Path | None] = find_ollama,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._transport = transport
        self._launcher = launcher or self._launch
        self._finder = finder
        self.process: subprocess.Popen | None = None  # seulement si ALICIA l'a démarré

    def _client(self, timeout: float = 3.0) -> httpx.Client:
        return httpx.Client(timeout=timeout, transport=self._transport)

    def running(self) -> bool:
        try:
            with self._client(2.0) as client:
                return client.get(f"{self.base_url}/api/version").status_code == 200
        except httpx.HTTPError:
            return False

    @staticmethod
    def _launch(exe: Path) -> subprocess.Popen:
        return subprocess.Popen(  # programme fixe (ollama.exe), aucune commande libre
            [str(exe), "serve"],
            env=_ollama_env(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_NO_WINDOW,
        )

    def ensure_running(self, wait_s: float = 20.0) -> bool:
        """True si Ollama répond (déjà lancé, ou démarré par ALICIA)."""
        if self.running():
            return False
        if not is_local(self.base_url):
            raise AliciaError(
                f"Ollama ne répond pas à {self.base_url}. Démarre-le sur cette machine.",
                detail="adresse distante : pas de démarrage automatique",
            )
        exe = self._finder()
        if exe is None:
            raise AliciaError(
                f"Ollama n'est pas installé sur ce PC. Télécharge-le sur {DOWNLOAD_URL}, "
                "ou choisis Gemini (bouton IA).",
                detail="ollama.exe introuvable",
            )
        log.info("Démarrage d'Ollama : %s", exe)
        try:
            self.process = self._launcher(exe)
        except OSError as exc:
            raise AliciaError("Impossible de démarrer Ollama.", detail=repr(exc)) from exc
        deadline = time.monotonic() + wait_s
        while time.monotonic() < deadline:
            if self.running():
                log.info("Ollama prêt")
                return True
            time.sleep(0.5)
        raise AliciaError(
            "Ollama a été lancé mais ne répond pas encore. Réessaie dans un instant.",
            detail=f"pas de réponse en {wait_s:.0f} s",
        )

    def gpu_share(self) -> float | None:
        """Part du modèle chargée sur la carte graphique (0 = tout sur le processeur),
        ou None si le modèle n'est pas chargé."""
        try:
            with self._client(3.0) as client:
                models = client.get(f"{self.base_url}/api/ps").json().get("models", [])
        except (httpx.HTTPError, ValueError):
            return None
        wanted = self.model if ":" in self.model else f"{self.model}:latest"
        for entry in models:
            if entry.get("name") in (self.model, wanted) or entry.get("model") in (
                self.model,
                wanted,
            ):
                size = float(entry.get("size") or 0)
                return float(entry.get("size_vram") or 0) / size if size else None
        return None

    def has_model(self) -> bool:
        with self._client(5.0) as client:
            response = client.get(f"{self.base_url}/api/tags")
        names = {m.get("name", "") for m in response.json().get("models", [])}
        wanted = self.model if ":" in self.model else f"{self.model}:latest"
        return wanted in names or self.model in names

    def pull(self, progress: Callable[[int], None] | None = None) -> None:
        """Télécharge le modèle (plusieurs Go) ; progress reçoit un pourcentage."""
        last = -1
        with self._client(None) as client:  # type: ignore[arg-type]
            with client.stream(
                "POST", f"{self.base_url}/api/pull", json={"model": self.model}
            ) as response:
                if response.status_code >= 400:
                    raise AliciaError(
                        f"Ollama refuse de télécharger « {self.model} ».",
                        detail=f"HTTP {response.status_code}",
                    )
                for line in response.iter_lines():
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    if "error" in data:
                        raise AliciaError(
                            f"Téléchargement du modèle « {self.model} » impossible.",
                            detail=str(data["error"]),
                        )
                    total, done = data.get("total"), data.get("completed")
                    if total and done is not None and progress is not None:
                        percent = int(done * 100 / total)
                        if percent != last:
                            last = percent
                            progress(percent)
        log.info("Modèle Ollama « %s » téléchargé", self.model)

    def unload(self, models: list[str]) -> list[str]:
        """Libère tout de suite la VRAM et la RAM de ces modèles (keep_alive = 0).

        Même si Ollama tourne tout seul (lancé avec Windows), nos modèles ne restent pas
        chargés après la fermeture. Renvoie les modèles libérés."""
        freed = []
        try:
            with self._client(3.0) as client:
                loaded = {
                    m.get("name") or m.get("model")
                    for m in client.get(f"{self.base_url}/api/ps").json().get("models", [])
                }
                for name in dict.fromkeys(models):
                    if name and (name in loaded or f"{name}:latest" in loaded):
                        client.post(
                            f"{self.base_url}/api/generate",
                            json={"model": name, "keep_alive": 0},
                        )
                        freed.append(name)
        except (httpx.HTTPError, ValueError, AttributeError):
            return freed
        if freed:
            log.info("Ollama : modèle(s) déchargé(s) de la mémoire : %s", ", ".join(freed))
        return freed

    def stop(self) -> None:
        """Arrête Ollama seulement si c'est ALICIA qui l'a démarré."""
        process, self.process = self.process, None
        if process is not None and process.poll() is None:
            process.terminate()
            log.info("Ollama arrêté (démarré par ALICIA)")


def _ollama_env() -> dict[str, str]:
    """Environnement d'Ollama : reprend OLLAMA_MODELS tout juste réglé dans Windows (dossier
    des modèles sur un autre disque) sans attendre un redémarrage du PC."""
    import os
    import sys

    env = dict(os.environ)
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                value, _kind = winreg.QueryValueEx(key, "OLLAMA_MODELS")
            if value:
                env["OLLAMA_MODELS"] = str(value)
        except OSError:
            pass
    return env
