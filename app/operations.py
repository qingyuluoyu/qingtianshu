from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.config import Settings
from app.db import Database
from app.operational_db import OperationalDatabase
from app.postgres_maintenance import backup_status
from app.utils import utc_now


def build_operations_report(
    database: Database,
    job_store: OperationalDatabase,
    settings: Settings,
    *,
    require_postgres: bool = False,
    minimum_active_workers: int = 1,
    max_queue_lag_seconds: float = 600,
    max_failure_rate_24h: float = 0.2,
    check_backup: bool = True,
    check_data_health: bool = False,
    max_data_health_age_seconds: float = 300,
) -> dict[str, Any]:
    queue = job_store.health(
        worker_stale_seconds=settings.job_worker_stale_seconds
    )
    workers = job_store.list_workers(
        stale_after_seconds=settings.job_worker_stale_seconds
    )
    domain = database.schema_status()
    backups = (
        backup_status(
            settings.backup_dir,
            max_age_seconds=settings.backup_max_age_seconds,
        )
        if check_backup
        else {"status": "skipped", "backend": "postgresql"}
    )
    failures: list[str] = []
    warnings: list[str] = []
    data_health: dict[str, Any] = {
        "status": "skipped",
        "snapshot_status": None,
        "created_at": None,
        "age_seconds": None,
    }
    if domain["schema_version"] < Database.SCHEMA_VERSION:
        failures.append("domain_schema_outdated")
    if queue["schema_version"] < OperationalDatabase.SCHEMA_VERSION:
        failures.append("operational_schema_outdated")
    active_workers = int(queue["workers"]["active"])
    if active_workers < max(0, minimum_active_workers):
        failures.append("active_worker_count_below_minimum")
    queue_metrics = queue["queue"]
    if int(queue_metrics["expired_running"]) > 0:
        failures.append("expired_running_jobs_present")
    if float(queue_metrics["oldest_ready_age_seconds"]) > max(
        0.0, max_queue_lag_seconds
    ):
        failures.append("queue_lag_above_threshold")
    if float(queue_metrics["failure_rate_24h"]) > max(
        0.0, max_failure_rate_24h
    ):
        failures.append("failure_rate_above_threshold")
    elif int(queue_metrics["failed_24h"]) > 0:
        warnings.append("recent_failed_jobs_present")
    if check_backup and backups["status"] != "ok":
        failures.append("postgres_backup_not_healthy")
    if check_data_health:
        snapshot = database.latest_data_health_snapshot()
        if snapshot is None:
            data_health["status"] = "missing"
            failures.append("data_health_snapshot_missing")
        else:
            snapshot_status = str(snapshot.get("status") or "").strip().lower()
            created_at = str(snapshot.get("created_at") or "").strip() or None
            age_seconds: float | None = None
            if created_at is not None:
                try:
                    parsed = datetime.fromisoformat(created_at)
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=UTC)
                    age_seconds = max(
                        0.0,
                        (datetime.now(UTC) - parsed).total_seconds(),
                    )
                except ValueError:
                    pass
            data_health.update(
                {
                    "snapshot_status": snapshot_status or None,
                    "created_at": created_at,
                    "age_seconds": (
                        round(age_seconds, 3) if age_seconds is not None else None
                    ),
                }
            )
            if age_seconds is None:
                data_health["status"] = "invalid"
                failures.append("data_health_snapshot_timestamp_invalid")
            elif age_seconds > max(0.0, max_data_health_age_seconds):
                data_health["status"] = "stale"
                failures.append("data_health_snapshot_stale")
            elif snapshot_status == "degraded":
                data_health["status"] = "degraded"
                failures.append("data_health_degraded")
            elif snapshot_status == "attention":
                data_health["status"] = "attention"
                warnings.append("data_health_attention")
            elif snapshot_status == "healthy":
                data_health["status"] = "ok"
            else:
                data_health["status"] = "invalid"
                failures.append("data_health_status_unknown")
    return {
        "status": "degraded" if failures else "ok",
        "checked_at": utc_now(),
        "failures": failures,
        "warnings": warnings,
        "thresholds": {
            "require_postgres": require_postgres,
            "minimum_active_workers": max(0, minimum_active_workers),
            "max_queue_lag_seconds": max(0.0, max_queue_lag_seconds),
            "max_failure_rate_24h": max(0.0, max_failure_rate_24h),
            "backup_checked": bool(check_backup),
            "data_health_checked": bool(check_data_health),
            "max_data_health_age_seconds": max(
                0.0, max_data_health_age_seconds
            ),
        },
        "storage": {
            "domain_database": {
                **domain,
                "connection_pool": database.pool_status(),
            },
            "operational_database": {
                "backend": queue["backend"],
                "schema_version": queue["schema_version"],
            },
        },
        "queue": queue,
        "workers": workers,
        "backups": backups,
        "data_health": data_health,
    }


__all__ = ["build_operations_report"]
