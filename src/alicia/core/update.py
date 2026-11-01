"""Mise à jour d'ALICIA depuis GitHub, sans Git ni terminal.

1. `check()` demande à GitHub le dernier commit de la branche suivie.
2. `apply()` télécharge l'archive de ce commit et remplace les fichiers d'ALICIA dans le
   dossier d'installation. Ne sont jamais touchés : `.env` (clés), `.venv` (Python),
   `.git`. Seuls les fichiers modifiés sont réécrits.
3. ALICIA redémarre par Lancer_Alicia.bat, qui met à jour les dépendances si `uv.lock`
   a changé.

Dépôt privé : un jeton GitHub en lecture seule dans `.env` (ALICIA_GITHUB_TOKEN).
"""

from __future__ import annotations

import io
import json
import logging
import tomllib
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import httpx

from alicia.core.config import Secret
from alicia.core.errors import AliciaError

log = logging.getLogger("alicia.update")

API = "https://api.github.com"
VERSION_FILE = ".alicia-version"
PROTECTED = (".env", ".venv/", ".git/", VERSION_FILE)
CRLF_SUFFIXES = (".bat", ".cmd", ".ps1")
PROJECT_NAME = "alicia-copilot"


@dataclass(frozen=True)
class UpdateInfo:
    sha: str
    message: str
    date: str

    @property
    def short(self) -> str:
        return self.sha[:7]

    @property
    def title(self) -> str:
        return self.message.strip().splitlines()[0] if self.message.strip() else self.short


@dataclass(frozen=True)
class ApplyResult:
    changed: tuple[str, ...]
    dependencies_changed: bool


def install_root() -> Path | None:
    """Dossier d'installation (celui de Lancer_Alicia.bat), ou None si ALICIA n'y est
    pas installée depuis ses sources (paquet installé ailleurs : pas de mise à jour)."""
    root = Path(__file__).resolve().parents[3]
    try:
        project = tomllib.loads((root / "pyproject.toml").read_text("utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    if project.get("project", {}).get("name") != PROJECT_NAME:
        return None
    return root


class Updater:
    def __init__(
        self,
        root: Path,
        repo: str,
        branch: str,
        token: Secret | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout_s: float = 30.0,
    ) -> None:
        self.root = root
        self.repo = repo
        self.branch = branch
        self.token = token or Secret(None)
        self._transport = transport
        self.timeout_s = timeout_s

    # --- version installée ----------------------------------------------------------------------

    def installed(self) -> str | None:
        try:
            data = json.loads((self.root / VERSION_FILE).read_text("utf-8"))
            return str(data["sha"])
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def _remember(self, info: UpdateInfo) -> None:
        (self.root / VERSION_FILE).write_text(
            json.dumps({"sha": info.sha, "branch": self.branch, "date": info.date}),
            encoding="utf-8",
        )

    # --- GitHub ---------------------------------------------------------------------------------

    def _client(self) -> httpx.Client:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "ALICIA-copilot-updater",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token.get()}"
        return httpx.Client(
            headers=headers,
            timeout=self.timeout_s,
            follow_redirects=True,
            transport=self._transport,
        )

    def _get(self, client: httpx.Client, path: str) -> httpx.Response:
        try:
            response = client.get(f"{API}/repos/{self.repo}/{path}")
        except httpx.HTTPError as exc:
            raise AliciaError(
                "Impossible de joindre GitHub : vérifie ta connexion Internet.",
                detail=f"{type(exc).__name__}: {exc}",
            ) from exc
        if response.status_code in (401, 403, 404):
            hint = (
                "Le jeton GitHub (ALICIA_GITHUB_TOKEN dans .env) est refusé ou n'a pas accès."
                if self.token
                else "Le dépôt est privé ou introuvable : ajoute ALICIA_GITHUB_TOKEN dans .env "
                "(jeton GitHub en lecture seule, voir le README)."
            )
            if response.status_code == 403 and "rate limit" in response.text.lower():
                hint = "GitHub limite les vérifications : réessaie dans une heure."
            raise AliciaError(hint, detail=f"HTTP {response.status_code} sur {path}")
        if response.status_code >= 400:
            raise AliciaError(
                "GitHub a refusé la demande de mise à jour.",
                detail=f"HTTP {response.status_code} sur {path} : {response.text[:200]}",
            )
        return response

    def check(self) -> UpdateInfo | None:
        """La nouvelle version si elle diffère de celle installée, sinon None."""
        with self._client() as client:
            data = self._get(client, f"commits/{self.branch}").json()
        commit = data.get("commit", {})
        info = UpdateInfo(
            sha=str(data.get("sha", "")),
            message=str(commit.get("message", "")),
            date=str(commit.get("committer", {}).get("date", "")),
        )
        if not info.sha:
            raise AliciaError("Réponse de GitHub inattendue.", detail=str(data)[:200])
        current = self.installed()
        log.info(
            "Mise à jour : installée %s, dernière %s (%s)",
            current[:7] if current else "inconnue",
            info.short,
            self.branch,
        )
        return None if current == info.sha else info

    # --- installation ---------------------------------------------------------------------------

    def apply(self, info: UpdateInfo) -> ApplyResult:
        with self._client() as client:
            archive = self._get(client, f"zipball/{info.sha}").content
        try:
            zipped = zipfile.ZipFile(io.BytesIO(archive))
        except zipfile.BadZipFile as exc:
            raise AliciaError("Archive de mise à jour illisible.", detail=repr(exc)) from exc
        files = self._files(zipped)
        if "pyproject.toml" not in files or "src/alicia/__init__.py" not in files:
            raise AliciaError(
                "L'archive ne ressemble pas à COP'IA'LOTE : mise à jour annulée.",
                detail=f"{len(files)} fichiers, sans pyproject.toml ou src/alicia",
            )
        lock_before = self._read(self.root / "uv.lock")
        changed = []
        root = self.root.resolve()
        for relative, data in files.items():
            target = (root / relative).resolve()
            if root not in target.parents:
                log.warning("Fichier ignoré (hors du dossier) : %s", relative)
                continue
            if self._read(target) == data:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(target.name + ".alicia-tmp")
            temporary.write_bytes(data)
            temporary.replace(target)
            changed.append(relative)
        self._remember(info)
        deps = lock_before != self._read(self.root / "uv.lock")
        log.info(
            "Mise à jour %s installée : %d fichier(s) modifié(s)%s",
            info.short,
            len(changed),
            ", dépendances à mettre à jour" if deps else "",
        )
        return ApplyResult(tuple(changed), deps)

    @staticmethod
    def _read(path: Path) -> bytes | None:
        try:
            return path.read_bytes()
        except OSError:
            return None

    @staticmethod
    def _files(zipped: zipfile.ZipFile) -> dict[str, bytes]:
        """Fichiers de l'archive, sans le dossier racine « owner-repo-sha/ »."""
        files = {}
        for entry in zipped.infolist():
            if entry.is_dir():
                continue
            parts = PurePosixPath(entry.filename).parts
            if len(parts) < 2 or ".." in parts:
                continue
            relative = "/".join(parts[1:])
            if relative == VERSION_FILE or any(
                relative == p or relative.startswith(p) for p in PROTECTED
            ):
                continue
            data = zipped.read(entry)
            if relative.lower().endswith(CRLF_SUFFIXES) and b"\r\n" not in data:
                data = data.replace(b"\n", b"\r\n")  # cmd.exe exige des fins de ligne Windows
            files[relative] = data
        return files
