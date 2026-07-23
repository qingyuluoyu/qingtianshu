from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest

from app.db import Database


PLAN_STATUSES = {
    "draft",
    "checked",
    "saved",
    "partially_executed",
    "executed",
    "cancelled",
    "expired",
}
REVIEW_STATUSES = {
    "waiting_data",
    "ready",
    "draft",
    "confirmed",
    "archived",
    "revised",
}


def _database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "qingshu.db", tmp_path / "workspaces")
    database.initialize()
    return database


def _columns(connection: sqlite3.Connection, table: str) -> dict[str, sqlite3.Row]:
    return {
        str(row["name"]): row
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }


def _seed_scope(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    workspace_id: str,
    symbol: str,
    workspace_path: Path,
) -> None:
    now = "2026-07-23T09:30:00+08:00"
    connection.execute(
        "INSERT INTO users(id, name, workspace_path, created_at) VALUES (?, ?, ?, ?)",
        (user_id, user_id, str(workspace_path), now),
    )
    connection.execute(
        """
        INSERT INTO stock_workspaces(
            id, user_id, symbol, name, market, relation_type, priority,
            tracking_status, workflow_status, attention_tags_json, version,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, 'CN', 'watching', 'normal', 'active', 'idle',
                  '[]', 1, ?, ?)
        """,
        (workspace_id, user_id, symbol, symbol, now, now),
    )


def test_action_plan_and_trade_review_schema_is_idempotent(tmp_path: Path) -> None:
    database = _database(tmp_path)
    database.initialize()

    with database.connect() as connection:
        tables = {
            str(row["name"])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        assert {
            "action_plans",
            "action_plan_history",
            "operation_context_snapshots",
            "trade_reviews",
            "trade_review_versions",
        } <= tables

        action_plan_columns = _columns(connection, "action_plans")
        assert {
            "id",
            "user_id",
            "workspace_id",
            "action_type",
            "trigger_text",
            "target_quantity",
            "target_amount",
            "target_position_percent",
            "thesis_version_id",
            "check_result_json",
            "status",
            "expires_at",
            "version",
            "created_at",
            "updated_at",
        } <= action_plan_columns.keys()
        assert action_plan_columns["check_result_json"]["dflt_value"] == "'{}'"
        assert action_plan_columns["status"]["dflt_value"] == "'draft'"

        history_columns = _columns(connection, "action_plan_history")
        assert {
            "id",
            "plan_id",
            "user_id",
            "workspace_id",
            "version",
            "event_type",
            "from_status",
            "to_status",
            "snapshot_json",
            "created_at",
        } <= history_columns.keys()
        assert history_columns["snapshot_json"]["dflt_value"] == "'{}'"

        context_columns = _columns(connection, "operation_context_snapshots")
        assert {
            "id",
            "user_id",
            "workspace_id",
            "operation_id",
            "plan_id",
            "thesis_version_id",
            "snapshot_json",
            "data_time",
            "snapshot_version",
            "created_at",
        } <= context_columns.keys()
        assert context_columns["snapshot_json"]["dflt_value"] == "'{}'"

        review_columns = _columns(connection, "trade_reviews")
        assert {
            "id",
            "user_id",
            "workspace_id",
            "operation_id",
            "plan_id",
            "status",
            "horizon_sessions",
            "data_status",
            "current_version_id",
            "ready_at",
            "confirmed_at",
            "archived_at",
            "created_at",
            "updated_at",
        } <= review_columns.keys()
        assert review_columns["status"]["dflt_value"] == "'waiting_data'"
        assert review_columns["data_status"]["dflt_value"] == "'missing'"

        review_version_columns = _columns(connection, "trade_review_versions")
        assert review_version_columns["bias_tags_json"]["dflt_value"] == "'[]'"
        assert review_version_columns["status"]["dflt_value"] == "'draft'"

        index_names = {
            str(row["name"])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            ).fetchall()
        }
        assert {
            "idx_action_plans_scope_status",
            "idx_action_plan_history_scope_version",
            "idx_operation_context_scope_time",
            "idx_trade_reviews_scope_status",
            "idx_trade_reviews_operation_horizon",
            "idx_trade_review_versions_scope_version",
        } <= index_names

        plan_sql = str(
            connection.execute(
                "SELECT sql FROM sqlite_master WHERE name = 'action_plans'"
            ).fetchone()["sql"]
        )
        review_sql = str(
            connection.execute(
                "SELECT sql FROM sqlite_master WHERE name = 'trade_reviews'"
            ).fetchone()["sql"]
        )
        assert all(f"'{status}'" in plan_sql for status in PLAN_STATUSES)
        assert all(f"'{status}'" in review_sql for status in REVIEW_STATUSES)


