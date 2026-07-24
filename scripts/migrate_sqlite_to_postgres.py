from __future__ import annotations

import argparse
import os
from pathlib import Path
import sqlite3
from typing import Any

from app.db import Database
from app.operational_db import OperationalDatabase


MIGRATION_TABLES = {
    "domain_schema_migrations",
    "qingshu_schema_migrations",
}


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description="将清数智算 SQLite 主库一次性迁移到 PostgreSQL。"
    )
    value.add_argument("--source", required=True, type=Path, help="SQLite 数据库路径")
    value.add_argument(
        "--database-url",
        default=os.getenv("QINGSHU_DATABASE_URL", ""),
        help="目标 PostgreSQL URL；默认读取 QINGSHU_DATABASE_URL",
    )
    value.add_argument(
        "--workspace-root",
        type=Path,
        default=Path("/tmp/qingshu-migration-workspaces"),
        help="仅用于初始化仓储层，不复制用户工作区文件",
    )
    value.add_argument(
        "--dry-run",
        action="store_true",
        help="只检查源表、目标表和行数，不写入业务数据",
    )
    return value


def _source_tables(connection: sqlite3.Connection) -> list[str]:
    rows = connection.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    ).fetchall()
    return [str(row["name"]) for row in rows]


def _target_columns(connection: Any, table: str) -> list[dict[str, str]]:
    rows = connection.execute(
        """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = %s
        ORDER BY ordinal_position
        """,
        (table,),
    ).fetchall()
    return [
        {"name": str(row["column_name"]), "type": str(row["data_type"])}
        for row in rows
    ]


def _source_columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return [
        str(row["name"])
        for row in connection.execute(f'PRAGMA table_info("{table}")').fetchall()
    ]


def _convert_value(value: Any, data_type: str) -> Any:
    if value is None:
        return None
    if data_type == "boolean":
        return bool(value)
    return value


def migrate(
    source_path: Path,
    database_url: str,
    workspace_root: Path,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    source_path = source_path.expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"SQLite source does not exist: {source_path}")
    if not database_url.startswith(
        ("postgresql://", "postgres://", "postgresql+psycopg://")
    ):
        raise ValueError("Target must be a PostgreSQL database URL")
    psycopg_url = database_url.replace(
        "postgresql+psycopg://", "postgresql://", 1
    )
    if psycopg_url.startswith("postgres://"):
        psycopg_url = "postgresql://" + psycopg_url.removeprefix("postgres://")

    domain = Database(source_path, workspace_root.expanduser().resolve(), database_url)
    operations = OperationalDatabase(database_url)
    try:
        domain.initialize()
        operations.initialize()
    finally:
        domain.close()
        operations.close()

    import psycopg
    from psycopg.rows import dict_row

    uri = f"file:{source_path}?mode=ro"
    report: dict[str, Any] = {
        "source": str(source_path),
        "target_backend": "postgresql",
        "dry_run": dry_run,
        "tables": [],
        "copied_rows": 0,
    }
    with (
        sqlite3.connect(uri, uri=True) as source,
        psycopg.connect(psycopg_url, row_factory=dict_row) as target,
    ):
        source.row_factory = sqlite3.Row
        source_tables = _source_tables(source)
        target_tables = {
            str(row["table_name"])
            for row in target.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = current_schema()
                    AND table_type = 'BASE TABLE'
                """
            ).fetchall()
        }
        missing = [
            table
            for table in source_tables
            if table not in target_tables and table not in MIGRATION_TABLES
        ]
        if missing:
            raise RuntimeError(
                "Target schema is missing source tables: " + ", ".join(missing)
            )

        copy_tables = [
            table
            for table in source_tables
            if table in target_tables and table not in MIGRATION_TABLES
        ]
        for table in copy_tables:
            source_count = int(
                source.execute(f'SELECT COUNT(*) AS count FROM "{table}"').fetchone()[
                    "count"
                ]
            )
            target_count = int(
                target.execute(
                    f'SELECT COUNT(*) AS count FROM "{table}"'
                ).fetchone()["count"]
            )
            if target_count:
                raise RuntimeError(
                    f'Target table "{table}" is not empty ({target_count} rows)'
                )
            report["tables"].append(
                {
                    "table": table,
                    "source_rows": source_count,
                    "target_rows_before": target_count,
                }
            )

        if dry_run:
            target.rollback()
            return report

        try:
            target.execute("SET session_replication_role = replica")
        except Exception as exc:
            raise RuntimeError(
                "Migration role must be allowed to disable FK triggers temporarily"
            ) from exc

        for item in report["tables"]:
            table = item["table"]
            source_columns = set(_source_columns(source, table))
            target_columns = [
                column
                for column in _target_columns(target, table)
                if column["name"] in source_columns
            ]
            if not target_columns:
                continue
            names = [column["name"] for column in target_columns]
            select_sql = ", ".join(f'"{name}"' for name in names)
            value_sql = ", ".join(
                "%s::jsonb" if column["type"] == "jsonb" else "%s"
                for column in target_columns
            )
            insert_sql = (
                f'INSERT INTO "{table}" ({select_sql}) '
                f"VALUES ({value_sql}) ON CONFLICT DO NOTHING"
            )
            cursor = source.execute(f'SELECT {select_sql} FROM "{table}"')
            copied = 0
            while True:
                rows = cursor.fetchmany(500)
                if not rows:
                    break
                values = [
                    tuple(
                        _convert_value(row[column["name"]], column["type"])
                        for column in target_columns
                    )
                    for row in rows
                ]
                with target.cursor() as target_cursor:
                    target_cursor.executemany(insert_sql, values)
                copied += len(values)
            item["copied_rows"] = copied
            report["copied_rows"] += copied

        target.execute("SET session_replication_role = origin")
        for item in report["tables"]:
            table = item["table"]
            target_count = int(
                target.execute(
                    f'SELECT COUNT(*) AS count FROM "{table}"'
                ).fetchone()["count"]
            )
            item["target_rows_after"] = target_count
            if target_count != item["source_rows"]:
                raise RuntimeError(
                    f'Row-count mismatch for "{table}": '
                    f"{item['source_rows']} != {target_count}"
                )
        target.execute("ANALYZE")
    return report


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    report = migrate(
        args.source,
        args.database_url.strip(),
        args.workspace_root,
        dry_run=args.dry_run,
    )
    nonempty = [
        item for item in report["tables"] if int(item["source_rows"]) > 0
    ]
    print(
        "migration_ok",
        f"tables={len(report['tables'])}",
        f"nonempty_tables={len(nonempty)}",
        f"copied_rows={report['copied_rows']}",
        f"dry_run={report['dry_run']}",
    )


if __name__ == "__main__":
    main()
