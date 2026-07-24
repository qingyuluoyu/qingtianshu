from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess

import pytest

from app.postgres_maintenance import (
    backup_status,
    create_backup,
    parse_postgres_url,
    prune_backups,
    restore_backup,
)


def test_parse_postgres_url_decodes_credentials_without_exposing_them():
    target = parse_postgres_url(
        "postgresql+psycopg://user:p%40ss@db.example:5544/qingshu"
    )
    assert target.host == "db.example"
    assert target.port == 5544
    assert target.user == "user"
    assert target.password == "p@ss"
    assert target.database == "qingshu"


def test_create_backup_is_atomic_and_keeps_password_out_of_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        "app.postgres_maintenance.shutil.which", lambda name: f"/usr/bin/{name}"
    )
    captured: dict[str, object] = {}

    def runner(command, **kwargs):
        captured["command"] = command
        captured["env"] = kwargs["env"]
        output = Path(command[command.index("--file") + 1])
        output.write_bytes(b"valid-custom-backup")
        return subprocess.CompletedProcess(command, 0, "", "")

    report = create_backup(
        "postgresql://qingshu:secret-value@db:5432/qingshu",
        tmp_path,
        now=datetime(2026, 7, 24, 10, 0, tzinfo=timezone.utc),
        runner=runner,
    )
    assert report["status"] == "complete"
    assert report["size_bytes"] > 0
    assert Path(report["backup_path"]).is_file()
    assert (tmp_path / "latest.json").is_file()
    assert not list(tmp_path.glob("*.partial"))
    assert "secret-value" not in " ".join(captured["command"])
    assert captured["env"]["PGPASSWORD"] == "secret-value"
    assert backup_status(tmp_path, max_age_seconds=10**9)["status"] == "ok"


def test_backup_status_detects_stale_or_missing_files(tmp_path: Path):
    assert backup_status(tmp_path)["status"] == "missing"
    (tmp_path / "latest.json").write_text(
        json.dumps(
            {
                "created_at": "2020-01-01T00:00:00+00:00",
                "backup_file": "missing.dump",
            }
        ),
        encoding="utf-8",
    )
    assert backup_status(tmp_path, max_age_seconds=60)["status"] == "stale"


def test_retention_keeps_minimum_newest_backups(tmp_path: Path):
    current = datetime.now(timezone.utc)
    for index in range(5):
        backup = tmp_path / f"qingshu-2020010{index}T000000Z-a{index}.dump"
        backup.write_bytes(b"x")
        timestamp = (current - timedelta(days=30 + index)).timestamp()
        backup.touch()
        import os

        os.utime(backup, (timestamp, timestamp))
    removed = prune_backups(
        tmp_path,
        retention_days=14,
        minimum_retained=2,
        now=current,
    )
    assert len(removed) == 3
    assert len(list(tmp_path.glob("*.dump"))) == 2


def test_restore_requires_exact_database_confirmation(tmp_path: Path):
    backup = tmp_path / "backup.dump"
    backup.write_bytes(b"backup")
    with pytest.raises(ValueError, match="does not match"):
        restore_backup(
            backup,
            "postgresql://user:secret@db/qingshu",
            confirmed_database="production",
        )
