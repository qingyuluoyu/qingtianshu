from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
from typing import Any
from uuid import uuid4

from app.catalog import INDEX_CATALOG, normalize_symbol
from app.db import Database
from app.utils import json_dumps, utc_now


class PositionLedgerNotFound(ValueError):
    pass


class PositionLedgerInvalidState(ValueError):
    pass


class PositionLedgerConflict(ValueError):
    pass


class PositionLedgerService:
    """Immutable position facts with deterministic moving-average snapshots."""

    CONTRACT_VERSION = "position_ledger_v1"
    CALCULATION_VERSION = "moving_weighted_average_v1"
    OPERATION_TYPES = {"buy", "add", "reduce", "sell"}
    ADJUSTMENT_TYPES = {
        "quantity_correction",
        "cost_correction",
        "corporate_action",
        "other",
    }
    _PRICE_QUANT = Decimal("0.000001")
    _QUANTITY_QUANT = Decimal("0.000001")
    _AMOUNT_QUANT = Decimal("0.0001")

    def __init__(self, database: Database) -> None:
        self.database = database

    def get_position(self, user_id: str, symbol: str) -> dict[str, Any]:
        canonical = normalize_symbol(symbol)
        with self.database.connect() as connection:
            workspace = self._workspace(connection, user_id, canonical)
            opening = connection.execute(
                """
                SELECT * FROM position_openings
                WHERE user_id = ? AND workspace_id = ?
                """,
                (user_id, workspace["id"]),
            ).fetchone()
            if opening is None:
                return self._empty_packet(workspace)
            snapshot = connection.execute(
                """
                SELECT * FROM position_snapshots
                WHERE user_id = ? AND workspace_id = ?
                ORDER BY created_at DESC, rowid DESC LIMIT 1
                """,
                (user_id, workspace["id"]),
            ).fetchone()
            operations = self._operation_rows(
                connection, user_id=user_id, workspace_id=str(workspace["id"])
            )
            adjustments = connection.execute(
                """
                SELECT * FROM position_adjustments
                WHERE user_id = ? AND workspace_id = ?
                ORDER BY effective_at ASC, created_at ASC, rowid ASC
                """,
                (user_id, workspace["id"]),
            ).fetchall()
            snapshots = connection.execute(
                """
                SELECT * FROM position_snapshots
                WHERE user_id = ? AND workspace_id = ?
                ORDER BY created_at DESC, rowid DESC LIMIT 20
                """,
                (user_id, workspace["id"]),
            ).fetchall()
        return self._packet(
            workspace=workspace,
            opening=dict(opening),
            snapshot=dict(snapshot) if snapshot is not None else None,
            operations=operations,
            adjustments=[dict(row) for row in adjustments],
            snapshots=[dict(row) for row in snapshots],
        )

    def create_opening(
        self,
        *,
        user_id: str,
        symbol: str,
        as_of_date: str,
        quantity: str,
        cost_price: str,
        fees: str | None,
        note: str | None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        canonical = normalize_symbol(symbol)
        parsed_date = self._date(as_of_date, "期初持仓日期")
        quantity_value = self._positive_decimal(quantity, "期初持仓数量")
        cost_value = self._non_negative_decimal(cost_price, "期初持仓成本")
        fee_value = self._optional_non_negative_decimal(fees, "期初费用")
        now = utc_now()
        with self.database.connect() as connection:
            workspace = self._workspace(connection, user_id, canonical)
            repeated = connection.execute(
                """
                SELECT id FROM position_openings
                WHERE user_id = ? AND idempotency_key = ?
                """,
                (user_id, idempotency_key),
            ).fetchone()
            if repeated is not None:
                return self.get_position(user_id, canonical)
            existing = connection.execute(
                """
                SELECT id FROM position_openings
                WHERE user_id = ? AND workspace_id = ?
                """,
                (user_id, workspace["id"]),
            ).fetchone()
            if existing is not None:
                raise PositionLedgerConflict("每个股票空间只能录入一个有效期初持仓")
            opening_id = str(uuid4())
            connection.execute(
                """
                INSERT INTO position_openings(
                    id, workspace_id, user_id, symbol, as_of_date,
                    quantity, cost_price, fees, note, idempotency_key, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    opening_id,
                    workspace["id"],
                    user_id,
                    canonical,
                    parsed_date.isoformat(),
                    self._quantity_text(quantity_value),
                    self._price_text(cost_value),
                    self._amount_text(fee_value) if fee_value is not None else None,
                    self._clean_text(note, 1000),
                    idempotency_key,
                    now,
                ),
            )
            self._mark_workspace_holding(
                connection, workspace=workspace, user_id=user_id, now=now
            )
            self._recalculate_and_save(
                connection,
                user_id=user_id,
                workspace=workspace,
                source_event_type="opening",
                source_event_id=opening_id,
                snapshot_at=f"{parsed_date.isoformat()}T00:00:00+08:00",
            )
        return self.get_position(user_id, canonical)

    def record_operation(
        self,
        *,
        user_id: str,
        symbol: str,
        operation_type: str,
        operated_at: str,
        price: str,
        quantity: str,
        fees: str | None,
        reason_text: str,
        plan_id: str | None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        canonical = normalize_symbol(symbol)
        if operation_type not in self.OPERATION_TYPES:
            raise PositionLedgerInvalidState("操作类型不受支持")
        operation_time = self._datetime(operated_at, "操作时间")
        price_value = self._positive_decimal(price, "操作价格")
        quantity_value = self._positive_decimal(quantity, "操作数量")
        fee_value = self._optional_non_negative_decimal(fees, "操作费用")
        reason = self._required_text(reason_text, "操作原因", 1200)
        now = utc_now()
        with self.database.connect() as connection:
            workspace = self._workspace(connection, user_id, canonical)
            normalized_plan_id = self._clean_text(plan_id, 80)
            repeated = connection.execute(
                """
                SELECT id FROM position_operations
                WHERE user_id = ? AND idempotency_key = ?
                """,
                (user_id, idempotency_key),
            ).fetchone()
            if repeated is not None:
                return self.get_position(user_id, canonical)
            plan = self._validated_plan(
                connection,
                user_id=user_id,
                workspace_id=str(workspace["id"]),
                operation_type=operation_type,
                plan_id=normalized_plan_id,
            )
            opening = self._opening(connection, user_id, str(workspace["id"]))
            if operation_time.date() < date.fromisoformat(str(opening["as_of_date"])):
                raise PositionLedgerInvalidState("操作时间不能早于期初持仓日期")
            operation_id = str(uuid4())
            connection.execute(
                """
                INSERT INTO position_operations(
                    id, workspace_id, user_id, symbol, operation_type,
                    operated_at, price, quantity, fees, reason_text,
                    plan_id, idempotency_key, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    operation_id,
                    workspace["id"],
                    user_id,
                    canonical,
                    operation_type,
                    operation_time.isoformat(),
                    self._price_text(price_value),
                    self._quantity_text(quantity_value),
                    self._amount_text(fee_value) if fee_value is not None else None,
                    reason,
                    normalized_plan_id,
                    idempotency_key,
                    now,
                ),
            )
            calculated = self._recalculate_and_save(
                connection,
                user_id=user_id,
                workspace=workspace,
                source_event_type="operation",
                source_event_id=operation_id,
                snapshot_at=operation_time.isoformat(),
            )
            self._capture_operation_context_and_review(
                connection,
                user_id=user_id,
                workspace=workspace,
                operation_id=operation_id,
                operation_type=operation_type,
                operation_time=operation_time,
                price=self._price_text(price_value),
                quantity=self._quantity_text(quantity_value),
                fees=(
                    self._amount_text(fee_value) if fee_value is not None else None
                ),
                reason_text=reason,
                plan=plan,
                position_snapshot=calculated,
                created_at=now,
            )
            if plan is not None:
                self._advance_plan_after_operation(
                    connection,
                    plan=plan,
                    user_id=user_id,
                    created_at=now,
                )
        return self.get_position(user_id, canonical)

    def revise_operation(
        self,
        *,
        user_id: str,
        operation_id: str,
        base_revision: int,
        price: str,
        quantity: str,
        fees: str | None,
        reason_text: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        price_value = self._positive_decimal(price, "修正价格")
        quantity_value = self._positive_decimal(quantity, "修正数量")
        fee_value = self._optional_non_negative_decimal(fees, "修正费用")
        reason = self._required_text(reason_text, "修正原因", 1200)
        now = utc_now()
        symbol: str | None = None
        with self.database.connect() as connection:
            repeated = connection.execute(
                """
                SELECT operation_id FROM operation_revisions
                WHERE user_id = ? AND idempotency_key = ?
                """,
                (user_id, idempotency_key),
            ).fetchone()
            if repeated is not None:
                operation = connection.execute(
                    """
                    SELECT symbol FROM position_operations
                    WHERE id = ? AND user_id = ?
                    """,
                    (repeated["operation_id"], user_id),
                ).fetchone()
                if operation is None:
                    raise PositionLedgerNotFound("操作记录不存在")
                symbol = str(operation["symbol"])
            else:
                operation = connection.execute(
                    """
                    SELECT * FROM position_operations
                    WHERE id = ? AND user_id = ?
                    """,
                    (operation_id, user_id),
                ).fetchone()
                if operation is None:
                    raise PositionLedgerNotFound("操作记录不存在")
                latest = connection.execute(
                    """
                    SELECT COALESCE(MAX(revision_no), 0) AS revision_no
                    FROM operation_revisions
                    WHERE operation_id = ? AND user_id = ?
                    """,
                    (operation_id, user_id),
                ).fetchone()
                current_revision = int(latest["revision_no"] or 0)
                if int(base_revision) != current_revision:
                    raise PositionLedgerConflict(
                        f"操作记录已更新，当前修订版本为 {current_revision}"
                    )
                revision_id = str(uuid4())
                connection.execute(
                    """
                    INSERT INTO operation_revisions(
                        id, operation_id, workspace_id, user_id, revision_no,
                        price, quantity, fees, reason_text,
                        idempotency_key, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        revision_id,
                        operation_id,
                        operation["workspace_id"],
                        user_id,
                        current_revision + 1,
                        self._price_text(price_value),
                        self._quantity_text(quantity_value),
                        self._amount_text(fee_value)
                        if fee_value is not None
                        else None,
                        reason,
                        idempotency_key,
                        now,
                    ),
                )
                workspace = self._workspace_by_id(
                    connection, user_id, str(operation["workspace_id"])
                )
                self._recalculate_and_save(
                    connection,
                    user_id=user_id,
                    workspace=workspace,
                    source_event_type="operation_revision",
                    source_event_id=revision_id,
                    snapshot_at=now,
                )
                symbol = str(operation["symbol"])
        if symbol is None:
            raise PositionLedgerNotFound("操作记录不存在")
        return self.get_position(user_id, symbol)

    def record_adjustment(
        self,
        *,
        user_id: str,
        symbol: str,
        adjustment_type: str,
        effective_at: str,
        quantity_delta: str,
        cost_delta: str,
        reason_text: str,
        evidence_text: str | None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        canonical = normalize_symbol(symbol)
        if adjustment_type not in self.ADJUSTMENT_TYPES:
            raise PositionLedgerInvalidState("调整类型不受支持")
        effective_time = self._datetime(effective_at, "调整生效时间")
        quantity_value = self._decimal(quantity_delta, "数量调整")
        cost_value = self._decimal(cost_delta, "成本调整")
        if quantity_value == 0 and cost_value == 0:
            raise PositionLedgerInvalidState("数量调整和成本调整不能同时为零")
        reason = self._required_text(reason_text, "调整原因", 1200)
        now = utc_now()
        with self.database.connect() as connection:
            workspace = self._workspace(connection, user_id, canonical)
            repeated = connection.execute(
                """
                SELECT id FROM position_adjustments
                WHERE user_id = ? AND idempotency_key = ?
                """,
                (user_id, idempotency_key),
            ).fetchone()
            if repeated is not None:
                return self.get_position(user_id, canonical)
            opening = self._opening(connection, user_id, str(workspace["id"]))
            if effective_time.date() < date.fromisoformat(str(opening["as_of_date"])):
                raise PositionLedgerInvalidState("调整生效时间不能早于期初持仓日期")
            adjustment_id = str(uuid4())
            connection.execute(
                """
                INSERT INTO position_adjustments(
                    id, workspace_id, user_id, symbol, adjustment_type,
                    effective_at, quantity_delta, cost_delta, reason_text,
                    evidence_text, idempotency_key, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    adjustment_id,
                    workspace["id"],
                    user_id,
                    canonical,
                    adjustment_type,
                    effective_time.isoformat(),
                    self._quantity_text(quantity_value),
                    self._amount_text(cost_value),
                    reason,
                    self._clean_text(evidence_text, 1200),
                    idempotency_key,
                    now,
                ),
            )
            self._recalculate_and_save(
                connection,
                user_id=user_id,
                workspace=workspace,
                source_event_type="adjustment",
                source_event_id=adjustment_id,
                snapshot_at=effective_time.isoformat(),
            )
        return self.get_position(user_id, canonical)

    def _recalculate_and_save(
        self,
        connection: Any,
        *,
        user_id: str,
        workspace: Any,
        source_event_type: str,
        source_event_id: str,
        snapshot_at: str,
    ) -> dict[str, Any]:
        opening = self._opening(connection, user_id, str(workspace["id"]))
        operations = self._operation_rows(
            connection, user_id=user_id, workspace_id=str(workspace["id"])
        )
        adjustments = [
            dict(row)
            for row in connection.execute(
                """
                SELECT * FROM position_adjustments
                WHERE user_id = ? AND workspace_id = ?
                ORDER BY effective_at ASC, created_at ASC, rowid ASC
                """,
                (user_id, workspace["id"]),
            ).fetchall()
        ]
        calculated = self._calculate(dict(opening), operations, adjustments)
        snapshot_id = str(uuid4())
        connection.execute(
            """
            INSERT INTO position_snapshots(
                id, workspace_id, user_id, symbol, snapshot_at,
                source_event_type, source_event_id, quantity, cost_basis,
                average_cost, realized_gross_pnl, realized_net_pnl,
                known_fees, fees_complete, data_status, warnings_json,
                calculation_version, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                workspace["id"],
                user_id,
                workspace["symbol"],
                snapshot_at,
                source_event_type,
                source_event_id,
                calculated["quantity"],
                calculated["cost_basis"],
                calculated["average_cost"],
                calculated["realized_gross_pnl"],
                calculated["realized_net_pnl"],
                calculated["known_fees"],
                int(calculated["fees_complete"]),
                calculated["data_status"],
                json_dumps(calculated["warnings"]),
                self.CALCULATION_VERSION,
                utc_now(),
            ),
        )
        return calculated

    def _validated_plan(
        self,
        connection: Any,
        *,
        user_id: str,
        workspace_id: str,
        operation_type: str,
        plan_id: str | None,
    ) -> dict[str, Any] | None:
        if plan_id is None:
            return None
        row = connection.execute(
            """
            SELECT * FROM action_plans
            WHERE id = ? AND user_id = ? AND workspace_id = ?
            """,
            (plan_id, user_id, workspace_id),
        ).fetchone()
        if row is None:
            raise PositionLedgerNotFound("关联的操作计划不存在")
        item = dict(row)
        if item.get("status") not in {"saved", "partially_executed"}:
            raise PositionLedgerInvalidState("只有已保存或部分执行的计划可以关联操作")
        if item.get("action_type") != operation_type:
            raise PositionLedgerInvalidState("实际操作方向与关联计划不一致")
        return item

    def _capture_operation_context_and_review(
        self,
        connection: Any,
        *,
        user_id: str,
        workspace: Any,
        operation_id: str,
        operation_type: str,
        operation_time: datetime,
        price: str,
        quantity: str,
        fees: str | None,
        reason_text: str,
        plan: dict[str, Any] | None,
        position_snapshot: dict[str, Any],
        created_at: str,
    ) -> None:
        thesis_row = connection.execute(
            """
            SELECT * FROM thesis_versions
            WHERE user_id = ? AND workspace_id = ? AND status = 'active'
            ORDER BY version_no DESC LIMIT 1
            """,
            (user_id, workspace["id"]),
        ).fetchone()
        thesis = dict(thesis_row) if thesis_row is not None else None
        if thesis is not None:
            thesis["watch_items"] = json.loads(
                thesis.pop("watch_items_json") or "[]"
            )
            thesis["recheck_conditions"] = json.loads(
                thesis.pop("recheck_conditions_json") or "[]"
            )
        market_bar = connection.execute(
            """
            SELECT symbol, interval, timestamp, open, high, low, close,
                   adjusted_close, volume, source, fetched_at
            FROM market_bars
            WHERE symbol = ? AND interval = '1d'
              AND substr(timestamp, 1, 10) < ?
            ORDER BY timestamp DESC LIMIT 1
            """,
            (workspace["symbol"], operation_time.date().isoformat()),
        ).fetchone()
        report_rows = connection.execute(
            """
            SELECT id, symbol, name, title, summary, status, evidence_json,
                   market_timestamp, generated_at
            FROM research_reports
            WHERE symbol = ?
            ORDER BY generated_at DESC LIMIT 50
            """,
            (workspace["symbol"],),
        ).fetchall()
        report_row = self._latest_row_before(
            report_rows, "generated_at", operation_time
        )
        valuation_rows = connection.execute(
            """
            SELECT * FROM valuation_snapshots
            WHERE symbol = ?
            ORDER BY market_timestamp DESC, fetched_at DESC LIMIT 50
            """,
            (workspace["symbol"],),
        ).fetchall()
        valuation_row = self._latest_row_before(
            valuation_rows, "market_timestamp", operation_time
        )
        market_indices = self._market_index_context(
            connection, workspace=workspace, operation_time=operation_time
        )
        change_rows = connection.execute(
            """
            SELECT * FROM research_change_events
            WHERE symbol = ?
            ORDER BY created_at DESC LIMIT 50
            """,
            (workspace["symbol"],),
        ).fetchall()
        change_row = self._latest_row_before(
            change_rows, "created_at", operation_time
        )
        report = dict(report_row) if report_row is not None else None
        report_evidence: dict[str, Any] = {}
        if report is not None:
            try:
                report_evidence = json.loads(report.pop("evidence_json") or "{}")
            except json.JSONDecodeError:
                report_evidence = {}
        important_change = dict(change_row) if change_row is not None else None
        if important_change is not None:
            try:
                important_change["payload"] = json.loads(
                    important_change.pop("payload_json") or "{}"
                )
            except json.JSONDecodeError:
                important_change["payload"] = {}
        missing_items: list[str] = []
        if thesis is None:
            missing_items.append("操作时没有正式判断")
        if plan is None:
            missing_items.append("本次操作未关联已保存计划")
        if market_bar is None:
            missing_items.append("操作时没有可冻结的已完成日线")
        if report_row is None:
            missing_items.append("操作时没有可冻结的研究报告")
        if valuation_row is None:
            missing_items.append("操作时没有可冻结的估值快照")
        if not market_indices:
            missing_items.append("操作时没有可冻结的市场指数背景")
        if fees is None:
            missing_items.append("操作费用未填写")
        sources = self._context_sources(
            market_bar=market_bar,
            market_indices=market_indices,
            valuation=valuation_row,
            report=report,
            change=important_change,
        )
        for source in self._evidence_sources(report_evidence):
            if source not in sources:
                sources.append(source)
        context = {
            "operation": {
                "id": operation_id,
                "operation_type": operation_type,
                "operated_at": operation_time.isoformat(),
                "price": price,
                "quantity": quantity,
                "fees": fees,
                "reason_text": reason_text,
            },
            "action_plan": self._context_plan(plan),
            "thesis": self._context_thesis(thesis),
            "market_bar": dict(market_bar) if market_bar is not None else None,
            "market_indices": market_indices,
            "industry_background": self._industry_context(report_evidence),
            "valuation": dict(valuation_row) if valuation_row is not None else None,
            "important_change": important_change,
            "research_report": report,
            "position_snapshot": position_snapshot,
            "sources": sources,
            "data_completeness": {
                "status": "complete" if not missing_items else "partial",
                "missing_items": missing_items,
            },
        }
        connection.execute(
            """
            INSERT INTO operation_context_snapshots(
                id, operation_id, workspace_id, user_id,
                plan_id, thesis_version_id, snapshot_json, data_time,
                snapshot_version, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'trade_context_v2', ?)
            """,
            (
                str(uuid4()),
                operation_id,
                workspace["id"],
                user_id,
                plan.get("id") if plan else None,
                thesis.get("id") if thesis else None,
                json_dumps(context),
                operation_time.isoformat(),
                created_at,
            ),
        )
        if operation_type not in {"reduce", "sell"}:
            return
        review_id = str(uuid4())
        connection.execute(
            """
            INSERT INTO trade_reviews(
                id, user_id, workspace_id, operation_id, plan_id,
                status, horizon_sessions, data_status, current_version_id,
                ready_at, confirmed_at, archived_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'waiting_data', 3, ?, NULL,
                      NULL, NULL, NULL, ?, ?)
            """,
            (
                review_id,
                user_id,
                workspace["id"],
                operation_id,
                plan.get("id") if plan else None,
                "missing",
                created_at,
                created_at,
            ),
        )
        tags = json.loads(workspace["attention_tags_json"] or "[]")
        if "待复盘" not in tags:
            tags.append("待复盘")
        connection.execute(
            """
            UPDATE stock_workspaces
            SET workflow_status = 'waiting_data', attention_tags_json = ?,
                version = version + 1, updated_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (json_dumps(tags), created_at, workspace["id"], user_id),
        )

    def _advance_plan_after_operation(
        self,
        connection: Any,
        *,
        plan: dict[str, Any],
        user_id: str,
        created_at: str,
    ) -> None:
        target_quantity = (
            self._decimal(plan["target_quantity"], "计划目标数量")
            if plan.get("target_quantity")
            else None
        )
        target_amount = (
            self._decimal(plan["target_amount"], "计划目标金额")
            if plan.get("target_amount")
            else None
        )
        operations = self._operation_rows(
            connection,
            user_id=user_id,
            workspace_id=str(plan["workspace_id"]),
        )
        linked = [item for item in operations if item.get("plan_id") == plan["id"]]
        cumulative_quantity = sum(
            (
                self._decimal(item["effective_quantity"], "累计操作数量")
                for item in linked
            ),
            Decimal("0"),
        )
        cumulative_amount = sum(
            (
                self._decimal(item["effective_price"], "累计操作价格")
                * self._decimal(item["effective_quantity"], "累计操作数量")
                for item in linked
            ),
            Decimal("0"),
        )
        completed = (
            cumulative_quantity >= target_quantity
            if target_quantity is not None
            else cumulative_amount >= target_amount
            if target_amount is not None
            else False
        )
        next_status = "executed" if completed else "partially_executed"
        next_version = int(plan["version"]) + 1
        updated = {
            **plan,
            "status": next_status,
            "version": next_version,
            "updated_at": created_at,
            "execution_progress": {
                "cumulative_quantity": self._quantity_text(cumulative_quantity),
                "cumulative_amount": self._amount_text(cumulative_amount),
                "target_position_percent_verified": False,
            },
        }
        connection.execute(
            """
            UPDATE action_plans
            SET status = ?, version = ?, updated_at = ?
            WHERE id = ? AND user_id = ? AND version = ?
            """,
            (
                next_status,
                next_version,
                created_at,
                plan["id"],
                user_id,
                plan["version"],
            ),
        )
        connection.execute(
            """
            INSERT INTO action_plan_history(
                id, plan_id, user_id, workspace_id, version, event_type,
                from_status, to_status, snapshot_json, created_at
            ) VALUES (?, ?, ?, ?, ?, 'operation_linked', ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                plan["id"],
                user_id,
                plan["workspace_id"],
                next_version,
                plan["status"],
                next_status,
                json_dumps(updated),
                created_at,
            ),
        )

    def _market_index_context(
        self, connection: Any, *, workspace: Any, operation_time: datetime
    ) -> list[dict[str, Any]]:
        market = str(workspace["market"] or "")
        symbol = str(workspace["symbol"])
        if symbol.endswith((".SS", ".SZ")) or "A股" in market:
            groups = {"china"}
        elif market in {"美股", "美国"} or not symbol.startswith("^"):
            groups = {"us"}
        else:
            groups = {"china", "us"}
        output: list[dict[str, Any]] = []
        for index in INDEX_CATALOG:
            if index["group"] not in groups:
                continue
            row = connection.execute(
                """
                SELECT symbol, interval, timestamp, open, high, low, close,
                       adjusted_close, volume, source, fetched_at
                FROM market_bars
                WHERE symbol = ? AND interval = '1d'
                  AND substr(timestamp, 1, 10) < ?
                ORDER BY timestamp DESC LIMIT 1
                """,
                (index["symbol"], operation_time.date().isoformat()),
            ).fetchone()
            if row is None:
                continue
            output.append({**dict(row), "name": index["name"], "group": index["group"]})
        return output

    @classmethod
    def _latest_row_before(
        cls, rows: list[Any], field: str, boundary: datetime
    ) -> Any | None:
        for row in rows:
            value = row[field]
            if not value:
                continue
            try:
                parsed = cls._datetime(str(value), field)
            except PositionLedgerInvalidState:
                continue
            if parsed <= boundary:
                return row
        return None

    @staticmethod
    def _industry_context(evidence: dict[str, Any]) -> dict[str, Any] | None:
        market_context = evidence.get("stock_market_context") or {}
        peers = evidence.get("peer_comparison") or {}
        industry_index = market_context.get("exact_industry_index")
        mapping = market_context.get("industry_mapping")
        if not industry_index and not mapping and not peers:
            return None
        return {
            "exact_industry_index": industry_index,
            "industry_mapping": mapping,
            "peer_group": {
                "label": peers.get("group_label"),
                "selection_basis": peers.get("selection_basis"),
                "as_of": peers.get("as_of"),
            }
            if peers
            else None,
        }

    @staticmethod
    def _evidence_sources(evidence: dict[str, Any]) -> list[dict[str, Any]]:
        claims = (evidence.get("research_claims") or {}).get("claims") or []
        output: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for claim in claims:
            source_name = str(
                claim.get("source_name") or claim.get("source") or "研究证据"
            ).strip()
            source_url = str(claim.get("source_url") or "").strip()
            data_time = str(
                claim.get("data_time") or claim.get("report_period") or ""
            ).strip()
            key = (source_name, source_url, data_time)
            if key in seen:
                continue
            seen.add(key)
            output.append(
                {
                    "source_name": source_name,
                    "source_url": source_url or None,
                    "data_time": data_time or None,
                }
            )
            if len(output) >= 12:
                break
        return output

    @classmethod
    def _context_sources(
        cls,
        *,
        market_bar: Any | None,
        market_indices: list[dict[str, Any]],
        valuation: Any | None,
        report: dict[str, Any] | None,
        change: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []

        def add(source_name: Any, source_url: Any, data_time: Any) -> None:
            if not source_name and not source_url:
                return
            item = {
                "source_name": str(source_name or "研究数据"),
                "source_url": str(source_url) if source_url else None,
                "data_time": str(data_time) if data_time else None,
            }
            if item not in output:
                output.append(item)

        if market_bar is not None:
            row = dict(market_bar)
            add(row.get("source"), None, row.get("timestamp"))
        for row in market_indices:
            add(row.get("source"), None, row.get("timestamp"))
        if valuation is not None:
            row = dict(valuation)
            add(row.get("source"), row.get("source_url"), row.get("market_timestamp"))
        if report is not None:
            add("已保存研究报告", None, report.get("generated_at"))
        if change is not None:
            add("研究变化记录", None, change.get("created_at"))
        return output

    @staticmethod
    def _context_plan(plan: dict[str, Any] | None) -> dict[str, Any] | None:
        if plan is None:
            return None
        return {
            key: plan.get(key)
            for key in (
                "id",
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
            )
        }

    @staticmethod
    def _context_thesis(thesis: dict[str, Any] | None) -> dict[str, Any] | None:
        if thesis is None:
            return None
        return {
            key: thesis.get(key)
            for key in (
                "id",
                "version_no",
                "reason_text",
                "watch_items",
                "recheck_conditions",
                "source",
                "confirmed_at",
                "created_at",
            )
        }

    def _calculate(
        self,
        opening: dict[str, Any],
        operations: list[dict[str, Any]],
        adjustments: list[dict[str, Any]],
    ) -> dict[str, Any]:
        quantity = self._decimal(opening["quantity"], "期初持仓数量")
        opening_cost = self._decimal(opening["cost_price"], "期初持仓成本")
        cost_basis = quantity * opening_cost
        known_fees = Decimal("0")
        fees_complete = opening.get("fees") is not None
        if opening.get("fees") is not None:
            opening_fees = self._decimal(opening["fees"], "期初费用")
            cost_basis += opening_fees
            known_fees += opening_fees
        realized_gross = Decimal("0")
        realized_net = Decimal("0")
        events: list[tuple[datetime, int, dict[str, Any]]] = []
        for operation in operations:
            events.append(
                (
                    self._datetime(operation["operated_at"], "操作时间"),
                    0,
                    {"kind": "operation", **operation},
                )
            )
        for adjustment in adjustments:
            events.append(
                (
                    self._datetime(adjustment["effective_at"], "调整生效时间"),
                    1,
                    {"kind": "adjustment", **adjustment},
                )
            )
        events.sort(key=lambda item: (item[0], item[1], str(item[2].get("created_at"))))

        for _, _, event in events:
            if event["kind"] == "adjustment":
                quantity += self._decimal(event["quantity_delta"], "数量调整")
                cost_basis += self._decimal(event["cost_delta"], "成本调整")
                if quantity < 0:
                    raise PositionLedgerInvalidState("调整后持仓数量不能为负数")
                if cost_basis < 0:
                    raise PositionLedgerInvalidState("调整后持仓成本不能为负数")
                if quantity == 0:
                    cost_basis = Decimal("0")
                continue

            operation_quantity = self._decimal(event["effective_quantity"], "操作数量")
            operation_price = self._decimal(event["effective_price"], "操作价格")
            fee = (
                self._decimal(event["effective_fees"], "操作费用")
                if event.get("effective_fees") is not None
                else None
            )
            if fee is None:
                fees_complete = False
            else:
                known_fees += fee
            if event["operation_type"] in {"buy", "add"}:
                cost_basis += operation_price * operation_quantity
                if fee is not None:
                    cost_basis += fee
                quantity += operation_quantity
                continue
            if operation_quantity > quantity:
                raise PositionLedgerInvalidState(
                    f"{event['operated_at']} 的卖出数量超过当时可用持仓"
                )
            average_before = cost_basis / quantity if quantity else Decimal("0")
            allocated_cost = average_before * operation_quantity
            gross_result = operation_price * operation_quantity - allocated_cost
            realized_gross += gross_result
            realized_net += gross_result - (fee or Decimal("0"))
            cost_basis -= allocated_cost
            quantity -= operation_quantity
            if quantity == 0:
                cost_basis = Decimal("0")

        warnings: list[str] = []
        if not fees_complete:
            warnings.append("部分费用尚未录入，不能展示伪精确净收益。")
        if quantity == 0:
            warnings.append("持仓数量已归零；是否转为关注或结束由用户确认。")
        average_cost = cost_basis / quantity if quantity else None
        return {
            "quantity": self._quantity_text(quantity),
            "cost_basis": self._amount_text(cost_basis),
            "average_cost": self._price_text(average_cost)
            if average_cost is not None
            else None,
            "realized_gross_pnl": self._amount_text(realized_gross),
            "realized_net_pnl": self._amount_text(realized_net)
            if fees_complete
            else None,
            "known_fees": self._amount_text(known_fees),
            "fees_complete": fees_complete,
            "data_status": "complete" if fees_complete else "partial",
            "warnings": warnings,
        }

    def _operation_rows(
        self, connection: Any, *, user_id: str, workspace_id: str
    ) -> list[dict[str, Any]]:
        rows = connection.execute(
            """
            SELECT * FROM position_operations
            WHERE user_id = ? AND workspace_id = ?
            ORDER BY operated_at ASC, created_at ASC, rowid ASC
            """,
            (user_id, workspace_id),
        ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            revision = connection.execute(
                """
                SELECT * FROM operation_revisions
                WHERE user_id = ? AND operation_id = ?
                ORDER BY revision_no DESC, rowid DESC LIMIT 1
                """,
                (user_id, item["id"]),
            ).fetchone()
            revision_item = dict(revision) if revision is not None else None
            item["current_revision"] = int(
                revision_item["revision_no"] if revision_item else 0
            )
            item["effective_price"] = (
                revision_item["price"] if revision_item else item["price"]
            )
            item["effective_quantity"] = (
                revision_item["quantity"] if revision_item else item["quantity"]
            )
            item["effective_fees"] = (
                revision_item["fees"] if revision_item else item["fees"]
            )
            item["latest_revision"] = revision_item
            items.append(item)
        return items

    def _packet(
        self,
        *,
        workspace: Any,
        opening: dict[str, Any],
        snapshot: dict[str, Any] | None,
        operations: list[dict[str, Any]],
        adjustments: list[dict[str, Any]],
        snapshots: list[dict[str, Any]],
    ) -> dict[str, Any]:
        public_snapshot = self._snapshot(snapshot) if snapshot else None
        return {
            "contract_version": self.CONTRACT_VERSION,
            "status": (
                "ready"
                if public_snapshot and public_snapshot["data_status"] == "complete"
                else "partial"
            ),
            "workspace_id": workspace["id"],
            "symbol": workspace["symbol"],
            "opening": self._opening_public(opening),
            "current": public_snapshot,
            "operations": [self._operation_public(item) for item in operations],
            "adjustments": [self._adjustment_public(item) for item in adjustments],
            "snapshots": [self._snapshot(item) for item in snapshots],
            "completeness": {
                "fees_complete": bool(
                    public_snapshot and public_snapshot["fees_complete"]
                ),
                "can_show_precise_net_result": bool(
                    public_snapshot
                    and public_snapshot["realized_net_pnl"] is not None
                ),
                "method": self.CALCULATION_VERSION,
            },
            "boundary": (
                "持仓由期初、操作、修正和非交易调整流水派生；"
                "页面不能直接编辑快照。费用缺失时不展示伪精确净收益。"
            ),
        }

    def _empty_packet(self, workspace: Any) -> dict[str, Any]:
        return {
            "contract_version": self.CONTRACT_VERSION,
            "status": "not_configured",
            "workspace_id": workspace["id"],
            "symbol": workspace["symbol"],
            "opening": None,
            "current": None,
            "operations": [],
            "adjustments": [],
            "snapshots": [],
            "completeness": {
                "fees_complete": False,
                "can_show_precise_net_result": False,
                "method": self.CALCULATION_VERSION,
            },
            "boundary": "录入期初持仓后，系统才会依据不可变流水派生持仓。",
        }

    @staticmethod
    def _opening_public(item: dict[str, Any]) -> dict[str, Any]:
        return {
            key: item.get(key)
            for key in (
                "id",
                "as_of_date",
                "quantity",
                "cost_price",
                "fees",
                "note",
                "created_at",
            )
        }

    @staticmethod
    def _operation_public(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": item.get("id"),
            "operation_type": item.get("operation_type"),
            "operated_at": item.get("operated_at"),
            "price": item.get("effective_price"),
            "quantity": item.get("effective_quantity"),
            "fees": item.get("effective_fees"),
            "reason_text": item.get("reason_text"),
            "plan_id": item.get("plan_id"),
            "current_revision": item.get("current_revision"),
            "latest_revision": (
                {
                    key: item["latest_revision"].get(key)
                    for key in (
                        "id",
                        "revision_no",
                        "price",
                        "quantity",
                        "fees",
                        "reason_text",
                        "created_at",
                    )
                }
                if item.get("latest_revision")
                else None
            ),
            "created_at": item.get("created_at"),
        }

    @staticmethod
    def _adjustment_public(item: dict[str, Any]) -> dict[str, Any]:
        return {
            key: item.get(key)
            for key in (
                "id",
                "adjustment_type",
                "effective_at",
                "quantity_delta",
                "cost_delta",
                "reason_text",
                "evidence_text",
                "created_at",
            )
        }

    @staticmethod
    def _snapshot(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": item.get("id"),
            "snapshot_at": item.get("snapshot_at"),
            "source_event_type": item.get("source_event_type"),
            "source_event_id": item.get("source_event_id"),
            "quantity": item.get("quantity"),
            "cost_basis": item.get("cost_basis"),
            "average_cost": item.get("average_cost"),
            "realized_gross_pnl": item.get("realized_gross_pnl"),
            "realized_net_pnl": item.get("realized_net_pnl"),
            "known_fees": item.get("known_fees"),
            "fees_complete": bool(item.get("fees_complete")),
            "data_status": item.get("data_status"),
            "warnings": json.loads(item.get("warnings_json") or "[]"),
            "calculation_version": item.get("calculation_version"),
            "created_at": item.get("created_at"),
        }

    def _opening(self, connection: Any, user_id: str, workspace_id: str) -> Any:
        row = connection.execute(
            """
            SELECT * FROM position_openings
            WHERE user_id = ? AND workspace_id = ?
            """,
            (user_id, workspace_id),
        ).fetchone()
        if row is None:
            raise PositionLedgerInvalidState("请先录入期初持仓")
        return row

    @staticmethod
    def _workspace(connection: Any, user_id: str, symbol: str) -> Any:
        row = connection.execute(
            """
            SELECT * FROM stock_workspaces
            WHERE user_id = ? AND symbol = ?
            """,
            (user_id, symbol),
        ).fetchone()
        if row is None:
            raise PositionLedgerNotFound("股票研究空间不存在")
        return row

    @staticmethod
    def _workspace_by_id(connection: Any, user_id: str, workspace_id: str) -> Any:
        row = connection.execute(
            """
            SELECT * FROM stock_workspaces
            WHERE user_id = ? AND id = ?
            """,
            (user_id, workspace_id),
        ).fetchone()
        if row is None:
            raise PositionLedgerNotFound("股票研究空间不存在")
        return row

    @staticmethod
    def _mark_workspace_holding(
        connection: Any, *, workspace: Any, user_id: str, now: str
    ) -> None:
        if workspace["relation_type"] == "holding":
            return
        connection.execute(
            """
            UPDATE stock_relation_history SET ended_at = ?
            WHERE workspace_id = ? AND ended_at IS NULL
            """,
            (now, workspace["id"]),
        )
        connection.execute(
            """
            INSERT INTO stock_relation_history(
                id, workspace_id, user_id, relation_type, priority,
                tracking_status, source, effective_at, ended_at
            ) VALUES (?, ?, ?, 'holding', NULL, 'active',
                      'position_opening', ?, NULL)
            """,
            (str(uuid4()), workspace["id"], user_id, now),
        )
        connection.execute(
            """
            UPDATE stock_workspaces
            SET relation_type = 'holding', priority = NULL,
                tracking_status = 'active', version = version + 1,
                updated_at = ?, ended_at = NULL
            WHERE id = ? AND user_id = ?
            """,
            (now, workspace["id"], user_id),
        )

    @staticmethod
    def _required_text(value: str, label: str, limit: int) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            raise PositionLedgerInvalidState(f"{label}不能为空")
        return cleaned[:limit]

    @staticmethod
    def _clean_text(value: str | None, limit: int) -> str | None:
        cleaned = str(value or "").strip()
        return cleaned[:limit] if cleaned else None

    @staticmethod
    def _date(value: str, label: str) -> date:
        try:
            return date.fromisoformat(str(value))
        except ValueError as exc:
            raise PositionLedgerInvalidState(f"{label}必须使用 YYYY-MM-DD") from exc

    @staticmethod
    def _datetime(value: str, label: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise PositionLedgerInvalidState(f"{label}必须使用 ISO 8601 时间") from exc
        if parsed.tzinfo is None:
            raise PositionLedgerInvalidState(f"{label}必须包含时区")
        return parsed

    def _positive_decimal(self, value: str, label: str) -> Decimal:
        parsed = self._decimal(value, label)
        if parsed <= 0:
            raise PositionLedgerInvalidState(f"{label}必须大于零")
        return parsed

    def _non_negative_decimal(self, value: str, label: str) -> Decimal:
        parsed = self._decimal(value, label)
        if parsed < 0:
            raise PositionLedgerInvalidState(f"{label}不能为负数")
        return parsed

    def _optional_non_negative_decimal(
        self, value: str | None, label: str
    ) -> Decimal | None:
        if value is None or not str(value).strip():
            return None
        return self._non_negative_decimal(value, label)

    @staticmethod
    def _decimal(value: str, label: str) -> Decimal:
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise PositionLedgerInvalidState(f"{label}不是有效数字") from exc
        if not parsed.is_finite():
            raise PositionLedgerInvalidState(f"{label}不是有效数字")
        return parsed

    def _price_text(self, value: Decimal) -> str:
        return self._decimal_text(value, self._PRICE_QUANT)

    def _quantity_text(self, value: Decimal) -> str:
        return self._decimal_text(value, self._QUANTITY_QUANT)

    def _amount_text(self, value: Decimal) -> str:
        return self._decimal_text(value, self._AMOUNT_QUANT)

    @staticmethod
    def _decimal_text(value: Decimal, quant: Decimal) -> str:
        normalized = value.quantize(quant, rounding=ROUND_HALF_UP)
        if normalized == 0:
            normalized = abs(normalized)
        return format(normalized, "f")
