from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from app.postgres_maintenance import run_restore_drill


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description="在临时数据库中恢复备份、核验核心表和 Schema 后自动删除。"
    )
    value.add_argument("backup", type=Path)
    value.add_argument(
        "--database-url",
        default=os.getenv("QINGSHU_DATABASE_URL", ""),
        help="同一 PostgreSQL 服务器上的现有数据库 URL；用户需有 CREATEDB 权限。",
    )
    return value


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    if not args.database_url.strip():
        raise SystemExit("QINGSHU_DATABASE_URL or --database-url is required")
    report = run_restore_drill(args.backup, args.database_url.strip())
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
