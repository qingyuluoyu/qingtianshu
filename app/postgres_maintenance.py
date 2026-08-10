from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlsplit, urlunsplit
from uuid import uuid4

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class PostgresTarget:
    host: str
    port: int
    user: str
    password: str
    database: str


def parse_postgres_url(database_url: str) -> PostgresTarget:
    normalized = str(database_url or "").strip().replace(
        "postgresql+psycopg://", "postgresql://", 1
    )
    if normalized.startswith("postgres://"):
        normalized = "postgresql://" + normalized.removeprefix("postgres://")
    parsed = urlsplit(normalized)
    if parsed.scheme != "postgresql" or not parsed.hostname:
        raise ValueError("database URL must use postgresql://")
    database = unquote(parsed.path.lstrip("/"))
    if not database:
        raise ValueError("database URL must include a database name")
    return PostgresTarget(
        host=parsed.hostname,
        port=int(parsed.port or 5432),
        user=unquote(parsed.username or ""),
        password=unquote(parsed.password or ""),
        database=database,
    )


def _command_environment(target: PostgresTarget) -> dict[str, str]:
    environment = dict(os.environ)
    if target.password:
        environment["PGPASSWORD"] = target.password
    return environment


def _connection_arguments(
    target: PostgresTarget, *, database: str | None = None
) -> list[str]:
    arguments = [
        "--host",
        target.host,
        "--port",
        str(target.port),
        "--dbname",
        database or target.database,
    ]
    if target.user:
        arguments.extend(["--username", target.user])
    return arguments


