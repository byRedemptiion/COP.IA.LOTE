import io
import json
import zipfile

import httpx
import pytest

from alicia.core.config import Secret
from alicia.core.errors import AliciaError
from alicia.core.update import Updater, install_root

SHA = "a" * 40


def make_zip(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in files.items():
            archive.writestr(f"byRedemptiion-ALICIA_COPILOTE-{SHA[:7]}/{name}", data)
    return buffer.getvalue()


ARCHIVE = make_zip(
    {
        "pyproject.toml": b'[project]\nname = "alicia-copilot"\n',
        "src/alicia/__init__.py": b'__version__ = "0.4.0"\n',
        "uv.lock": b"nouveau lock\n",
        "Lancer_Alicia.bat": b"@echo off\necho ok\n",
        ".env": b"GEMINI_API_KEY=VOLEE\n",
        ".venv/pyvenv.cfg": b"home = ailleurs\n",
        "../../evasion.txt": b"non\n",
        "README.md": b"pareil\n",
    }
)


def transport(seen):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if "/repos/byRedemptiion/COP_IA_LOTE/" not in request.url.path:
            return httpx.Response(404, json={"message": "Not Found"})
        if request.url.path.endswith("/commits/alice-v0.3"):
            return httpx.Response(
                200,
                json={
                    "sha": SHA,
                    "commit": {
                        "message": "Onglet Jeux\n\ndétails",
                        "committer": {"date": "2026-10-29T21:00:00Z"},
                    },
                },
            )
        if request.url.path.endswith(f"/zipball/{SHA}"):
            return httpx.Response(200, content=ARCHIVE)
        return httpx.Response(404, json={"message": "Not Found"})

    return httpx.MockTransport(handler)


@pytest.fixture
def install(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "alicia-copilot"\n', "utf-8")
    (tmp_path / "uv.lock").write_text("ancien lock\n", "utf-8")
    (tmp_path / ".env").write_text("GEMINI_API_KEY=ma-cle\n", "utf-8")
    (tmp_path / "README.md").write_bytes(b"pareil\n")  # octets exacts (Windows : \\r\\n)
    return tmp_path


def test_update_is_found_installed_then_up_to_date(install):
    seen = []
    updater = Updater(install, "byRedemptiion/COP_IA_LOTE", "alice-v0.3", transport=transport(seen))
    info = updater.check()
    assert info is not None and info.short == SHA[:7] and info.title == "Onglet Jeux"

    result = updater.apply(info)
    assert result.dependencies_changed
    assert (install / "src/alicia/__init__.py").read_text("utf-8") == '__version__ = "0.4.0"\n'
    assert (install / ".env").read_text("utf-8") == "GEMINI_API_KEY=ma-cle\n"  # clé intacte
    assert not (install / ".venv").exists()
    assert not (install.parent.parent / "evasion.txt").exists()
    assert (install / "Lancer_Alicia.bat").read_bytes() == b"@echo off\r\necho ok\r\n"
    assert "README.md" not in result.changed  # inchangé : pas réécrit
    assert json.loads((install / ".alicia-version").read_text("utf-8"))["sha"] == SHA
    assert updater.check() is None  # à jour
    assert all("Authorization" not in r.headers for r in seen)  # pas de jeton : rien envoyé


def test_private_repo_without_token_explains_what_to_do(install):
    updater = Updater(install, "quelquun/prive", "alice-v0.3", transport=transport([]))
    with pytest.raises(AliciaError) as info:
        updater.check()
    assert "ALICIA_GITHUB_TOKEN" in info.value.user_message


def test_token_is_sent_but_never_shown(install):
    seen = []
    updater = Updater(
        install,
        "byRedemptiion/COP_IA_LOTE",
        "alice-v0.3",
        token=Secret("jeton-secret"),
        transport=transport(seen),
    )
    updater.check()
    assert seen[0].headers["Authorization"] == "Bearer jeton-secret"
    assert "jeton-secret" not in repr(updater.token)


def test_archive_that_is_not_alicia_is_refused(install):
    bad = make_zip({"autre.txt": b"rien"})

    def handler(request):
        return httpx.Response(200, content=bad)

    updater = Updater(install, "x/y", "b", transport=httpx.MockTransport(handler))
    from alicia.core.update import UpdateInfo

    with pytest.raises(AliciaError):
        updater.apply(UpdateInfo(SHA, "m", ""))
    assert (install / ".env").read_text("utf-8") == "GEMINI_API_KEY=ma-cle\n"


def test_source_checkout_is_updatable():
    root = install_root()
    assert root is not None and (root / "Lancer_Alicia.bat").exists()
