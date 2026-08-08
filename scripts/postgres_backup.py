from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import threading

from app.postgres_maintenance import backup_status, create_backup


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description="创建、轮换并检查清数智算 PostgreSQL 备份。"
    )
    value.add_argument(
        "--database-url",
        default=os.getenv("QINGSHU_DATABASE_URL", ""),
        help="PostgreSQL URL；默认读取 QINGSHU_DATABASE_URL。",
    )
    value.add_argument(
        "--output-dir",
        type=Path,
        default=Path(os.getenv("QINGSHU_BACKUP_DIR", "./backups")),
    )
    value.add_argument(
        "--retention-days",
        type=int,
        default=int(os.getenv("QINGSHU_BACKUP_RETENTION_DAYS", "14")),
    )
    value.add_argument(
        "--minimum-retained",
        type=int,
        default=int(os.getenv("QINGSHU_BACKUP_MINIMUM_RETAINED", "7")),
    )
    value.add_argument(
        "--interval-seconds",
        type=int,
        default=0,
        help="大于 0 时持续运行，并按此间隔自动备份。",
    )
    value.add_argument(
        "--check-max-age-seconds",
        type=int,
        help="只检查最近备份；过旧、缺失或无效时返回非零状态。",
    )
    return value


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    if args.check_max_age_seconds is not None:
        report = backup_status(
            args.output_dir,
            max_age_seconds=args.check_max_age_seconds,
        )
        print(json.dumps(report, ensure_ascii=False))
        if report["status"] != "ok":
            raise SystemExit(1)
        return
    if not args.database_url.strip():
        raise SystemExit("QINGSHU_DATABASE_URL or --database-url is required")
    stop = threading.Event()

    def stop_loop(*_: object) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, stop_loop)
    signal.signal(signal.SIGINT, stop_loop)
    while True:
        report = create_backup(
            args.database_url.strip(),
            args.output_dir,
            retention_days=max(1, args.retention_days),
            minimum_retained=max(1, args.minimum_retained),
        )
        print(json.dumps(report, ensure_ascii=False), flush=True)
        if args.interval_seconds <= 0 or stop.wait(
            timeout=max(60, args.interval_seconds)
        ):
            return


if __name__ == "__main__":
    main()
