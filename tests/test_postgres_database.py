from __future__ import annotations

from pathlib import Path
import os
from urllib.parse import quote
from uuid import uuid4

import pytest

from app.db import Database
from app.operational_db import OperationalDatabase
from scripts.migrate_sqlite_to_postgres import migrate


def test_postgres_domain_database_core_round_trip(tmp_path: Path):
    url = os.getenv("QINGSHU_TEST_POSTGRES_URL", "").strip()
    if not url:
        pytest.skip("QINGSHU_TEST_POSTGRES_URL is not configured")
    database = Database(
        tmp_path / "unused.db",
        tmp_path / "workspaces",
        url,
    )
    database.initialize()
    assert database.pool_status()["pool_max"] == int(
        os.getenv("QINGSHU_DB_POOL_MAX_SIZE", "8")
    )
    suffix = str(uuid4())[:8]
    try:
        user = database.create_user(f"postgres-{suffix}")
        session = database.create_user_session(user["id"])
        assert database.get_user_by_session(session["token"])["id"] == user["id"]

        watchlist = database.upsert_watchlist(
            user["id"],
            "000063.SZ",
            "中兴通讯",
            "A股",
            "验证 PostgreSQL 业务库读写",
        )
        assert watchlist["symbol"] == "000063.SZ"
        assert database.list_watchlist(user["id"])[0]["name"] == "中兴通讯"

        conversation = database.create_conversation(user["id"], "PG 持久化验证")
        database.add_conversation_message(
            user["id"],
            conversation["id"],
            "user",
            "中兴通讯为什么下跌？",
        )
        conversations = database.list_conversations(user["id"])
        assert conversations[0]["message_count"] == 1
        assert conversations[0]["last_message_preview"] == "中兴通讯为什么下跌？"

        run = database.create_run(
            user["id"],
            "stock_research",
            "economy",
            {"symbol": "000063.SZ"},
            Path(user["workspace_path"]) / "runs" / suffix,
        )
        database.finish_run(
            run["id"],
            user["id"],
            "completed",
            {"facts": ["postgres"]},
            "验证完成",
        )
        assert database.get_run(run["id"], user["id"])["status"] == "completed"

        background_id = database.start_background_job("postgres-domain-smoke")
        database.finish_background_job(
            background_id,
            "completed",
            summary={"backend": "postgresql"},
        )
        assert any(
            item["job_name"] == "postgres-domain-smoke"
            for item in database.latest_background_jobs()
        )
    finally:
        database.close()


def test_sqlite_to_postgres_migration_preserves_domain_and_queue_rows(
    tmp_path: Path,
):
    base_url = os.getenv("QINGSHU_TEST_POSTGRES_URL", "").strip()
    if not base_url:
        pytest.skip("QINGSHU_TEST_POSTGRES_URL is not configured")
    import psycopg

    schema = "migration_" + uuid4().hex[:12]
    with psycopg.connect(base_url) as connection:
        connection.execute(f'CREATE SCHEMA "{schema}"')
    separator = "&" if "?" in base_url else "?"
    schema_url = f"{base_url}{separator}options={quote(f'-csearch_path={schema}')}"
    source_path = tmp_path / "source.db"
    source = Database(source_path, tmp_path / "source-workspaces")
    source.initialize()
    source_operations = OperationalDatabase(f"sqlite:///{source_path}")
    source_operations.initialize()
    try:
        user = source.create_user("migration-user")
        source.upsert_watchlist(
            user["id"],
            "NVDA",
            "英伟达",
            "美股",
            "验证迁移",
        )
        queued = source_operations.enqueue(
            "market_intraday_refresh",
            idempotency_key="migration-job-20260724",
        )
    finally:
        source_operations.close()
        source.close()

    try:
        report = migrate(
            source_path,
            schema_url,
            tmp_path / "target-workspaces",
        )
        assert report["copied_rows"] > 0

        target = Database(
            tmp_path / "unused.db",
            tmp_path / "target-workspaces",
            schema_url,
        )
        target.initialize()
        target_operations = OperationalDatabase(schema_url)
        target_operations.initialize()
        try:
            assert target.list_watchlist(user["id"])[0]["symbol"] == "NVDA"
            jobs = target_operations.list_jobs()
            assert [item["id"] for item in jobs] == [queued["id"]]
        finally:
            target_operations.close()
            target.close()
    finally:
        with psycopg.connect(base_url) as connection:
            connection.execute(f'DROP SCHEMA "{schema}" CASCADE')
