from __future__ import annotations

from typing import Any


def _compact_stock_workspace_context(
    workspace: dict[str, Any], plan: dict[str, Any]
) -> dict[str, Any]:
    """Keep the user's formal stock state available without copying the UI packet."""

    def select(value: dict[str, Any] | None, keys: tuple[str, ...]) -> dict[str, Any]:
        packet = value or {}
        return {
            key: packet.get(key)
            for key in keys
            if packet.get(key) not in (None, "", [], {})
        }

    position = workspace.get("position_snapshot") or {}
    action_plans = workspace.get("action_plans") or {}
    observation_tasks = workspace.get("observation_tasks") or {}
    trade_reviews = workspace.get("trade_reviews") or {}
    return {
        "contract_version": "stock_workspace_agent_context_v1",
        "symbol": workspace.get("symbol"),
        "name": workspace.get("name"),
        "research_focus": plan.get("focus"),
        "relation": select(
            workspace.get("relation"),
            (
                "type",
                "label",
                "priority",
                "priority_label",
                "tracking_status",
                "workflow_status",
                "attention_tags",
                "version",
                "updated_at",
            ),
        ),
        "formal_thesis": select(
            workspace.get("thesis"),
            (
                "id",
                "summary",
                "source",
                "status",
                "version",
                "watch_items",
                "recheck_conditions",
                "updated_at",
            ),
        ),
        "position": {
            "opening": select(
                position.get("opening"),
                (
                    "id",
                    "as_of_date",
                    "quantity",
                    "cost_price",
                    "fees",
                    "note",
                    "created_at",
                ),
            ),
            "current_snapshot": select(
                position.get("current"),
                (
                    "quantity",
                    "cost_basis",
                    "average_cost",
                    "realized_gross_pnl",
                    "realized_net_pnl",
                    "known_fees",
                    "fees_complete",
                    "data_status",
                    "snapshot_at",
                ),
            ),
            "recent_operations": [
                select(
                    item,
                    (
                        "id",
                        "operation_type",
                        "operated_at",
                        "quantity",
                        "price",
                        "fees",
                        "reason_text",
                        "plan_id",
                        "current_revision",
                    ),
                )
                for item in (position.get("operations") or [])[:3]
            ],
        },
        "active_action_plans": [
            select(
                item,
                (
                    "id",
                    "status",
                    "action_type",
                    "trigger_text",
                    "target_quantity",
                    "target_amount",
                    "target_position_percent",
                    "expires_at",
                    "version",
                    "updated_at",
                ),
            )
            for item in (action_plans.get("items") or [])
            if item.get("status") in {"draft", "checked", "saved", "partially_executed"}
        ][:3],
        "active_observation_tasks": [
            select(
                item,
                (
                    "id",
                    "title",
                    "description",
                    "status",
                    "priority",
                    "due_at",
                    "version",
                    "updated_at",
                ),
            )
            for item in (observation_tasks.get("items") or [])
            if item.get("status") in {"pending", "in_progress", "waiting_data"}
        ][:5],
        "recent_trade_reviews": [
            {
                **select(
                    item,
                    (
                        "id",
                        "status",
                        "horizon_sessions",
                        "data_status",
                        "ready_at",
                        "updated_at",
                    ),
                ),
                "current_version": select(
                    item.get("current_version"),
                    (
                        "version_no",
                        "price_result",
                        "logic_result",
                        "plan_deviation",
                        "bias_tags",
                        "improvement_text",
                        "status",
                        "created_at",
                    ),
                ),
            }
            for item in (trade_reviews.get("items") or [])[:3]
        ],
        "important_changes": [
            select(
                item,
                (
                    "id",
                    "title",
                    "summary",
                    "severity",
                    "occurred_at",
                    "created_at",
                    "source_type",
                ),
            )
            for item in (workspace.get("important_changes") or [])[:5]
        ],
        "pending_actions": [
            select(
                item,
                ("id", "title", "status", "severity", "next_step", "source"),
            )
            for item in (workspace.get("pending_actions") or [])[:5]
        ],
        "history_summary": workspace.get("history_summary") or {},
        "completeness": workspace.get("completeness") or {},
        "data_meta": workspace.get("data_meta") or {},
        "boundary": workspace.get("boundary"),
    }
