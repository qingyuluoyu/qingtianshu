from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest

from app.config import DEFAULT_DATA_DIR, PROJECT_ROOT, Settings


PORTABLE_FILES = (
    ".env.example",
    "README.md",
    "TUSHARE使用说明.md",
    "VERIFICATION.md",
    "Dockerfile",
    "docker-compose.yml",
    "一键启动并演示.command",
    "app/config.py",
)


def test_user_facing_installation_files_do_not_depend_on_developer_paths():
    for relative_path in PORTABLE_FILES:
        content = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
        assert "/Users/chr" not in content, relative_path
        assert "/Users/chr/.hermes" not in content, relative_path


def test_explicit_configuration_uses_portable_data_and_path_resolved_hermes(
    monkeypatch, tmp_path: Path
):
    monkeypatch.delenv("HERMES_BIN", raising=False)
    monkeypatch.setenv("QINGSHU_DATA_DIR", str(tmp_path / "portable-data"))

    settings = Settings.from_env()

    assert settings.hermes_bin == Path("hermes")
    assert settings.data_dir == (tmp_path / "portable-data").resolve()
    assert settings.database_path.parent == settings.data_dir
    assert settings.workspace_root.parent == settings.data_dir


def test_default_configuration_uses_writable_user_data_directory(monkeypatch):
    monkeypatch.delenv("QINGSHU_DATA_DIR", raising=False)

    settings = Settings.from_env()

    assert settings.data_dir == DEFAULT_DATA_DIR.resolve()
    assert settings.data_dir == (Path.home() / ".qingshu").resolve()
    assert PROJECT_ROOT not in settings.data_dir.parents


@pytest.mark.skipif(shutil.which("zsh") is None, reason="macOS launcher uses zsh")
def test_macos_launcher_has_valid_shell_syntax():
    result = subprocess.run(
        ["zsh", "-n", str(PROJECT_ROOT / "一键启动并演示.command")],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    launcher = (PROJECT_ROOT / "一键启动并演示.command").read_text(encoding="utf-8")
    assert 'uv pip install --python "$PYTHON_BIN" -e "$ROOT_DIR"' in launcher
    assert '"$PYTHON_BIN" -m ensurepip --upgrade' in launcher
