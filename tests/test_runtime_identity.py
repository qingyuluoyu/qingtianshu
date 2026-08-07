from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


def test_runtime_identity_records_candidate_without_secret_environment(
    monkeypatch, tmp_path: Path
):
    from app.runtime_identity import build_runtime_identity, write_runtime_identity

    monkeypatch.setenv("TUSHARE_TOKEN", "must-not-appear")
    monkeypatch.setenv("STEPFUN_API_KEY", "must-not-appear")
    identity = build_runtime_identity(
        worktree=Path(__file__).parents[1],
        backend_url="http://127.0.0.1:8011",
        frontend_url="http://127.0.0.1:5174",
        database_schema="runtime_test_schema",
    )

    assert identity["git"]["commit"]
    assert identity["git"]["branch"].startswith("codex/")
    assert identity["runtime"] == {
        "backend_url": "http://127.0.0.1:8011",
        "frontend_url": "http://127.0.0.1:5174",
        "database_schema": "runtime_test_schema",
    }
    assert "TUSHARE_TOKEN" not in str(identity)
    assert "STEPFUN_API_KEY" not in str(identity)
    assert "must-not-appear" not in str(identity)

    target = write_runtime_identity(identity, tmp_path / "runtime-identity.json")

    assert target.read_text(encoding="utf-8").startswith("{\n")


def test_runtime_identity_script_writes_non_secret_manifest(tmp_path: Path):
    target = tmp_path / "runtime-identity.json"

    result = subprocess.run(
        [
            sys.executable,
            "scripts/write_runtime_identity.py",
            "--backend-url",
            "http://127.0.0.1:8011",
            "--frontend-url",
            "http://127.0.0.1:5174",
            "--database-schema",
            "runtime_test_schema",
            "--output",
            str(target),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(target.read_text(encoding="utf-8"))["runtime"]["backend_url"] == (
        "http://127.0.0.1:8011"
    )
