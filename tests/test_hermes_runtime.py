from __future__ import annotations

from pathlib import Path

from app.hermes_runtime import (
    resolve_hermes_executable,
    resolve_hermes_python,
    resolve_hermes_stream_bridge,
)


def test_packaged_stream_bridge_is_available():
    bridge = resolve_hermes_stream_bridge()

    assert bridge.name == "hermes_stream_bridge.py"
    assert bridge.parent.name == "app"
    assert bridge.is_file()


def _make_executable(path: Path, content: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def test_resolve_hermes_command_from_path(monkeypatch, tmp_path: Path):
    hermes = tmp_path / "bin" / "hermes"
    _make_executable(hermes, "#!/bin/sh\nexit 0\n")
    monkeypatch.setenv("PATH", str(hermes.parent))

    assert resolve_hermes_executable(Path("hermes")) == hermes.resolve()


def test_resolve_hermes_python_through_shell_wrapper(tmp_path: Path):
    runtime = tmp_path / "hermes-runtime" / "venv" / "bin"
    python = runtime / "python3"
    console_script = runtime / "hermes"
    wrapper = tmp_path / "bin" / "hermes"
    _make_executable(python)
    _make_executable(console_script, f"#!{python}\nprint('hermes')\n")
    _make_executable(
        wrapper,
        f'#!/usr/bin/env bash\nexec "{console_script}" "$@"\n',
    )

    assert resolve_hermes_python(wrapper) == python.resolve()


def test_explicit_hermes_python_override_wins(tmp_path: Path):
    hermes = tmp_path / "bin" / "hermes"
    override = tmp_path / "custom" / "python"
    _make_executable(hermes, "#!/bin/sh\nexit 0\n")
    _make_executable(override)

    assert resolve_hermes_python(hermes, str(override)) == override.resolve()


def test_resolve_hermes_python_preserves_virtualenv_symlink(tmp_path: Path):
    base_python = tmp_path / "runtime" / "python3.11"
    venv_python = tmp_path / "venv" / "bin" / "python3"
    hermes = tmp_path / "venv" / "bin" / "hermes"
    _make_executable(base_python)
    venv_python.parent.mkdir(parents=True, exist_ok=True)
    venv_python.symlink_to(base_python)
    _make_executable(hermes, f"#!{venv_python}\nprint('hermes')\n")

    resolved = resolve_hermes_python(hermes)

    assert resolved == venv_python.absolute()
    assert resolved != base_python.resolve()
