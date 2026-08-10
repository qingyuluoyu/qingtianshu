from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app.cli import build_parser
from app.config import (
    DEFAULT_DATA_DIR,
    PROJECT_ROOT,
    Settings,
    validate_deployment_environment,
)

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


def test_development_configuration_allows_loopback_security_defaults():
    validate_deployment_environment(
        "development",
        database_url="postgresql://qingshu:change-me@127.0.0.1/qingshu",
        session_cookie_secure=False,
        sec_user_agent="QingshuFinancialResearch/0.1 research@example.com",
        admin_api_token="",
    )


@pytest.mark.parametrize(
    ("overrides", "expected_field"),
    [
        (
            {"database_url": "postgresql://qingshu:change-me@postgres/qingshu"},
            "QINGSHU_DATABASE_URL",
        ),
        ({"session_cookie_secure": False}, "SESSION_COOKIE_SECURE"),
        (
            {
                "sec_user_agent": (
                    "QingshuFinancialResearch/0.1 research@example.com"
                )
            },
            "SEC_USER_AGENT",
        ),
        ({"admin_api_token": "replace-with-token"}, "QINGSHU_ADMIN_API_TOKEN"),
    ],
)
def test_staging_and_production_reject_unsafe_configuration(
    overrides, expected_field
):
    values = {
        "database_url": (
            "postgresql://qingshu:correct-horse-battery-staple@postgres/qingshu"
        ),
        "session_cookie_secure": True,
        "sec_user_agent": "QingshuFinancialResearch/1.0 ops@qingshu.example.cn",
        "admin_api_token": "",
    }
    values.update(overrides)

    with pytest.raises(ValueError, match=expected_field) as exc_info:
        validate_deployment_environment("staging", **values)

    assert "correct-horse-battery-staple" not in str(exc_info.value)
    assert "replace-with-token" not in str(exc_info.value)


def test_production_configuration_accepts_rotated_credentials():
    validate_deployment_environment(
        "production",
        database_url=(
            "postgresql://qingshu:correct-horse-battery-staple@postgres/qingshu"
        ),
        session_cookie_secure=True,
        sec_user_agent="QingshuFinancialResearch/1.0 ops@qingshu.example.cn",
        admin_api_token="4f633ee9b3da4a3b9078d4f4cf59d134",
    )


def test_settings_from_env_applies_production_gate(monkeypatch):
    monkeypatch.setenv("QINGSHU_DEPLOYMENT_ENV", "production")
    monkeypatch.setenv(
        "QINGSHU_DATABASE_URL",
        "postgresql://qingshu:change-me@postgres/qingshu",
    )
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "true")
    monkeypatch.setenv(
        "SEC_USER_AGENT",
        "QingshuFinancialResearch/1.0 ops@qingshu.example.cn",
    )
    monkeypatch.delenv("QINGSHU_ADMIN_API_TOKEN", raising=False)

    with pytest.raises(ValueError, match="QINGSHU_DATABASE_URL"):
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
    dependency_paths = [
        value
        for value in sys.path
        if value and Path(value).name.casefold() == "site-packages"
    ]
    env["PYTHONPATH"] = os.pathsep.join(
        dict.fromkeys(
            [str(PROJECT_ROOT), *dependency_paths, env.get("PYTHONPATH", "")]
        )
    ).rstrip(os.pathsep)

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
