from __future__ import annotations

from typing import Any

from app.db import Database
from app.services.stock_workspace import StockWorkspaceService


class StockAssetListService:
    """List one user's long-lived stock research spaces as research assets."""

    CONTRACT_VERSION = "stock_asset_list_v1"
    RELATION_LABELS = {
        "watching": "关注",
        "holding": "持仓",
        "ended": "已结束",
    }

    def __init__(
        self,
        database: Database,
        stock_workspace: StockWorkspaceService,
    ) -> None:
        self.database = database
        self.stock_workspace = stock_workspace

    def list_assets(self, user_id: str) -> dict[str, Any]:
        workspaces = self.database.list_stock_workspaces(user_id)
        items = [self._asset_item(user_id, workspace) for workspace in workspaces]
        summary = {
            "total": len(items),
            "watching": sum(item["relation_type"] == "watching" for item in items),
            "holding": sum(item["relation_type"] == "holding" for item in items),
            "ended": sum(item["relation_type"] == "ended" for item in items),
            "paused": sum(item["tracking_status"] == "paused" for item in items),
            "waiting_data": sum(
                item["workflow_status"] == "waiting_data" for item in items
            ),
        }
        return {
            "contract_version": self.CONTRACT_VERSION,
            "status": (
                "empty"
                if not items
                else "partial"
                if any(item["data_status"] != "ready" for item in items)
                else "ready"
            ),
            "items": items,
            "summary": summary,
            "boundary": (
                "该列表组织用户的长期股票研究资产；已结束空间仍保留"
                "判断、任务和历史。持仓数量、成本和盈亏事实链尚未建立时，"
                "不生成伪精确持仓数据。"
            ),
        }

    def _asset_item(
        self,
        user_id: str,
        formal_workspace: dict[str, Any],
    ) -> dict[str, Any]:
        workspace_id = str(formal_workspace["id"])
        active_thesis = self._safe_active_thesis(user_id, workspace_id)
        base = {
            "workspace_id": workspace_id,
            "version": formal_workspace.get("version"),
            "symbol": formal_workspace.get("symbol"),
            "name": formal_workspace.get("name") or formal_workspace.get("symbol"),
            "market": formal_workspace.get("market"),
            "relation_type": formal_workspace.get("relation_type"),
            "relation_label": self.RELATION_LABELS.get(
                str(formal_workspace.get("relation_type") or ""), "股票研究空间"
            ),
            "priority": formal_workspace.get("priority"),
            "tracking_status": formal_workspace.get("tracking_status"),
            "workflow_status": formal_workspace.get("workflow_status"),
            "attention_tags": formal_workspace.get("attention_tags") or [],
            "active_thesis": self._public_thesis(active_thesis),
            "latest_change": None,
            "next_action": None,
            "open_task_count": 0,
            "position_snapshot": {
                "available": False,
                "status": "not_configured",
            },
            "quote": self._empty_quote(),
            "data_status": "partial" if active_thesis is None else "ready",
            "warnings": [],
        }
        try:
            aggregate = self.stock_workspace.get_workspace(
                user_id, str(formal_workspace["symbol"])
            )
        except Exception:
            base["data_status"] = "partial"
            base["warnings"] = ["该股票的行情或研究摘要暂未完整返回"]
            return base

        relation = aggregate.get("relation") or {}
        thesis = aggregate.get("thesis") or {}
        if thesis.get("status") == "active":
            base["active_thesis"] = {
                "summary": thesis.get("summary"),
                "version": thesis.get("version"),
                "watch_items": thesis.get("watch_items") or [],
                "recheck_conditions": thesis.get("recheck_conditions") or [],
            }
        base["workflow_status"] = (
            relation.get("workflow_status") or base["workflow_status"]
        )
        base["latest_change"] = self._latest_change(aggregate)
        base["next_action"] = self._next_action(aggregate)
        task_summary = (aggregate.get("observation_tasks") or {}).get("summary") or {}
        base["open_task_count"] = int(task_summary.get("active") or 0)
        base["position_snapshot"] = aggregate.get("position_snapshot") or {
            "available": False,
            "status": "not_configured",
        }
        base["quote"] = self._quote(aggregate)
        aggregate_status = str((aggregate.get("data_meta") or {}).get("status") or "")
        base["data_status"] = "ready" if aggregate_status == "ready" else "partial"
        return base

    def _safe_active_thesis(
        self, user_id: str, workspace_id: str
    ) -> dict[str, Any] | None:
        try:
            return self.database.get_active_thesis(user_id, workspace_id)
        except Exception:
            return None

    @staticmethod
    def _public_thesis(thesis: dict[str, Any] | None) -> dict[str, Any] | None:
        if thesis is None:
            return None
        return {
            "summary": thesis.get("reason_text"),
            "version": thesis.get("version_no"),
            "watch_items": thesis.get("watch_items") or [],
            "recheck_conditions": thesis.get("recheck_conditions") or [],
        }

    @staticmethod
    def _latest_change(aggregate: dict[str, Any]) -> dict[str, Any] | None:
        change = (aggregate.get("overview") or {}).get("latest_change")
        if not isinstance(change, dict):
            changes = aggregate.get("important_changes") or []
            change = changes[0] if changes else None
        if not isinstance(change, dict):
            return None
        return {
            "summary": change.get("summary") or change.get("title"),
            "created_at": change.get("created_at")
            or change.get("data_as_of")
            or change.get("as_of_date"),
        }

    @staticmethod
    def _next_action(aggregate: dict[str, Any]) -> dict[str, Any] | None:
        actions = aggregate.get("pending_actions") or []
        action = actions[0] if actions else None
        if not isinstance(action, dict):
            return None
        return {
            "title": action.get("title"),
            "next_step": action.get("next_step") or action.get("current_evidence"),
            "status": action.get("task_status") or action.get("status"),
        }

    @staticmethod
    def _quote(aggregate: dict[str, Any]) -> dict[str, Any]:
        quote = (aggregate.get("overview") or {}).get("quote") or {}
        price = quote.get("price")
        return {
            "price": price,
            "pct_change": quote.get("pct_change"),
            "label": quote.get("label"),
            "market_timestamp": quote.get("market_timestamp"),
            "status": "available" if price is not None else "unavailable",
            "currency": quote.get("currency"),
        }

    @staticmethod
    def _empty_quote() -> dict[str, Any]:
        return {
            "price": None,
            "pct_change": None,
            "label": None,
            "market_timestamp": None,
            "status": "unavailable",
            "currency": None,
        }
