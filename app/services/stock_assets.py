from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

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
        report = self.database.latest_research_report(
            str(formal_workspace.get("symbol") or "")
        )
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
            "report_meta": self._report_meta(report),
            "report_freshness": self._report_freshness(
                report, str(formal_workspace.get("symbol") or "")
            ),
            "data_times": {
                "quote_as_of": None,
                "daily_as_of": None,
                "financial_report_period": None,
                "report_generated_at": (report or {}).get("generated_at"),
                "report_market_timestamp": (report or {}).get("market_timestamp"),
            },
            "counterevidence": [],
            "invalidation_conditions": [],
            "next_evidence": [],
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
        data_meta = aggregate.get("data_meta") or {}
        base["data_times"] = {
            "quote_as_of": data_meta.get("quote_as_of"),
            "daily_as_of": data_meta.get("daily_as_of"),
            "financial_report_period": data_meta.get("financial_report_period"),
            "report_generated_at": data_meta.get("report_generated_at"),
            "report_market_timestamp": data_meta.get("report_market_timestamp"),
        }
        base["counterevidence"] = [
            self._public_counterevidence(item)
            for item in (aggregate.get("counterevidence") or [])[:3]
        ]
        base["invalidation_conditions"] = list(
            (aggregate.get("invalidation_conditions") or [])[:3]
        )
        base["next_evidence"] = list((aggregate.get("next_evidence") or [])[:3])
        aggregate_status = str(data_meta.get("status") or "")
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
            "link_id": change.get("link_id"),
            "event_id": change.get("event_id") or change.get("id"),
            "event_type": change.get("event_type"),
            "title": change.get("title"),
            "summary": change.get("summary") or change.get("title"),
            "occurred_at": change.get("occurred_at") or change.get("data_as_of"),
            "detected_at": change.get("detected_at"),
            "created_at": change.get("created_at")
            or change.get("data_as_of")
            or change.get("as_of_date"),
            "read_at": change.get("read_at"),
            "handled_at": change.get("handled_at"),
            "relevance_status": change.get("relevance_status"),
            "relevance_status_label": change.get("relevance_status_label"),
            "source_name": change.get("source_name"),
            "source_url": change.get("source_url") or change.get("url"),
            "boundary": change.get("boundary"),
        }

    @staticmethod
    def _report_meta(report: dict[str, Any] | None) -> dict[str, Any] | None:
        if report is None:
            return None
        return {
            "id": report.get("id"),
            "symbol": report.get("symbol"),
            "name": report.get("name"),
            "title": report.get("title"),
            "summary": report.get("summary"),
            "status": report.get("status"),
            "generated_at": report.get("generated_at"),
            "market_timestamp": report.get("market_timestamp"),
            "source_scope": "server_evidence_snapshot",
            "source_scope_label": "服务器公共证据快照",
        }

    @classmethod
    def _report_freshness(
        cls,
        report: dict[str, Any] | None,
        symbol: str,
    ) -> dict[str, Any]:
        if report is None:
            return {
                "status": "missing",
                "label": "等待生成",
                "is_today": False,
            }
        generated_at = cls._parse_datetime(report.get("generated_at"))
        timezone_name = (
            "Asia/Shanghai"
            if symbol.upper().endswith((".SS", ".SZ"))
            else "America/New_York"
        )
        is_today = bool(
            generated_at
            and generated_at.astimezone(ZoneInfo(timezone_name)).date()
            == datetime.now(ZoneInfo(timezone_name)).date()
        )
        report_status = str(report.get("status") or "unknown")
        if report_status == "failed":
            status, label = "failed", "生成失败"
        elif report_status != "completed":
            status, label = "partial", "部分完成"
        elif is_today:
            status, label = "today", "今日已更新"
        else:
            status, label = "existing", "已有快照"
        return {
            "status": status,
            "label": label,
            "is_today": is_today,
        }

    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None

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
    def _public_counterevidence(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "label": item.get("label"),
            "statement": item.get("statement"),
            "evidence": item.get("evidence"),
            "source_name": item.get("source_name"),
            "data_time": item.get("data_time"),
            "coverage_status": item.get("coverage_status"),
            "limitations": list(item.get("limitations") or [])[:2],
            "next_step": item.get("next_step"),
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
