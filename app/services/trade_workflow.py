from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
from typing import Any
from uuid import uuid4

from app.catalog import normalize_symbol
from app.db import Database
from app.utils import json_dumps, utc_now


class TradeWorkflowNotFound(ValueError):
    pass


class TradeWorkflowInvalidState(ValueError):
    pass


class TradeWorkflowConflict(ValueError):
    pass


class TradeWorkflowService:
    """Versioned user plans and review drafts around immutable operations."""

    PLAN_ACTIONS = {"buy", "add", "reduce", "sell", "hold"}
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
    _PLAN_TRANSITIONS = {
        "draft": {"checked", "cancelled", "expired"},
        "checked": {"saved", "cancelled", "expired"},
        "saved": {"cancelled", "expired"},
        "partially_executed": {"cancelled", "expired"},
        "executed": set(),
        "cancelled": set(),
        "expired": set(),
    }
    _DECIMAL_QUANT = Decimal("0.000001")

    def __init__(self, database: Database) -> None:
        self.database = database

    def list_action_plans(self, user_id: str, symbol: str) -> dict[str, Any]:
        canonical = normalize_symbol(symbol)
        with self.database.connect() as connection:
            workspace = self._workspace(connection, user_id, canonical)
            self._expire_plans(connection, user_id, str(workspace["id"]))
            rows = connection.execute(
                """
                SELECT * FROM action_plans
                WHERE user_id = ? AND workspace_id = ?
                ORDER BY updated_at DESC, rowid DESC
                """,
                (user_id, workspace["id"]),
            ).fetchall()
        items = [self._plan_row(row) for row in rows]
        return {
            "contract_version": "action_plan_v1",
            "symbol": canonical,
            "items": items,
            "summary": {
                "total": len(items),
                "active": sum(
                    item["status"]
                    in {"draft", "checked", "saved", "partially_executed"}
                    for item in items
                ),
            },
            "boundary": "操作计划只保存用户自己的条件，系统不生成交易建议或自动执行。",
        }

    def create_action_plan(
        self,
        *,
        user_id: str,
        symbol: str,
        action_type: str,
        trigger_text: str,
        target_quantity: str | None,
        target_amount: str | None,
        target_position_percent: str | None,
        thesis_version_id: str | None,
        expires_at: str | None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        canonical = normalize_symbol(symbol)
        action = self._action(action_type)
        trigger = self._required_text(trigger_text, "用户触发条件", 2000)
        quantity = self._optional_positive(target_quantity, "目标数量")
        amount = self._optional_positive(target_amount, "目标金额")
        position = self._optional_positive(
            target_position_percent, "目标仓位比例", maximum=Decimal("100")
        )
        expiry = self._optional_datetime(expires_at, "计划到期时间")
        now = utc_now()
        with self.database.connect() as connection:
            workspace = self._workspace(connection, user_id, canonical)
            repeated = connection.execute(
                """
                SELECT id FROM action_plans
                WHERE user_id = ? AND idempotency_key = ?
                """,
                (user_id, idempotency_key),
            ).fetchone()
            if repeated is not None:
                return self.get_action_plan(user_id, str(repeated["id"]))
            thesis = self._resolve_thesis(
                connection,
                user_id=user_id,
                workspace_id=str(workspace["id"]),
                thesis_version_id=thesis_version_id,
            )
            plan_id = str(uuid4())
            connection.execute(
                """
                INSERT INTO action_plans(
                    id, user_id, workspace_id, action_type, trigger_text,
                    target_quantity, target_amount, target_position_percent,
                    thesis_version_id, check_result_json, status, expires_at,
                    idempotency_key, version, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', 'draft', ?, ?, 1, ?, ?)
                """,
                (
                    plan_id,
                    user_id,
                    workspace["id"],
                    action,
                    trigger,
                    self._decimal_text(quantity),
                    self._decimal_text(amount),
                    self._decimal_text(position),
                    thesis["id"] if thesis is not None else None,
                    expiry,
                    idempotency_key,
                    now,
                    now,
                ),
            )
            plan = self._plan_by_id(connection, user_id, plan_id)
            self._append_plan_history(
                connection,
                plan=plan,
                event_type="created",
                from_status=None,
                created_at=now,
            )
        return self.get_action_plan(user_id, plan_id)

    def get_action_plan(self, user_id: str, plan_id: str) -> dict[str, Any]:
        with self.database.connect() as connection:
            plan = self._plan_by_id(connection, user_id, plan_id)
            history = connection.execute(
                """
                SELECT * FROM action_plan_history
                WHERE user_id = ? AND plan_id = ?
                ORDER BY version DESC, rowid DESC
                """,
                (user_id, plan_id),
            ).fetchall()
        item = self._plan_row(plan)
        item["history"] = [self._plan_history_row(row) for row in history]
        return item

    def update_action_plan(
        self,
        *,
        user_id: str,
        plan_id: str,
        base_version: int,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        now = utc_now()
        with self.database.connect() as connection:
            current = self._plan_by_id(connection, user_id, plan_id)
            self._require_version(current, base_version)
            if current["status"] not in {"draft", "checked", "saved"}:
                raise TradeWorkflowInvalidState("当前计划状态不允许编辑")
            action = self._action(fields.get("action_type") or current["action_type"])
            trigger = self._required_text(
                fields.get("trigger_text", current["trigger_text"]),
                "用户触发条件",
                2000,
            )
            quantity = self._optional_positive(
                fields.get("target_quantity", current["target_quantity"]), "目标数量"
            )
            amount = self._optional_positive(
                fields.get("target_amount", current["target_amount"]), "目标金额"
            )
            position = self._optional_positive(
                fields.get(
                    "target_position_percent", current["target_position_percent"]
                ),
                "目标仓位比例",
                maximum=Decimal("100"),
            )
            expiry = self._optional_datetime(
                fields.get("expires_at", current["expires_at"]), "计划到期时间"
            )
            next_version = int(current["version"]) + 1
            next_status = "draft"
            check_result = "{}"
            cursor = connection.execute(
                """
                UPDATE action_plans
                SET action_type = ?, trigger_text = ?, target_quantity = ?,
                    target_amount = ?, target_position_percent = ?, expires_at = ?,
                    check_result_json = ?, status = ?, version = ?, updated_at = ?
                WHERE id = ? AND user_id = ? AND version = ?
                """,
                (
                    action,
                    trigger,
                    self._decimal_text(quantity),
                    self._decimal_text(amount),
                    self._decimal_text(position),
                    expiry,
                    check_result,
                    next_status,
                    next_version,
                    now,
                    plan_id,
                    user_id,
                    base_version,
                ),
            )
            if cursor.rowcount != 1:
                raise TradeWorkflowConflict("操作计划已被其他页面更新，请刷新后重试")
            updated = self._plan_by_id(connection, user_id, plan_id)
            self._append_plan_history(
                connection,
                plan=updated,
                event_type="updated",
                from_status=str(current["status"]),
                created_at=now,
            )
        return self.get_action_plan(user_id, plan_id)

    def transition_action_plan(
        self,
        *,
        user_id: str,
        plan_id: str,
        base_version: int,
        status: str,
    ) -> dict[str, Any]:
        if status not in self.PLAN_STATUSES:
            raise TradeWorkflowInvalidState("操作计划目标状态不受支持")
        now = utc_now()
        with self.database.connect() as connection:
            current = self._plan_by_id(connection, user_id, plan_id)
            self._require_version(current, base_version)
            if status not in self._PLAN_TRANSITIONS[str(current["status"])]:
                raise TradeWorkflowInvalidState(
                    f"操作计划不能从 {current['status']} 直接变为 {status}"
                )
            check_result = current["check_result_json"]
            if status == "checked":
                check_result = json_dumps(self._check_plan(current))
            if status == "saved":
                check = json.loads(check_result or "{}")
                if not check.get("passed"):
                    raise TradeWorkflowInvalidState("计划尚未通过完整性检查")
            next_version = int(current["version"]) + 1
            cursor = connection.execute(
                """
                UPDATE action_plans
                SET status = ?, check_result_json = ?, version = ?, updated_at = ?
                WHERE id = ? AND user_id = ? AND version = ?
                """,
                (
                    status,
                    check_result,
                    next_version,
                    now,
                    plan_id,
                    user_id,
                    base_version,
                ),
            )
            if cursor.rowcount != 1:
                raise TradeWorkflowConflict("操作计划已被其他页面更新，请刷新后重试")
            updated = self._plan_by_id(connection, user_id, plan_id)
            self._append_plan_history(
                connection,
                plan=updated,
                event_type=f"transitioned_to_{status}",
                from_status=str(current["status"]),
                created_at=now,
            )
        return self.get_action_plan(user_id, plan_id)

    def list_trade_reviews(self, user_id: str, symbol: str) -> dict[str, Any]:
        canonical = normalize_symbol(symbol)
        with self.database.connect() as connection:
            workspace = self._workspace(connection, user_id, canonical)
            ids = [
                str(row["id"])
                for row in connection.execute(
                    """
                    SELECT id FROM trade_reviews
                    WHERE user_id = ? AND workspace_id = ?
                    ORDER BY updated_at DESC, rowid DESC
                    """,
                    (user_id, workspace["id"]),
                ).fetchall()
            ]
        items = [self.refresh_trade_review(user_id, review_id) for review_id in ids]
        return {
            "contract_version": "trade_review_v1",
            "symbol": canonical,
            "items": items,
            "summary": {
                "total": len(items),
                "waiting_data": sum(item["status"] == "waiting_data" for item in items),
                "needs_confirmation": sum(item["status"] == "draft" for item in items),
            },
            "boundary": (
                "价格结果与逻辑结果分开；AI 只能生成草稿，用户确认后才成为正式复盘。"
            ),
        }

    def refresh_pending_reviews(self, limit: int = 200) -> dict[str, Any]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, user_id, status FROM trade_reviews
                WHERE status IN ('waiting_data', 'ready')
                ORDER BY updated_at ASC, rowid ASC LIMIT ?
                """,
                (max(1, min(int(limit), 1000)),),
            ).fetchall()
        refreshed = 0
        promoted = 0
        failed = 0
        for row in rows:
            try:
                item = self.refresh_trade_review(str(row["user_id"]), str(row["id"]))
                refreshed += 1
                if row["status"] == "waiting_data" and item["status"] == "ready":
                    promoted += 1
            except (TradeWorkflowNotFound, TradeWorkflowInvalidState):
                failed += 1
        return {
            "scanned": len(rows),
            "refreshed": refreshed,
            "promoted_to_ready": promoted,
            "failed": failed,
        }

    def get_trade_review(self, user_id: str, review_id: str) -> dict[str, Any]:
        return self.refresh_trade_review(user_id, review_id)

    def get_operation_context(
        self, user_id: str, operation_id: str
    ) -> dict[str, Any]:
        with self.database.connect() as connection:
            operation = self._operation(connection, user_id, operation_id)
            row = connection.execute(
                """
                SELECT * FROM operation_context_snapshots
                WHERE operation_id = ? AND user_id = ? AND workspace_id = ?
                """,
                (operation_id, user_id, operation["workspace_id"]),
            ).fetchone()
            if row is None:
                raise TradeWorkflowNotFound("操作时上下文快照不存在")
            item = dict(row)
            item["snapshot"] = json.loads(item.pop("snapshot_json") or "{}")
            return item

    def prepare_review_agent_evidence(
        self, user_id: str, review_id: str
    ) -> dict[str, Any]:
        review = self.refresh_trade_review(user_id, review_id)
        if not review["can_generate_draft"]:
            raise TradeWorkflowInvalidState(
                "后续交易日数据尚不足，暂不能生成复盘草稿"
            )
        return {
            "type": "trade_review",
            "symbol": review["symbol"],
            "name": review["name"],
            "review_id": review["id"],
            "operation": review["operation"],
            "action_plan": review["action_plan"],
            "frozen_operation_context": review["context_snapshot"],
            "price_observation": review["price_observation"],
            "user_confirmation_required": True,
            "boundary": (
                "价格结果由确定性数据生成；Agent 只分析操作时逻辑、计划偏离、"
                "候选认知偏差和改进项，不得把盈亏直接等同于逻辑对错。"
            ),
        }

    @staticmethod
    def parse_review_agent_answer(answer: str) -> dict[str, Any]:
        text = str(answer or "").strip()
        if not text:
            raise TradeWorkflowInvalidState("Agent 未返回可保存的复盘内容")
        unfenced = text
        if unfenced.startswith("```") and unfenced.endswith("```"):
            unfenced = "\n".join(unfenced.splitlines()[1:-1]).strip()
        try:
            payload = json.loads(unfenced)
        except (TypeError, json.JSONDecodeError):
            payload = None
        if isinstance(payload, dict):
            logic = str(payload.get("logic_result") or "").strip()
            if logic:
                return {
                    "logic_result": logic,
                    "plan_deviation": TradeWorkflowService._clean_text(
                        payload.get("plan_deviation"), 4000
                    ),
                    "bias_tags": [
                        str(item).strip()
                        for item in (payload.get("bias_tags") or [])
                        if str(item).strip()
                    ][:12],
                    "improvement_text": TradeWorkflowService._clean_text(
                        payload.get("improvement_text"), 4000
                    ),
                }

        sections: dict[str, list[str]] = {
            "logic_result": [],
            "plan_deviation": [],
            "bias_tags": [],
            "improvement_text": [],
        }
        aliases = {
            "逻辑结果": "logic_result",
            "逻辑复盘": "logic_result",
            "计划偏离": "plan_deviation",
            "计划偏差": "plan_deviation",
            "候选偏差标签": "bias_tags",
            "偏差标签": "bias_tags",
            "改进记录": "improvement_text",
            "改进建议": "improvement_text",
            "下一步改进": "improvement_text",
        }
        current: str | None = None
        for raw_line in text.splitlines():
            line = raw_line.strip()
            heading = line.lstrip("#").strip().rstrip("：:")
            if heading in aliases:
                current = aliases[heading]
                continue
            if current is not None and line:
                sections[current].append(line.lstrip("-* "))
        logic = "\n".join(sections["logic_result"]).strip() or text
        tags_text = "、".join(sections["bias_tags"])
        tags = [
            item.strip()
            for item in tags_text.replace("，", "、").replace(",", "、").split("、")
            if item.strip()
        ][:12]
        return {
            "logic_result": logic,
            "plan_deviation": "\n".join(sections["plan_deviation"]).strip() or None,
            "bias_tags": tags,
            "improvement_text": "\n".join(sections["improvement_text"]).strip()
            or None,
        }

    def refresh_trade_review(self, user_id: str, review_id: str) -> dict[str, Any]:
        now = utc_now()
        with self.database.connect() as connection:
            review = self._review_by_id(connection, user_id, review_id)
            operation = self._operation(connection, user_id, str(review["operation_id"]))
            context = self._context(connection, user_id, str(review["operation_id"]))
            observation = self._price_observation(
                connection,
                symbol=str(operation["symbol"]),
                operated_at=str(operation["operated_at"]),
                operation_price=str(operation["price"]),
                operation_type=str(operation["operation_type"]),
                fees=operation["fees"],
                horizon_sessions=int(review["horizon_sessions"]),
            )
            if review["status"] in {"waiting_data", "ready"}:
                next_status = "ready" if observation["ready"] else "waiting_data"
                data_status = "fresh" if observation["ready"] else "missing"
                ready_at = now if observation["ready"] else None
                connection.execute(
                    """
                    UPDATE trade_reviews
                    SET status = ?, data_status = ?, ready_at = COALESCE(ready_at, ?),
                        updated_at = ?
                    WHERE id = ? AND user_id = ?
                    """,
                    (next_status, data_status, ready_at, now, review_id, user_id),
                )
                review = self._review_by_id(connection, user_id, review_id)
            packet = self._review_packet(
                connection,
                review=review,
                operation=operation,
                context=context,
                observation=observation,
            )
        return packet

    def save_ai_draft(
        self,
        *,
        user_id: str,
        review_id: str,
        source_run_id: str,
        base_version: int,
        logic_result: str,
        plan_deviation: str | None,
        bias_tags: list[str],
        improvement_text: str | None,
    ) -> dict[str, Any]:
        review_packet = self.refresh_trade_review(user_id, review_id)
        if review_packet["status"] != "ready":
            raise TradeWorkflowInvalidState("后续交易日数据尚不足，暂不能生成复盘草稿")
        price_result = str(review_packet["price_observation"]["summary"])
        self._required_text(logic_result, "逻辑结果", 6000)
        return self._create_review_version(
            user_id=user_id,
            review_id=review_id,
            price_result=price_result,
            logic_result=logic_result,
            plan_deviation=plan_deviation,
            bias_tags=bias_tags,
            improvement_text=improvement_text,
            created_source="ai",
            source_run_id=source_run_id,
            expected_version=base_version,
        )

    def save_user_draft(
        self,
        *,
        user_id: str,
        review_id: str,
        base_version: int,
        price_result: str,
        logic_result: str,
        plan_deviation: str | None,
        bias_tags: list[str],
        improvement_text: str | None,
    ) -> dict[str, Any]:
        with self.database.connect() as connection:
            review = self._review_by_id(connection, user_id, review_id)
            current = self._current_review_version(connection, review)
            if current is None:
                raise TradeWorkflowInvalidState("请先生成复盘草稿")
            if int(current["version_no"]) != base_version:
                raise TradeWorkflowConflict("复盘草稿已更新，请刷新后重试")
        return self._create_review_version(
            user_id=user_id,
            review_id=review_id,
            price_result=self._required_text(price_result, "价格结果", 4000),
            logic_result=self._required_text(logic_result, "逻辑结果", 6000),
            plan_deviation=plan_deviation,
            bias_tags=bias_tags,
            improvement_text=improvement_text,
            created_source="user",
            source_run_id=None,
            expected_version=base_version,
        )

    def confirm_trade_review(
        self, *, user_id: str, review_id: str, base_version: int
    ) -> dict[str, Any]:
        now = utc_now()
        with self.database.connect() as connection:
            review = self._review_by_id(connection, user_id, review_id)
            if review["status"] != "draft":
                raise TradeWorkflowInvalidState("只有待确认草稿可以形成正式复盘")
            current = self._current_review_version(connection, review)
            if current is None or int(current["version_no"]) != base_version:
                raise TradeWorkflowConflict("复盘草稿已更新，请刷新后重试")
            if review["data_status"] != "fresh":
                raise TradeWorkflowInvalidState("后续价格观察仍未完成，暂不能确认复盘")
            connection.execute(
                """
                UPDATE trade_review_versions SET status = 'confirmed'
                WHERE id = ? AND user_id = ?
                """,
                (current["id"], user_id),
            )
            connection.execute(
                """
                UPDATE trade_reviews
                SET status = 'confirmed', confirmed_at = ?, updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (now, now, review_id, user_id),
            )
        return self.get_trade_review(user_id, review_id)

    def archive_trade_review(
        self, *, user_id: str, review_id: str, base_version: int
    ) -> dict[str, Any]:
        now = utc_now()
        with self.database.connect() as connection:
            review = self._review_by_id(connection, user_id, review_id)
            if review["status"] != "confirmed":
                raise TradeWorkflowInvalidState("只有已确认复盘可以归档")
            current = self._current_review_version(connection, review)
            if current is None or int(current["version_no"]) != base_version:
                raise TradeWorkflowConflict("复盘版本已更新，请刷新后重试")
            connection.execute(
                """
                UPDATE trade_reviews
                SET status = 'archived', archived_at = ?, updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (now, now, review_id, user_id),
            )
        return self.get_trade_review(user_id, review_id)

    def _create_review_version(
        self,
        *,
        user_id: str,
        review_id: str,
        price_result: str,
        logic_result: str,
        plan_deviation: str | None,
        bias_tags: list[str],
        improvement_text: str | None,
        created_source: str,
        source_run_id: str | None,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        cleaned_tags = [
            self._required_text(item, "偏差标签", 80)
            for item in bias_tags[:12]
            if str(item).strip()
        ]
        with self.database.connect() as connection:
            review = self._review_by_id(connection, user_id, review_id)
            if review["status"] not in {"ready", "draft"}:
                raise TradeWorkflowInvalidState("当前复盘状态不允许保存草稿")
            current = self._current_review_version(connection, review)
            current_no = int(current["version_no"]) if current is not None else 0
            if expected_version is not None and current_no != expected_version:
                raise TradeWorkflowConflict("复盘草稿已更新，请刷新后重试")
            if source_run_id is not None:
                run = connection.execute(
                    """
                    SELECT id, status FROM runs WHERE id = ? AND user_id = ?
                    """,
                    (source_run_id, user_id),
                ).fetchone()
                if run is None or run["status"] != "completed":
                    raise TradeWorkflowInvalidState("只有已完成的当次 Agent Run 可以生成草稿")
                if current is not None and current["created_source"] == "user":
                    raise TradeWorkflowConflict(
                        "当前草稿已经由用户编辑，不能用重新生成覆盖"
                    )
            version_id = str(uuid4())
            next_no = current_no + 1
            if current is not None:
                connection.execute(
                    """
                    UPDATE trade_review_versions SET status = 'revised'
                    WHERE id = ? AND user_id = ? AND status = 'draft'
                    """,
                    (current["id"], user_id),
                )
            connection.execute(
                """
                INSERT INTO trade_review_versions(
                    id, review_id, user_id, workspace_id, version_no,
                    price_result, logic_result, plan_deviation, bias_tags_json,
                    improvement_text, created_source, source_run_id, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?)
                """,
                (
                    version_id,
                    review_id,
                    user_id,
                    review["workspace_id"],
                    next_no,
                    self._required_text(price_result, "价格结果", 4000),
                    self._required_text(logic_result, "逻辑结果", 6000),
                    self._clean_text(plan_deviation, 4000),
                    json_dumps(cleaned_tags),
                    self._clean_text(improvement_text, 4000),
                    created_source,
                    source_run_id,
                    now,
                ),
            )
            connection.execute(
                """
                UPDATE trade_reviews
                SET status = 'draft', current_version_id = ?, updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (version_id, now, review_id, user_id),
            )
        return self.get_trade_review(user_id, review_id)

    def _review_packet(
        self,
        connection: Any,
        *,
        review: dict[str, Any],
        operation: dict[str, Any],
        context: dict[str, Any],
        observation: dict[str, Any],
    ) -> dict[str, Any]:
        workspace = connection.execute(
            "SELECT symbol, name FROM stock_workspaces WHERE id = ?",
            (review["workspace_id"],),
        ).fetchone()
        plan = None
        if review.get("plan_id"):
            row = connection.execute(
                "SELECT * FROM action_plans WHERE id = ? AND user_id = ?",
                (review["plan_id"], review["user_id"]),
            ).fetchone()
            if row is not None:
                plan = self._plan_row(row)
        versions = connection.execute(
            """
            SELECT * FROM trade_review_versions
            WHERE review_id = ? AND user_id = ?
            ORDER BY version_no DESC, rowid DESC
            """,
            (review["id"], review["user_id"]),
        ).fetchall()
        version_items = [self._review_version_row(row) for row in versions]
        current = next(
            (item for item in version_items if item["id"] == review["current_version_id"]),
            None,
        )
        return {
            **review,
            "symbol": workspace["symbol"] if workspace is not None else operation["symbol"],
            "name": workspace["name"] if workspace is not None else operation["symbol"],
            "operation": operation,
            "action_plan": plan,
            "context_snapshot": context,
            "price_observation": observation,
            "current_version": current,
            "versions": version_items,
            "can_generate_draft": review["status"] == "ready" and observation["ready"],
            "can_confirm": (
                review["status"] == "draft"
                and current is not None
                and review["data_status"] == "fresh"
            ),
        }

    def _price_observation(
        self,
        connection: Any,
        *,
        symbol: str,
        operated_at: str,
        operation_price: str,
        operation_type: str,
        fees: Any,
        horizon_sessions: int,
    ) -> dict[str, Any]:
        operation_date = operated_at[:10]
        rows = connection.execute(
            """
            SELECT timestamp, close, adjusted_close, fetched_at
            FROM market_bars
            WHERE symbol = ? AND interval = '1d'
              AND substr(timestamp, 1, 10) > ?
            ORDER BY timestamp ASC LIMIT ?
            """,
            (symbol, operation_date, horizon_sessions),
        ).fetchall()
        if len(rows) < horizon_sessions:
            return {
                "ready": False,
                "required_sessions": horizon_sessions,
                "available_sessions": len(rows),
                "summary": (
                    f"需要 {horizon_sessions} 个后续交易日，当前只有 {len(rows)} 个；"
                    "暂不生成价格结论。"
                ),
            }
        end = rows[horizon_sessions - 1]
        start_price = Decimal(operation_price)
        end_price = Decimal(str(end["adjusted_close"] or end["close"]))
        change = ((end_price / start_price) - Decimal("1")) * Decimal("100")
        change_text = str(change.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        summary = (
            f"操作价 {self._display_decimal(start_price)}；第 {horizon_sessions} 个后续交易日"
            f"（{str(end['timestamp'])[:10]}）复权收盘 {self._display_decimal(end_price)}，"
            f"价格变化 {change_text}%。该结果只描述操作后的价格路径，"
            "不自动判断操作逻辑正确与否。"
        )
        if fees is None:
            summary += " 操作费用未填写，因此不计算精确净收益。"
        return {
            "ready": True,
            "required_sessions": horizon_sessions,
            "available_sessions": len(rows),
            "operation_type": operation_type,
            "operation_price": self._display_decimal(start_price),
            "end_price": self._display_decimal(end_price),
            "end_date": str(end["timestamp"])[:10],
            "price_change_pct": change_text,
            "fees_complete": fees is not None,
            "summary": summary,
        }

    def _expire_plans(self, connection: Any, user_id: str, workspace_id: str) -> None:
        now = utc_now()
        rows = connection.execute(
            """
            SELECT * FROM action_plans
            WHERE user_id = ? AND workspace_id = ?
              AND status IN ('draft', 'checked', 'saved', 'partially_executed')
              AND expires_at IS NOT NULL AND expires_at < ?
            """,
            (user_id, workspace_id, now),
        ).fetchall()
        for row in rows:
            current = dict(row)
            next_version = int(current["version"]) + 1
            connection.execute(
                """
                UPDATE action_plans
                SET status = 'expired', version = ?, updated_at = ?
                WHERE id = ? AND user_id = ? AND version = ?
                """,
                (next_version, now, current["id"], user_id, current["version"]),
            )
            current.update(status="expired", version=next_version, updated_at=now)
            self._append_plan_history(
                connection,
                plan=current,
                event_type="expired_by_time",
                from_status=str(row["status"]),
                created_at=now,
            )

    @staticmethod
    def _check_plan(plan: dict[str, Any]) -> dict[str, Any]:
        missing: list[str] = []
        if not str(plan.get("trigger_text") or "").strip():
            missing.append("用户触发条件")
        has_target = any(
            plan.get(key)
            for key in ("target_quantity", "target_amount", "target_position_percent")
        )
        return {
            "passed": not missing,
            "missing_items": missing,
            "checks": [
                "条件由用户填写",
                (
                    "已记录目标数量、金额或仓位"
                    if has_target
                    else "未填写数量、金额或仓位；计划仍可保存，但执行完成度不能自动判断"
                ),
                "未生成买卖建议",
                "不会自动执行交易",
            ],
        }

    @staticmethod
    def _resolve_thesis(
        connection: Any,
        *,
        user_id: str,
        workspace_id: str,
        thesis_version_id: str | None,
    ) -> Any:
        if thesis_version_id:
            row = connection.execute(
                """
                SELECT id FROM thesis_versions
                WHERE id = ? AND user_id = ? AND workspace_id = ?
                """,
                (thesis_version_id, user_id, workspace_id),
            ).fetchone()
            if row is None:
                raise TradeWorkflowInvalidState("关联判断不属于当前股票空间")
            return row
        return connection.execute(
            """
            SELECT id FROM thesis_versions
            WHERE user_id = ? AND workspace_id = ? AND status = 'active'
            ORDER BY version_no DESC LIMIT 1
            """,
            (user_id, workspace_id),
        ).fetchone()

    def _append_plan_history(
        self,
        connection: Any,
        *,
        plan: dict[str, Any],
        event_type: str,
        from_status: str | None,
        created_at: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO action_plan_history(
                id, plan_id, user_id, workspace_id, version, event_type,
                from_status, to_status, snapshot_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                plan["id"],
                plan["user_id"],
                plan["workspace_id"],
                plan["version"],
                event_type,
                from_status,
                plan["status"],
                json_dumps(self._plan_row(plan)),
                created_at,
            ),
        )

    def _workspace(self, connection: Any, user_id: str, symbol: str) -> Any:
        row = connection.execute(
            "SELECT * FROM stock_workspaces WHERE user_id = ? AND symbol = ?",
            (user_id, symbol),
        ).fetchone()
        if row is None:
            raise TradeWorkflowNotFound("股票研究空间不存在")
        return row

    def _plan_by_id(self, connection: Any, user_id: str, plan_id: str) -> dict[str, Any]:
        row = connection.execute(
            "SELECT * FROM action_plans WHERE id = ? AND user_id = ?",
            (plan_id, user_id),
        ).fetchone()
        if row is None:
            raise TradeWorkflowNotFound("操作计划不存在")
        return dict(row)

    def _review_by_id(
        self, connection: Any, user_id: str, review_id: str
    ) -> dict[str, Any]:
        row = connection.execute(
            "SELECT * FROM trade_reviews WHERE id = ? AND user_id = ?",
            (review_id, user_id),
        ).fetchone()
        if row is None:
            raise TradeWorkflowNotFound("交易复盘不存在")
        return dict(row)

    def _operation(self, connection: Any, user_id: str, operation_id: str) -> dict[str, Any]:
        row = connection.execute(
            "SELECT * FROM position_operations WHERE id = ? AND user_id = ?",
            (operation_id, user_id),
        ).fetchone()
        if row is None:
            raise TradeWorkflowNotFound("复盘关联的操作不存在")
        return dict(row)

    def _context(self, connection: Any, user_id: str, operation_id: str) -> dict[str, Any]:
        row = connection.execute(
            """
            SELECT snapshot_json FROM operation_context_snapshots
            WHERE operation_id = ? AND user_id = ?
            """,
            (operation_id, user_id),
        ).fetchone()
        if row is None:
            return {
                "data_completeness": {
                    "status": "partial",
                    "missing_items": ["操作时上下文快照"],
                }
            }
        return json.loads(row["snapshot_json"] or "{}")

    @staticmethod
    def _current_review_version(connection: Any, review: dict[str, Any]) -> Any:
        if not review.get("current_version_id"):
            return None
        return connection.execute(
            """
            SELECT * FROM trade_review_versions
            WHERE id = ? AND user_id = ? AND review_id = ?
            """,
            (review["current_version_id"], review["user_id"], review["id"]),
        ).fetchone()

    @staticmethod
    def _plan_row(row: Any) -> dict[str, Any]:
        item = dict(row)
        item["check_result"] = json.loads(item.pop("check_result_json") or "{}")
        return item

    @staticmethod
    def _plan_history_row(row: Any) -> dict[str, Any]:
        item = dict(row)
        item["snapshot"] = json.loads(item.pop("snapshot_json") or "{}")
        return item

    @staticmethod
    def _review_version_row(row: Any) -> dict[str, Any]:
        item = dict(row)
        item["bias_tags"] = json.loads(item.pop("bias_tags_json") or "[]")
        return item

    @staticmethod
    def _require_version(current: dict[str, Any], base_version: int) -> None:
        if int(current["version"]) != base_version:
            raise TradeWorkflowConflict("操作计划已更新，请刷新后重试")

    def _action(self, value: str) -> str:
        if value not in self.PLAN_ACTIONS:
            raise TradeWorkflowInvalidState("操作计划方向不受支持")
        return value

    @staticmethod
    def _required_text(value: Any, label: str, max_length: int) -> str:
        text = str(value or "").strip()
        if not text:
            raise TradeWorkflowInvalidState(f"{label}不能为空")
        if len(text) > max_length:
            raise TradeWorkflowInvalidState(f"{label}过长")
        return text

    @staticmethod
    def _clean_text(value: Any, max_length: int) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        return text[:max_length]

    def _optional_positive(
        self, value: Any, label: str, maximum: Decimal | None = None
    ) -> Decimal | None:
        if value is None or str(value).strip() == "":
            return None
        try:
            parsed = Decimal(str(value).strip())
        except (InvalidOperation, ValueError) as exc:
            raise TradeWorkflowInvalidState(f"{label}必须是有效数字") from exc
        if not parsed.is_finite() or parsed <= 0:
            raise TradeWorkflowInvalidState(f"{label}必须大于 0")
        if maximum is not None and parsed > maximum:
            raise TradeWorkflowInvalidState(f"{label}不能超过 {maximum}")
        return parsed.quantize(self._DECIMAL_QUANT, rounding=ROUND_HALF_UP)

    @staticmethod
    def _optional_datetime(value: Any, label: str) -> str | None:
        if value is None or not str(value).strip():
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise TradeWorkflowInvalidState(f"{label}格式无效") from exc
        if parsed.tzinfo is None:
            raise TradeWorkflowInvalidState(f"{label}必须包含时区")
        return parsed.isoformat()

    @staticmethod
    def _decimal_text(value: Decimal | None) -> str | None:
        if value is None:
            return None
        return format(value, "f")

    @staticmethod
    def _display_decimal(value: Decimal) -> str:
        return format(value.normalize(), "f")
