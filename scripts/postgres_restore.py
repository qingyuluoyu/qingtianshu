from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from app.postgres_maintenance import restore_backup


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description="将清数智算 PostgreSQL 自定义格式备份恢复到明确确认的目标库。"
    )
    value.add_argument("backup", type=Path)
    value.add_argument(
        "--database-url",
        default=os.getenv("QINGSHU_DATABASE_URL", ""),
        help="恢复目标 PostgreSQL URL。",
    )
    value.add_argument(
        "--confirm-database",
        required=True,
        help="必须逐字填写目标数据库名，避免误恢复。",
    )
    value.add_argument(
        "--clean",
        action="store_true",
        help="恢复前删除备份中已有对象；仅适用于明确的灾备恢复。",
    )
    return value


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    if not args.database_url.strip():
        raise SystemExit("QINGSHU_DATABASE_URL or --database-url is required")
    report = restore_backup(
        args.backup,
        args.database_url.strip(),
        confirmed_database=args.confirm_database,
        clean=args.clean,
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
