import re
from pathlib import Path

import pytest

from alicia.core.config import Secret, load_settings
from alicia.core.errors import ConfigError


def test_defaults_without_any_file(tmp_path):
    settings = load_settings(cwd=tmp_path, environ={}, user_dir=tmp_path / "none")
    assert settings.ai.provider == "gemini"
    assert settings.ai.gemini.model == "gemini-flash-latest"
    assert not settings.ai.gemini.api_key
    assert settings.capture.backend == "auto"
    assert settings.capture.monitor_fallback is True


def test_env_file_key_and_toml_override(tmp_path):
    (tmp_path / ".env").write_text("GEMINI_API_KEY=abc123\n", encoding="utf-8")
    (tmp_path / "alicia.toml").write_text(
        '[ai.gemini]\nmodel = "gemini-flash-lite-latest"\nthinking_budget = 0\n'
        "[capture]\nmax_image_side = 1024\n",
        encoding="utf-8",
    )
    settings = load_settings(cwd=tmp_path, environ={}, user_dir=tmp_path / "none")
    assert settings.ai.gemini.api_key.get() == "abc123"
    assert settings.ai.gemini.model == "gemini-flash-lite-latest"
    assert settings.ai.gemini.thinking_budget == 0
    assert settings.capture.max_image_side == 1024
    assert settings.capture.jpeg_quality == 88  # le reste garde la valeur par défaut


def test_environment_wins_over_env_file(tmp_path):
    (tmp_path / ".env").write_text("GEMINI_API_KEY=from-file\nALICE_AI_PROVIDER=ollama\n")
    settings = load_settings(
        cwd=tmp_path,
        environ={"GEMINI_API_KEY": "from-env", "ALICE_AI_PROVIDER": "fake"},
        user_dir=tmp_path / "none",
    )
    assert settings.ai.gemini.api_key.get() == "from-env"
    assert settings.ai.provider == "fake"


def test_secret_is_never_printed():
    secret = Secret("super-secret-key")
    assert "super-secret-key" not in repr(secret)
    assert "super-secret-key" not in str(secret)
    assert "super-secret-key" not in f"{secret}"


@pytest.mark.parametrize(
    "content",
    ['[ai]\nprovider = "chatgpt"\n', '[capture]\nbackend = "magic"\n', "[ai\nbroken"],
)
def test_invalid_config_is_reported(tmp_path, content):
    (tmp_path / "alicia.toml").write_text(content)
    with pytest.raises(ConfigError):
        load_settings(cwd=tmp_path, environ={}, user_dir=tmp_path / "none")


def test_no_api_key_committed_in_repository():
    root = Path(__file__).resolve().parents[1]
    tracked = [
        p
        for p in root.rglob("*")
        if p.is_file()
        and ".git" not in p.parts
        and ".venv" not in p.parts
        and p.suffix in {".py", ".toml", ".md", ".example", ".yml", ".ps1", ".bat"}
    ]
    patterns = [re.compile(r"AIza[0-9A-Za-z_\-]{35}"), re.compile(r"sk-[A-Za-z0-9_\-]{30,}")]
    for path in tracked:
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in patterns:
            assert not pattern.search(text), f"clé API possible dans {path}"


def test_legacy_alice_folders_and_toml_are_kept(tmp_path, monkeypatch):
    from alicia.core.config import migrate_legacy_dirs

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "state"))
    old = tmp_path / "state" / "Alice" / "models"
    old.mkdir(parents=True)
    (old / "kokoro.onnx").write_text("x")
    migrate_legacy_dirs()
    assert (tmp_path / "state" / "Alicia" / "models" / "kokoro.onnx").is_file()
    (tmp_path / "alice.toml").write_text("[capture]\nmax_image_side = 1000\n")
    settings = load_settings(cwd=tmp_path, environ={}, user_dir=tmp_path / "none")
    assert settings.capture.max_image_side == 1000
