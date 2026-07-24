from __future__ import annotations

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
        if database.backend == "postgresql" and check_backup
        else {
            "status": "skipped"
            if database.backend == "postgresql"
            else "not_applicable",
            "backend": database.backend,
        }
    )
    failures: list[str] = []
    warnings: list[str] = []
    if require_postgres and database.backend != "postgresql":
        failures.append("domain_database_not_postgresql")
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
    if (
        database.backend == "postgresql"
        and check_backup
        and backups["status"] != "ok"
    ):
        failures.append("postgres_backup_not_healthy")
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
    }


__all__ = ["build_operations_report"]