def test_plan_review_defaults_scope_guards_and_existing_data_survive_reinitialize(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    now = "2026-07-23T10:00:00+08:00"

    with database.connect() as connection:
        _seed_scope(
            connection,
            user_id="user-1",
            workspace_id="workspace-1",
            symbol="000063.SZ",
            workspace_path=tmp_path / "workspaces" / "user-1",
        )
        _seed_scope(
            connection,
            user_id="user-2",
            workspace_id="workspace-2",
            symbol="300308.SZ",
            workspace_path=tmp_path / "workspaces" / "user-2",
        )
        connection.execute(
            """
            INSERT INTO thesis_versions(
                id, workspace_id, user_id, symbol, version_no, status,
                reason_text, source, created_at
            ) VALUES ('thesis-1', 'workspace-1', 'user-1', '000063.SZ', 1,
                      'active', '已确认判断', 'user', ?)
            """,
            (now,),
        )
        connection.execute(
            """
            INSERT INTO action_plans(
                id, user_id, workspace_id, action_type, trigger_text,
                target_quantity, target_amount, target_position_percent,
                thesis_version_id, created_at, updated_at
            ) VALUES ('plan-1', 'user-1', 'workspace-1', 'hold',
                      '等待下一份财报并复核现金流', '100', '5000', '10.5',
                      'thesis-1', ?, ?)
            """,
            (now, now),
        )
        connection.execute(
            """
            INSERT INTO action_plan_history(
                id, plan_id, user_id, workspace_id, version, event_type,
                from_status, to_status, created_at
            ) VALUES ('plan-history-1', 'plan-1', 'user-1', 'workspace-1', 1,
                      'created', NULL, 'draft', ?)
            """,
            (now,),
        )
        connection.execute(
            """
            INSERT INTO position_operations(
                id, workspace_id, user_id, symbol, operation_type, operated_at,
                price, quantity, fees, reason_text, plan_id, idempotency_key,
                created_at
            ) VALUES ('operation-1', 'workspace-1', 'user-1', '000063.SZ',
                      'buy', ?, '50.00', '100', NULL, '用户手工记录', 'plan-1',
                      'operation-key-1', ?)
            """,
            (now, now),
        )
        connection.execute(
            """
            INSERT INTO operation_context_snapshots(
                id, user_id, workspace_id, operation_id, plan_id,
                thesis_version_id, data_time, snapshot_version, created_at
            ) VALUES ('context-1', 'user-1', 'workspace-1', 'operation-1',
                      'plan-1', 'thesis-1', ?, 'operation_context_v1', ?)
            """,
            (now, now),
        )
        connection.execute(
            """
            INSERT INTO trade_reviews(
                id, user_id, workspace_id, operation_id, plan_id,
                horizon_sessions, created_at, updated_at
            ) VALUES ('review-1', 'user-1', 'workspace-1', 'operation-1',
                      'plan-1', 5, ?, ?)
            """,
            (now, now),
        )
        connection.execute(
            """
            INSERT INTO trade_review_versions(
                id, review_id, user_id, workspace_id, version_no,
                price_result, logic_result, plan_deviation, improvement_text,
                created_source, created_at
            ) VALUES ('review-version-1', 'review-1', 'user-1', 'workspace-1', 1,
                      '等待足够价格数据', 'inconclusive', NULL, '继续核验',
                      'ai', ?)
            """,
            (now,),
        )
        connection.execute(
            """
            UPDATE trade_reviews SET current_version_id = 'review-version-1'
            WHERE id = 'review-1'
            """
        )

        plan = connection.execute(
            "SELECT * FROM action_plans WHERE id = 'plan-1'"
        ).fetchone()
        history = connection.execute(
            "SELECT * FROM action_plan_history WHERE id = 'plan-history-1'"
        ).fetchone()
        context = connection.execute(
            "SELECT * FROM operation_context_snapshots WHERE id = 'context-1'"
        ).fetchone()
        review = connection.execute(
            "SELECT * FROM trade_reviews WHERE id = 'review-1'"
        ).fetchone()
        review_version = connection.execute(
            "SELECT * FROM trade_review_versions WHERE id = 'review-version-1'"
        ).fetchone()
        assert plan is not None and plan["status"] == "draft"
        assert json.loads(plan["check_result_json"]) == {}
        assert history is not None and json.loads(history["snapshot_json"]) == {}
        assert context is not None and json.loads(context["snapshot_json"]) == {}
        assert review is not None and review["status"] == "waiting_data"
        assert review["data_status"] == "missing"
        assert review["current_version_id"] == "review-version-1"
        assert review_version is not None
        assert json.loads(review_version["bias_tags_json"]) == []
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

    with database.connect() as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO action_plan_history(
                id, plan_id, user_id, workspace_id, version, event_type,
                from_status, to_status, created_at
            ) VALUES ('cross-scope-history', 'plan-1', 'user-2', 'workspace-2', 2,
                      'updated', 'draft', 'checked', ?)
            """,
            (now,),
        )

    with database.connect() as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO operation_context_snapshots(
                id, user_id, workspace_id, operation_id, data_time,
                snapshot_version, created_at
            ) VALUES ('cross-scope-context', 'user-2', 'workspace-2',
                      'operation-1', ?, 'operation_context_v1', ?)
            """,
            (now, now),
        )

    with database.connect() as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO trade_review_versions(
                id, review_id, user_id, workspace_id, version_no,
                created_source, created_at
            ) VALUES ('cross-scope-version', 'review-1', 'user-2', 'workspace-2',
                      2, 'user', ?)
            """,
            (now,),
        )

    with database.connect() as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO action_plans(
                id, user_id, workspace_id, action_type, trigger_text, status,
                created_at, updated_at
            ) VALUES ('invalid-plan', 'user-1', 'workspace-1', 'hold', '条件',
                      'waiting_review', ?, ?)
            """,
            (now, now),
        )

    with database.connect() as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO trade_reviews(
                id, user_id, workspace_id, operation_id, status,
                horizon_sessions, created_at, updated_at
            ) VALUES ('invalid-review', 'user-1', 'workspace-1', 'operation-1',
                      'completed', 10, ?, ?)
            """,
            (now, now),
        )

    database.initialize()
    with database.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) AS count FROM action_plans WHERE id = 'plan-1'"
        ).fetchone()["count"] == 1
        assert connection.execute(
            "SELECT COUNT(*) AS count FROM trade_reviews WHERE id = 'review-1'"
        ).fetchone()["count"] == 1
        connection.execute("DELETE FROM users WHERE id = 'user-1'")
        for table in (
            "action_plans",
            "action_plan_history",
            "operation_context_snapshots",
            "trade_reviews",
            "trade_review_versions",
        ):
            assert connection.execute(
                f"SELECT COUNT(*) AS count FROM {table} WHERE user_id = 'user-1'"
            ).fetchone()["count"] == 0
