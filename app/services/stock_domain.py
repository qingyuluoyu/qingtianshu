from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.catalog import normalize_symbol
from app.db import Database
from app.utils import json_dumps, utc_now


class StockDomainNotFound(ValueError):
    pass


class StockDomainVersionConflict(ValueError):
    pass


class StockDomainInvalidState(ValueError):
    pass


class StockDomainService:
    """Versioned user-stock relationship and confirmed thesis workflow."""

    CONTRACT_VERSION = "stock_domain_v1"
    RELATION_TYPES = {"watching", "holding", "ended"}
    PRIORITIES = {"high", "normal", "low"}
    TRACKING_STATUSES = {"active", "paused"}
    WORKFLOW_STATUSES = {"idle", "researching", "waiting_data"}

    def __init__(self, database: Database):
        self.database = database

    def get_workspace(self, user_id: str, symbol: str) -> dict[str, Any]:
        canonical = normalize_symbol(symbol)
        workspace = self.database.get_stock_workspace(user_id, canonical)
        if workspace is None:
            raise StockDomainNotFound("股票研究空间不存在")
        return self._workspace_packet(user_id, workspace)

    def update_relation(
        self,
        *,
        user_id: str,
        symbol: str,
        base_version: int,
        relation_type: str,
        priority: str | None,
        tracking_status: str,
        workflow_status: str,
        attention_tags: list[str],
    ) -> dict[str, Any]:
        canonical = normalize_symbol(symbol)
        if relation_type not in self.RELATION_TYPES:
            raise StockDomainInvalidState("关系状态不受支持")
        if priority is not None and priority not in self.PRIORITIES:
            raise StockDomainInvalidState("关注优先级不受支持")
        if tracking_status not in self.TRACKING_STATUSES:
            raise StockDomainInvalidState("跟踪状态不受支持")
        if workflow_status not in self.WORKFLOW_STATUSES:
            raise StockDomainInvalidState("研究流程状态不受支持")
        if relation_type != "watching":
            priority = None
        elif priority is None:
            priority = "normal"
        tags = self._clean_text_list(attention_tags, limit=12, item_limit=40)
        now = utc_now()
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM stock_workspaces
                WHERE user_id = ? AND symbol = ?
                """,
                (user_id, canonical),
            ).fetchone()
            if row is None:
                raise StockDomainNotFound("股票研究空间不存在")
            if int(row["version"]) != int(base_version):
                raise StockDomainVersionConflict(
                    f"股票空间已更新，当前版本为 {row['version']}"
                )
            relation_changed = any(
                (
                    str(row["relation_type"]) != relation_type,
                    row["priority"] != priority,
                    str(row["tracking_status"]) != tracking_status,
                )
            )
            if relation_changed:
                connection.execute(
                    """
                    UPDATE stock_relation_history SET ended_at = ?
                    WHERE workspace_id = ? AND ended_at IS NULL
                    """,
                    (now, row["id"]),
                )
                connection.execute(
                    """
                    INSERT INTO stock_relation_history(
                        id, workspace_id, user_id, relation_type, priority,
                        tracking_status, source, effective_at, ended_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'user_confirmed', ?, NULL)
                    """,
                    (
                        str(uuid4()),
                        row["id"],
                        user_id,
                        relation_type,
                        priority,
                        tracking_status,
                        now,
                    ),
                )
            connection.execute(
                """
                UPDATE stock_workspaces
                SET relation_type = ?, priority = ?, tracking_status = ?,
                    workflow_status = ?, attention_tags_json = ?,
                    version = version + 1, updated_at = ?, ended_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (
                    relation_type,
                    priority,
                    tracking_status,
                    workflow_status,
                    json_dumps(tags),
                    now,
                    now if relation_type == "ended" else None,
                    row["id"],
                    user_id,
                ),
            )
            if relation_type == "ended":
                connection.execute(
                    "DELETE FROM watchlist WHERE user_id = ? AND symbol = ?",
                    (user_id, canonical),
                )
            else:
                active = connection.execute(
                    """
                    SELECT reason_text FROM thesis_versions
                    WHERE workspace_id = ? AND status = 'active'
                    ORDER BY version_no DESC LIMIT 1
                    """,
                    (row["id"],),
                ).fetchone()
                connection.execute(
                    """
                    INSERT INTO watchlist(
                        user_id, symbol, name, market, thesis, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, symbol) DO UPDATE SET
                        name = excluded.name, market = excluded.market,
                        thesis = COALESCE(excluded.thesis, watchlist.thesis),
                        updated_at = excluded.updated_at
                    """,
                    (
                        user_id,
                        canonical,
                        row["name"],
                        row["market"],
                        active["reason_text"] if active else None,
                        row["created_at"],
                        now,
                    ),
                )
        self.database._sync_watchlist_file(user_id)
        return self.get_workspace(user_id, canonical)

    def list_theses(self, user_id: str, symbol: str) -> dict[str, Any]:
        canonical = normalize_symbol(symbol)
        workspace = self.database.get_stock_workspace(user_id, canonical)
        if workspace is None:
            raise StockDomainNotFound("股票研究空间不存在")
        items = self.database.list_thesis_versions(user_id, str(workspace["id"]))
        return {
            "contract_version": self.CONTRACT_VERSION,
            "symbol": canonical,
            "workspace_id": workspace["id"],
            "active": next((item for item in items if item["status"] == "active"), None),
            "candidates": [
                item
                for item in items
                if item["status"] in {"draft", "pending_confirmation"}
            ],
            "history": [
                item
                for item in items
                if item["status"] in {"superseded", "invalidated", "rejected"}
            ],
        }

    def create_thesis_candidate(
        self,
        *,
        user_id: str,
        symbol: str,
        reason_text: str,
        watch_items: list[str],
        recheck_conditions: list[str],
        source: str,
        source_run_id: str | None,
        base_version: int,
    ) -> dict[str, Any]:
        canonical = normalize_symbol(symbol)
        clean_reason = str(reason_text or "").strip()
        if not clean_reason:
            raise StockDomainInvalidState("当前判断不能为空")
        if source not in {"user", "ai"}:
            raise StockDomainInvalidState("判断来源不受支持")
        if source == "ai" and not source_run_id:
            raise StockDomainInvalidState("AI 判断草稿必须关联已完成 Run")
        now = utc_now()
        with self.database.connect() as connection:
            workspace = connection.execute(
                """
                SELECT * FROM stock_workspaces
                WHERE user_id = ? AND symbol = ?
                """,
                (user_id, canonical),
            ).fetchone()
            if workspace is None:
                raise StockDomainNotFound("股票研究空间不存在")
            if workspace["relation_type"] == "ended":
                raise StockDomainInvalidState("已结束的股票空间需先恢复后再建立新判断")
            active = connection.execute(
                """
                SELECT * FROM thesis_versions
                WHERE user_id = ? AND workspace_id = ? AND status = 'active'
                ORDER BY version_no DESC LIMIT 1
                """,
                (user_id, workspace["id"]),
            ).fetchone()
            current_version = int(active["version_no"]) if active else 0
            if int(base_version) != current_version:
                raise StockDomainVersionConflict(
                    f"正式判断已更新，当前版本为 {current_version}"
                )
            if source == "ai":
                run = connection.execute(
                    "SELECT * FROM runs WHERE id = ? AND user_id = ?",
                    (source_run_id, user_id),
                ).fetchone()
                if run is None or run["status"] != "completed":
                    raise StockDomainInvalidState("AI 判断草稿只能关联已完成 Run")
            next_row = connection.execute(
                """
                SELECT COALESCE(MAX(version_no), 0) + 1 AS next_version
                FROM thesis_versions WHERE workspace_id = ?
                """,
                (workspace["id"],),
            ).fetchone()
            thesis_id = str(uuid4())
            connection.execute(
                """
                INSERT INTO thesis_versions(
                    id, workspace_id, user_id, symbol, version_no, status,
                    reason_text, watch_items_json, recheck_conditions_json,
                    source, source_run_id, base_version, created_at,
                    confirmed_at, superseded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
                """,
                (
                    thesis_id,
                    workspace["id"],
                    user_id,
                    canonical,
                    int(next_row["next_version"]),
                    "pending_confirmation" if source == "ai" else "draft",
                    clean_reason,
                    json_dumps(self._clean_text_list(watch_items, 20, 200)),
                    json_dumps(
                        self._clean_text_list(recheck_conditions, 20, 300)
                    ),
                    source,
                    source_run_id,
                    current_version,
                    now,
                ),
            )
        thesis = self.database.get_thesis_version(user_id, thesis_id)
        return thesis  # type: ignore[return-value]

    def confirm_thesis(
        self, *, user_id: str, symbol: str, thesis_id: str
    ) -> dict[str, Any]:
        canonical = normalize_symbol(symbol)
        now = utc_now()
        workspace_id: str | None = None
        with self.database.connect() as connection:
            candidate = connection.execute(
                """
                SELECT * FROM thesis_versions
                WHERE id = ? AND user_id = ? AND symbol = ?
                """,
                (thesis_id, user_id, canonical),
            ).fetchone()
            if candidate is None:
                raise StockDomainNotFound("判断草稿不存在")
            if candidate["status"] not in {"draft", "pending_confirmation"}:
                raise StockDomainInvalidState("该判断草稿已经处理")
            workspace_id = str(candidate["workspace_id"])
            workspace = connection.execute(
                """
                SELECT * FROM stock_workspaces
                WHERE id = ? AND user_id = ?
                """,
                (workspace_id, user_id),
            ).fetchone()
            if workspace is None:
                raise StockDomainNotFound("股票研究空间不存在")
            active = connection.execute(
                """
                SELECT * FROM thesis_versions
                WHERE workspace_id = ? AND status = 'active'
                ORDER BY version_no DESC LIMIT 1
                """,
                (workspace_id,),
            ).fetchone()
            current_version = int(active["version_no"]) if active else 0
            if int(candidate["base_version"]) != current_version:
                raise StockDomainVersionConflict(
                    f"正式判断已更新，当前版本为 {current_version}"
                )
            if active is not None:
                connection.execute(
                    """
                    UPDATE thesis_versions
                    SET status = 'superseded', superseded_at = ?
                    WHERE id = ? AND status = 'active'
                    """,
                    (now, active["id"]),
                )
            connection.execute(
                """
                UPDATE thesis_versions
                SET status = 'active', confirmed_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (now, thesis_id, user_id),
            )
            connection.execute(
                """
                UPDATE stock_workspaces
                SET version = version + 1, updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (now, workspace_id, user_id),
            )
            if workspace["relation_type"] != "ended":
                connection.execute(
                    """
                    INSERT INTO watchlist(
                        user_id, symbol, name, market, thesis, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, symbol) DO UPDATE SET
                        thesis = excluded.thesis, updated_at = excluded.updated_at
                    """,
                    (
                        user_id,
                        canonical,
                        workspace["name"],
                        workspace["market"],
                        candidate["reason_text"],
                        workspace["created_at"],
                        now,
                    ),
                )
        self.database._sync_watchlist_file(user_id)
        thesis = self.database.get_thesis_version(user_id, thesis_id)
        return thesis  # type: ignore[return-value]

    def reject_thesis(
        self, *, user_id: str, symbol: str, thesis_id: str
    ) -> dict[str, Any]:
        canonical = normalize_symbol(symbol)
        with self.database.connect() as connection:
            candidate = connection.execute(
                """
                SELECT * FROM thesis_versions
                WHERE id = ? AND user_id = ? AND symbol = ?
                """,
                (thesis_id, user_id, canonical),
            ).fetchone()
            if candidate is None:
                raise StockDomainNotFound("判断草稿不存在")
            if candidate["status"] not in {"draft", "pending_confirmation"}:
                raise StockDomainInvalidState("该判断草稿已经处理")
            connection.execute(
                """
                UPDATE thesis_versions SET status = 'rejected'
                WHERE id = ? AND user_id = ?
                """,
                (thesis_id, user_id),
            )
        thesis = self.database.get_thesis_version(user_id, thesis_id)
        return thesis  # type: ignore[return-value]

    def _workspace_packet(
        self, user_id: str, workspace: dict[str, Any]
    ) -> dict[str, Any]:
        active = self.database.get_active_thesis(user_id, str(workspace["id"]))
        history = self.database.list_stock_relation_history(
            user_id, str(workspace["id"])
        )
        return {
            "contract_version": self.CONTRACT_VERSION,
            **workspace,
            "active_thesis": active,
            "relation_history": history,
        }

    @staticmethod
    def _clean_text_list(
        values: list[str], limit: int, item_limit: int
    ) -> list[str]:
        output: list[str] = []
        for value in values:
            text = " ".join(str(value or "").split())[:item_limit]
            if text and text not in output:
                output.append(text)
            if len(output) >= limit:
                break
        return output
