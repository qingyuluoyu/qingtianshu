from __future__ import annotations

from pathlib import Path
import os
import shutil
import subprocess
import sys

import pytest

from app.config import DEFAULT_DATA_DIR, PROJECT_ROOT, Settings
from app.cli import build_parser


PORTABLE_FILES = (
    ".env.example",
    "staging.env.example",
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
    assert settings.database_url.startswith("postgresql://")
    assert settings.workspace_root.parent == settings.data_dir


def test_default_configuration_uses_writable_user_data_directory(monkeypatch):
    monkeypatch.delenv("QINGSHU_DATA_DIR", raising=False)

    settings = Settings.from_env()

    assert settings.data_dir == DEFAULT_DATA_DIR.resolve()
    assert settings.data_dir == (Path.home() / ".qingshu").resolve()
    assert PROJECT_ROOT not in settings.data_dir.parents


def test_optional_market_snapshot_database_uses_postgres(monkeypatch):
    url = "postgresql://reader@localhost/qingshu_market"
    monkeypatch.setenv("QINGSHU_MARKET_SNAPSHOT_DATABASE_URL", url)

    settings = Settings.from_env()

    assert settings.market_snapshot_database_url == url


def test_optional_market_snapshot_database_rejects_file_url(monkeypatch):
    monkeypatch.setenv(
        "QINGSHU_MARKET_SNAPSHOT_DATABASE_URL",
        "sqlite:////tmp/qingshu-market.sqlite3",
    )

    with pytest.raises(ValueError, match="must use PostgreSQL"):
        Settings.from_env()


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
    assert '"$PYTHON_BIN" -m app' in launcher
    assert '"$BASE_URL/today"' in launcher


def test_cli_contract_supports_port_and_no_browser():
    args = build_parser().parse_args(["--port", "8773", "--no-browser"])
    assert args.host == "127.0.0.1"
    assert args.port == 8773
    assert args.no_browser is True


def test_current_directory_and_explicit_env_files_are_portable(tmp_path: Path):
    cwd_data = tmp_path / "cwd-data"
    explicit_data = tmp_path / "explicit-data"
    (tmp_path / ".env").write_text(f"QINGSHU_DATA_DIR={cwd_data}\n", encoding="utf-8")
    explicit = tmp_path / "portable.env"
    explicit.write_text(f"QINGSHU_DATA_DIR={explicit_data}\n", encoding="utf-8")
    command = [
        sys.executable,
        "-c",
        "from app.config import Settings; print(Settings.from_env().data_dir)",
    ]
    env = os.environ.copy()
    env.pop("QINGSHU_DATA_DIR", None)
    env.pop("QINGSHU_ENV_FILE", None)
    env["PYTHONPATH"] = str(PROJECT_ROOT)

    cwd_result = subprocess.run(
        command,
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert Path(cwd_result.stdout.strip()) == cwd_data.resolve()

    env["QINGSHU_ENV_FILE"] = str(explicit)
    explicit_result = subprocess.run(
        command,
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert Path(explicit_result.stdout.strip()) == explicit_data.resolve()