def _executable(name: str) -> str:
    resolved = shutil.which(name)
    if not resolved:
        raise RuntimeError(f"{name} is required but was not found on PATH")
    return resolved


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def prune_backups(
    output_dir: Path,
    *,
    retention_days: int,
    minimum_retained: int,
    now: datetime | None = None,
) -> list[str]:
    resolved = output_dir.expanduser().resolve()
    current = now or datetime.now(UTC)
    cutoff = current - timedelta(days=max(1, retention_days))
    backups = sorted(
        resolved.glob("qingshu-*.dump"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    removed: list[str] = []
    for index, backup in enumerate(backups):
        modified = datetime.fromtimestamp(backup.stat().st_mtime, UTC)
        if index < max(1, minimum_retained) or modified >= cutoff:
            continue
        backup.unlink(missing_ok=True)
        backup.with_suffix(".json").unlink(missing_ok=True)
        removed.append(backup.name)
    return removed


def create_backup(
    database_url: str,
    output_dir: Path,
    *,
    retention_days: int = 14,
    minimum_retained: int = 7,
    now: datetime | None = None,
    runner: CommandRunner = subprocess.run,
) -> dict[str, Any]:
    target = parse_postgres_url(database_url)
    current = now or datetime.now(UTC)
    resolved = output_dir.expanduser().resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    stamp = current.strftime("%Y%m%dT%H%M%SZ")
    backup = resolved / f"qingshu-{stamp}-{uuid4().hex[:8]}.dump"
    temporary = backup.with_suffix(".dump.partial")
    command = [
        _executable("pg_dump"),
        "--format=custom",
        "--compress=6",
        "--no-owner",
        "--no-privileges",
        "--file",
        str(temporary),
        *_connection_arguments(target),
    ]
    try:
        runner(
            command,
            check=True,
            text=True,
            capture_output=True,
            env=_command_environment(target),
        )
        if not temporary.is_file() or temporary.stat().st_size == 0:
            raise RuntimeError("pg_dump completed without producing a backup")
        # Windows requires a writable descriptor for fsync/_commit even when
        # pg_dump has already closed the archive. No bytes are modified here.
        with temporary.open("rb+") as created:
            os.fsync(created.fileno())
        os.replace(temporary, backup)
        runner(
            [_executable("pg_restore"), "--list", str(backup)],
            check=True,
            text=True,
            capture_output=True,
        )
    except Exception:
        temporary.unlink(missing_ok=True)
        backup.unlink(missing_ok=True)
        raise
    manifest = {
        "status": "complete",
        "created_at": current.isoformat(),
        "database": target.database,
        "server": f"{target.host}:{target.port}",
        "backup_file": backup.name,
        "format": "postgresql_custom",
        "archive_verified": True,
        "size_bytes": backup.stat().st_size,
        "sha256": _sha256(backup),
    }
    _write_json_atomic(backup.with_suffix(".json"), manifest)
    removed = prune_backups(
        resolved,
        retention_days=retention_days,
        minimum_retained=minimum_retained,
        now=current,
    )
    manifest["retention"] = {
        "days": max(1, retention_days),
        "minimum_retained": max(1, minimum_retained),
        "removed": removed,
    }
    _write_json_atomic(resolved / "latest.json", manifest)
    return {**manifest, "backup_path": str(backup)}


def backup_status(
    output_dir: Path, *, max_age_seconds: int | None = None
) -> dict[str, Any]:
    resolved = output_dir.expanduser().resolve()
    latest = resolved / "latest.json"
    if not latest.is_file():
        return {"status": "missing", "backup_dir": str(resolved)}
    try:
        manifest = json.loads(latest.read_text(encoding="utf-8"))
        created_at = datetime.fromisoformat(str(manifest["created_at"]))
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        backup = resolved / str(manifest["backup_file"])
        age = max(0.0, (datetime.now(UTC) - created_at).total_seconds())
        status = "ok" if backup.is_file() and backup.stat().st_size > 0 else "missing"
        if max_age_seconds is not None and age > max(1, max_age_seconds):
            status = "stale"
        return {
            **manifest,
            "status": status,
            "backup_dir": str(resolved),
            "age_seconds": round(age, 3),
            "file_exists": backup.is_file(),
        }
    except (KeyError, ValueError, json.JSONDecodeError, OSError) as exc:
        return {
            "status": "invalid",
            "backup_dir": str(resolved),
            "error": f"{type(exc).__name__}: {exc}",
        }


def restore_backup(
    backup_path: Path,
    database_url: str,
    *,
    confirmed_database: str,
    clean: bool = False,
    runner: CommandRunner = subprocess.run,
) -> dict[str, Any]:
    target = parse_postgres_url(database_url)
    if confirmed_database != target.database:
        raise ValueError(
            "confirmed database name does not match restore target; restore aborted"
        )
    backup = backup_path.expanduser().resolve()
    if not backup.is_file():
        raise FileNotFoundError(backup)
    command = [
        _executable("pg_restore"),
        "--exit-on-error",
        "--no-owner",
        "--no-privileges",
    ]
    if clean:
        command.extend(["--clean", "--if-exists"])
    command.extend([*_connection_arguments(target), str(backup)])
    runner(
        command,
        check=True,
        text=True,
        capture_output=True,
        env=_command_environment(target),
    )
    return {
        "status": "restored",
        "backup_path": str(backup),
        "database": target.database,
        "server": f"{target.host}:{target.port}",
        "clean": clean,
    }


def run_restore_drill(
    backup_path: Path,
    database_url: str,
    *,
    runner: CommandRunner = subprocess.run,
) -> dict[str, Any]:
    import psycopg
    from psycopg import sql
    from psycopg.rows import dict_row

    backup = backup_path.expanduser().resolve()
    target = parse_postgres_url(database_url)
    parsed = urlsplit(
        str(database_url)
        .strip()
        .replace("postgresql+psycopg://", "postgresql://", 1)
        .replace("postgres://", "postgresql://", 1)
    )

    def database_url_for(name: str) -> str:
        return urlunsplit(
            (parsed.scheme, parsed.netloc, f"/{quote(name)}", parsed.query, "")
        )

    manifest_path = backup.with_suffix(".json")
    checksum_verified = False
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected = str(manifest.get("sha256") or "")
        if expected and expected != _sha256(backup):
            raise RuntimeError("backup checksum does not match its manifest")
        checksum_verified = bool(expected)

    drill_database = f"qingshu_restore_{uuid4().hex[:12]}"
    maintenance_url = database_url_for("postgres")
    drill_url = database_url_for(drill_database)
    created = False
    report: dict[str, Any] = {
        "status": "failed",
        "backup_path": str(backup),
        "source_database": target.database,
        "drill_database": drill_database,
        "checksum_verified": checksum_verified,
    }
    try:
        with psycopg.connect(maintenance_url, autocommit=True) as maintenance:
            maintenance.execute(
                sql.SQL("CREATE DATABASE {}").format(sql.Identifier(drill_database))
            )
            created = True
        restore_backup(
            backup,
            drill_url,
            confirmed_database=drill_database,
            runner=runner,
        )
        with psycopg.connect(drill_url, row_factory=dict_row) as restored:
            table_rows = restored.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = current_schema()
                    AND table_type = 'BASE TABLE'
                ORDER BY table_name
                """
            ).fetchall()
            tables = {str(row["table_name"]) for row in table_rows}
            required = {
                "domain_schema_migrations",
                "persistent_jobs",
                "persistent_schedules",
                "qingshu_schema_migrations",
                "users",
            }
            missing = sorted(required - tables)
            if missing:
                raise RuntimeError(
                    "restored database is missing required tables: "
                    + ", ".join(missing)
                )
            domain_version = restored.execute(
                "SELECT MAX(version) AS version FROM domain_schema_migrations"
            ).fetchone()
            operations_version = restored.execute(
                "SELECT MAX(version) AS version FROM qingshu_schema_migrations"
            ).fetchone()
            counts: dict[str, int] = {}
            for table in ("users", "persistent_jobs", "persistent_schedules"):
                row = restored.execute(
                    sql.SQL("SELECT COUNT(*) AS count FROM {}").format(
                        sql.Identifier(table)
                    )
                ).fetchone()
                counts[table] = int(row["count"])
        report.update(
            {
                "status": "passed",
                "table_count": len(tables),
                "domain_schema_version": int(domain_version["version"] or 0),
                "operational_schema_version": int(
                    operations_version["version"] or 0
                ),
                "row_counts": counts,
            }
        )
        return report
    finally:
        if created:
            with psycopg.connect(maintenance_url, autocommit=True) as maintenance:
                maintenance.execute(
                    """
                    SELECT pg_terminate_backend(pid)
                    FROM pg_stat_activity
                    WHERE datname = %s AND pid <> pg_backend_pid()
                    """,
                    (drill_database,),
                )
                maintenance.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {}").format(
                        sql.Identifier(drill_database)
                    )
                )


__all__ = [
    "PostgresTarget",
    "backup_status",
    "create_backup",
    "parse_postgres_url",
    "prune_backups",
    "restore_backup",
    "run_restore_drill",
]
