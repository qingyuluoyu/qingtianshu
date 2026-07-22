from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import uuid4

from app.catalog import normalize_symbol
from app.db import Database
from app.utils import json_dumps, utc_now


class ObservationTaskNotFound(ValueError):
    pass


class ObservationTaskVersionConflict(ValueError):
    pass


class ObservationTaskInvalidState(ValueError):
    pass


class ObservationTaskService:
    """Persist user-owned research tasks separately from evidence collection jobs."""

    CONTRACT_VERSION = "observation_tasks_v1"
    STATUSES = {
        "pending",
        "in_progress",
        "waiting_data",
        "completed",
        "ignored",
        "cancelled",
    }
    ACTIVE_STATUSES = {"pending", "in_progress", "waiting_data"}
    TERMINAL_STATUSES = {"completed", "ignored", "cancelled"}
    PRIORITIES = {"high", "normal", "low"}
    SOURCE_TYPES = {"user", "research_action"}
    TRANSITIONS = {
        "pending": {"in_progress", "waiting_data", "completed", "ignored", "cancelled"},
        "in_progress": {"waiting_data", "completed", "ignored", "cancelled"},
        "waiting_data": {"in_progress", "completed", "ignored", "cancelled"},
        "completed": {"pending"},
        "ignored": {"pending"},
        "cancelled": {"pending"},
    }
    STATUS_LABELS = {
        "pending": "待处理",
        "in_progress": "处理中",
        "waiting_data": "等待数据",
        "completed": "已完成",
        "ignored": "已忽略",
        "cancelled": "已取消",
    }

    def __init__(self, database: Database):
        self.database = database

    def create_task(
        self,
        *,
        user_id: str,
        symbol: str,
        title: str,
        description: str,
        priority: str = "normal",
        due_at: str | None = None,
        thesis_id: str | None = None,
        change_ref: str | None = None,
        source_type: str = "user",
        source_ref_id: str | None = None,
    ) -> dict[str, Any]:
        canonical = normalize_symbol(symbol)
        clean_title = self._clean_text(title, 160)
        clean_description = self._clean_text(description, 2000)
        if not clean_title:
            raise ObservationTaskInvalidState("任务标题不能为空")
        if not clean_description:
            raise ObservationTaskInvalidState("任务说明不能为空")
        if priority not in self.PRIORITIES:
            raise ObservationTaskInvalidState("任务优先级不受支持")
        if source_type not in self.SOURCE_TYPES:
            raise ObservationTaskInvalidState("任务来源不受支持")
        clean_due_at = self._normalize_datetime(due_at)
        clean_source_ref = self._clean_text(source_ref_id, 160) or None
        dedupe_key = (
            f"{canonical}:{source_type}:{clean_source_ref}"
            if source_type == "research_action" and clean_source_ref
            else None
        )
        workspace = self.database.get_stock_workspace(user_id, canonical)
        if thesis_id:
            thesis = self.database.get_thesis_version(user_id, thesis_id)
            if thesis is None or thesis.get("symbol") != canonical:
                raise ObservationTaskInvalidState("关联判断不属于当前股票空间")

        task_id = str(uuid4())
        now = utc_now()
        with self.database.connect() as connection:
            if dedupe_key:
                existing = connection.execute(
                    """
                    SELECT * FROM observation_tasks
                    WHERE user_id = ? AND dedupe_key = ?
                    """,
                    (user_id, dedupe_key),
                ).fetchone()
                if existing is not None:
                    return self._task_packet(connection, existing, include_history=True)
            connection.execute(
                """
                INSERT INTO observation_tasks(
                    id, user_id, workspace_id, symbol, thesis_id, change_ref,
                    title, description, status, priority, source_type,
                    source_ref_id, dedupe_key, due_at, result_text,
                    completion_evidence_json, version, created_at, updated_at,
                    completed_at, ignored_at, cancelled_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?,
                          NULL, '[]', 1, ?, ?, NULL, NULL, NULL)
                """,
                (
                    task_id,
                    user_id,
                    (workspace or {}).get("id"),
                    canonical,
                    thesis_id,
                    self._clean_text(change_ref, 160) or None,
                    clean_title,
                    clean_description,
                    priority,
                    source_type,
                    clean_source_ref,
                    dedupe_key,
                    clean_due_at,
                    now,
                    now,
                ),
            )
            row = self._task_for_user(connection, user_id, task_id)
            self._record_history(
                connection,
                row,
                event_type="created",
                from_status=None,
            )
            return self._task_packet(connection, row, include_history=True)

    def list_tasks(
        self,
        *,
        user_id: str,
        symbol: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        canonical = normalize_symbol(symbol) if symbol else None
        if status is not None and status not in self.STATUSES:
            raise ObservationTaskInvalidState("任务状态不受支持")
        clauses = ["user_id = ?"]
        params: list[Any] = [user_id]
        if canonical:
            clauses.append("symbol = ?")
            params.append(canonical)
        if status:
            clauses.append("status = ?")
            params.append(status)
        params.append(max(1, min(int(limit), 200)))
        with self.database.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM observation_tasks
                WHERE {' AND '.join(clauses)}
                ORDER BY
                    CASE priority WHEN 'high' THEN 3 WHEN 'normal' THEN 2 ELSE 1 END DESC,
                    CASE status
                        WHEN 'in_progress' THEN 3
                        WHEN 'pending' THEN 2
                        WHEN 'waiting_data' THEN 1
                        ELSE 0
                    END DESC,
                    updated_at DESC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
            items = [self._task_packet(connection, row) for row in rows]
        return {
            "contract_version": self.CONTRACT_VERSION,
            "items": items,
            "summary": {
                "total": len(items),
                "active": sum(item["status"] in self.ACTIVE_STATUSES for item in items),
                "pending": sum(item["status"] == "pending" for item in items),
                "in_progress": sum(item["status"] == "in_progress" for item in items),
                "waiting_data": sum(item["status"] == "waiting_data" for item in items),
                "completed": sum(item["status"] == "completed" for item in items),
            },
            "boundary": (
                "观察任务只保存用户需要核验的事实、证据和复核结果；"
                "不是交易指令、价格提醒、仓位建议或收益承诺。"
            ),
        }

    def get_task(self, *, user_id: str, task_id: str) -> dict[str, Any]:
        with self.database.connect() as connection:
            row = self._task_for_user(connection, user_id, task_id)
            return self._task_packet(connection, row, include_history=True)

    def update_task(
        self,
        *,
        user_id: str,
        task_id: str,
        base_version: int,
        title: str | None = None,
        description: str | None = None,
        priority: str | None = None,
        due_at: str | None = None,
        due_at_provided: bool = False,
    ) -> dict[str, Any]:
        if (
            title is None
            and description is None
            and priority is None
            and not due_at_provided
        ):
            raise ObservationTaskInvalidState("没有需要更新的任务字段")
        with self.database.connect() as connection:
            row = self._task_for_user(connection, user_id, task_id)
            self._check_version(row, base_version)
            if row["status"] in self.TERMINAL_STATUSES:
                raise ObservationTaskInvalidState("已结束任务需先重开才能编辑")
            values = {
                "title": self._clean_text(title, 160) if title is not None else row["title"],
                "description": (
                    self._clean_text(description, 2000)
                    if description is not None
                    else row["description"]
                ),
                "priority": priority if priority is not None else row["priority"],
                "due_at": (
                    self._normalize_datetime(due_at)
                    if due_at_provided
                    else row["due_at"]
                ),
            }
            if not values["title"] or not values["description"]:
                raise ObservationTaskInvalidState("任务标题和说明不能为空")
            if values["priority"] not in self.PRIORITIES:
                raise ObservationTaskInvalidState("任务优先级不受支持")
            next_version = int(row["version"]) + 1
            connection.execute(
                """
                UPDATE observation_tasks
                SET title = ?, description = ?, priority = ?, due_at = ?,
                    version = ?, updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (
                    values["title"],
                    values["description"],
                    values["priority"],
                    values["due_at"],
                    next_version,
                    utc_now(),
                    task_id,
                    user_id,
                ),
            )
            updated = self._task_for_user(connection, user_id, task_id)
            self._record_history(
                connection,
                updated,
                event_type="updated",
                from_status=str(row["status"]),
            )
            return self._task_packet(connection, updated, include_history=True)

    def transition_task(
        self,
        *,
        user_id: str,
        task_id: str,
        base_version: int,
        status: str,
        result_text: str | None = None,
        evidence_refs: list[str] | None = None,
    ) -> dict[str, Any]:
        if status not in self.STATUSES:
            raise ObservationTaskInvalidState("任务状态不受支持")
        clean_result = self._clean_text(result_text, 3000) or None
        clean_evidence = self._clean_refs(evidence_refs or [])
        now = utc_now()
        with self.database.connect() as connection:
            row = self._task_for_user(connection, user_id, task_id)
            self._check_version(row, base_version)
            current = str(row["status"])
            if status not in self.TRANSITIONS[current]:
                raise ObservationTaskInvalidState(
                    f"任务不能从“{self.STATUS_LABELS[current]}”变为“{self.STATUS_LABELS[status]}”"
                )
            if status == "completed" and not (clean_result or clean_evidence):
                raise ObservationTaskInvalidState("完成任务必须填写结果或选择证据")
            reopened = current in self.TERMINAL_STATUSES and status == "pending"
            next_version = int(row["version"]) + 1
            connection.execute(
                """
                UPDATE observation_tasks
                SET status = ?, result_text = ?, completion_evidence_json = ?,
                    version = ?, updated_at = ?, completed_at = ?, ignored_at = ?,
                    cancelled_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (
                    status,
                    None if reopened else clean_result,
                    json_dumps([] if reopened else clean_evidence),
                    next_version,
                    now,
                    now if status == "completed" else None,
                    now if status == "ignored" else None,
                    now if status == "cancelled" else None,
                    task_id,
                    user_id,
                ),
            )
            updated = self._task_for_user(connection, user_id, task_id)
            self._record_history(
                connection,
                updated,
                event_type="reopened" if reopened else "status_changed",
                from_status=current,
            )
            return self._task_packet(connection, updated, include_history=True)

    def _task_for_user(self, connection: Any, user_id: str, task_id: str) -> Any:
        row = connection.execute(
            "SELECT * FROM observation_tasks WHERE id = ? AND user_id = ?",
            (task_id, user_id),
        ).fetchone()
        if row is None:
            raise ObservationTaskNotFound("观察任务不存在")
        return row

    def _task_packet(
        self, connection: Any, row: Any, include_history: bool = False
    ) -> dict[str, Any]:
        item = dict(row)
        item["completion_evidence"] = json.loads(
            item.pop("completion_evidence_json") or "[]"
        )
        item["status_label"] = self.STATUS_LABELS.get(item["status"], item["status"])
        item["terminal"] = item["status"] in self.TERMINAL_STATUSES
        item["can_reopen"] = item["terminal"]
        item["can_edit"] = not item["terminal"]
        if include_history:
            rows = connection.execute(
                """
                SELECT * FROM observation_task_history
                WHERE task_id = ? AND user_id = ?
                ORDER BY version DESC
                """,
                (item["id"], item["user_id"]),
            ).fetchall()
            item["history"] = [self._history_packet(history) for history in rows]
        return item

    def _record_history(
        self,
        connection: Any,
        row: Any,
        *,
        event_type: str,
        from_status: str | None,
    ) -> None:
        snapshot = dict(row)
        snapshot["completion_evidence"] = json.loads(
            snapshot.pop("completion_evidence_json") or "[]"
        )
        connection.execute(
            """
            INSERT INTO observation_task_history(
                id, task_id, user_id, version, event_type, from_status,
                to_status, snapshot_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                row["id"],
                row["user_id"],
                row["version"],
                event_type,
                from_status,
                row["status"],
                json_dumps(snapshot),
                utc_now(),
            ),
        )

    def _history_packet(self, row: Any) -> dict[str, Any]:
        item = dict(row)
        item["snapshot"] = json.loads(item.pop("snapshot_json") or "{}")
        item["from_status_label"] = self.STATUS_LABELS.get(item.get("from_status"))
        item["to_status_label"] = self.STATUS_LABELS.get(item.get("to_status"))
        return item

    @staticmethod
    def _check_version(row: Any, base_version: int) -> None:
        if int(row["version"]) != int(base_version):
            raise ObservationTaskVersionConflict(
                f"任务已更新，当前版本为 {row['version']}"
            )

    @staticmethod
    def _clean_text(value: Any, limit: int) -> str:
        return " ".join(str(value or "").split()).strip()[:limit]

    @classmethod
    def _clean_refs(cls, values: list[str]) -> list[str]:
        output: list[str] = []
        for value in values:
            text = cls._clean_text(value, 300)
            if text and text not in output:
                output.append(text)
            if len(output) >= 12:
                break
        return output

    @staticmethod
    def _normalize_datetime(value: str | None) -> str | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ObservationTaskInvalidState("截止时间必须是 ISO 8601 格式") from exc
        return text[:40]
