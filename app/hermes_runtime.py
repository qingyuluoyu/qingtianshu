from __future__ import annotations

import os
from pathlib import Path
import shlex
import shutil


def resolve_hermes_stream_bridge() -> Path:
    """Return the bridge bundled with the installed application package."""

    bridge = Path(__file__).with_name("hermes_stream_bridge.py")
    if bridge.is_file():
        return bridge
    raise FileNotFoundError("Hermes streaming bridge runtime is unavailable")


def resolve_hermes_executable(configured: Path) -> Path:
    """Resolve either an explicit Hermes path or a command available on PATH."""

    candidate = configured.expanduser()
    if candidate.is_file():
        return candidate.resolve()

    resolved = shutil.which(str(candidate))
    if resolved:
        path = Path(resolved).expanduser().resolve()
        if path.is_file() and os.access(path, os.X_OK):
            return path

    raise FileNotFoundError(f"Hermes 可执行文件不存在：{configured}")


def resolve_hermes_python(
    hermes_executable: Path,
    configured: str | None = None,
) -> Path:
    """Locate the Python runtime that owns the installed Hermes package.

    Hermes can be installed as a console script, symlink, or a small shell
    launcher.  The streaming bridge must run inside the same environment so it
    can import Hermes internals.  An explicit HERMES_PYTHON_BIN always wins.
    """

    override = (configured or os.getenv("HERMES_PYTHON_BIN") or "").strip()
    if override:
        return _require_file(Path(override).expanduser(), "Hermes Python")

    launcher = _unwrap_shell_launcher(hermes_executable)
    shebang_python = _python_from_shebang(launcher)
    if shebang_python is not None:
        return shebang_python

    for name in ("python", "python3"):
        sibling = launcher.parent / name
        if sibling.is_file():
            return sibling.absolute()

    raise FileNotFoundError(
        "Hermes streaming bridge runtime is unavailable; "
        "set HERMES_PYTHON_BIN to the Python executable from the Hermes environment"
    )


def _require_file(path: Path, label: str) -> Path:
    if path.is_file():
        return path.absolute()
    raise FileNotFoundError(f"{label} 不存在：{path}")


def _unwrap_shell_launcher(path: Path) -> Path:
    current = path.resolve()
    visited: set[Path] = set()
    for _ in range(4):
        if current in visited:
            break
        visited.add(current)
        try:
            lines = current.read_text(encoding="utf-8").splitlines()[:20]
        except (OSError, UnicodeDecodeError):
            break
        first_line = lines[0].strip() if lines else ""
        if not first_line.startswith("#!") or "sh" not in first_line.lower():
            break
        target: Path | None = None
        for line in lines:
            stripped = line.strip()
            if not stripped.startswith("exec "):
                continue
            try:
                tokens = shlex.split(stripped[5:])
            except ValueError:
                continue
            if tokens and Path(tokens[0]).is_absolute():
                possible = Path(tokens[0]).expanduser()
                if possible.is_file() and os.access(possible, os.X_OK):
                    target = possible.resolve()
                    break
        if target is None:
            break
        current = target
    return current


def _python_from_shebang(path: Path) -> Path | None:
    try:
        first_line = path.open(encoding="utf-8").readline().strip()
    except (OSError, UnicodeDecodeError):
        return None
    if not first_line.startswith("#!"):
        return None
    raw = first_line[2:].strip()
    if not raw or raw.startswith("/usr/bin/env"):
        return None
    python = Path(raw.split()[0]).expanduser()
    if "python" not in python.name.lower():
        return None
    if python.is_file() and os.access(python, os.X_OK):
        # Keep the virtual-environment entry path. Resolving its symlink to the
        # base interpreter loses pyvenv.cfg discovery and Hermes imports fail.
        return python.absolute()
    return None
