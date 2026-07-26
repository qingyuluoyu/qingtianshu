from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
from typing import Any
from uuid import uuid4

from app.domain_schema import DOMAIN_SCHEMA_SQL
from app.postgres_compat import PostgresConnection, create_postgres_pool
from app.utils import json_dumps, utc_now, write_json


class Database:
    SYSTEM_EDITOR_ID = "system-market-editor"
    SCHEMA_VERSION = 2

    def __init__(
        self,
        workspace_root: Path,
        database_url: str = "",
    ):
        self.workspace_root = Path(workspace_root)
        self.database_url = str(
            database_url or os.getenv("QINGSHU_DATABASE_URL", "")
        ).strip()
        if not self.database_url.startswith(
            ("postgresql://", "postgres://", "postgresql+psycopg://")
        ):
            raise ValueError("QINGSHU_DATABASE_URL is required and must use PostgreSQL")
        self._postgres_pool = create_postgres_pool(self.database_url)

    def __del__(self) -> None:
        pool = getattr(self, "_postgres_pool", None)
        if pool is not None:
            pool.close()
            self._postgres_pool = None

    def connect(self) -> PostgresConnection:
        if self._postgres_pool is None:
            raise RuntimeError("PostgreSQL connection pool is closed")
        return PostgresConnection(self._postgres_pool)

    def initialize(self) -> None:
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute(
                """
                SELECT pg_advisory_xact_lock(
                    hashtext('qingshu_domain_schema_migration')
                )
                """
            )
            connection.executescript(DOMAIN_SCHEMA_SQL)
            self._ensure_column(connection, "market_bars", "adjusted_close", "REAL")
            self._ensure_column(
                connection,
                "conversations",
                "quality_scope",
                "TEXT NOT NULL DEFAULT 'user'",
            )
            self._ensure_column(connection, "financial_periods", "eps_diluted", "REAL")
            self._ensure_column(
                connection, "financial_periods", "total_liabilities", "REAL"
            )
            self._ensure_column(
                connection,
                "strategy_screen_runs",
                "run_scope",
                "TEXT NOT NULL DEFAULT 'symbol_batch'",
            )
            self._ensure_column(
                connection,
                "strategy_screen_runs",
                "universe_count",
                "INTEGER NOT NULL DEFAULT 0",
            )
            self._ensure_column(
                connection,
                "strategy_screen_runs",
                "prefiltered_count",
                "INTEGER NOT NULL DEFAULT 0",
            )
            self._ensure_column(
                connection,
                "strategy_screen_runs",
                "coverage_ratio",
                "REAL NOT NULL DEFAULT 0",
            )
            self._ensure_column(
                connection,
                "strategy_screen_runs",
                "warnings_json",
                "TEXT NOT NULL DEFAULT '[]'",
            )
            self._ensure_column(
                connection,
                "trade_review_versions",
                "source_run_id",
                "TEXT REFERENCES runs(id) ON DELETE SET NULL",
            )
            self._ensure_column(
                connection,
                "action_plans",
                "idempotency_key",
                "TEXT",
            )
            self._ensure_column(
                connection,
                "background_job_runs",
                "queue_job_id",
                "TEXT",
            )
            self._ensure_column(
                connection,
                "background_job_runs",
                "worker_id",
                "TEXT",
            )
            self._upgrade_postgres_real_columns(connection)
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_action_plans_idempotency
                ON action_plans(user_id, idempotency_key)
                WHERE idempotency_key IS NOT NULL
                """
            )
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_deep_stock_user_conversation
                ON deep_stock_sessions(user_id, conversation_id)
                """
            )
            self._backfill_stock_domains(connection)
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS domain_schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO domain_schema_migrations(version, applied_at)
                VALUES (?, ?)
                """,
                (self.SCHEMA_VERSION, utc_now()),
            )

    def close(self) -> None:
        if self._postgres_pool is not None:
            self._postgres_pool.close()
            self._postgres_pool = None

    def schema_status(self) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT MAX(version) AS version FROM domain_schema_migrations"
            ).fetchone()
        return {
            "backend": "postgresql",
            "schema_version": int(row["version"] or 0),
        }

    def pool_status(self) -> dict[str, Any]:
        if self._postgres_pool is None:
            return {"backend": "postgresql", "status": "closed"}
        return dict(self._postgres_pool.get_stats())

    @staticmethod
    def _ensure_column(
        connection: PostgresConnection,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        columns = {
            str(row["column_name"])
            for row in connection.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = current_schema() AND table_name = ?
                """,
                (table,),
            ).fetchall()
        }
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    @staticmethod
    def _upgrade_postgres_real_columns(connection: PostgresConnection) -> None:
        rows = connection.execute(
            """
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND data_type = 'real'
            ORDER BY table_name, ordinal_position
            """
        ).fetchall()
        for row in rows:
            table = str(row["table_name"]).replace('"', '""')
            column = str(row["column_name"]).replace('"', '""')
            connection.execute(
                f'ALTER TABLE "{table}" ALTER COLUMN "{column}" '
                f'TYPE DOUBLE PRECISION USING "{column}"::DOUBLE PRECISION'
            )

    @staticmethod
    def _row(row: Any | None) -> dict[str, Any] | None:
        return dict(row) if row is not None else None

    @staticmethod
    def _stock_workspace_row(
        row: Any | None,
    ) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        item["attention_tags"] = json.loads(item.pop("attention_tags_json") or "[]")
        return item

    @staticmethod
    def _thesis_row(row: Any | None) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        item["watch_items"] = json.loads(item.pop("watch_items_json") or "[]")
        item["recheck_conditions"] = json.loads(
            item.pop("recheck_conditions_json") or "[]"
        )
        return item

    def _backfill_stock_domains(self, connection: PostgresConnection) -> None:
        rows = connection.execute(
            "SELECT * FROM watchlist ORDER BY created_at ASC"
        ).fetchall()
        for row in rows:
            self._sync_stock_domain_from_watchlist(
                connection,
                user_id=str(row["user_id"]),
                symbol=str(row["symbol"]),
                name=row["name"],
                market=row["market"],
                thesis=row["thesis"],
                source="watchlist_migration",
                observed_at=str(row["updated_at"] or row["created_at"]),
            )

    def _sync_stock_domain_from_watchlist(
        self,
        connection: PostgresConnection,
        *,
        user_id: str,
        symbol: str,
        name: str | None,
        market: str | None,
        thesis: str | None,
        source: str,
        observed_at: str,
    ) -> dict[str, Any]:
        workspace_row = connection.execute(
            "SELECT * FROM stock_workspaces WHERE user_id = ? AND symbol = ?",
            (user_id, symbol),
        ).fetchone()
        if workspace_row is None:
            workspace_id = str(uuid4())
            connection.execute(
                """
                INSERT INTO stock_workspaces(
                    id, user_id, symbol, name, market, relation_type, priority,
                    tracking_status, workflow_status, attention_tags_json,
                    version, created_at, updated_at, ended_at
                ) VALUES (?, ?, ?, ?, ?, 'watching', 'normal', 'active',
                          'idle', '[]', 1, ?, ?, NULL)
                """,
                (
                    workspace_id,
                    user_id,
                    symbol,
                    name,
                    market,
                    observed_at,
                    observed_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO stock_relation_history(
                    id, workspace_id, user_id, relation_type, priority,
                    tracking_status, source, effective_at, ended_at
                ) VALUES (?, ?, ?, 'watching', 'normal', 'active', ?, ?, NULL)
                """,
                (str(uuid4()), workspace_id, user_id, source, observed_at),
            )
        else:
            workspace_id = str(workspace_row["id"])
            if workspace_row["relation_type"] == "ended":
                connection.execute(
                    """
                    UPDATE stock_relation_history SET ended_at = ?
                    WHERE workspace_id = ? AND ended_at IS NULL
                    """,
                    (observed_at, workspace_id),
                )
                connection.execute(
                    """
                    UPDATE stock_workspaces
                    SET name = COALESCE(?, name), market = COALESCE(?, market),
                        relation_type = 'watching', priority = 'normal',
                        tracking_status = 'active', workflow_status = 'idle',
                        version = version + 1, updated_at = ?, ended_at = NULL
                    WHERE id = ?
                    """,
                    (name, market, observed_at, workspace_id),
                )
                connection.execute(
                    """
                    INSERT INTO stock_relation_history(
                        id, workspace_id, user_id, relation_type, priority,
                        tracking_status, source, effective_at, ended_at
                    ) VALUES (?, ?, ?, 'watching', 'normal', 'active', ?, ?, NULL)
                    """,
                    (str(uuid4()), workspace_id, user_id, source, observed_at),
                )
            elif name != workspace_row["name"] or market != workspace_row["market"]:
                connection.execute(
                    """
                    UPDATE stock_workspaces
                    SET name = COALESCE(?, name), market = COALESCE(?, market),
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (name, market, observed_at, workspace_id),
                )

        clean_thesis = str(thesis or "").strip()
        if clean_thesis:
            active = connection.execute(
                """
                SELECT * FROM thesis_versions
                WHERE workspace_id = ? AND status = 'active'
                ORDER BY version_no DESC LIMIT 1
                """,
                (workspace_id,),
            ).fetchone()
            if active is None or str(active["reason_text"]).strip() != clean_thesis:
                current_version = int(active["version_no"]) if active else 0
                if active is not None:
                    connection.execute(
                        """
                        UPDATE thesis_versions
                        SET status = 'superseded', superseded_at = ?
                        WHERE id = ? AND status = 'active'
                        """,
                        (observed_at, active["id"]),
                    )
                next_version_row = connection.execute(
                    """
                    SELECT COALESCE(MAX(version_no), 0) + 1 AS next_version
                    FROM thesis_versions WHERE workspace_id = ?
                    """,
                    (workspace_id,),
                ).fetchone()
                next_version = int(next_version_row["next_version"])
                connection.execute(
                    """
                    INSERT INTO thesis_versions(
                        id, workspace_id, user_id, symbol, version_no, status,
                        reason_text, watch_items_json, recheck_conditions_json,
                        source, source_run_id, base_version, created_at,
                        confirmed_at, superseded_at
                    ) VALUES (?, ?, ?, ?, ?, 'active', ?, '[]', '[]', ?, NULL,
                              ?, ?, ?, NULL)
                    """,
                    (
                        str(uuid4()),
                        workspace_id,
                        user_id,
                        symbol,
                        next_version,
                        clean_thesis,
                        source,
                        current_version,
                        observed_at,
                        observed_at,
                    ),
                )
        row = connection.execute(
            "SELECT * FROM stock_workspaces WHERE id = ?", (workspace_id,)
        ).fetchone()
        return self._stock_workspace_row(row)  # type: ignore[return-value]

    def create_user(self, name: str) -> dict[str, Any]:
        user_id = str(uuid4())
        workspace = (self.workspace_root / user_id).resolve()
        workspace.mkdir(parents=True, exist_ok=False)
        created_at = utc_now()
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO users(id, name, workspace_path, created_at) VALUES (?, ?, ?, ?)",
                (user_id, name.strip(), str(workspace), created_at),
            )
        user = self.get_user(user_id)  # type: ignore[assignment]
        write_json(workspace / "profile.json", user)
        write_json(workspace / "memory" / "confirmed.json", [])
        write_json(workspace / "watchlist.json", [])
        return user  # type: ignore[return-value]

    def ensure_system_editor(self) -> dict[str, Any]:
        workspace = (self.workspace_root / "_system_market_editor").resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO users(id, name, workspace_path, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (self.SYSTEM_EDITOR_ID, "清数智算系统编辑", str(workspace), utc_now()),
            )
        return self.get_user(self.SYSTEM_EDITOR_ID)  # type: ignore[return-value]

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            return self._row(
                connection.execute(
                    "SELECT * FROM users WHERE id = ?", (user_id,)
                ).fetchone()
            )

    @staticmethod
    def _session_token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def create_user_session(self, user_id: str, ttl_days: int = 365) -> dict[str, Any]:
        token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        created_at = now.isoformat(timespec="seconds")
        expires_at = (now + timedelta(days=ttl_days)).isoformat(timespec="seconds")
        session_id = str(uuid4())
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO user_sessions(
                    id, token_hash, user_id, created_at, expires_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    self._session_token_hash(token),
                    user_id,
                    created_at,
                    expires_at,
                    created_at,
                ),
            )
        return {
            "id": session_id,
            "token": token,
            "user_id": user_id,
            "created_at": created_at,
            "expires_at": expires_at,
        }

    def get_user_by_session(self, token: str | None) -> dict[str, Any] | None:
        if not token:
            return None
        token_hash = self._session_token_hash(token)
        now = utc_now()
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT users.*, user_sessions.expires_at AS session_expires_at
                FROM user_sessions
                JOIN users ON users.id = user_sessions.user_id
                WHERE user_sessions.token_hash = ?
                  AND user_sessions.revoked_at IS NULL
                  AND user_sessions.expires_at > ?
                """,
                (token_hash, now),
            ).fetchone()
            if row is not None:
                connection.execute(
                    "UPDATE user_sessions SET last_seen_at = ? WHERE token_hash = ?",
                    (now, token_hash),
                )
        return self._row(row)

    def revoke_user_session(self, token: str | None) -> None:
        if not token:
            return
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE user_sessions SET revoked_at = ?
                WHERE token_hash = ? AND revoked_at IS NULL
                """,
                (utc_now(), self._session_token_hash(token)),
            )

    def user_has_session_history(self, user_id: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM user_sessions WHERE user_id = ? LIMIT 1", (user_id,)
            ).fetchone()
        return row is not None

    def create_user_upload(
        self,
        upload_id: str,
        user_id: str,
        kind: str,
        original_name: str,
        mime_type: str,
        size_bytes: int,
        width: int,
        height: int,
        workspace_path: Path,
    ) -> dict[str, Any]:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO user_uploads(
                    id, user_id, kind, original_name, mime_type, size_bytes,
                    width, height, workspace_path, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    upload_id,
                    user_id,
                    kind,
                    original_name,
                    mime_type,
                    size_bytes,
                    width,
                    height,
                    str(Path(workspace_path).resolve()),
                    utc_now(),
                ),
            )
        return self.get_user_upload(user_id, upload_id)  # type: ignore[return-value]

    def get_user_upload(self, user_id: str, upload_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            return self._row(
                connection.execute(
                    "SELECT * FROM user_uploads WHERE user_id = ? AND id = ?",
                    (user_id, upload_id),
                ).fetchone()
            )

    def mark_user_upload_used(self, user_id: str, upload_id: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE user_uploads SET used_at = ?
                WHERE user_id = ? AND id = ?
                """,
                (utc_now(), user_id, upload_id),
            )

    def upsert_watchlist(
        self,
        user_id: str,
        symbol: str,
        name: str | None,
        market: str | None,
        thesis: str | None,
    ) -> dict[str, Any]:
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO watchlist(user_id, symbol, name, market, thesis, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, symbol) DO UPDATE SET
                    name = excluded.name,
                    market = excluded.market,
                    thesis = COALESCE(excluded.thesis, watchlist.thesis),
                    updated_at = excluded.updated_at
                """,
                (user_id, symbol, name, market, thesis, now, now),
            )
            row = connection.execute(
                "SELECT * FROM watchlist WHERE user_id = ? AND symbol = ?",
                (user_id, symbol),
            ).fetchone()
            self._sync_stock_domain_from_watchlist(
                connection,
                user_id=user_id,
                symbol=symbol,
                name=row["name"],
                market=row["market"],
                thesis=row["thesis"],
                source="legacy_watchlist_confirmed",
                observed_at=now,
            )
        result = dict(row)
        self._sync_watchlist_file(user_id)
        return result

    def list_watchlist(self, user_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM watchlist WHERE user_id = ? ORDER BY updated_at DESC",
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_distinct_watchlist_symbols(
        self, *, exclude_user_id: str | None = None
    ) -> list[str]:
        with self.connect() as connection:
            if exclude_user_id is None:
                rows = connection.execute(
                    "SELECT DISTINCT symbol FROM watchlist ORDER BY symbol"
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT DISTINCT symbol
                    FROM watchlist
                    WHERE user_id <> ?
                    ORDER BY symbol
                    """,
                    (exclude_user_id,),
                ).fetchall()
        return [str(row["symbol"]) for row in rows]

    def get_watchlist_item(self, user_id: str, symbol: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            return self._row(
                connection.execute(
                    "SELECT * FROM watchlist WHERE user_id = ? AND symbol = ?",
                    (user_id, symbol),
                ).fetchone()
            )

    def delete_watchlist_item(self, user_id: str, symbol: str) -> bool:
        now = utc_now()
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT * FROM watchlist WHERE user_id = ? AND symbol = ?",
                (user_id, symbol),
            ).fetchone()
            if existing is None:
                return False
            workspace = connection.execute(
                "SELECT * FROM stock_workspaces WHERE user_id = ? AND symbol = ?",
                (user_id, symbol),
            ).fetchone()
            if workspace is not None and workspace["relation_type"] != "ended":
                connection.execute(
                    """
                    UPDATE stock_relation_history SET ended_at = ?
                    WHERE workspace_id = ? AND ended_at IS NULL
                    """,
                    (now, workspace["id"]),
                )
                connection.execute(
                    """
                    UPDATE stock_workspaces
                    SET relation_type = 'ended', priority = NULL,
                        tracking_status = 'paused', workflow_status = 'idle',
                        version = version + 1, updated_at = ?, ended_at = ?
                    WHERE id = ?
                    """,
                    (now, now, workspace["id"]),
                )
                connection.execute(
                    """
                    INSERT INTO stock_relation_history(
                        id, workspace_id, user_id, relation_type, priority,
                        tracking_status, source, effective_at, ended_at
                    ) VALUES (?, ?, ?, 'ended', NULL, 'paused',
                              'legacy_watchlist_delete', ?, NULL)
                    """,
                    (str(uuid4()), workspace["id"], user_id, now),
                )
            cursor = connection.execute(
                "DELETE FROM watchlist WHERE user_id = ? AND symbol = ?",
                (user_id, symbol),
            )
        if cursor.rowcount:
            self._sync_watchlist_file(user_id)
            return True
        return False

    def get_stock_workspace(self, user_id: str, symbol: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM stock_workspaces
                WHERE user_id = ? AND symbol = ?
                """,
                (user_id, symbol),
            ).fetchone()
        return self._stock_workspace_row(row)

    def list_stock_workspaces(self, user_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM stock_workspaces
                WHERE user_id = ?
                ORDER BY updated_at DESC, rowid DESC
                """,
                (user_id,),
            ).fetchall()
        return [
            self._stock_workspace_row(row)  # type: ignore[misc]
            for row in rows
        ]

    def list_stock_relation_history(
        self, user_id: str, workspace_id: str
    ) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM stock_relation_history
                WHERE user_id = ? AND workspace_id = ?
                ORDER BY effective_at ASC, rowid ASC
                """,
                (user_id, workspace_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_active_thesis(
        self, user_id: str, workspace_id: str
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM thesis_versions
                WHERE user_id = ? AND workspace_id = ? AND status = 'active'
                ORDER BY version_no DESC LIMIT 1
                """,
                (user_id, workspace_id),
            ).fetchone()
        return self._thesis_row(row)

    def get_thesis_version(self, user_id: str, thesis_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM thesis_versions WHERE user_id = ? AND id = ?",
                (user_id, thesis_id),
            ).fetchone()
        return self._thesis_row(row)

    def list_thesis_versions(
        self, user_id: str, workspace_id: str
    ) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM thesis_versions
                WHERE user_id = ? AND workspace_id = ?
                ORDER BY version_no DESC, rowid DESC
                """,
                (user_id, workspace_id),
            ).fetchall()
        return [
            self._thesis_row(row)  # type: ignore[misc]
            for row in rows
        ]

    def create_memory(self, user_id: str, kind: str, content: str) -> dict[str, Any]:
        memory_id = str(uuid4())
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO memories(id, user_id, kind, content, status, created_at)
                VALUES (?, ?, ?, ?, 'candidate', ?)
                """,
                (memory_id, user_id, kind, content.strip(), utc_now()),
            )
        return self.get_memory(user_id, memory_id)  # type: ignore[return-value]

    def get_memory(self, user_id: str, memory_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            return self._row(
                connection.execute(
                    "SELECT * FROM memories WHERE user_id = ? AND id = ?",
                    (user_id, memory_id),
                ).fetchone()
            )

    def confirm_memory(self, user_id: str, memory_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE memories SET status = 'confirmed', confirmed_at = ?
                WHERE user_id = ? AND id = ? AND status = 'candidate'
                """,
                (utc_now(), user_id, memory_id),
            )
            if cursor.rowcount == 0:
                return None
        memory = self.get_memory(user_id, memory_id)
        self._sync_confirmed_memory_file(user_id)
        return memory

    def reject_memory(self, user_id: str, memory_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE memories SET status = 'rejected'
                WHERE user_id = ? AND id = ? AND status = 'candidate'
                """,
                (user_id, memory_id),
            )
            if cursor.rowcount == 0:
                return None
        return self.get_memory(user_id, memory_id)

    def list_memories(
        self, user_id: str, status: str = "confirmed"
    ) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM memories WHERE user_id = ? AND status = ? ORDER BY created_at DESC",
                (user_id, status),
            ).fetchall()
        return [dict(row) for row in rows]

    def _sync_watchlist_file(self, user_id: str) -> None:
        user = self.get_user(user_id)
        if user is None:
            return
        write_json(
            Path(user["workspace_path"]) / "watchlist.json",
            self.list_watchlist(user_id),
        )

    def _sync_confirmed_memory_file(self, user_id: str) -> None:
        user = self.get_user(user_id)
        if user is None:
            return
        memories = [
            {
                "id": item["id"],
                "kind": item["kind"],
                "content": item["content"],
                "confirmed_at": item["confirmed_at"],
            }
            for item in self.list_memories(user_id, status="confirmed")
        ]
        write_json(Path(user["workspace_path"]) / "memory" / "confirmed.json", memories)

    def create_conversation(
        self,
        user_id: str,
        title: str = "新的研究对话",
        quality_scope: str = "user",
    ) -> dict[str, Any]:
        if quality_scope not in {"user", "evaluation"}:
            raise ValueError("Unsupported conversation quality scope")
        conversation_id = str(uuid4())
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO conversations(
                    id, user_id, title, quality_scope, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'active', ?, ?)
                """,
                (
                    conversation_id,
                    user_id,
                    title.strip() or "新的研究对话",
                    quality_scope,
                    now,
                    now,
                ),
            )
        return self.get_conversation(user_id, conversation_id)  # type: ignore[return-value]

    def get_conversation(
        self, user_id: str, conversation_id: str
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT conversations.*,
                    (SELECT COUNT(*) FROM conversation_messages
                     WHERE conversation_id = conversations.id) AS message_count,
                    (SELECT intent FROM conversation_messages
                     WHERE conversation_id = conversations.id
                       AND intent IS NOT NULL AND intent <> ''
                     ORDER BY created_at DESC, rowid DESC LIMIT 1) AS last_intent,
                    (SELECT metadata_json FROM conversation_messages
                     WHERE conversation_id = conversations.id
                       AND role = 'assistant'
                     ORDER BY created_at DESC, rowid DESC LIMIT 1) AS last_metadata_json,
                    (SELECT symbol FROM deep_stock_sessions
                     WHERE conversation_id = conversations.id
                     ORDER BY updated_at DESC, rowid DESC LIMIT 1) AS bound_symbol,
                    (SELECT name FROM deep_stock_sessions
                     WHERE conversation_id = conversations.id
                     ORDER BY updated_at DESC, rowid DESC LIMIT 1) AS bound_name
                FROM conversations
                WHERE id = ? AND user_id = ?
                """,
                (conversation_id, user_id),
            ).fetchone()
        return self._conversation_row(row)

    def list_conversations(
        self, user_id: str, include_archived: bool = False, limit: int = 100
    ) -> list[dict[str, Any]]:
        status_clause = (
            "" if include_archived else "AND conversations.status = 'active'"
        )
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT conversations.*,
                    (SELECT COUNT(*) FROM conversation_messages
                     WHERE conversation_id = conversations.id) AS message_count,
                    (SELECT substr(content, 1, 120) FROM conversation_messages
                     WHERE conversation_id = conversations.id
                     ORDER BY created_at DESC, rowid DESC LIMIT 1) AS last_message_preview,
                    (SELECT intent FROM conversation_messages
                     WHERE conversation_id = conversations.id
                       AND intent IS NOT NULL AND intent <> ''
                     ORDER BY created_at DESC, rowid DESC LIMIT 1) AS last_intent,
                    (SELECT metadata_json FROM conversation_messages
                     WHERE conversation_id = conversations.id
                       AND role = 'assistant'
                     ORDER BY created_at DESC, rowid DESC LIMIT 1) AS last_metadata_json,
                    (SELECT symbol FROM deep_stock_sessions
                     WHERE conversation_id = conversations.id
                     ORDER BY updated_at DESC, rowid DESC LIMIT 1) AS bound_symbol,
                    (SELECT name FROM deep_stock_sessions
                     WHERE conversation_id = conversations.id
                     ORDER BY updated_at DESC, rowid DESC LIMIT 1) AS bound_name
                FROM conversations
                WHERE user_id = ? {status_clause}
                ORDER BY updated_at DESC, rowid DESC LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [
            self._conversation_row(row)  # type: ignore[misc]
            for row in rows
        ]

    @staticmethod
    def _conversation_row(row: Any | None) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        raw_metadata = item.pop("last_metadata_json", None)
        bound_symbol = str(item.pop("bound_symbol", "") or "").strip().upper()
        bound_name = str(item.pop("bound_name", "") or "").strip()
        try:
            metadata = json.loads(raw_metadata or "{}")
        except (TypeError, ValueError):
            metadata = {}
        targets: dict[str, dict[str, str]] = {}

        def add_target(symbol: Any, name: Any = None) -> None:
            canonical = str(symbol or "").strip().upper().replace(".SH", ".SS")
            if not canonical:
                return
            display_name = str(name or canonical).strip() or canonical
            existing = targets.get(canonical)
            if existing is None or (
                existing["name"] == canonical and display_name != canonical
            ):
                targets[canonical] = {"symbol": canonical, "name": display_name}

        for target in metadata.get("research_targets") or []:
            if isinstance(target, dict):
                add_target(target.get("symbol"), target.get("name"))
            else:
                add_target(target)
        add_target(metadata.get("symbol"))
        add_target(bound_symbol, bound_name)
        item["research_targets"] = list(targets.values())[:10]
        return item

    def rename_conversation(
        self, user_id: str, conversation_id: str, title: str
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE conversations SET title = ?, updated_at = ?
                WHERE id = ? AND user_id = ? AND status = 'active'
                """,
                (title.strip(), utc_now(), conversation_id, user_id),
            )
            if cursor.rowcount == 0:
                return None
        return self.get_conversation(user_id, conversation_id)

    def set_conversation_quality_scope(
        self, user_id: str, conversation_id: str, quality_scope: str
    ) -> dict[str, Any] | None:
        if quality_scope not in {"user", "evaluation"}:
            raise ValueError("Unsupported conversation quality scope")
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE conversations SET quality_scope = ?, updated_at = ?
                WHERE id = ? AND user_id = ? AND status = 'active'
                """,
                (quality_scope, utc_now(), conversation_id, user_id),
            )
            if cursor.rowcount == 0:
                return None
        return self.get_conversation(user_id, conversation_id)

    def archive_conversation(self, user_id: str, conversation_id: str) -> bool:
        now = utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE conversations
                SET status = 'archived', archived_at = ?, updated_at = ?
                WHERE id = ? AND user_id = ? AND status = 'active'
                """,
                (now, now, conversation_id, user_id),
            )
        return cursor.rowcount > 0

    def add_conversation_message(
        self,
        user_id: str,
        conversation_id: str,
        role: str,
        content: str,
        intent: str | None = None,
        run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        message_id = str(uuid4())
        now = utc_now()
        with self.connect() as connection:
            owner = connection.execute(
                """
                SELECT 1 FROM conversations
                WHERE id = ? AND user_id = ? AND status = 'active'
                """,
                (conversation_id, user_id),
            ).fetchone()
            if owner is None:
                raise ValueError("对话不存在或已归档")
            connection.execute(
                """
                INSERT INTO conversation_messages(
                    id, conversation_id, user_id, role, content, intent,
                    run_id, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    conversation_id,
                    user_id,
                    role,
                    content,
                    intent,
                    run_id,
                    json_dumps(metadata or {}),
                    now,
                ),
            )
            connection.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now, conversation_id),
            )
        return self.get_conversation_message(user_id, message_id)  # type: ignore[return-value]

    def get_conversation_message(
        self, user_id: str, message_id: str
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM conversation_messages
                WHERE id = ? AND user_id = ?
                """,
                (message_id, user_id),
            ).fetchone()
        item = self._row(row)
        if item is not None:
            item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
        return item

    def update_assistant_conversation_message(
        self,
        *,
        user_id: str,
        conversation_id: str,
        message_id: str,
        content: str,
        intent: str,
        run_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        now = utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE conversation_messages
                SET content = ?, intent = ?, run_id = ?, metadata_json = ?
                WHERE id = ? AND conversation_id = ? AND user_id = ?
                  AND role = 'assistant'
                """,
                (
                    content,
                    intent,
                    run_id,
                    json_dumps(metadata or {}),
                    message_id,
                    conversation_id,
                    user_id,
                ),
            )
            if cursor.rowcount == 0:
                return None
            connection.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ? AND user_id = ?",
                (now, conversation_id, user_id),
            )
        return self.get_conversation_message(user_id, message_id)

    def list_conversation_messages(
        self, user_id: str, conversation_id: str, limit: int = 200
    ) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT conversation_messages.*
                FROM conversation_messages
                JOIN conversations ON conversations.id = conversation_messages.conversation_id
                WHERE conversation_messages.conversation_id = ?
                  AND conversations.user_id = ?
                ORDER BY conversation_messages.created_at ASC,
                    conversation_messages.rowid ASC LIMIT ?
                """,
                (conversation_id, user_id, limit),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
            items.append(item)
        return items

    def list_recent_conversation_messages(
        self, user_id: str, conversation_id: str, limit: int = 200
    ) -> list[dict[str, Any]]:
        """Return the latest messages in chronological display order."""
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT conversation_messages.*
                FROM conversation_messages
                JOIN conversations ON conversations.id = conversation_messages.conversation_id
                WHERE conversation_messages.conversation_id = ?
                  AND conversations.user_id = ?
                ORDER BY conversation_messages.created_at DESC,
                    conversation_messages.rowid DESC LIMIT ?
                """,
                (conversation_id, user_id, limit),
            ).fetchall()
        items = []
        for row in reversed(rows):
            item = dict(row)
            item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
            items.append(item)
        return items

    def list_recent_user_assistant_messages(
        self, user_id: str, limit: int = 500
    ) -> list[dict[str, Any]]:
        """Return one user's latest assistant messages across research conversations."""
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT conversation_messages.*
                FROM conversation_messages
                JOIN conversations ON conversations.id = conversation_messages.conversation_id
                WHERE conversations.user_id = ?
                  AND conversation_messages.role = 'assistant'
                ORDER BY conversation_messages.created_at DESC,
                    conversation_messages.rowid DESC LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
            items.append(item)
        return items

    def save_deep_stock_session(
        self,
        *,
        user_id: str,
        symbol: str,
        name: str,
        conversation_id: str,
        workflow_version: str,
        status: str,
        stages: list[dict[str, Any]],
        evidence_modules: dict[str, Any],
        unresolved_items: list[str],
        next_question: str,
        latest_run_id: str | None = None,
        latest_report_id: str | None = None,
        completed_at: str | None = None,
    ) -> dict[str, Any]:
        existing = self.get_deep_stock_session(user_id, symbol)
        session_id = str(existing["id"]) if existing else str(uuid4())
        created_at = str(existing["created_at"]) if existing else utc_now()
        updated_at = utc_now()
        with self.connect() as connection:
            owner = connection.execute(
                """
                SELECT 1 FROM conversations
                WHERE id = ? AND user_id = ? AND status = 'active'
                """,
                (conversation_id, user_id),
            ).fetchone()
            if owner is None:
                raise ValueError("个股研究绑定的研究对话不存在或已归档")
            connection.execute(
                """
                INSERT INTO deep_stock_sessions(
                    id, user_id, symbol, name, conversation_id,
                    workflow_version, status, stages_json,
                    evidence_modules_json, unresolved_json, next_question,
                    latest_run_id, latest_report_id, created_at, updated_at,
                    completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, symbol) DO UPDATE SET
                    name = excluded.name,
                    conversation_id = excluded.conversation_id,
                    workflow_version = excluded.workflow_version,
                    status = excluded.status,
                    stages_json = excluded.stages_json,
                    evidence_modules_json = excluded.evidence_modules_json,
                    unresolved_json = excluded.unresolved_json,
                    next_question = excluded.next_question,
                    latest_run_id = excluded.latest_run_id,
                    latest_report_id = excluded.latest_report_id,
                    updated_at = excluded.updated_at,
                    completed_at = excluded.completed_at
                """,
                (
                    session_id,
                    user_id,
                    symbol,
                    name,
                    conversation_id,
                    workflow_version,
                    status,
                    json_dumps(stages),
                    json_dumps(evidence_modules),
                    json_dumps(unresolved_items),
                    next_question,
                    latest_run_id,
                    latest_report_id,
                    created_at,
                    updated_at,
                    completed_at,
                ),
            )
        session = self.get_deep_stock_session(user_id, symbol)
        if session is not None:
            self._sync_deep_stock_session_file(user_id, session)
        return session  # type: ignore[return-value]

    def get_deep_stock_session(
        self, user_id: str, symbol: str
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM deep_stock_sessions
                WHERE user_id = ? AND symbol = ?
                """,
                (user_id, symbol),
            ).fetchone()
        return self._deep_stock_session_row(row)

    def get_deep_stock_session_by_conversation(
        self, user_id: str, conversation_id: str
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM deep_stock_sessions
                WHERE user_id = ? AND conversation_id = ?
                """,
                (user_id, conversation_id),
            ).fetchone()
        return self._deep_stock_session_row(row)

    def list_deep_stock_sessions(
        self, user_id: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM deep_stock_sessions
                WHERE user_id = ?
                ORDER BY updated_at DESC, rowid DESC LIMIT ?
                """,
                (user_id, max(1, min(limit, 200))),
            ).fetchall()
        return [
            self._deep_stock_session_row(row)  # type: ignore[misc]
            for row in rows
        ]

    def list_distinct_deep_stock_symbols(self) -> list[str]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT symbol, MAX(updated_at) AS latest_updated_at
                FROM deep_stock_sessions
                GROUP BY symbol
                ORDER BY latest_updated_at DESC, symbol ASC
                """
            ).fetchall()
        return [str(row["symbol"]) for row in rows if row["symbol"]]

    @staticmethod
    def _deep_stock_session_row(
        row: Any | None,
    ) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        item["stages"] = json.loads(item.pop("stages_json") or "[]")
        item["evidence_modules"] = json.loads(item.pop("evidence_modules_json") or "{}")
        item["unresolved_items"] = json.loads(item.pop("unresolved_json") or "[]")
        return item

    def _sync_deep_stock_session_file(
        self, user_id: str, session: dict[str, Any]
    ) -> None:
        user = self.get_user(user_id)
        if user is None:
            return
        write_json(
            Path(user["workspace_path"])
            / "deep-stock"
            / f"{session['symbol'].replace('.', '_')}.json",
            session,
        )

    def upsert_knowledge_document(
        self,
        document_id: str,
        scope: str,
        title: str,
        original_name: str,
        mime_type: str,
        content: str,
        source_key: str,
        owner_user_id: str | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO knowledge_documents(
                    id, owner_user_id, scope, title, original_name, mime_type,
                    content, source_key, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    original_name = excluded.original_name,
                    mime_type = excluded.mime_type,
                    content = excluded.content,
                    source_key = excluded.source_key,
                    updated_at = excluded.updated_at
                """,
                (
                    document_id,
                    owner_user_id,
                    scope,
                    title.strip(),
                    original_name,
                    mime_type,
                    content,
                    source_key,
                    now,
                    now,
                ),
            )
        return self.get_knowledge_document(owner_user_id, document_id)  # type: ignore[return-value]

    def get_knowledge_document(
        self, user_id: str | None, document_id: str
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM knowledge_documents
                WHERE id = ? AND (
                    scope = 'common' OR (scope = 'user' AND owner_user_id = ?)
                )
                """,
                (document_id, user_id),
            ).fetchone()
        return self._row(row)

    def list_knowledge_documents(
        self, user_id: str | None, include_content: bool = False
    ) -> list[dict[str, Any]]:
        fields = (
            "*"
            if include_content
            else (
                "id, owner_user_id, scope, title, original_name, mime_type, "
                "source_key, length(content) AS content_chars, created_at, updated_at"
            )
        )
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT {fields} FROM knowledge_documents
                WHERE scope = 'common' OR (scope = 'user' AND owner_user_id = ?)
                ORDER BY scope ASC, updated_at DESC
                """,
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_user_knowledge_document(self, user_id: str, document_id: str) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM knowledge_documents
                WHERE id = ? AND owner_user_id = ? AND scope = 'user'
                """,
                (document_id, user_id),
            )
        return cursor.rowcount > 0

    def create_run(
        self,
        user_id: str,
        intent: str,
        model_tier: str,
        input_data: dict[str, Any],
        workspace_path: Path,
    ) -> dict[str, Any]:
        run_id = str(uuid4())
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO runs(
                    id, user_id, intent, model_tier, status, input_json,
                    workspace_path, created_at
                ) VALUES (?, ?, ?, ?, 'running', ?, ?, ?)
                """,
                (
                    run_id,
                    user_id,
                    intent,
                    model_tier,
                    json_dumps(input_data),
                    str(workspace_path),
                    utc_now(),
                ),
            )
        return self.get_run(run_id, user_id)  # type: ignore[return-value]

    def finish_run(
        self,
        run_id: str,
        user_id: str,
        status: str,
        evidence: dict[str, Any],
        answer: str,
        usage: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE runs SET status = ?, evidence_json = ?, answer = ?, usage_json = ?,
                    error = ?, finished_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (
                    status,
                    json_dumps(evidence),
                    answer,
                    json_dumps(usage) if usage is not None else None,
                    error,
                    utc_now(),
                    run_id,
                    user_id,
                ),
            )

    def get_run(self, run_id: str, user_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM runs WHERE id = ? AND user_id = ?", (run_id, user_id)
            ).fetchone()
        item = self._row(row)
        if item is None:
            return None
        for key in ("input_json", "evidence_json", "usage_json"):
            raw = item.pop(key)
            item[key.removesuffix("_json")] = json.loads(raw) if raw else None
        return item

    def list_user_runs(self, user_id: str, limit: int = 500) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM runs
                WHERE user_id = ?
                ORDER BY created_at DESC, rowid DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            for key in ("input_json", "evidence_json", "usage_json"):
                raw = item.pop(key)
                item[key.removesuffix("_json")] = json.loads(raw) if raw else None
            items.append(item)
        return items

    def save_conversation_quality_snapshot(
        self,
        user_id: str,
        fingerprint: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        snapshot_id = str(uuid4())
        created_at = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO conversation_quality_snapshots(
                    id, user_id, fingerprint, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id, fingerprint) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    created_at = excluded.created_at
                """,
                (
                    snapshot_id,
                    user_id,
                    fingerprint,
                    json_dumps(payload),
                    created_at,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM conversation_quality_snapshots
                WHERE user_id = ? AND fingerprint = ?
                """,
                (user_id, fingerprint),
            ).fetchone()
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json"))
        return item

    def latest_conversation_quality_snapshot(
        self, user_id: str
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM conversation_quality_snapshots
                WHERE user_id = ?
                ORDER BY created_at DESC, rowid DESC LIMIT 1
                """,
                (user_id,),
            ).fetchone()
        item = self._row(row)
        if item is not None:
            item["payload"] = json.loads(item.pop("payload_json"))
        return item

    def create_article(
        self,
        user_id: str,
        kind: str,
        title: str,
        summary: str,
        body: str,
        status: str,
        fingerprint: str,
        evidence: dict[str, Any],
        run_id: str | None,
    ) -> dict[str, Any]:
        article_id = str(uuid4())
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO articles(
                    id, user_id, kind, title, summary, body, status,
                    fingerprint, evidence_json, run_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    article_id,
                    user_id,
                    kind,
                    title,
                    summary,
                    body,
                    status,
                    fingerprint,
                    json_dumps(evidence),
                    run_id,
                    utc_now(),
                ),
            )
        return self.get_article(user_id, article_id)  # type: ignore[return-value]

    def get_article(self, user_id: str, article_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM articles WHERE user_id = ? AND id = ?",
                (user_id, article_id),
            ).fetchone()
        item = self._row(row)
        if item is not None:
            item["evidence"] = json.loads(item.pop("evidence_json"))
        return item

    def list_articles(self, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM articles WHERE user_id = ?
                ORDER BY created_at DESC LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["evidence"] = json.loads(item.pop("evidence_json"))
            items.append(item)
        return items

    def latest_article(self, user_id: str, kind: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM articles WHERE user_id = ? AND kind = ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (user_id, kind),
            ).fetchone()
        item = self._row(row)
        if item is not None:
            item["evidence"] = json.loads(item.pop("evidence_json"))
        return item

    def count_articles_since(self, user_id: str, kind: str, since: str) -> int:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS count FROM articles
                WHERE user_id = ? AND kind = ? AND created_at >= ?
                """,
                (user_id, kind, since),
            ).fetchone()
        return int(row["count"])

    def put_cache(
        self, cache_key: str, payload: dict[str, Any], ttl_seconds: int
    ) -> None:
        fetched_at = payload.get("fetched_at") or utc_now()
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
        ).isoformat(timespec="seconds")
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO market_cache(
                    cache_key, payload_json, source, market_at, fetched_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    source = excluded.source,
                    market_at = excluded.market_at,
                    fetched_at = excluded.fetched_at,
                    expires_at = excluded.expires_at
                """,
                (
                    cache_key,
                    json_dumps(payload),
                    payload.get("source", "unknown"),
                    payload.get("market_timestamp"),
                    fetched_at,
                    expires_at,
                ),
            )

    def update_cache_payload_preserving_expiry(
        self, cache_key: str, payload: dict[str, Any]
    ) -> bool:
        """Replace a cached payload without turning a read into a TTL renewal."""
        fetched_at = payload.get("fetched_at") or utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE market_cache
                SET payload_json = ?, source = ?, market_at = ?, fetched_at = ?
                WHERE cache_key = ?
                """,
                (
                    json_dumps(payload),
                    payload.get("source", "unknown"),
                    payload.get("market_timestamp"),
                    fetched_at,
                    cache_key,
                ),
            )
        return cursor.rowcount > 0

    def upsert_market_breadth_snapshot(self, payload: dict[str, Any]) -> None:
        market_date = str(payload.get("market_date") or "").strip()
        if not market_date:
            return
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO market_breadth_snapshots(
                    market_date, payload_json, source, fetched_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(market_date) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    source = excluded.source,
                    fetched_at = excluded.fetched_at
                """,
                (
                    market_date,
                    json_dumps(payload),
                    payload.get("source") or "unknown",
                    payload.get("fetched_at") or utc_now(),
                ),
            )

    def list_market_breadth_snapshots(self, limit: int = 21) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT market_date, payload_json, source, fetched_at
                FROM market_breadth_snapshots
                ORDER BY market_date DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        items = []
        for row in rows:
            payload = json.loads(row["payload_json"])
            payload.setdefault("market_date", row["market_date"])
            payload.setdefault("source", row["source"])
            payload.setdefault("fetched_at", row["fetched_at"])
            items.append(payload)
        return items

    def get_cache(
        self, cache_key: str, allow_stale: bool = False
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM market_cache WHERE cache_key = ?", (cache_key,)
            ).fetchone()
        if row is None:
            return None
        expired = datetime.fromisoformat(row["expires_at"]) <= datetime.now(
            timezone.utc
        )
        if expired and not allow_stale:
            return None
        payload = json.loads(row["payload_json"])
        payload["cache_hit"] = True
        payload["is_stale"] = expired
        if expired:
            payload.setdefault("warnings", []).append(
                "实时上游不可用，当前返回已过期缓存。"
            )
        return payload

    def upsert_market_bars(
        self,
        symbol: str,
        interval: str,
        points: list[dict[str, Any]],
        source: str,
        fetched_at: str,
    ) -> int:
        rows = [
            (
                symbol,
                interval,
                point["timestamp"],
                point.get("open"),
                point.get("high"),
                point.get("low"),
                point["close"],
                point.get("adjusted_close"),
                point.get("volume"),
                source,
                fetched_at,
            )
            for point in points
            if point.get("timestamp") and point.get("close") is not None
        ]
        if not rows:
            return 0
        with self.connect() as connection:
            connection.executemany(
                """
                INSERT INTO market_bars(
                    symbol, interval, timestamp, open, high, low, close,
                    adjusted_close, volume, source, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, interval, timestamp) DO UPDATE SET
                    open = excluded.open,
                    high = excluded.high,
                    low = excluded.low,
                    close = excluded.close,
                    adjusted_close = excluded.adjusted_close,
                    volume = excluded.volume,
                    source = excluded.source,
                    fetched_at = excluded.fetched_at
                """,
                rows,
            )
        return len(rows)

    def get_market_bars(
        self, symbol: str, interval: str, limit: int = 1000
    ) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT symbol, interval, timestamp, open, high, low, close,
                    adjusted_close, volume, source, fetched_at
                FROM market_bars
                WHERE symbol = ? AND interval = ?
                ORDER BY timestamp DESC LIMIT ?
                """,
                (symbol, interval, limit),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def delete_market_bars(
        self, symbol: str, interval: str, timestamps: list[str]
    ) -> int:
        values = [str(value).strip() for value in timestamps if str(value).strip()]
        if not values:
            return 0
        placeholders = ",".join("?" for _ in values)
        with self.connect() as connection:
            cursor = connection.execute(
                f"""
                DELETE FROM market_bars
                WHERE symbol = ? AND interval = ?
                    AND timestamp IN ({placeholders})
                """,
                (symbol, interval, *values),
            )
        return cursor.rowcount

    def start_background_job(
        self,
        job_name: str,
        *,
        queue_job_id: str | None = None,
        worker_id: str | None = None,
    ) -> str:
        job_id = str(uuid4())
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO background_job_runs(
                    id, job_name, status, queue_job_id, worker_id, started_at
                )
                VALUES (?, ?, 'running', ?, ?, ?)
                """,
                (job_id, job_name, queue_job_id, worker_id, utc_now()),
            )
        return job_id

    def finish_background_job(
        self,
        job_id: str,
        status: str,
        summary: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE background_job_runs
                SET status = ?, summary_json = ?, error = ?, finished_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    json_dumps(summary) if summary is not None else None,
                    error,
                    utc_now(),
                    job_id,
                ),
            )

    def repair_interrupted_background_runs(self) -> dict[str, int]:
        """Close runs left in `running` when a previous process stopped."""

        finished_at = utc_now()
        repaired: dict[str, int] = {}
        with self.connect() as connection:
            background = connection.execute(
                """
                UPDATE background_job_runs
                SET status = 'failed',
                    error = COALESCE(error, 'process_restarted_before_completion'),
                    finished_at = COALESCE(finished_at, ?)
                WHERE status = 'running'
                """,
                (finished_at,),
            )
            repaired["background_job_runs"] = background.rowcount
            tushare = connection.execute(
                """
                UPDATE tushare_sync_runs
                SET status = 'failed',
                    error = COALESCE(error, 'process_restarted_before_completion'),
                    finished_at = COALESCE(finished_at, ?)
                WHERE status = 'running'
                """,
                (finished_at,),
            )
            repaired["tushare_sync_runs"] = tushare.rowcount
            strategy = connection.execute(
                """
                UPDATE strategy_screen_runs
                SET status = 'failed',
                    error = COALESCE(error, 'process_restarted_before_completion'),
                    finished_at = COALESCE(finished_at, ?)
                WHERE status = 'running'
                """,
                (finished_at,),
            )
            repaired["strategy_screen_runs"] = strategy.rowcount
        return repaired

    def repair_background_job_runs_from_queue(self) -> int:
        """Close audit rows whose durable queue lease is no longer active."""

        finished_at = utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE background_job_runs
                SET status = 'failed',
                    error = COALESCE(
                        error, 'queue_lease_no_longer_active'
                    ),
                    finished_at = COALESCE(finished_at, ?)
                WHERE status = 'running'
                    AND (
                        queue_job_id IS NULL
                        OR NOT EXISTS (
                            SELECT 1
                            FROM persistent_jobs AS jobs
                            WHERE CAST(jobs.id AS TEXT) =
                                  background_job_runs.queue_job_id
                                AND jobs.status = 'running'
                        )
                    )
                """,
                (finished_at,),
            )
        return int(cursor.rowcount)

    def prune_background_history(
        self,
        *,
        completed_retention_hours: int = 720,
        failed_retention_hours: int = 2160,
        data_health_retention_hours: int = 720,
    ) -> dict[str, int]:
        now = datetime.now(timezone.utc)
        completed_cutoff = (
            now - timedelta(hours=max(1, completed_retention_hours))
        ).isoformat()
        failed_cutoff = (
            now - timedelta(hours=max(1, failed_retention_hours))
        ).isoformat()
        health_cutoff = (
            now - timedelta(hours=max(1, data_health_retention_hours))
        ).isoformat()
        with self.connect() as connection:
            completed = connection.execute(
                """
                DELETE FROM background_job_runs
                WHERE status = 'completed'
                    AND finished_at IS NOT NULL
                    AND finished_at < ?
                """,
                (completed_cutoff,),
            )
            failed = connection.execute(
                """
                DELETE FROM background_job_runs
                WHERE status = 'failed'
                    AND finished_at IS NOT NULL
                    AND finished_at < ?
                """,
                (failed_cutoff,),
            )
            health = connection.execute(
                """
                DELETE FROM data_health_snapshots
                WHERE created_at < ?
                """,
                (health_cutoff,),
            )
        return {
            "completed_background_runs": int(completed.rowcount),
            "failed_background_runs": int(failed.rowcount),
            "data_health_snapshots": int(health.rowcount),
        }

    def latest_background_jobs(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM background_job_runs AS runs
                WHERE id = (
                    SELECT inner_runs.id
                    FROM background_job_runs AS inner_runs
                    WHERE inner_runs.job_name = runs.job_name
                    ORDER BY inner_runs.started_at DESC, inner_runs.rowid DESC
                    LIMIT 1
                )
                ORDER BY job_name
                """
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            raw_summary = item.pop("summary_json")
            item["summary"] = json.loads(raw_summary) if raw_summary else None
            items.append(item)
        return items

    def save_data_health_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        snapshot_id = str(uuid4())
        created_at = snapshot.get("created_at") or utc_now()
        payload = dict(snapshot)
        payload["id"] = snapshot_id
        payload["created_at"] = created_at
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO data_health_snapshots(id, status, payload_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    snapshot["status"],
                    json_dumps(payload),
                    created_at,
                ),
            )
        return payload

    def latest_data_health_snapshot(self) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT payload_json FROM data_health_snapshots
                ORDER BY created_at DESC, rowid DESC LIMIT 1
                """
            ).fetchone()
        return json.loads(row["payload_json"]) if row is not None else None

    def start_tushare_sync_run(
        self,
        *,
        job_scope: str,
        as_of_date: str | None,
        datasets: list[str],
    ) -> dict[str, Any]:
        run_id = str(uuid4())
        started_at = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO tushare_sync_runs(
                    id, job_scope, status, as_of_date, data_version,
                    datasets_json, summary_json, error, started_at, finished_at
                ) VALUES (?, ?, 'running', ?, NULL, ?, NULL, NULL, ?, NULL)
                """,
                (run_id, job_scope, as_of_date, json_dumps(datasets), started_at),
            )
        return self.get_tushare_sync_run(run_id)  # type: ignore[return-value]

    def finish_tushare_sync_run(
        self,
        run_id: str,
        *,
        status: str,
        data_version: str | None,
        summary: dict[str, Any] | None,
        error: str | None = None,
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE tushare_sync_runs
                SET status = ?, data_version = ?, summary_json = ?, error = ?,
                    finished_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    data_version,
                    json_dumps(summary) if summary is not None else None,
                    error,
                    utc_now(),
                    run_id,
                ),
            )
        return self.get_tushare_sync_run(run_id)

    def get_tushare_sync_run(self, run_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM tushare_sync_runs WHERE id = ?", (run_id,)
            ).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["datasets"] = json.loads(item.pop("datasets_json") or "[]")
        raw_summary = item.pop("summary_json")
        item["summary"] = json.loads(raw_summary) if raw_summary else None
        return item

    def save_tushare_dataset_snapshot(
        self,
        *,
        dataset: str,
        scope_key: str,
        as_of_date: str | None,
        report_period: str | None,
        source_updated_at: str | None,
        sync_run_id: str,
        data_version: str,
        data_status: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        snapshot_id = str(uuid4())
        created_at = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO tushare_dataset_snapshots(
                    id, dataset, scope_key, as_of_date, report_period,
                    source_updated_at, sync_run_id, data_version, data_status,
                    payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    dataset,
                    scope_key,
                    as_of_date,
                    report_period,
                    source_updated_at,
                    sync_run_id,
                    data_version,
                    data_status,
                    json_dumps(payload),
                    created_at,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM tushare_dataset_snapshots
                WHERE dataset = ? AND scope_key = ? AND data_version = ?
                """,
                (dataset, scope_key, data_version),
            ).fetchone()
        return self._tushare_snapshot_row(row)  # type: ignore[return-value]

    def latest_tushare_dataset_snapshot(
        self,
        dataset: str,
        scope_key: str,
        *,
        stable_only: bool = True,
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                f"""
                SELECT * FROM tushare_dataset_snapshots
                WHERE dataset = ? AND scope_key = ?
                    {"AND data_status = 'stable'" if stable_only else ""}
                ORDER BY created_at DESC, rowid DESC LIMIT 1
                """,
                (dataset, scope_key),
            ).fetchone()
        return self._tushare_snapshot_row(row)

    def list_latest_tushare_dataset_snapshots(
        self,
        dataset: str,
        *,
        data_status: str | None = None,
        include_payload: bool = True,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return the newest published snapshot for every scope in a dataset."""

        if data_status not in {None, "stable", "incomplete"}:
            raise ValueError("unsupported Tushare snapshot status")
        size = None if limit is None else max(1, min(int(limit), 20_000))
        selected = (
            "*"
            if include_payload
            else (
                "id, dataset, scope_key, as_of_date, report_period, "
                "source_updated_at, sync_run_id, data_version, data_status, created_at"
            )
        )
        status_clause = "AND data_status = ?" if data_status else ""
        parameters: list[Any] = [dataset]
        if data_status:
            parameters.append(data_status)
        limit_clause = " LIMIT ?" if size is not None else ""
        if size is not None:
            parameters.append(size)
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                WITH ranked AS (
                    SELECT {selected},
                           ROW_NUMBER() OVER (
                               PARTITION BY scope_key
                               ORDER BY created_at DESC, rowid DESC
                           ) AS snapshot_rank
                    FROM tushare_dataset_snapshots
                    WHERE dataset = ? {status_clause}
                )
                SELECT * FROM ranked
                WHERE snapshot_rank = 1
                ORDER BY created_at DESC, scope_key ASC{limit_clause}
                """,
                parameters,
            ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item.pop("snapshot_rank", None)
            if include_payload:
                item["payload"] = json.loads(item.pop("payload_json") or "{}")
            items.append(item)
        return items

    @staticmethod
    def _tushare_snapshot_row(
        row: Any | None,
    ) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json") or "{}")
        return item

    def upsert_strategy_definition(self, definition: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO strategy_definitions(
                    strategy_id, name, description, status, owner_type,
                    current_version, boundary, subscriptions_enabled,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(strategy_id) DO UPDATE SET
                    name = excluded.name,
                    description = excluded.description,
                    status = excluded.status,
                    owner_type = excluded.owner_type,
                    current_version = excluded.current_version,
                    boundary = excluded.boundary,
                    subscriptions_enabled = excluded.subscriptions_enabled,
                    updated_at = excluded.updated_at
                """,
                (
                    definition["strategy_id"],
                    definition["name"],
                    definition["description"],
                    definition.get("status", "active"),
                    definition.get("owner_type", "system"),
                    definition["current_version"],
                    definition["boundary"],
                    int(bool(definition.get("subscriptions_enabled", False))),
                    now,
                    now,
                ),
            )
        return self.get_strategy_definition(str(definition["strategy_id"]))  # type: ignore[return-value]

    def save_strategy_version(self, version: dict[str, Any]) -> dict[str, Any]:
        version_id = str(uuid4())
        published_at = version.get("published_at") or utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO strategy_versions(
                    id, strategy_id, version, method, rules_json,
                    formulas_json, change_notes, published_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    version_id,
                    version["strategy_id"],
                    version["version"],
                    version["method"],
                    json_dumps(version.get("rules") or []),
                    json_dumps(version.get("formulas") or {}),
                    version.get("change_notes") or "",
                    published_at,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM strategy_versions
                WHERE strategy_id = ? AND version = ?
                """,
                (version["strategy_id"], version["version"]),
            ).fetchone()
        return self._strategy_version_row(row)  # type: ignore[return-value]

    def save_strategy_parameter_version(
        self, parameter: dict[str, Any]
    ) -> dict[str, Any]:
        parameter_id = str(uuid4())
        created_at = parameter.get("created_at") or utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO strategy_parameter_versions(
                    id, strategy_id, strategy_version, parameter_version,
                    parameters_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    parameter_id,
                    parameter["strategy_id"],
                    parameter["strategy_version"],
                    parameter["parameter_version"],
                    json_dumps(parameter.get("parameters") or {}),
                    created_at,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM strategy_parameter_versions
                WHERE strategy_id = ? AND strategy_version = ?
                    AND parameter_version = ?
                """,
                (
                    parameter["strategy_id"],
                    parameter["strategy_version"],
                    parameter["parameter_version"],
                ),
            ).fetchone()
        return self._strategy_parameter_row(row)  # type: ignore[return-value]

    def list_strategy_definitions(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM strategy_definitions
                ORDER BY name ASC, strategy_id ASC
                """
            ).fetchall()
        return [self._strategy_definition_row(row) for row in rows]  # type: ignore[misc]

    def get_strategy_definition(self, strategy_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM strategy_definitions WHERE strategy_id = ?",
                (strategy_id,),
            ).fetchone()
        return self._strategy_definition_row(row)

    def get_strategy_version(
        self, strategy_id: str, version: str
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM strategy_versions
                WHERE strategy_id = ? AND version = ?
                """,
                (strategy_id, version),
            ).fetchone()
        return self._strategy_version_row(row)

    def get_strategy_parameter_version(
        self,
        strategy_id: str,
        strategy_version: str,
        parameter_version: str,
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM strategy_parameter_versions
                WHERE strategy_id = ? AND strategy_version = ?
                    AND parameter_version = ?
                """,
                (strategy_id, strategy_version, parameter_version),
            ).fetchone()
        return self._strategy_parameter_row(row)

    def start_strategy_screen_run(
        self,
        *,
        strategy_id: str,
        strategy_version: str,
        parameter_version: str,
        data_version: str,
        data_versions: dict[str, str],
        as_of_date: str | None,
        requested_count: int,
        run_scope: str = "symbol_batch",
        universe_count: int = 0,
        prefiltered_count: int = 0,
        coverage_ratio: float = 0.0,
        warnings: list[str] | None = None,
    ) -> dict[str, Any]:
        run_id = str(uuid4())
        started_at = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO strategy_screen_runs(
                    id, strategy_id, strategy_version, parameter_version,
                    data_version, data_versions_json, as_of_date, run_scope,
                    universe_count, prefiltered_count, coverage_ratio,
                    warnings_json, status, requested_count, started_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'running', ?, ?)
                """,
                (
                    run_id,
                    strategy_id,
                    strategy_version,
                    parameter_version,
                    data_version,
                    json_dumps(data_versions),
                    as_of_date,
                    run_scope,
                    max(0, int(universe_count)),
                    max(0, int(prefiltered_count)),
                    max(0.0, min(float(coverage_ratio), 1.0)),
                    json_dumps(warnings or []),
                    requested_count,
                    started_at,
                ),
            )
        return self.get_strategy_screen_run(run_id)  # type: ignore[return-value]

    def finish_strategy_screen_run(
        self,
        run_id: str,
        *,
        status: str,
        counts: dict[str, int],
        error: str | None = None,
        coverage_ratio: float | None = None,
        warnings: list[str] | None = None,
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE strategy_screen_runs
                SET status = ?, processed_count = ?, qualified_count = ?,
                    triggered_count = ?, incomplete_count = ?,
                    invalidated_count = ?, coverage_ratio = COALESCE(?, coverage_ratio),
                    warnings_json = COALESCE(?, warnings_json), error = ?, finished_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    counts.get("processed", 0),
                    counts.get("qualified", 0),
                    counts.get("triggered", 0),
                    counts.get("data_incomplete", 0),
                    counts.get("invalidated", 0),
                    (
                        max(0.0, min(float(coverage_ratio), 1.0))
                        if coverage_ratio is not None
                        else None
                    ),
                    json_dumps(warnings) if warnings is not None else None,
                    error,
                    utc_now(),
                    run_id,
                ),
            )
        return self.get_strategy_screen_run(run_id)

    def get_strategy_screen_run(self, run_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM strategy_screen_runs WHERE id = ?", (run_id,)
            ).fetchone()
        return self._strategy_run_row(row)

    def latest_strategy_screen_run(
        self,
        *,
        strategy_id: str,
        parameter_version: str | None = None,
        run_scope: str | None = None,
    ) -> dict[str, Any] | None:
        clauses = ["strategy_id = ?"]
        params: list[Any] = [strategy_id]
        if parameter_version is not None:
            clauses.append("parameter_version = ?")
            params.append(parameter_version)
        if run_scope is not None:
            clauses.append("run_scope = ?")
            params.append(run_scope)
        with self.connect() as connection:
            row = connection.execute(
                f"""
                SELECT * FROM strategy_screen_runs
                WHERE {" AND ".join(clauses)}
                ORDER BY started_at DESC, rowid DESC LIMIT 1
                """,
                tuple(params),
            ).fetchone()
        return self._strategy_run_row(row)

    def repair_unstable_strategy_prefilter_runs(self, strategy_id: str) -> int:
        """Quarantine prefilter runs produced without any usable market-cap row."""

        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE strategy_screen_runs
                SET status = 'failed',
                    error = COALESCE(error, 'unstable_universe_market_cap_snapshot'),
                    finished_at = COALESCE(finished_at, ?)
                WHERE strategy_id = ?
                    AND run_scope = 'universe_prefilter'
                    AND status <> 'failed'
                    AND universe_count > 0
                    AND prefiltered_count = 0
                    AND processed_count = universe_count
                    AND incomplete_count = universe_count
                """,
                (utc_now(), strategy_id),
            )
        return cursor.rowcount

    def save_strategy_candidate_snapshot(
        self,
        *,
        run_id: str,
        strategy_id: str,
        strategy_version: str,
        parameter_version: str,
        data_version: str,
        symbol: str,
        as_of_date: str,
        status: str,
        evaluation: dict[str, Any],
        previous_status: str | None,
    ) -> tuple[dict[str, Any], bool]:
        candidate_id = str(uuid4())
        created_at = utc_now()
        invalidated_at = created_at if status == "invalidated" else None
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO strategy_candidate_snapshots(
                    id, run_id, strategy_id, strategy_version,
                    parameter_version, data_version, symbol, as_of_date,
                    status, evaluation_status, previous_status, result_json,
                    created_at, invalidated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate_id,
                    run_id,
                    strategy_id,
                    strategy_version,
                    parameter_version,
                    data_version,
                    symbol,
                    as_of_date,
                    status,
                    evaluation["status"],
                    previous_status,
                    json_dumps(evaluation),
                    created_at,
                    invalidated_at,
                ),
            )
            created = cursor.rowcount > 0
            row = connection.execute(
                """
                SELECT * FROM strategy_candidate_snapshots
                WHERE strategy_id = ? AND strategy_version = ?
                    AND parameter_version = ? AND data_version = ?
                    AND symbol = ?
                """,
                (
                    strategy_id,
                    strategy_version,
                    parameter_version,
                    data_version,
                    symbol,
                ),
            ).fetchone()
            if created:
                rule_rows = []
                for rule in evaluation.get("rule_results") or []:
                    rule_rows.append(
                        (
                            str(uuid4()),
                            candidate_id,
                            rule["rule_id"],
                            rule["status"],
                            json_dumps(rule.get("actual_value")),
                            json_dumps(rule.get("threshold")),
                            rule.get("evidence_date"),
                            rule.get("report_period"),
                            rule["source"],
                            rule["formula_version"],
                            json_dumps(rule.get("limitations") or []),
                            created_at,
                        )
                    )
                connection.executemany(
                    """
                    INSERT INTO strategy_rule_results(
                        id, candidate_snapshot_id, rule_id, status,
                        actual_value_json, threshold_json, evidence_date,
                        report_period, source, formula_version,
                        limitations_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rule_rows,
                )
        candidate = self._strategy_candidate_row(row)  # type: ignore[assignment]
        candidate["rule_results"] = self.list_strategy_rule_results(
            str(candidate["id"])
        )
        return candidate, created

    def latest_strategy_candidate_snapshot(
        self,
        *,
        strategy_id: str,
        strategy_version: str,
        parameter_version: str,
        symbol: str,
        exclude_data_version: str | None = None,
    ) -> dict[str, Any] | None:
        exclude_clause = (
            "AND candidates.data_version <> ?"
            if exclude_data_version is not None
            else ""
        )
        params: list[Any] = [
            strategy_id,
            strategy_version,
            parameter_version,
            symbol,
        ]
        if exclude_data_version is not None:
            params.append(exclude_data_version)
        with self.connect() as connection:
            row = connection.execute(
                f"""
                SELECT candidates.*
                FROM strategy_candidate_snapshots AS candidates
                JOIN strategy_screen_runs AS runs ON runs.id = candidates.run_id
                WHERE candidates.strategy_id = ?
                    AND candidates.strategy_version = ?
                    AND candidates.parameter_version = ?
                    AND candidates.symbol = ?
                    AND runs.status <> 'failed'
                    {exclude_clause}
                ORDER BY candidates.created_at DESC, candidates.rowid DESC LIMIT 1
                """,
                params,
            ).fetchone()
        item = self._strategy_candidate_row(row)
        if item is not None:
            item["rule_results"] = self.list_strategy_rule_results(str(item["id"]))
        return item

    def list_strategy_candidate_snapshots(
        self,
        *,
        strategy_id: str,
        strategy_version: str,
        parameter_version: str,
        status: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        status_clause = "AND candidates.status = ?" if status is not None else ""
        params: list[Any] = [strategy_id, strategy_version, parameter_version]
        if status is not None:
            params.append(status)
        params.append(max(1, min(int(limit), 1000)))
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT candidates.*
                FROM strategy_candidate_snapshots AS candidates
                JOIN strategy_screen_runs AS runs ON runs.id = candidates.run_id
                WHERE candidates.strategy_id = ?
                    AND candidates.strategy_version = ?
                    AND candidates.parameter_version = ?
                    AND runs.status <> 'failed'
                    {status_clause}
                    AND candidates.id = (
                        SELECT current.id
                        FROM strategy_candidate_snapshots AS current
                        JOIN strategy_screen_runs AS current_runs
                            ON current_runs.id = current.run_id
                        WHERE current.strategy_id = candidates.strategy_id
                            AND current.strategy_version = candidates.strategy_version
                            AND current.parameter_version = candidates.parameter_version
                            AND current.symbol = candidates.symbol
                            AND current_runs.status <> 'failed'
                        ORDER BY current.created_at DESC, current.rowid DESC
                        LIMIT 1
                    )
                ORDER BY candidates.as_of_date DESC, candidates.symbol ASC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._strategy_candidate_row(row) for row in rows]  # type: ignore[misc]

    def latest_strategy_candidate_dates(
        self,
        *,
        strategy_id: str,
        strategy_version: str,
        parameter_version: str,
    ) -> dict[str, str]:
        states = self.latest_strategy_candidate_states(
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            parameter_version=parameter_version,
        )
        return {symbol: str(state["as_of_date"]) for symbol, state in states.items()}

    def latest_strategy_candidate_states(
        self,
        *,
        strategy_id: str,
        strategy_version: str,
        parameter_version: str,
    ) -> dict[str, dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT candidates.symbol, candidates.as_of_date, candidates.status,
                       candidates.result_json
                FROM strategy_candidate_snapshots AS candidates
                JOIN strategy_screen_runs AS runs ON runs.id = candidates.run_id
                WHERE candidates.strategy_id = ?
                    AND candidates.strategy_version = ?
                    AND candidates.parameter_version = ?
                    AND runs.status <> 'failed'
                    AND candidates.id = (
                        SELECT current.id
                        FROM strategy_candidate_snapshots AS current
                        JOIN strategy_screen_runs AS current_runs
                            ON current_runs.id = current.run_id
                        WHERE current.strategy_id = candidates.strategy_id
                            AND current.strategy_version = candidates.strategy_version
                            AND current.parameter_version = candidates.parameter_version
                            AND current.symbol = candidates.symbol
                            AND current_runs.status <> 'failed'
                        ORDER BY current.created_at DESC, current.rowid DESC
                        LIMIT 1
                    )
                """,
                (strategy_id, strategy_version, parameter_version),
            ).fetchall()
        return {
            str(row["symbol"]): {
                "as_of_date": str(row["as_of_date"]),
                "status": str(row["status"]),
                "result": json.loads(str(row["result_json"] or "{}")),
            }
            for row in rows
        }

    def strategy_candidate_summary(
        self,
        *,
        strategy_id: str,
        strategy_version: str,
        parameter_version: str,
        minimum_as_of_date: str | None = None,
    ) -> dict[str, int]:
        date_clause = "AND candidates.as_of_date >= ?" if minimum_as_of_date else ""
        params: list[Any] = [strategy_id, strategy_version, parameter_version]
        if minimum_as_of_date:
            params.append(minimum_as_of_date)
        with self.connect() as connection:
            row = connection.execute(
                f"""
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN candidates.status = 'qualified' THEN 1 ELSE 0 END) AS qualified,
                    SUM(CASE WHEN candidates.status = 'triggered' THEN 1 ELSE 0 END) AS triggered,
                    SUM(CASE WHEN candidates.status = 'not_qualified' THEN 1 ELSE 0 END) AS not_qualified,
                    SUM(CASE WHEN candidates.status = 'data_incomplete' THEN 1 ELSE 0 END) AS data_incomplete,
                    SUM(CASE WHEN candidates.status = 'invalidated' THEN 1 ELSE 0 END) AS invalidated
                FROM strategy_candidate_snapshots AS candidates
                JOIN strategy_screen_runs AS runs ON runs.id = candidates.run_id
                WHERE candidates.strategy_id = ?
                    AND candidates.strategy_version = ?
                    AND candidates.parameter_version = ?
                    AND runs.status <> 'failed'
                    {date_clause}
                    AND candidates.id = (
                        SELECT current.id
                        FROM strategy_candidate_snapshots AS current
                        JOIN strategy_screen_runs AS current_runs
                            ON current_runs.id = current.run_id
                        WHERE current.strategy_id = candidates.strategy_id
                            AND current.strategy_version = candidates.strategy_version
                            AND current.parameter_version = candidates.parameter_version
                            AND current.symbol = candidates.symbol
                            AND current_runs.status <> 'failed'
                        ORDER BY current.created_at DESC, current.rowid DESC
                        LIMIT 1
                    )
                """,
                tuple(params),
            ).fetchone()
        return {
            key: int((row or {})[key] or 0)
            for key in (
                "total",
                "qualified",
                "triggered",
                "not_qualified",
                "data_incomplete",
                "invalidated",
            )
        }

    def list_strategy_rule_results(
        self, candidate_snapshot_id: str
    ) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM strategy_rule_results
                WHERE candidate_snapshot_id = ?
                ORDER BY rowid ASC
                """,
                (candidate_snapshot_id,),
            ).fetchall()
        return [self._strategy_rule_row(row) for row in rows]  # type: ignore[misc]

    def save_strategy_trigger_event(
        self, event: dict[str, Any]
    ) -> tuple[dict[str, Any], bool]:
        event_id = str(uuid4())
        created_at = utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO strategy_trigger_events(
                    id, candidate_snapshot_id, strategy_id, strategy_version,
                    parameter_version, data_version, symbol, rule_id,
                    evidence_date, evidence_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    event["candidate_snapshot_id"],
                    event["strategy_id"],
                    event["strategy_version"],
                    event["parameter_version"],
                    event["data_version"],
                    event["symbol"],
                    event["rule_id"],
                    event["evidence_date"],
                    json_dumps(event.get("evidence") or {}),
                    created_at,
                ),
            )
            created = cursor.rowcount > 0
            row = connection.execute(
                """
                SELECT * FROM strategy_trigger_events
                WHERE strategy_id = ? AND strategy_version = ?
                    AND parameter_version = ? AND symbol = ?
                    AND rule_id = ? AND evidence_date = ?
                """,
                (
                    event["strategy_id"],
                    event["strategy_version"],
                    event["parameter_version"],
                    event["symbol"],
                    event["rule_id"],
                    event["evidence_date"],
                ),
            ).fetchone()
        return self._strategy_trigger_row(row), created  # type: ignore[return-value]

    def list_strategy_trigger_events(
        self,
        *,
        strategy_id: str,
        strategy_version: str,
        parameter_version: str,
        symbol: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        symbol_clause = "AND symbol = ?" if symbol is not None else ""
        params: list[Any] = [strategy_id, strategy_version, parameter_version]
        if symbol is not None:
            params.append(symbol)
        params.append(max(1, min(int(limit), 1000)))
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM strategy_trigger_events
                WHERE strategy_id = ? AND strategy_version = ?
                    AND parameter_version = ? {symbol_clause}
                ORDER BY evidence_date DESC, created_at DESC, rowid DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._strategy_trigger_row(row) for row in rows]  # type: ignore[misc]

    @staticmethod
    def _strategy_definition_row(
        row: Any | None,
    ) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        item["subscriptions_enabled"] = bool(item["subscriptions_enabled"])
        return item

    @staticmethod
    def _strategy_version_row(
        row: Any | None,
    ) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        item["rules"] = json.loads(item.pop("rules_json") or "[]")
        item["formulas"] = json.loads(item.pop("formulas_json") or "{}")
        return item

    @staticmethod
    def _strategy_parameter_row(
        row: Any | None,
    ) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        item["parameters"] = json.loads(item.pop("parameters_json") or "{}")
        return item

    @staticmethod
    def _strategy_run_row(row: Any | None) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        item["data_versions"] = json.loads(item.pop("data_versions_json") or "{}")
        item["warnings"] = json.loads(item.pop("warnings_json") or "[]")
        return item

    @staticmethod
    def _strategy_candidate_row(
        row: Any | None,
    ) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        item["result"] = json.loads(item.pop("result_json") or "{}")
        return item

    @staticmethod
    def _strategy_rule_row(row: Any | None) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        item["actual_value"] = json.loads(item.pop("actual_value_json") or "null")
        item["threshold"] = json.loads(item.pop("threshold_json") or "{}")
        item["limitations"] = json.loads(item.pop("limitations_json") or "[]")
        return item

    @staticmethod
    def _strategy_trigger_row(
        row: Any | None,
    ) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        item["evidence"] = json.loads(item.pop("evidence_json") or "{}")
        return item

    def upsert_news_items(self, items: list[dict[str, Any]]) -> int:
        rows = []
        for item in items:
            rows.append(
                (
                    item.get("id") or str(uuid4()),
                    item["symbol"],
                    item["category"],
                    item["title"],
                    item.get("summary"),
                    item["source"],
                    item["url"],
                    item.get("published_at"),
                    item.get("engagement"),
                    item.get("fetched_at") or utc_now(),
                )
            )
        if not rows:
            return 0
        with self.connect() as connection:
            for row in rows:
                (
                    item_id,
                    symbol,
                    category,
                    title,
                    summary,
                    source,
                    url,
                    published_at,
                    engagement,
                    fetched_at,
                ) = row
                update_parameters = (
                    symbol,
                    category,
                    title,
                    summary,
                    source,
                    url,
                    published_at,
                    engagement,
                    fetched_at,
                    item_id,
                    symbol,
                    url,
                )
                updated = connection.execute(
                    """
                    UPDATE news_items
                    SET symbol = ?, category = ?, title = ?, summary = ?,
                        source = ?, url = ?, published_at = ?, engagement = ?,
                        fetched_at = ?
                    WHERE id = ? OR (symbol = ? AND url = ?)
                    """,
                    update_parameters,
                )
                if updated.rowcount:
                    continue
                inserted = connection.execute(
                    """
                    INSERT INTO news_items(
                        id, symbol, category, title, summary, source, url,
                        published_at, engagement, fetched_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT DO NOTHING
                    """,
                    row,
                )
                if not inserted.rowcount:
                    # A concurrent refresh may have inserted the same URL after
                    # the first UPDATE. Re-apply the fresh payload without
                    # changing the existing stable row id.
                    connection.execute(
                        """
                        UPDATE news_items
                        SET symbol = ?, category = ?, title = ?, summary = ?,
                            source = ?, url = ?, published_at = ?, engagement = ?,
                            fetched_at = ?
                        WHERE id = ? OR (symbol = ? AND url = ?)
                        """,
                        update_parameters,
                    )
        return len(rows)

    def list_news(
        self,
        symbol: str | None = None,
        limit: int = 30,
        categories: tuple[str, ...] | None = None,
    ) -> list[dict[str, Any]]:
        clauses = []
        parameters: list[Any] = []
        if symbol:
            clauses.append("symbol = ?")
            parameters.append(symbol)
        if categories:
            placeholders = ",".join("?" for _ in categories)
            clauses.append(f"category IN ({placeholders})")
            parameters.extend(categories)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        parameters.append(limit)
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM news_items{where}
                ORDER BY COALESCE(published_at, fetched_at) DESC LIMIT ?
                """,
                parameters,
            ).fetchall()
        return [dict(row) for row in rows]

    def save_sentiment_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        snapshot_id = str(uuid4())
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO sentiment_snapshots(
                    id, symbol, score, band, confidence, sample_size,
                    positive_count, negative_count, neutral_count, method,
                    evidence_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    snapshot["symbol"],
                    snapshot["score"],
                    snapshot["band"],
                    snapshot["confidence"],
                    snapshot["sample_size"],
                    snapshot["positive_count"],
                    snapshot["negative_count"],
                    snapshot["neutral_count"],
                    snapshot["method"],
                    json_dumps(snapshot.get("evidence", {})),
                    snapshot.get("created_at") or utc_now(),
                ),
            )
        return self.latest_sentiment(snapshot["symbol"])  # type: ignore[return-value]

    def latest_sentiment(self, symbol: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM sentiment_snapshots
                WHERE symbol = ? ORDER BY created_at DESC LIMIT 1
                """,
                (symbol,),
            ).fetchone()
        item = self._row(row)
        if item is not None:
            item["evidence"] = json.loads(item.pop("evidence_json"))
        return item

    def save_valuation_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        snapshot_id = str(uuid4())
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO valuation_snapshots(
                    id, symbol, name, currency, price, previous_close, pct_change,
                    turnover_rate_pct, pe_ttm, pe_dynamic, pe_static, pb,
                    float_market_cap, total_market_cap, market_timestamp, source,
                    source_url, field_mapping, warnings_json, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, source, market_timestamp) DO UPDATE SET
                    name = excluded.name,
                    currency = excluded.currency,
                    price = excluded.price,
                    previous_close = excluded.previous_close,
                    pct_change = excluded.pct_change,
                    turnover_rate_pct = excluded.turnover_rate_pct,
                    pe_ttm = excluded.pe_ttm,
                    pe_dynamic = excluded.pe_dynamic,
                    pe_static = excluded.pe_static,
                    pb = excluded.pb,
                    float_market_cap = excluded.float_market_cap,
                    total_market_cap = excluded.total_market_cap,
                    source_url = excluded.source_url,
                    field_mapping = excluded.field_mapping,
                    warnings_json = excluded.warnings_json,
                    fetched_at = excluded.fetched_at
                """,
                (
                    snapshot_id,
                    snapshot["symbol"],
                    snapshot["name"],
                    snapshot.get("currency") or "CNY",
                    snapshot.get("price"),
                    snapshot.get("previous_close"),
                    snapshot.get("pct_change"),
                    snapshot.get("turnover_rate_pct"),
                    snapshot.get("pe_ttm"),
                    snapshot.get("pe_dynamic"),
                    snapshot.get("pe_static"),
                    snapshot.get("pb"),
                    snapshot.get("float_market_cap"),
                    snapshot.get("total_market_cap"),
                    snapshot["market_timestamp"],
                    snapshot["source"],
                    snapshot["source_url"],
                    snapshot.get("field_mapping") or "unknown",
                    json_dumps(snapshot.get("warnings", [])),
                    snapshot.get("fetched_at") or utc_now(),
                ),
            )
        return self.latest_valuation_snapshot(snapshot["symbol"])  # type: ignore[return-value]

    def latest_valuation_snapshot(self, symbol: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM valuation_snapshots
                WHERE symbol = ?
                ORDER BY market_timestamp DESC, fetched_at DESC LIMIT 1
                """,
                (symbol,),
            ).fetchone()
        item = self._row(row)
        if item is not None:
            item["warnings"] = json.loads(item.pop("warnings_json"))
        return item

    def upsert_financial_periods(self, periods: list[dict[str, Any]]) -> int:
        rows = []
        for item in periods:
            rows.append(
                (
                    item["symbol"],
                    item["report_date"],
                    item["report_type"],
                    item.get("report_date_name") or item["report_date"],
                    item.get("notice_date"),
                    item.get("name") or item["symbol"],
                    item.get("currency") or "CNY",
                    item.get("eps_basic"),
                    item.get("eps_diluted"),
                    item.get("book_value_per_share"),
                    item.get("revenue"),
                    item.get("revenue_yoy_pct"),
                    item.get("parent_net_profit"),
                    item.get("net_profit_yoy_pct"),
                    item.get("roe_weighted_pct"),
                    item.get("gross_margin_pct"),
                    item.get("net_margin_pct"),
                    item.get("debt_asset_ratio_pct"),
                    item.get("operating_cashflow"),
                    item.get("operating_cashflow_per_share"),
                    item.get("total_assets"),
                    item.get("total_liabilities"),
                    item.get("total_equity"),
                    item.get("period_basis") or "year_to_date_cumulative",
                    item["source"],
                    item["source_url"],
                    json_dumps(item.get("warnings", [])),
                    item.get("fetched_at") or utc_now(),
                )
            )
        if not rows:
            return 0
        with self.connect() as connection:
            connection.executemany(
                """
                INSERT INTO financial_periods(
                    symbol, report_date, report_type, report_date_name, notice_date,
                    name, currency, eps_basic, eps_diluted, book_value_per_share, revenue,
                    revenue_yoy_pct, parent_net_profit, net_profit_yoy_pct,
                    roe_weighted_pct, gross_margin_pct, net_margin_pct,
                    debt_asset_ratio_pct, operating_cashflow,
                    operating_cashflow_per_share, total_assets, total_liabilities, total_equity,
                    period_basis, source, source_url, warnings_json, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, report_date, report_type) DO UPDATE SET
                    report_date_name = excluded.report_date_name,
                    notice_date = excluded.notice_date,
                    name = excluded.name,
                    currency = excluded.currency,
                    eps_basic = excluded.eps_basic,
                    eps_diluted = excluded.eps_diluted,
                    book_value_per_share = excluded.book_value_per_share,
                    revenue = excluded.revenue,
                    revenue_yoy_pct = excluded.revenue_yoy_pct,
                    parent_net_profit = excluded.parent_net_profit,
                    net_profit_yoy_pct = excluded.net_profit_yoy_pct,
                    roe_weighted_pct = excluded.roe_weighted_pct,
                    gross_margin_pct = excluded.gross_margin_pct,
                    net_margin_pct = excluded.net_margin_pct,
                    debt_asset_ratio_pct = excluded.debt_asset_ratio_pct,
                    operating_cashflow = excluded.operating_cashflow,
                    operating_cashflow_per_share = excluded.operating_cashflow_per_share,
                    total_assets = excluded.total_assets,
                    total_liabilities = excluded.total_liabilities,
                    total_equity = excluded.total_equity,
                    period_basis = excluded.period_basis,
                    source = excluded.source,
                    source_url = excluded.source_url,
                    warnings_json = excluded.warnings_json,
                    fetched_at = excluded.fetched_at
                """,
                rows,
            )
        return len(rows)

    def list_financial_periods(
        self, symbol: str, limit: int = 8
    ) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM financial_periods
                WHERE symbol = ?
                ORDER BY report_date DESC LIMIT ?
                """,
                (symbol, limit),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["warnings"] = json.loads(item.pop("warnings_json"))
            items.append(item)
        return items

    def save_earnings_quality_snapshot(
        self, snapshot: dict[str, Any], fingerprint: str
    ) -> dict[str, Any]:
        snapshot_id = str(uuid4())
        created_at = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO earnings_quality_snapshots(
                    id, symbol, report_date, method, fingerprint,
                    payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, report_date, method) DO UPDATE SET
                    fingerprint = excluded.fingerprint,
                    payload_json = excluded.payload_json,
                    created_at = excluded.created_at
                """,
                (
                    snapshot_id,
                    snapshot["symbol"],
                    snapshot["latest_report"]["report_date"],
                    snapshot["method"],
                    fingerprint,
                    json_dumps(snapshot),
                    created_at,
                ),
            )
        return self.latest_earnings_quality_snapshot(snapshot["symbol"])  # type: ignore[return-value]

    def latest_earnings_quality_snapshot(self, symbol: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM earnings_quality_snapshots
                WHERE symbol = ?
                ORDER BY report_date DESC, created_at DESC, rowid DESC LIMIT 1
                """,
                (symbol,),
            ).fetchone()
        item = self._row(row)
        if item is not None:
            item["payload"] = json.loads(item.pop("payload_json") or "{}")
        return item

    def upsert_financial_statement_details(
        self, statements: list[dict[str, Any]]
    ) -> int:
        rows = []
        for item in statements:
            rows.append(
                (
                    item["symbol"],
                    item["report_date"],
                    item["report_type"],
                    item.get("report_date_name") or item["report_date"],
                    item.get("notice_date"),
                    item.get("name") or item["symbol"],
                    item.get("currency") or "CNY",
                    item.get("fiscal_period") or "UNKNOWN",
                    item.get("period_basis") or "year_to_date_cumulative",
                    item["statement_type"],
                    json_dumps(item.get("fields") or {}),
                    item["source"],
                    item["source_url"],
                    json_dumps(item.get("warnings") or []),
                    item.get("fetched_at") or utc_now(),
                )
            )
        if not rows:
            return 0
        with self.connect() as connection:
            connection.executemany(
                """
                INSERT INTO financial_statement_details(
                    symbol, report_date, report_type, report_date_name, notice_date,
                    name, currency, fiscal_period, period_basis, statement_type,
                    fields_json, source, source_url, warnings_json, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, report_date, report_type, statement_type) DO UPDATE SET
                    report_date_name = excluded.report_date_name,
                    notice_date = excluded.notice_date,
                    name = excluded.name,
                    currency = excluded.currency,
                    fiscal_period = excluded.fiscal_period,
                    period_basis = excluded.period_basis,
                    fields_json = excluded.fields_json,
                    source = excluded.source,
                    source_url = excluded.source_url,
                    warnings_json = excluded.warnings_json,
                    fetched_at = excluded.fetched_at
                """,
                rows,
            )
        return len(rows)

    def list_financial_statement_details(
        self, symbol: str, limit: int = 36
    ) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM financial_statement_details
                WHERE symbol = ?
                ORDER BY report_date DESC,
                    CASE statement_type
                        WHEN 'income' THEN 1
                        WHEN 'balance' THEN 2
                        ELSE 3
                    END
                LIMIT ?
                """,
                (symbol, limit),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["fields"] = json.loads(item.pop("fields_json") or "{}")
            item["warnings"] = json.loads(item.pop("warnings_json") or "[]")
            items.append(item)
        return items

    def save_financial_driver_snapshot(
        self, snapshot: dict[str, Any], fingerprint: str
    ) -> dict[str, Any]:
        snapshot_id = str(uuid4())
        created_at = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO financial_driver_snapshots(
                    id, symbol, report_date, method, fingerprint,
                    payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, report_date, method) DO UPDATE SET
                    fingerprint = excluded.fingerprint,
                    payload_json = excluded.payload_json,
                    created_at = excluded.created_at
                """,
                (
                    snapshot_id,
                    snapshot["symbol"],
                    snapshot["latest_period"]["report_date"],
                    snapshot["method"],
                    fingerprint,
                    json_dumps(snapshot),
                    created_at,
                ),
            )
        return self.latest_financial_driver_snapshot(snapshot["symbol"])  # type: ignore[return-value]

    def latest_financial_driver_snapshot(self, symbol: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM financial_driver_snapshots
                WHERE symbol = ?
                ORDER BY report_date DESC, created_at DESC, rowid DESC LIMIT 1
                """,
                (symbol,),
            ).fetchone()
        item = self._row(row)
        if item is not None:
            item["payload"] = json.loads(item.pop("payload_json") or "{}")
        return item

    def upsert_filing_document(self, document: dict[str, Any]) -> dict[str, Any]:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO filing_documents(
                    symbol, article_code, title, document_type, report_period,
                    notice_date, published_at, content_text, attach_url,
                    content_hash, source, source_url, warnings_json, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, article_code) DO UPDATE SET
                    title = excluded.title,
                    document_type = excluded.document_type,
                    report_period = excluded.report_period,
                    notice_date = excluded.notice_date,
                    published_at = excluded.published_at,
                    content_text = excluded.content_text,
                    attach_url = excluded.attach_url,
                    content_hash = excluded.content_hash,
                    source = excluded.source,
                    source_url = excluded.source_url,
                    warnings_json = excluded.warnings_json,
                    fetched_at = excluded.fetched_at
                """,
                (
                    document["symbol"],
                    document["article_code"],
                    document["title"],
                    document["document_type"],
                    document.get("report_period"),
                    document.get("notice_date"),
                    document.get("published_at"),
                    document.get("content_text") or "",
                    document.get("attach_url"),
                    document["content_hash"],
                    document.get("source") or "company_filing",
                    document["source_url"],
                    json_dumps(document.get("warnings") or []),
                    document.get("fetched_at") or utc_now(),
                ),
            )
        return self.get_filing_document(document["symbol"], document["article_code"])  # type: ignore[return-value]

    def get_filing_document(
        self, symbol: str, article_code: str
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM filing_documents
                WHERE symbol = ? AND article_code = ?
                """,
                (symbol, article_code),
            ).fetchone()
        item = self._row(row)
        if item is not None:
            item["warnings"] = json.loads(item.pop("warnings_json") or "[]")
        return item

    def list_filing_documents(
        self,
        symbol: str,
        limit: int = 6,
        *,
        include_content: bool = False,
    ) -> list[dict[str, Any]]:
        fields = (
            "*"
            if include_content
            else """
            symbol, article_code, title, document_type, report_period,
            notice_date, published_at, attach_url, content_hash, source,
            source_url, warnings_json, fetched_at,
            LENGTH(content_text) AS content_chars
        """
        )
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT {fields} FROM filing_documents
                WHERE symbol = ?
                ORDER BY COALESCE(report_period, notice_date, published_at) DESC,
                    published_at DESC
                LIMIT ?
                """,
                (symbol, limit),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["warnings"] = json.loads(item.pop("warnings_json") or "[]")
            items.append(item)
        return items

    def save_filing_evidence_snapshot(
        self, snapshot: dict[str, Any], fingerprint: str
    ) -> dict[str, Any]:
        snapshot_id = str(uuid4())
        created_at = utc_now()
        document = snapshot.get("document") or {}
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO filing_evidence_snapshots(
                    id, symbol, article_code, report_period, method,
                    fingerprint, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, article_code, method) DO UPDATE SET
                    report_period = excluded.report_period,
                    fingerprint = excluded.fingerprint,
                    payload_json = excluded.payload_json,
                    created_at = excluded.created_at
                """,
                (
                    snapshot_id,
                    snapshot["symbol"],
                    document["article_code"],
                    document.get("report_period"),
                    snapshot["method"],
                    fingerprint,
                    json_dumps(snapshot),
                    created_at,
                ),
            )
        return self.latest_filing_evidence_snapshot(
            snapshot["symbol"], article_code=document["article_code"]
        )  # type: ignore[return-value]

    def latest_filing_evidence_snapshot(
        self,
        symbol: str,
        *,
        report_period: str | None = None,
        article_code: str | None = None,
    ) -> dict[str, Any] | None:
        clauses = ["symbol = ?"]
        params: list[Any] = [symbol]
        if report_period is not None:
            clauses.append("report_period = ?")
            params.append(report_period)
        if article_code is not None:
            clauses.append("article_code = ?")
            params.append(article_code)
        with self.connect() as connection:
            row = connection.execute(
                f"""
                SELECT * FROM filing_evidence_snapshots
                WHERE {" AND ".join(clauses)}
                ORDER BY COALESCE(report_period, created_at) DESC,
                    created_at DESC, rowid DESC LIMIT 1
                """,
                params,
            ).fetchone()
        item = self._row(row)
        if item is not None:
            item["payload"] = json.loads(item.pop("payload_json") or "{}")
        return item

    def upsert_business_segment_rows(self, rows: list[dict[str, Any]]) -> int:
        values = [
            (
                item["symbol"],
                item["report_date"],
                item["classification"],
                item["item_name"],
                item.get("revenue"),
                item.get("revenue_share_pct"),
                item.get("cost"),
                item.get("cost_share_pct"),
                item.get("gross_profit"),
                item.get("gross_profit_share_pct"),
                item.get("gross_margin_pct"),
                item.get("source") or "business_composition",
                item["source_url"],
                item.get("fetched_at") or utc_now(),
            )
            for item in rows
        ]
        if not values:
            return 0
        with self.connect() as connection:
            connection.executemany(
                """
                INSERT INTO business_segment_rows(
                    symbol, report_date, classification, item_name,
                    revenue, revenue_share_pct, cost, cost_share_pct,
                    gross_profit, gross_profit_share_pct, gross_margin_pct,
                    source, source_url, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, report_date, classification, item_name)
                DO UPDATE SET
                    revenue = excluded.revenue,
                    revenue_share_pct = excluded.revenue_share_pct,
                    cost = excluded.cost,
                    cost_share_pct = excluded.cost_share_pct,
                    gross_profit = excluded.gross_profit,
                    gross_profit_share_pct = excluded.gross_profit_share_pct,
                    gross_margin_pct = excluded.gross_margin_pct,
                    source = excluded.source,
                    source_url = excluded.source_url,
                    fetched_at = excluded.fetched_at
                """,
                values,
            )
        return len(values)

    def list_business_segment_rows(
        self, symbol: str, limit: int = 500
    ) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM business_segment_rows
                WHERE symbol = ?
                ORDER BY report_date DESC,
                    CASE classification
                        WHEN 'product' THEN 1
                        WHEN 'region' THEN 2
                        ELSE 3
                    END,
                    revenue_share_pct DESC,
                    item_name ASC
                LIMIT ?
                """,
                (symbol, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def save_business_structure_snapshot(
        self, snapshot: dict[str, Any], fingerprint: str
    ) -> dict[str, Any]:
        snapshot_id = str(uuid4())
        created_at = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO business_structure_snapshots(
                    id, symbol, anchor_report_date, method, fingerprint,
                    payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, anchor_report_date, method) DO UPDATE SET
                    fingerprint = excluded.fingerprint,
                    payload_json = excluded.payload_json,
                    created_at = excluded.created_at
                """,
                (
                    snapshot_id,
                    snapshot["symbol"],
                    snapshot["anchor_report_date"],
                    snapshot["method"],
                    fingerprint,
                    json_dumps(snapshot),
                    created_at,
                ),
            )
        return self.latest_business_structure_snapshot(snapshot["symbol"])  # type: ignore[return-value]

    def latest_business_structure_snapshot(self, symbol: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM business_structure_snapshots
                WHERE symbol = ?
                ORDER BY anchor_report_date DESC, created_at DESC, rowid DESC
                LIMIT 1
                """,
                (symbol,),
            ).fetchone()
        item = self._row(row)
        if item is not None:
            item["payload"] = json.loads(item.pop("payload_json") or "{}")
        return item

    def save_peer_operating_snapshot(
        self, snapshot: dict[str, Any], fingerprint: str
    ) -> dict[str, Any]:
        snapshot_id = str(uuid4())
        created_at = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO peer_operating_snapshots(
                    id, symbol, anchor_report_date, method, fingerprint,
                    payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, fingerprint) DO UPDATE SET
                    anchor_report_date = excluded.anchor_report_date,
                    payload_json = excluded.payload_json,
                    created_at = excluded.created_at
                """,
                (
                    snapshot_id,
                    snapshot["symbol"],
                    snapshot["anchor_report_date"],
                    snapshot["method"],
                    fingerprint,
                    json_dumps(snapshot),
                    created_at,
                ),
            )
        return self.latest_peer_operating_snapshot(snapshot["symbol"])  # type: ignore[return-value]

    def latest_peer_operating_snapshot(self, symbol: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM peer_operating_snapshots
                WHERE symbol = ?
                ORDER BY anchor_report_date DESC, created_at DESC, rowid DESC
                LIMIT 1
                """,
                (symbol,),
            ).fetchone()
        item = self._row(row)
        if item is not None:
            item["payload"] = json.loads(item.pop("payload_json") or "{}")
        return item

    def save_shareholder_structure_snapshot(
        self, snapshot: dict[str, Any], fingerprint: str
    ) -> dict[str, Any]:
        snapshot_id = str(uuid4())
        created_at = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO shareholder_structure_snapshots(
                    id, symbol, name, holder_count_as_of, announced_at,
                    holder_count, previous_holder_count, holder_count_change,
                    change_pct, average_holding, average_market_cap,
                    interval_price_change_pct, top10_report_date, top10_ratio,
                    top3_ratio, top_holders_json, method, fingerprint,
                    payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, holder_count_as_of, method) DO UPDATE SET
                    name = excluded.name,
                    announced_at = excluded.announced_at,
                    holder_count = excluded.holder_count,
                    previous_holder_count = excluded.previous_holder_count,
                    holder_count_change = excluded.holder_count_change,
                    change_pct = excluded.change_pct,
                    average_holding = excluded.average_holding,
                    average_market_cap = excluded.average_market_cap,
                    interval_price_change_pct = excluded.interval_price_change_pct,
                    top10_report_date = excluded.top10_report_date,
                    top10_ratio = excluded.top10_ratio,
                    top3_ratio = excluded.top3_ratio,
                    top_holders_json = excluded.top_holders_json,
                    fingerprint = excluded.fingerprint,
                    payload_json = excluded.payload_json,
                    created_at = excluded.created_at
                """,
                (
                    snapshot_id,
                    snapshot["symbol"],
                    snapshot["name"],
                    snapshot["holder_count_as_of"],
                    snapshot.get("announced_at"),
                    snapshot.get("holder_count"),
                    snapshot.get("previous_holder_count"),
                    snapshot.get("holder_count_change"),
                    snapshot.get("holder_count_change_pct"),
                    snapshot.get("average_holding"),
                    snapshot.get("average_market_cap"),
                    snapshot.get("interval_price_change_pct"),
                    snapshot.get("top10_report_date"),
                    snapshot.get("top10_ratio_pct"),
                    snapshot.get("top3_ratio_pct"),
                    json_dumps(snapshot.get("top_holders") or []),
                    snapshot["method"],
                    fingerprint,
                    json_dumps(snapshot),
                    created_at,
                ),
            )
        return self.latest_shareholder_structure_snapshot(snapshot["symbol"])  # type: ignore[return-value]

    def latest_shareholder_structure_snapshot(
        self, symbol: str
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM shareholder_structure_snapshots
                WHERE symbol = ?
                ORDER BY holder_count_as_of DESC, created_at DESC, rowid DESC
                LIMIT 1
                """,
                (symbol,),
            ).fetchone()
        item = self._row(row)
        if item is not None:
            item["top_holders"] = json.loads(item.pop("top_holders_json") or "[]")
            item["payload"] = json.loads(item.pop("payload_json") or "{}")
        return item

    def save_analyst_expectation_snapshot(
        self, snapshot: dict[str, Any], fingerprint: str
    ) -> dict[str, Any]:
        snapshot_id = str(uuid4())
        created_at = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO analyst_expectation_snapshots(
                    id, symbol, name, as_of_date, latest_report_date,
                    rating_organization_count, method, fingerprint,
                    payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, fingerprint) DO UPDATE SET
                    name = excluded.name,
                    as_of_date = excluded.as_of_date,
                    latest_report_date = excluded.latest_report_date,
                    rating_organization_count = excluded.rating_organization_count,
                    payload_json = excluded.payload_json,
                    created_at = excluded.created_at
                """,
                (
                    snapshot_id,
                    snapshot["symbol"],
                    snapshot["name"],
                    snapshot["as_of_date"],
                    snapshot.get("latest_report_date"),
                    snapshot.get("rating_organization_count"),
                    snapshot["method"],
                    fingerprint,
                    json_dumps(snapshot),
                    created_at,
                ),
            )
        return self.latest_analyst_expectation_snapshot(snapshot["symbol"])  # type: ignore[return-value]

    def save_event_timeline_snapshot(
        self, snapshot: dict[str, Any], fingerprint: str
    ) -> dict[str, Any]:
        snapshot_id = str(uuid4())
        created_at = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO event_timeline_snapshots(
                    id, symbol, name, as_of_date, method, fingerprint,
                    payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    snapshot["symbol"],
                    snapshot["name"],
                    snapshot["as_of_date"],
                    snapshot["method"],
                    fingerprint,
                    json_dumps(snapshot),
                    created_at,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM event_timeline_snapshots
                WHERE symbol = ? AND fingerprint = ?
                """,
                (snapshot["symbol"], fingerprint),
            ).fetchone()
        return self._event_timeline_row(row)  # type: ignore[return-value]

    def latest_event_timeline_snapshot(self, symbol: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM event_timeline_snapshots
                WHERE symbol = ?
                ORDER BY created_at DESC, rowid DESC LIMIT 1
                """,
                (symbol,),
            ).fetchone()
        return self._event_timeline_row(row)

    @staticmethod
    def _event_timeline_row(row: Any | None) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json") or "{}")
        return item

    def upsert_change_event(
        self,
        *,
        symbol: str,
        event_type: str,
        title: str,
        fact_summary: str,
        occurred_at: str,
        detected_at: str,
        source_name: str,
        source_url: str | None,
        data_status: str,
        rule_version: str,
        dedupe_hash: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        event_id = str(uuid4())
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO change_events(
                    id, symbol, event_type, title, fact_summary, occurred_at,
                    detected_at, source_name, source_url, data_status,
                    rule_version, dedupe_hash, payload_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(dedupe_hash) DO UPDATE SET
                    title = excluded.title,
                    fact_summary = excluded.fact_summary,
                    detected_at = excluded.detected_at,
                    source_name = excluded.source_name,
                    source_url = excluded.source_url,
                    data_status = excluded.data_status,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    event_id,
                    symbol,
                    event_type,
                    title,
                    fact_summary,
                    occurred_at,
                    detected_at,
                    source_name,
                    source_url,
                    data_status,
                    rule_version,
                    dedupe_hash,
                    json_dumps(payload),
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM change_events WHERE dedupe_hash = ?",
                (dedupe_hash,),
            ).fetchone()
        return self._change_event_row(row)  # type: ignore[return-value]

    def get_change_event(self, event_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM change_events WHERE id = ?", (event_id,)
            ).fetchone()
        return self._change_event_row(row)

    def list_change_events(
        self, *, symbol: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        parameters: list[Any] = []
        if symbol:
            clauses.append("symbol = ?")
            parameters.append(symbol)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        parameters.append(max(1, min(limit, 500)))
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM change_events{where}
                ORDER BY occurred_at DESC, detected_at DESC, rowid DESC
                LIMIT ?
                """,
                parameters,
            ).fetchall()
        return [
            item for row in rows if (item := self._change_event_row(row)) is not None
        ]

    @staticmethod
    def _change_event_row(row: Any | None) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json") or "{}")
        return item

    def ensure_user_change_links(self, user_id: str, symbol: str) -> int:
        now = utc_now()
        with self.connect() as connection:
            event_rows = connection.execute(
                "SELECT id FROM change_events WHERE symbol = ?", (symbol,)
            ).fetchall()
            inserted = connection.executemany(
                """
                INSERT OR IGNORE INTO user_change_links(
                    id, user_id, change_event_id, symbol, relevance_status,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, 'pending', ?, ?)
                """,
                [
                    (str(uuid4()), user_id, str(row["id"]), symbol, now, now)
                    for row in event_rows
                ],
            )
        return max(0, int(inserted or 0))

    def list_watchlist_user_ids(self) -> list[str]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT user_id
                FROM watchlist
                ORDER BY user_id
                """
            ).fetchall()
        return [str(row["user_id"]) for row in rows]

    def list_user_change_links(
        self,
        user_id: str,
        *,
        symbol: str | None = None,
        relevance_status: str | None = None,
        unread_only: bool = False,
        pending_only: bool = False,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses = ["links.user_id = ?"]
        parameters: list[Any] = [user_id]
        if symbol:
            clauses.append("links.symbol = ?")
            parameters.append(symbol)
        if relevance_status:
            clauses.append("links.relevance_status = ?")
            parameters.append(relevance_status)
        if unread_only:
            clauses.append("links.read_at IS NULL")
        if pending_only:
            clauses.append("links.relevance_status = 'pending'")
            clauses.append("links.handled_at IS NULL")
        parameters.append(max(1, min(limit, 500)))
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    links.id AS link_id,
                    links.relevance_status,
                    links.read_at,
                    links.handled_at,
                    links.created_at AS linked_at,
                    links.updated_at AS link_updated_at,
                    events.id AS event_id,
                    events.symbol,
                    events.event_type,
                    events.title,
                    events.fact_summary,
                    events.occurred_at,
                    events.detected_at,
                    events.source_name,
                    events.source_url,
                    events.data_status,
                    events.rule_version,
                    events.payload_json,
                    events.created_at,
                    events.updated_at
                FROM user_change_links AS links
                JOIN change_events AS events ON events.id = links.change_event_id
                WHERE {" AND ".join(clauses)}
                ORDER BY events.occurred_at DESC, events.detected_at DESC, links.rowid DESC
                LIMIT ?
                """,
                parameters,
            ).fetchall()
        return [self._user_change_link_row(row) for row in rows]

    def get_user_change_link(self, user_id: str, link_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    links.id AS link_id,
                    links.relevance_status,
                    links.read_at,
                    links.handled_at,
                    links.created_at AS linked_at,
                    links.updated_at AS link_updated_at,
                    events.id AS event_id,
                    events.symbol,
                    events.event_type,
                    events.title,
                    events.fact_summary,
                    events.occurred_at,
                    events.detected_at,
                    events.source_name,
                    events.source_url,
                    events.data_status,
                    events.rule_version,
                    events.payload_json,
                    events.created_at,
                    events.updated_at
                FROM user_change_links AS links
                JOIN change_events AS events ON events.id = links.change_event_id
                WHERE links.id = ? AND links.user_id = ?
                """,
                (link_id, user_id),
            ).fetchone()
        return self._user_change_link_row(row) if row is not None else None

    @staticmethod
    def _user_change_link_row(row: Any) -> dict[str, Any]:
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json") or "{}")
        return item

    def mark_user_change_read(
        self, user_id: str, link_id: str
    ) -> dict[str, Any] | None:
        now = utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE user_change_links
                SET read_at = COALESCE(read_at, ?), updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (now, now, link_id, user_id),
            )
        if cursor.rowcount == 0:
            return None
        return self.get_user_change_link(user_id, link_id)

    def set_user_change_relevance(
        self, user_id: str, link_id: str, relevance_status: str
    ) -> dict[str, Any] | None:
        if relevance_status not in {"relevant", "irrelevant"}:
            raise ValueError("相关性状态只接受 relevant 或 irrelevant")
        now = utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE user_change_links
                SET relevance_status = ?, handled_at = ?, updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (relevance_status, now, now, link_id, user_id),
            )
        if cursor.rowcount == 0:
            return None
        return self.get_user_change_link(user_id, link_id)

    def latest_analyst_expectation_snapshot(self, symbol: str) -> dict[str, Any] | None:
        items = self.list_analyst_expectation_snapshots(symbol, limit=1)
        return items[0] if items else None

    def list_analyst_expectation_snapshots(
        self, symbol: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM analyst_expectation_snapshots
                WHERE symbol = ?
                ORDER BY created_at DESC, rowid DESC
                LIMIT ?
                """,
                (symbol, max(1, min(limit, 100))),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json") or "{}")
            items.append(item)
        return items

    def create_research_report(
        self,
        symbol: str,
        name: str,
        title: str,
        summary: str,
        body: str,
        status: str,
        fingerprint: str,
        evidence: dict[str, Any],
        run_id: str | None,
        market_timestamp: str | None,
    ) -> dict[str, Any]:
        report_id = str(uuid4())
        generated_at = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO research_reports(
                    id, symbol, name, title, summary, body, status, fingerprint,
                    evidence_json, run_id, market_timestamp, generated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report_id,
                    symbol,
                    name,
                    title,
                    summary,
                    body,
                    status,
                    fingerprint,
                    json_dumps(evidence),
                    run_id,
                    market_timestamp,
                    generated_at,
                ),
            )
        return self.latest_research_report(symbol)  # type: ignore[return-value]

    def latest_research_report(self, symbol: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM research_reports
                WHERE symbol = ? ORDER BY generated_at DESC, rowid DESC LIMIT 1
                """,
                (symbol,),
            ).fetchone()
        item = self._row(row)
        if item is not None:
            item["evidence"] = json.loads(item.pop("evidence_json"))
        return item

    def list_research_reports(
        self, symbol: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM research_reports
                WHERE symbol = ?
                ORDER BY generated_at DESC, rowid DESC LIMIT ?
                """,
                (symbol, limit),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["evidence"] = json.loads(item.pop("evidence_json"))
            items.append(item)
        return items

    def list_latest_research_reports(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM research_reports AS reports
                WHERE id = (
                    SELECT inner_reports.id
                    FROM research_reports AS inner_reports
                    WHERE inner_reports.symbol = reports.symbol
                    ORDER BY inner_reports.generated_at DESC, inner_reports.rowid DESC
                    LIMIT 1
                )
                ORDER BY generated_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["evidence"] = json.loads(item.pop("evidence_json"))
            items.append(item)
        return items

    def save_research_change_event(
        self,
        *,
        symbol: str,
        report_id: str,
        previous_report_id: str | None,
        event_type: str,
        severity: str,
        summary: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        event_id = str(uuid4())
        created_at = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO research_change_events(
                    id, symbol, report_id, previous_report_id, event_type,
                    severity, summary, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    symbol,
                    report_id,
                    previous_report_id,
                    event_type,
                    severity,
                    summary,
                    json_dumps(payload),
                    created_at,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM research_change_events
                WHERE symbol = ? AND report_id = ?
                """,
                (symbol, report_id),
            ).fetchone()
        return self._research_change_row(row)  # type: ignore[return-value]

    def research_change_event_for_report(
        self, symbol: str, report_id: str
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM research_change_events
                WHERE symbol = ? AND report_id = ?
                """,
                (symbol, report_id),
            ).fetchone()
        return self._research_change_row(row)

    def latest_research_change_event(self, symbol: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM research_change_events
                WHERE symbol = ? ORDER BY created_at DESC, rowid DESC LIMIT 1
                """,
                (symbol,),
            ).fetchone()
        return self._research_change_row(row)

    def list_research_change_events(
        self, symbols: list[str], limit: int = 20
    ) -> list[dict[str, Any]]:
        if not symbols:
            return []
        placeholders = ",".join("?" for _ in symbols)
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM research_change_events
                WHERE symbol IN ({placeholders})
                ORDER BY created_at DESC, rowid DESC LIMIT ?
                """,
                (*symbols, limit),
            ).fetchall()
        return [self._research_change_row(row) for row in rows]  # type: ignore[misc]

    @staticmethod
    def _research_change_row(row: Any | None) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json") or "{}")
        return item

    def save_research_priority_snapshot(
        self, user_id: str, fingerprint: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        snapshot_id = str(uuid4())
        created_at = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO research_priority_snapshots(
                    id, user_id, fingerprint, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    user_id,
                    fingerprint,
                    json_dumps(payload),
                    created_at,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM research_priority_snapshots
                WHERE user_id = ? AND fingerprint = ?
                """,
                (user_id, fingerprint),
            ).fetchone()
        return self._research_priority_row(row)  # type: ignore[return-value]

    def latest_research_priority_snapshot(self, user_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM research_priority_snapshots
                WHERE user_id = ?
                ORDER BY created_at DESC, rowid DESC LIMIT 1
                """,
                (user_id,),
            ).fetchone()
        return self._research_priority_row(row)

    @staticmethod
    def _research_priority_row(row: Any | None) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json") or "{}")
        return item

    def save_research_action_snapshot(
        self, user_id: str, fingerprint: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        snapshot_id = str(uuid4())
        created_at = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO research_action_snapshots(
                    id, user_id, fingerprint, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    user_id,
                    fingerprint,
                    json_dumps(payload),
                    created_at,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM research_action_snapshots
                WHERE user_id = ? AND fingerprint = ?
                """,
                (user_id, fingerprint),
            ).fetchone()
        return self._research_action_row(row)  # type: ignore[return-value]

    def latest_research_action_snapshot(self, user_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM research_action_snapshots
                WHERE user_id = ?
                ORDER BY created_at DESC, rowid DESC LIMIT 1
                """,
                (user_id,),
            ).fetchone()
        return self._research_action_row(row)

    @staticmethod
    def _research_action_row(row: Any | None) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json") or "{}")
        return item

    def upsert_evidence_task(self, task: dict[str, Any]) -> dict[str, Any]:
        task_id = str(task.get("id") or uuid4())
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO evidence_tasks(
                    id, user_id, conversation_id, run_id, subject_kind,
                    symbol, market_key, intent, task_type, gap_key, title,
                    description, query, status, priority, fingerprint,
                    retry_count, max_retries, metadata_json, created_at,
                    updated_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)
                ON CONFLICT(fingerprint) DO UPDATE SET
                    conversation_id = excluded.conversation_id,
                    run_id = excluded.run_id,
                    title = excluded.title,
                    description = excluded.description,
                    query = excluded.query,
                    priority = MAX(evidence_tasks.priority, excluded.priority),
                    metadata_json = excluded.metadata_json,
                    status = CASE
                        WHEN evidence_tasks.status = 'failed'
                             AND evidence_tasks.retry_count < evidence_tasks.max_retries
                        THEN 'pending'
                        ELSE evidence_tasks.status
                    END,
                    last_error = CASE
                        WHEN evidence_tasks.status = 'failed'
                             AND evidence_tasks.retry_count < evidence_tasks.max_retries
                        THEN NULL
                        ELSE evidence_tasks.last_error
                    END,
                    updated_at = excluded.updated_at,
                    last_seen_at = excluded.last_seen_at
                """,
                (
                    task_id,
                    task["user_id"],
                    task.get("conversation_id"),
                    task.get("run_id"),
                    task["subject_kind"],
                    task.get("symbol"),
                    task.get("market_key"),
                    task["intent"],
                    task["task_type"],
                    task["gap_key"],
                    task["title"],
                    task["description"],
                    task["query"],
                    task.get("status") or "pending",
                    int(task.get("priority") or 50),
                    task["fingerprint"],
                    int(task.get("max_retries") or 3),
                    json_dumps(task.get("metadata") or {}),
                    now,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM evidence_tasks WHERE fingerprint = ?",
                (task["fingerprint"],),
            ).fetchone()
        return self._evidence_task_row(row)  # type: ignore[return-value]

    def get_evidence_task(self, user_id: str, task_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM evidence_tasks WHERE id = ? AND user_id = ?",
                (task_id, user_id),
            ).fetchone()
        return self._evidence_task_row(row)

    def list_evidence_tasks(
        self,
        user_id: str,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        status_clause = " AND status = ?" if status is not None else ""
        parameters: list[Any] = [user_id]
        if status is not None:
            parameters.append(status)
        parameters.append(limit)
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM evidence_tasks
                WHERE user_id = ?{status_clause}
                ORDER BY
                    CASE status
                        WHEN 'collecting' THEN 5
                        WHEN 'pending' THEN 4
                        WHEN 'failed' THEN 3
                        WHEN 'pending_external' THEN 2
                        ELSE 1
                    END DESC,
                    priority DESC, updated_at DESC, rowid DESC
                LIMIT ?
                """,
                parameters,
            ).fetchall()
        return [self._evidence_task_row(row) for row in rows]  # type: ignore[misc]

    def list_pending_evidence_tasks(
        self, user_id: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        user_clause = "user_id = ? AND " if user_id is not None else ""
        parameters: list[Any] = []
        if user_id is not None:
            parameters.append(user_id)
        parameters.append(limit)
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM evidence_tasks
                WHERE {user_clause}(
                    status = 'pending'
                    OR (status = 'failed' AND retry_count < max_retries)
                  )
                ORDER BY priority DESC, updated_at ASC, rowid ASC
                LIMIT ?
                """,
                parameters,
            ).fetchall()
        return [self._evidence_task_row(row) for row in rows]  # type: ignore[misc]

    def claim_evidence_task(
        self, task_id: str, user_id: str | None = None
    ) -> dict[str, Any] | None:
        now = utc_now()
        user_clause = " AND user_id = ?" if user_id is not None else ""
        parameters: list[Any] = [now, now, task_id]
        if user_id is not None:
            parameters.append(user_id)
        with self.connect() as connection:
            cursor = connection.execute(
                f"""
                UPDATE evidence_tasks
                SET status = 'collecting', retry_count = retry_count + 1,
                    started_at = ?, updated_at = ?, last_error = NULL
                WHERE id = ?{user_clause}
                  AND (
                    status = 'pending'
                    OR (status = 'failed' AND retry_count < max_retries)
                  )
                """,
                parameters,
            )
            if cursor.rowcount == 0:
                return None
            row = connection.execute(
                "SELECT * FROM evidence_tasks WHERE id = ?", (task_id,)
            ).fetchone()
        return self._evidence_task_row(row)

    def finish_evidence_task(
        self,
        task_id: str,
        status: str,
        *,
        resolution_document_id: str | None = None,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        now = utc_now()
        resolved_at = now if status == "resolved" else None
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE evidence_tasks
                SET status = ?, resolution_document_id = ?, last_error = ?,
                    metadata_json = COALESCE(?, metadata_json),
                    updated_at = ?, resolved_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    resolution_document_id,
                    error,
                    json_dumps(metadata) if metadata is not None else None,
                    now,
                    resolved_at,
                    task_id,
                ),
            )
            row = connection.execute(
                "SELECT * FROM evidence_tasks WHERE id = ?", (task_id,)
            ).fetchone()
        return self._evidence_task_row(row)

    def evidence_task_summary(self, user_id: str) -> dict[str, int]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM evidence_tasks WHERE user_id = ? GROUP BY status
                """,
                (user_id,),
            ).fetchall()
        counts = {str(row["status"]): int(row["count"]) for row in rows}
        return {
            "total": sum(counts.values()),
            "pending": counts.get("pending", 0),
            "collecting": counts.get("collecting", 0),
            "resolved": counts.get("resolved", 0),
            "pending_external": counts.get("pending_external", 0),
            "failed": counts.get("failed", 0),
        }

    @staticmethod
    def _evidence_task_row(row: Any | None) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
        return item

    def list_research_anchor_reports(
        self, symbol: str | None = None, limit: int = 1000
    ) -> list[dict[str, Any]]:
        symbol_clause = "WHERE symbol = ?" if symbol is not None else ""
        parameters: list[Any] = []
        if symbol is not None:
            parameters.append(symbol)
        parameters.append(limit)
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                WITH ranked AS (
                    SELECT reports.*,
                        ROW_NUMBER() OVER (
                            PARTITION BY symbol,
                                COALESCE(market_timestamp, generated_at)
                            ORDER BY generated_at DESC, rowid DESC
                        ) AS anchor_rank
                    FROM research_reports AS reports
                    {symbol_clause}
                )
                SELECT * FROM ranked
                WHERE anchor_rank = 1
                ORDER BY COALESCE(market_timestamp, generated_at) DESC,
                    generated_at DESC
                LIMIT ?
                """,
                parameters,
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item.pop("anchor_rank", None)
            item["evidence"] = json.loads(item.pop("evidence_json"))
            items.append(item)
        return items

    def research_outcome_for_anchor(
        self, symbol: str, anchor_timestamp: str, horizon_sessions: int
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM research_outcomes
                WHERE symbol = ? AND anchor_timestamp = ?
                    AND horizon_sessions = ?
                """,
                (symbol, anchor_timestamp, horizon_sessions),
            ).fetchone()
        return self._research_outcome_row(row)

    def save_research_outcome(self, outcome: dict[str, Any]) -> dict[str, Any]:
        outcome_id = str(uuid4())
        calculated_at = outcome.get("calculated_at") or utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO research_outcomes(
                    id, report_id, symbol, name, anchor_timestamp,
                    horizon_sessions, result_status, observed_sessions,
                    anchor_close, target_timestamp, target_close,
                    close_return_pct, maximum_favorable_excursion_pct,
                    maximum_adverse_excursion_pct, scenario_result,
                    review_conclusion, payload_json, calculated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, anchor_timestamp, horizon_sessions) DO UPDATE SET
                    report_id = excluded.report_id,
                    name = excluded.name,
                    result_status = excluded.result_status,
                    observed_sessions = excluded.observed_sessions,
                    anchor_close = excluded.anchor_close,
                    target_timestamp = excluded.target_timestamp,
                    target_close = excluded.target_close,
                    close_return_pct = excluded.close_return_pct,
                    maximum_favorable_excursion_pct =
                        excluded.maximum_favorable_excursion_pct,
                    maximum_adverse_excursion_pct =
                        excluded.maximum_adverse_excursion_pct,
                    scenario_result = excluded.scenario_result,
                    review_conclusion = excluded.review_conclusion,
                    payload_json = excluded.payload_json,
                    calculated_at = excluded.calculated_at
                """,
                (
                    outcome_id,
                    outcome["report_id"],
                    outcome["symbol"],
                    outcome["name"],
                    outcome["anchor_timestamp"],
                    outcome["horizon_sessions"],
                    outcome["result_status"],
                    outcome["observed_sessions"],
                    outcome.get("anchor_close"),
                    outcome.get("target_timestamp"),
                    outcome.get("target_close"),
                    outcome.get("close_return_pct"),
                    outcome.get("maximum_favorable_excursion_pct"),
                    outcome.get("maximum_adverse_excursion_pct"),
                    outcome.get("scenario_result"),
                    outcome["review_conclusion"],
                    json_dumps(outcome.get("payload") or {}),
                    calculated_at,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM research_outcomes
                WHERE symbol = ? AND anchor_timestamp = ?
                    AND horizon_sessions = ?
                """,
                (
                    outcome["symbol"],
                    outcome["anchor_timestamp"],
                    outcome["horizon_sessions"],
                ),
            ).fetchone()
        return self._research_outcome_row(row)  # type: ignore[return-value]

    def list_research_outcomes(
        self, symbols: list[str] | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        params: list[Any] = []
        where = ""
        if symbols:
            placeholders = ",".join("?" for _ in symbols)
            where = f"WHERE symbol IN ({placeholders})"
            params.extend(symbols)
        params.append(limit)
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM research_outcomes
                {where}
                ORDER BY anchor_timestamp DESC, horizon_sessions ASC,
                    calculated_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._research_outcome_row(row) for row in rows]  # type: ignore[misc]

    @staticmethod
    def _research_outcome_row(row: Any | None) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json") or "{}")
        return item

    def save_outlook_calibration(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        calibration_id = str(uuid4())
        created_at = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO outlook_calibrations(
                    id, symbol, method, history_first, history_last,
                    history_points, source, payload_json, fetched_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, method, history_last) DO UPDATE SET
                    history_first = excluded.history_first,
                    history_points = excluded.history_points,
                    source = excluded.source,
                    payload_json = excluded.payload_json,
                    fetched_at = excluded.fetched_at,
                    created_at = excluded.created_at
                """,
                (
                    calibration_id,
                    snapshot["symbol"],
                    snapshot["method"],
                    snapshot.get("history_first"),
                    snapshot["history_last"],
                    snapshot["history_points"],
                    snapshot["source"],
                    json_dumps(snapshot["calibration"]),
                    snapshot.get("fetched_at") or created_at,
                    created_at,
                ),
            )
        return self.latest_outlook_calibration(snapshot["symbol"])  # type: ignore[return-value]

    def latest_outlook_calibration(self, symbol: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM outlook_calibrations
                WHERE symbol = ?
                ORDER BY created_at DESC, rowid DESC LIMIT 1
                """,
                (symbol,),
            ).fetchone()
        item = self._row(row)
        if item is not None:
            item["calibration"] = json.loads(item.pop("payload_json"))
        return item
