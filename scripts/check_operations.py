from __future__ import annotations

import argparse
import json

from app.config import Settings
from app.db import Database
from app.operational_db import OperationalDatabase
from app.operations import build_operations_report


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description="检查清数智算生产数据库、持久化队列、Worker 与备份状态。"
    )
    value.add_argument("--require-postgres", action="store_true")
    value.add_argument("--minimum-active-workers", type=int, default=1)
    value.add_argument("--max-queue-lag-seconds", type=float, default=600)
    value.add_argument("--max-failure-rate-24h", type=float, default=0.2)
    value.add_argument("--skip-backup", action="store_true")
    value.add_argument("--check-data-health", action="store_true")
    value.add_argument("--max-data-health-age-seconds", type=float, default=300)
    return value


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    settings = Settings.from_env()
    database = Database(
        settings.workspace_root,
        settings.database_url,
    )
    job_store = OperationalDatabase(settings.operational_database_url)
    try:
        report = build_operations_report(
            database,
            job_store,
            settings,
            require_postgres=args.require_postgres,
            minimum_active_workers=max(0, args.minimum_active_workers),
            max_queue_lag_seconds=max(0, args.max_queue_lag_seconds),
            max_failure_rate_24h=max(0, args.max_failure_rate_24h),
            check_backup=not args.skip_backup,
            check_data_health=args.check_data_health,
            max_data_health_age_seconds=max(
                0, args.max_data_health_age_seconds
            ),
        )
    finally:
        database.close()
        job_store.close()
    print(json.dumps(report, ensure_ascii=False))
    if report["status"] != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
