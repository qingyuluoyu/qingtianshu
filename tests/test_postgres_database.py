from __future__ import annotations

from pathlib import Path
import os
import sqlite3
from urllib.parse import quote
from uuid import uuid4

import pytest

from app.db import Database
from scripts.live_smoke import isolated_postgres_schema
from scripts.migrate_sqlite_to_postgres import (
    _rewrite_workspace_path,
    migrate,
    parser as migration_parser,
)


def test_live_smoke_schema_is_postgresql_and_always_removed():
    import psycopg

    base_url = os.environ["QINGSHU_DATABASE_URL"]
    with isolated_postgres_schema(base_url) as isolated_url:
        assert isolated_url.startswith("postgresql://")
        with psycopg.connect(isolated_url) as connection:
            schema = str(connection.execute("SELECT current_schema()").fetchone()[0])
        assert schema.startswith("live_smoke_")

    with psycopg.connect(base_url) as connection:
        exists = connection.execute(
            "SELECT 1 FROM pg_namespace WHERE nspname = %s", (schema,)
        ).fetchone()
    assert exists is None


def test_workspace_path_rewrite_is_relative_and_rejects_foreign_paths(
    tmp_path: Path,
):
    source_root = tmp_path / "source-workspaces"
    target_root = tmp_path / "target-workspaces"
    source_path = source_root / "user-1" / "runs" / "run-1"
    assert _rewrite_workspace_path(
        source_path,
        source_root,
        target_root,
    ) == str(target_root / "user-1" / "runs" / "run-1")
    with pytest.raises(RuntimeError, match="outside source root"):
        _rewrite_workspace_path(
            tmp_path / "different-root" / "user-1",
            source_root,
            target_root,
        )


def test_workspace_migration_mode_must_be_unambiguous():
    parsed = migration_parser().parse_args(
        ["--source", "source.db", "--preserve-workspace-paths"]
    )
    assert parsed.preserve_workspace_paths is True
    with pytest.raises(SystemExit):
        migration_parser().parse_args(
            [
                "--source",
                "source.db",
                "--source-workspace-root",
                "source-workspaces",
                "--preserve-workspace-paths",
            ]
        )


def test_postgres_domain_database_core_round_trip(tmp_path: Path):
    url = os.getenv("QINGSHU_TEST_POSTGRES_URL", "").strip()
    if not url:
        pytest.skip("QINGSHU_TEST_POSTGRES_URL is not configured")
    database = Database(
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
            intent="stock_research",
        )
        conversations = database.list_conversations(user["id"])
        assert conversations[0]["message_count"] == 1
        assert conversations[0]["last_message_preview"] == "中兴通讯为什么下跌？"
        assert conversations[0]["last_intent"] == "stock_research"
        assert conversations[0]["research_targets"] == []

        database.add_conversation_message(
            user["id"],
            conversation["id"],
            "assistant",
            "中兴通讯价格与公告证据。",
            intent="stock_research",
            metadata={
                "symbol": "000063.SZ",
                "research_targets": [
                    {"symbol": "000063.SZ", "name": "中兴通讯"}
                ],
            },
        )
        enriched = database.list_conversations(user["id"])[0]
        assert enriched["research_targets"] == [
            {"symbol": "000063.SZ", "name": "中兴通讯"}
        ]

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

        news_symbol = f"PG-{suffix}"
        news_url = f"https://example.invalid/postgres-news-{suffix}"
        database.upsert_news_items(
            [
                {
                    "id": f"postgres-news-{suffix}",
                    "symbol": news_symbol,
                    "category": "news",
                    "title": "PostgreSQL 新闻首次抓取",
                    "summary": None,
                    "source": "Original publisher",
                    "url": news_url,
                    "published_at": "2026-07-25T06:00:00+00:00",
                    "fetched_at": "2026-07-25T06:01:00+00:00",
                }
            ]
        )
        database.upsert_news_items(
            [
                {
                    "id": f"postgres-news-{suffix}",
                    "symbol": news_symbol,
                    "category": "news",
                    "title": "PostgreSQL 新闻重复抓取",
                    "summary": None,
                    "source": "Renamed publisher",
                    "url": news_url,
                    "published_at": "2026-07-25T06:00:00+00:00",
                    "fetched_at": "2026-07-25T06:02:00+00:00",
                }
            ]
        )
        stored_news = [
            item
            for item in database.list_news(news_symbol, limit=100)
            if item["url"] == news_url
        ]
        assert len(stored_news) == 1
        assert stored_news[0]["title"] == "PostgreSQL 新闻重复抓取"
        assert stored_news[0]["source"] == "Renamed publisher"
        assert stored_news[0]["fetched_at"] == "2026-07-25T06:02:00+00:00"

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
    user_id = "migration-user"
    run_id = "migration-run"
    source_user_workspace = tmp_path / "source-workspaces" / user_id
    source_run_workspace = source_user_workspace / "runs" / run_id
    now = "2026-07-24T10:00:00+00:00"
    with sqlite3.connect(source_path) as source:
        source.executescript(
            """
            CREATE TABLE users (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                workspace_path TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            );
            CREATE TABLE watchlist (
                user_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                name TEXT,
                market TEXT,
                thesis TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(user_id, symbol)
            );
            CREATE TABLE runs (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                intent TEXT NOT NULL,
                model_tier TEXT NOT NULL,
                status TEXT NOT NULL,
                input_json TEXT NOT NULL,
                evidence_json TEXT,
                answer TEXT,
                usage_json TEXT,
                error TEXT,
                workspace_path TEXT NOT NULL,
                created_at TEXT NOT NULL,
                finished_at TEXT
            );
            """
        )
        source.execute(
            "INSERT INTO users VALUES (?, ?, ?, ?)",
            (user_id, "migration-user", str(source_user_workspace), now),
        )
        source.execute(
            "INSERT INTO watchlist VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, "NVDA", "英伟达", "美股", "验证迁移", now, now),
        )
        source.execute(
            """
            INSERT INTO runs(
                id, user_id, intent, model_tier, status, input_json,
                workspace_path, created_at
            ) VALUES (?, ?, 'stock_research', 'economy', 'completed', ?, ?, ?)
            """,
            (run_id, user_id, '{"symbol":"NVDA"}', str(source_run_workspace), now),
        )

    try:
        report = migrate(
            source_path,
            schema_url,
            tmp_path / "target-workspaces",
            source_workspace_root=tmp_path / "source-workspaces",
        )
        assert report["copied_rows"] > 0
        assert report["workspace_path_rewrites"] >= 2

        target = Database(
            tmp_path / "target-workspaces",
            schema_url,
        )
        target.initialize()
        try:
            assert target.list_watchlist(user_id)[0]["symbol"] == "NVDA"
            migrated_user = target.get_user(user_id)
            assert migrated_user is not None
            assert Path(migrated_user["workspace_path"]).is_relative_to(
                tmp_path / "target-workspaces"
            )
            migrated_run = target.get_run(run_id, user_id)
            assert Path(migrated_run["workspace_path"]).is_relative_to(
                tmp_path / "target-workspaces"
            )
        finally:
            target.close()
    finally:
        with psycopg.connect(base_url) as connection:
            connection.execute(f'DROP SCHEMA "{schema}" CASCADE')
