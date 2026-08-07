from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _git_value(worktree: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(worktree), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def build_runtime_identity(
    *,
    worktree: Path,
    backend_url: str,
    frontend_url: str,
    database_schema: str,
) -> dict[str, Any]:
    """Return non-secret evidence that identifies one candidate runtime."""
    resolved_worktree = worktree.resolve()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git": {
            "worktree": str(resolved_worktree),
            "commit": _git_value(resolved_worktree, "rev-parse", "HEAD"),
            "branch": _git_value(resolved_worktree, "branch", "--show-current"),
        },
        "runtime": {
            "backend_url": backend_url.rstrip("/"),
            "frontend_url": frontend_url.rstrip("/"),
            "database_schema": database_schema,
        },
    }


def write_runtime_identity(identity: dict[str, Any], target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(identity, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target
