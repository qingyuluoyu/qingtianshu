from __future__ import annotations

from app.db import Database


def test_initialize_records_idempotent_schema_baseline(tmp_path):
    database = Database(tmp_path / "app.db", tmp_path / "workspaces")

    database.initialize()
    database.initialize()

    with database.connect() as connection:
        rows = connection.execute(
            "SELECT migration_id FROM schema_migrations ORDER BY migration_id"
        ).fetchall()

    assert [row["migration_id"] for row in rows] == [
        "0001_schema_baseline",
        "0002_user_phone_and_payment_orders",
        "0003_ai_research_runs",
        "0004_market_review_snapshots",
        "0005_research_task_reliability",
        "0006_investment_lifecycle",
        "0007_research_task_observability",
        "0008_public_data_refresh_tasks",
        "0009_portfolio_ledger_contract",
        "0010_ai_research_workflows",
    ]


def test_initialize_provisions_phone_and_payment_order_schema(tmp_path):
    database = Database(tmp_path / "app.db", tmp_path / "workspaces")
    database.initialize()

    with database.connect() as connection:
        user_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(users)")
        }
        order_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(payment_orders)")
        }

    assert {"phone_e164", "phone_verification_status"} <= user_columns
    assert {"user_id", "provider", "status", "payment_enabled"} <= order_columns


def test_initialize_provisions_durable_ai_research_schema(tmp_path):
    database = Database(tmp_path / "app.db", tmp_path / "workspaces")
    database.initialize()

    with database.connect() as connection:
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(ai_research_runs)")
        }

    assert {
        "run_id",
        "conversation_id",
        "snapshot_json",
        "dimensions_json",
        "detail_status",
        "detailed_answer",
    } <= columns
    with database.connect() as connection:
        task_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(research_tasks)")
        }
    assert {
        "request_id",
        "trace_id",
        "heartbeat_at",
        "last_error_type",
        "timeout_seconds",
        "budget_limit_usd",
    } <= task_columns


def test_initialize_provisions_market_review_evidence_schema(tmp_path):
    database = Database(tmp_path / "app.db", tmp_path / "workspaces")
    database.initialize()

    with database.connect() as connection:
        snapshot_columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(market_review_snapshots)"
            )
        }
        conclusion_columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(market_review_conclusions)"
            )
        }

    assert {"period_start", "period_end", "status", "source_status_json"} <= snapshot_columns
    assert {"source", "published_at", "url", "affected_sectors_json"} <= conclusion_columns


def test_initialize_provisions_public_data_refresh_schema(tmp_path):
    database = Database(tmp_path / "app.db", tmp_path / "workspaces")
    database.initialize()

    with database.connect() as connection:
        task_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(data_refresh_tasks)")
        }
        outbox_columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(data_refresh_task_outbox)"
            )
        }

    assert {
        "task_kind",
        "idempotency_key",
        "status",
        "payload_json",
        "lease_owner",
        "lease_expires_at",
        "request_id",
        "trace_id",
        "last_error_type",
    } <= task_columns
    assert {"task_id", "stream_name", "published_at"} <= outbox_columns


def test_initialize_provisions_portfolio_ledger_contract(tmp_path):
    database = Database(tmp_path / "app.db", tmp_path / "workspaces")
    database.initialize()

    with database.connect() as connection:
        position_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(positions)")
        }
        trade_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(trades)")
        }
        indexes = {
            row["name"] for row in connection.execute("PRAGMA index_list(trades)")
        }

    assert {"version", "method_version"} <= position_columns
    assert {
        "idempotency_key",
        "request_fingerprint",
        "position_closed",
    } <= trade_columns
    assert "uq_trades_user_idempotency" in indexes
