from __future__ import annotations

import logging
from typing import Any, Callable

from app.catalog import RESEARCH_TARGETS
from app.providers.market import ProviderError
from app.services.chat_routing import (
    _is_deep_stock_coverage_query,
    _needs_stock_market_context,
)
from app.services.chat_stock_context import _compact_stock_workspace_context
from app.services.li_zong_presentation import public_li_zong_candidate
from app.services.live_market import market_quote_semantics
from app.services.research_claims import build_research_claim_ledger
from app.services.stock_market_context import (
    _build_stock_market_context,
    _stock_analysis_target,
)
from app.services.stock_research_contract import (
    build_stock_research_contract,
    finalize_stock_research_contract,
)
from app.utils import utc_now


logger = logging.getLogger(__name__)


class ChatStockResearchEvidenceService:
    """Orchestrate live stock evidence without coupling it to FastAPI routes."""

    def __init__(
        self,
        *,
        database: Any,
        research_plan: Any,
        research_reports: Any,
        research_evidence: Any,
        li_zong_strategy: Any,
        analysis: Any,
        deep_stock: Any,
        research_tracking: Any,
        stock_workspace: Any,
    ) -> None:
        self.database = database
        self.research_plan = research_plan
        self.research_reports = research_reports
        self.research_evidence = research_evidence
        self.li_zong_strategy = li_zong_strategy
        self.analysis = analysis
        self.deep_stock = deep_stock
        self.research_tracking = research_tracking
        self.stock_workspace = stock_workspace

    def build(
        self,
        *,
        user_id: str,
        symbol: str,
        message: str,
        history: list[dict[str, Any]],
        publish_progress: Callable[..., None],
    ) -> dict[str, Any]:
        plan = dict(
            self.research_plan.build(message, conversation_history=history)
        )
        watchlist_item = self.database.get_watchlist_item(user_id, symbol)
        latest_report = (
            self.research_reports.get_latest(symbol, generate_if_missing=False)
            if watchlist_item is not None
            else None
        )
        evidence_contract = build_stock_research_contract(
            watchlist_item=watchlist_item,
            latest_report=latest_report,
        )
        plan["evidence_contract_version"] = evidence_contract["contract_version"]
        plan["evidence_path"] = evidence_contract["path"]
        plan["selected_skills"] = list(
            dict.fromkeys(
                [
                    *(plan.get("selected_skills") or []),
                    evidence_contract["skill_name"],
                ]
            )
        )
        module_max_age_hours = dict(plan.get("module_max_age_hours") or {})
        for module_key in evidence_contract["always_refresh_modules"]:
            if module_key in (plan.get("selected_modules") or []):
                module_max_age_hours[module_key] = 0
        plan["module_max_age_hours"] = module_max_age_hours
        publish_progress(
            "research_plan_ready",
            plan.get("progress_label") or "已识别研究重点，正在核验相关证据…",
            research_focus=plan.get("focus"),
            evidence_modules=plan.get("selected_modules"),
        )

        def publish_evidence_module(module_key: str, label: str) -> None:
            publish_progress(
                "evidence_module_started",
                label,
                research_focus=plan.get("focus"),
                evidence_module=module_key,
            )

        try:
            evidence = self.research_evidence.build(
                user_id,
                symbol,
                plan=plan,
                reusable_evidence=(latest_report or {}).get("evidence"),
                reusable_generated_at=(latest_report or {}).get("generated_at"),
                progress_callback=publish_evidence_module,
                force_online_refresh=bool(
                    evidence_contract.get("force_online_refresh")
                ),
            )
        except ProviderError as exc:
            if (
                not evidence_contract.get("precomputed_report_reuse_allowed")
                or latest_report is None
                or not latest_report.get("evidence")
            ):
                logger.warning(
                    "Online stock evidence unavailable for %s: %s",
                    symbol,
                    type(exc).__name__,
                )
                evidence = self._unavailable_online_evidence(
                    symbol=symbol,
                    plan=plan,
                )
            else:
                evidence = dict(latest_report["evidence"])
                evidence["generated_at"] = utc_now()
                evidence["research_plan"] = plan
                evidence["evidence_status"] = "partial"
                evidence["module_statuses"] = {
                    key: {
                        "module": key,
                        "label": (plan.get("module_labels") or {}).get(key, key),
                        "status": "reused_fallback",
                        "required": key in (plan.get("required_modules") or []),
                    }
                    for key in plan.get("selected_modules") or []
                    if key == "market" or key in evidence
                }
                evidence.setdefault("warnings", []).append(
                    "本轮使用已保存的最近可核验证据，并继续由 AI 针对当前问题生成回答。"
                )

        self._annotate_reused_report(evidence, latest_report)
        self._attach_user_context(evidence, user_id=user_id, symbol=symbol)
        if symbol.endswith((".SS", ".SZ")):
            self._attach_li_zong(evidence, symbol)
            self._attach_a_share_quote(evidence)
            self._attach_stock_market_context(evidence, symbol=symbol, message=message)
        if plan.get("focus") == "comprehensive" or _is_deep_stock_coverage_query(
            message
        ):
            evidence["deep_stock_coverage"] = (
                self.deep_stock.evidence_coverage_packet(
                    evidence,
                    intent="stock_research",
                )
            )
        if _is_deep_stock_coverage_query(message):
            tracking_packet = self.research_tracking.get_packet(
                user_id,
                symbol=symbol,
                limit=5,
            )
            tracking_item = (tracking_packet.get("items") or [{}])[0]
            evidence["research_change"] = {
                "latest_change": tracking_item.get("latest_change"),
                "next_review": tracking_item.get("next_review"),
                "boundary": tracking_packet.get("boundary"),
            }
        evidence["research_evidence_contract"] = finalize_stock_research_contract(
            evidence_contract,
            evidence=evidence,
            latest_report=latest_report,
        )
        return evidence

    @staticmethod
    def _unavailable_online_evidence(
        *,
        symbol: str,
        plan: dict[str, Any],
    ) -> dict[str, Any]:
        selected_modules = list(plan.get("selected_modules") or [])
        required_modules = set(plan.get("required_modules") or [])
        target = RESEARCH_TARGETS.get(symbol) or {}
        return {
            "type": "stock_research",
            "symbol": symbol,
            "display_name": target.get("name") or symbol,
            "generated_at": utc_now(),
            "evidence_status": "partial",
            "research_plan": plan,
            "metrics": {
                "latest_close": None,
                "trend_state": "行情暂不可用",
                "return_1d_pct": None,
                "return_20d_pct": None,
                "return_60d_pct": None,
                "volatility_20d_annualized_pct": None,
                "max_drawdown_60d_pct": None,
            },
            "research_frame": {
                "missing_information": [
                    "重新取得最近完整日线与当前报价",
                    "核对最新公司公告、财务与反方证据",
                ]
            },
            "module_statuses": {
                key: {
                    "module": key,
                    "label": (plan.get("module_labels") or {}).get(key, key),
                    "status": "unavailable",
                    "required": key in required_modules,
                }
                for key in selected_modules
            },
            "warnings": [
                "外部行情或公司证据刷新暂时未完成；本轮不会补写价格、涨跌、财务或事件事实。"
            ],
            "boundary": (
                "当前只确认在线证据暂时不可用；任何价格、财务、事件原因或正式判断都需要在数据恢复后重新核验。"
            ),
        }

    def attach_workspace_context(
        self,
        evidence: dict[str, Any],
        *,
        user_id: str,
        symbol: str,
        message: str,
        history: list[dict[str, Any]],
    ) -> dict[str, Any]:
        context_plan = evidence.get("research_plan") or self.research_plan.build(
            message,
            conversation_history=history,
        )
        evidence.setdefault("research_plan", context_plan)
        evidence["research_claims"] = build_research_claim_ledger(evidence)
        try:
            workspace_packet = self.stock_workspace.get_workspace(user_id, symbol)
            evidence["stock_workspace_context"] = _compact_stock_workspace_context(
                workspace_packet, context_plan
            )
        except Exception:
            evidence["stock_workspace_context"] = {
                "status": "partial",
                "boundary": "本轮仍使用当前用户的行情与研究证据回答。",
            }
        return evidence

    @staticmethod
    def _annotate_reused_report(
        evidence: dict[str, Any], latest_report: dict[str, Any] | None
    ) -> None:
        if latest_report is None or not latest_report.get("evidence"):
            return
        reused_modules = [
            item.get("label")
            for item in (evidence.get("module_statuses") or {}).values()
            if item.get("status") in {"reused", "reused_fallback"}
        ]
        if reused_modules:
            evidence["precomputed_report"] = {
                "title": latest_report.get("title"),
                "generated_at": latest_report.get("generated_at"),
                "market_timestamp": latest_report.get("market_timestamp"),
                "reused_modules": reused_modules,
            }

    def _attach_user_context(
        self,
        evidence: dict[str, Any],
        *,
        user_id: str,
        symbol: str,
    ) -> None:
        watchlist_item = self.database.get_watchlist_item(user_id, symbol)
        evidence["research_claims"] = build_research_claim_ledger(evidence)
        evidence["user_thesis"] = (
            watchlist_item.get("thesis") if watchlist_item else None
        )
        evidence["confirmed_user_memories"] = [
            {"kind": item["kind"], "content": item["content"]}
            for item in self.database.list_memories(user_id, status="confirmed")
        ]

    def _attach_li_zong(self, evidence: dict[str, Any], symbol: str) -> None:
        try:
            candidate = self.li_zong_strategy.get_candidate(symbol)
        except ValueError:
            candidate = None
        if candidate is not None:
            evidence["li_zong_strategy"] = public_li_zong_candidate(candidate)

    @staticmethod
    def _attach_a_share_quote(evidence: dict[str, Any]) -> None:
        valuation = (evidence.get("fundamentals") or {}).get("valuation") or {}
        if valuation.get("price") is None or not valuation.get("market_timestamp"):
            return
        evidence["current_quote"] = {
            key: valuation.get(key)
            for key in (
                "name",
                "currency",
                "price",
                "previous_close",
                "pct_change",
                "turnover_rate_pct",
                "market_timestamp",
                "source",
                "source_url",
                "fetched_at",
            )
            if valuation.get(key) is not None
        }
        evidence["current_quote"].update(
            market_quote_semantics("china", valuation.get("market_timestamp"))
        )

    def _attach_stock_market_context(
        self,
        evidence: dict[str, Any],
        *,
        symbol: str,
        message: str,
    ) -> None:
        if not _needs_stock_market_context(message):
            return
        try:
            industry_name = str(
                (evidence.get("analyst_expectations") or {}).get("industry")
                or ((evidence.get("li_zong_strategy") or {}).get("stock_basic") or {}).get(
                    "industry"
                )
                or (RESEARCH_TARGETS.get(symbol) or {}).get("industry")
                or ""
            )
            analysis_target = _stock_analysis_target(message, evidence)
            evidence["stock_market_context"] = _build_stock_market_context(
                message,
                evidence,
                self.analysis.market_brief(market_key="china"),
                self.analysis.industry_snapshot(
                    industry_name,
                    market_date=analysis_target.get("market_date"),
                ),
            )
        except Exception as exc:
            evidence.setdefault("warnings", []).append(
                f"个股市场对照证据刷新未完成：{type(exc).__name__}"
            )
