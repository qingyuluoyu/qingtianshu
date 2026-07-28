from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Callable
from zoneinfo import ZoneInfo

from app.catalog import RESEARCH_TARGETS, normalize_symbol
from app.config import Settings
from app.db import Database
from app.services.agent import AgentService
from app.services.analysis import (
    MarketAnalysisService,
    align_conditional_outlook_with_current_quote,
    build_conditional_outlook,
    build_evidence_debate,
    build_research_analysis_board,
)
from app.services.china_info import ChinaInformationService
from app.services.calibration import (
    OutlookCalibrationService,
    attach_outlook_calibration,
)
from app.services.fundamentals import FundamentalsService
from app.services.earnings_quality import EarningsQualityService
from app.services.event_timeline import EventTimelineService
from app.services.financial_drivers import FinancialDriverAnalysisService
from app.services.business_structure import BusinessStructureAnalysisService
from app.services.shareholders import ShareholderStructureAnalysisService
from app.services.analyst_expectations import AnalystExpectationsService
from app.services.global_info import GlobalInformationService
from app.services.us_fundamentals import USEquityFundamentalsService
from app.services.peer_comparison import PeerComparisonService
from app.services.research_tracking import ResearchTrackingService
from app.services.security_master import SecurityMasterService
from app.services.research_claims import build_research_claim_ledger


def _current_quote_from_valuation(
    valuation: dict[str, Any] | None,
) -> dict[str, Any] | None:
    valuation = valuation or {}
    if valuation.get("price") is None or not valuation.get("market_timestamp"):
        return None
    return {
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


class StockResearchEvidenceService:
    """Build one auditable stock packet for chat and scheduled reports."""

    def __init__(
        self,
        analysis: MarketAnalysisService,
        china_info: ChinaInformationService,
        fundamentals: FundamentalsService,
        global_info: GlobalInformationService,
        us_fundamentals: USEquityFundamentalsService,
        peer_comparison: PeerComparisonService,
        outlook_calibration: OutlookCalibrationService,
        earnings_quality: EarningsQualityService,
        financial_drivers: FinancialDriverAnalysisService,
        business_structure: BusinessStructureAnalysisService,
        shareholders: ShareholderStructureAnalysisService,
        analyst_expectations: AnalystExpectationsService,
        event_timeline: EventTimelineService,
    ):
        self.analysis = analysis
        self.china_info = china_info
        self.fundamentals = fundamentals
        self.global_info = global_info
        self.us_fundamentals = us_fundamentals
        self.peer_comparison = peer_comparison
        self.outlook_calibration = outlook_calibration
        self.earnings_quality = earnings_quality
        self.financial_drivers = financial_drivers
        self.business_structure = business_structure
        self.shareholders = shareholders
        self.analyst_expectations = analyst_expectations
        self.event_timeline = event_timeline

    def build(
        self,
        user_id: str,
        symbol: str,
        *,
        plan: dict[str, Any] | None = None,
        reusable_evidence: dict[str, Any] | None = None,
        reusable_generated_at: str | None = None,
        progress_callback: Callable[[str, str], None] | None = None,
        force_online_refresh: bool = False,
    ) -> dict[str, Any]:
        canonical = normalize_symbol(symbol)
        selected_modules = set(
            (plan or {}).get("selected_modules")
            or (
                "market",
                "company_information",
                "fundamentals",
                "earnings_quality",
                "financial_drivers",
                "business_structure",
                "shareholder_structure",
                "analyst_expectations",
                "event_timeline",
                "peer_comparison",
                "outlook_calibration",
            )
        )
        required_modules = set((plan or {}).get("required_modules") or selected_modules)
        reusable = dict(reusable_evidence or {})
        module_statuses: dict[str, dict[str, Any]] = {}

        self._notify(progress_callback, "market", "正在核验价格与技术结构…")
        try:
            evidence = self.analysis.stock_research(user_id, canonical)
            module_statuses["market"] = self._module_status(
                "market", "fresh", required=True
            )
        except Exception:
            evidence = self._market_fallback(reusable, canonical)
            if not evidence:
                raise
            module_statuses["market"] = self._module_status(
                "market", "reused_fallback", required=True
            )
            evidence.setdefault("warnings", []).append(
                "最新价格结构暂未更新，当前使用已保存的最近可核验日线。"
            )
        configured_name = RESEARCH_TARGETS.get(canonical, {}).get("name")
        if configured_name:
            evidence["display_name"] = configured_name
        price_signal_label = (evidence.get("conditional_outlook") or {}).get(
            "price_signal_label"
        ) or (evidence.get("conditional_outlook") or {}).get("label")
        is_a_share = canonical.endswith((".SS", ".SZ"))

        if (plan or {}).get("focus") == "price_cause":
            quote_service = self.fundamentals if is_a_share else self.us_fundamentals
            try:
                valuation = quote_service.get_quote(
                    canonical,
                    refresh_max_age_seconds=(
                        0 if force_online_refresh else (600 if is_a_share else 900)
                    ),
                )
            except (ValueError, TypeError):
                valuation = None
            current_quote = _current_quote_from_valuation(valuation)
            if current_quote:
                for key in (
                    "quote_basis",
                    "quote_label",
                    "market_state",
                    "complete_daily_bar_confirmed",
                ):
                    if valuation and valuation.get(key) is not None:
                        current_quote[key] = valuation[key]
                evidence["current_quote"] = current_quote

        if "company_information" in selected_modules:
            self._notify(
                progress_callback,
                "company_information",
                "正在核验公告、新闻与事件线索…",
            )
            information_key = (
                "a_share_information" if is_a_share else "global_information"
            )
            information = self._load_module(
                evidence=evidence,
                reusable=reusable,
                target_key=information_key,
                module_key="company_information",
                loader=(
                    (
                        lambda: self.china_info.get_packet(
                            canonical,
                            refresh_max_age_seconds=(
                                0 if force_online_refresh else 300
                            ),
                        )
                    )
                    if is_a_share
                    else (
                        lambda: self.global_info.get_packet(
                            canonical,
                            refresh_max_age_seconds=(
                                0 if force_online_refresh else 900
                            ),
                        )
                    )
                ),
                required="company_information" in required_modules,
                max_age_hours=self._max_age(plan, "company_information"),
                reusable_generated_at=reusable_generated_at,
                statuses=module_statuses,
            )
            if information and is_a_share:
                evidence["conditional_outlook"] = build_conditional_outlook(
                    evidence["metrics"],
                    evidence["price_levels"],
                    sentiment=information.get("sentiment"),
                )
                missing = evidence.get("research_frame", {}).get(
                    "missing_information", []
                )
                evidence["research_frame"]["missing_information"] = [
                    item
                    for item in missing
                    if not item.startswith("公司最新公告")
                    and not item.startswith("新闻与事件")
                ]
            elif information and not is_a_share and information.get("news"):
                missing = evidence.get("research_frame", {}).get(
                    "missing_information", []
                )
                evidence["research_frame"]["missing_information"] = [
                    item for item in missing if not item.startswith("新闻与事件")
                ]

        if "fundamentals" in selected_modules:
            self._notify(
                progress_callback,
                "fundamentals",
                "正在核验最新报价、财务与估值…",
            )
            packet = self._load_module(
                evidence=evidence,
                reusable=reusable,
                target_key="fundamentals",
                module_key="fundamentals",
                loader=(
                    (
                        lambda: self.fundamentals.get_packet(
                            canonical,
                            refresh_max_age_seconds=(
                                0 if force_online_refresh else 600
                            ),
                        )
                    )
                    if is_a_share
                    else (
                        lambda: self.us_fundamentals.get_packet(
                            canonical,
                            refresh_max_age_seconds=(
                                0 if force_online_refresh else 900
                            ),
                        )
                    )
                ),
                required="fundamentals" in required_modules,
                max_age_hours=self._max_age(plan, "fundamentals"),
                reusable_generated_at=reusable_generated_at,
                statuses=module_statuses,
            )
            if packet:
                current_quote = _current_quote_from_valuation(packet.get("valuation"))
                if current_quote:
                    evidence["current_quote"] = current_quote
                summary = packet.get("summary") or {}
                if packet.get("valuation") and summary.get("latest_report"):
                    missing = evidence.get("research_frame", {}).get(
                        "missing_information", []
                    )
                    evidence["research_frame"]["missing_information"] = [
                        item
                        for item in missing
                        if not item.startswith("结构化财务与估值")
                    ]
                if not is_a_share:
                    regulatory_filings = packet.get("regulatory_filings") or []
                    missing = evidence.get("research_frame", {}).get(
                        "missing_information", []
                    )
                    evidence["research_frame"]["missing_information"] = [
                        item
                        for item in missing
                        if not (item.startswith("公司最新公告") and regulatory_filings)
                    ]

        module_loaders: tuple[tuple[str, str, Callable[[], dict[str, Any]]], ...] = (
            (
                "earnings_quality",
                "earnings_quality",
                lambda: self.earnings_quality.get_packet(canonical),
            ),
            (
                "financial_drivers",
                "financial_drivers",
                lambda: self.financial_drivers.get_packet(canonical),
            ),
            (
                "business_structure",
                "business_structure",
                lambda: self.business_structure.get_packet(canonical),
            ),
            (
                "shareholder_structure",
                "shareholder_structure",
                lambda: self.shareholders.get_packet(canonical),
            ),
            (
                "analyst_expectations",
                "analyst_expectations",
                lambda: self.analyst_expectations.get_packet(canonical),
            ),
            (
                "event_timeline",
                "event_timeline",
                lambda: self.event_timeline.get_packet(
                    canonical, refresh_sources=force_online_refresh
                ),
            ),
            (
                "peer_comparison",
                "peer_comparison",
                lambda: self.peer_comparison.get_packet(canonical),
            ),
            (
                "outlook_calibration",
                "outlook_calibration",
                lambda: self.outlook_calibration.get_packet(canonical),
            ),
        )
        for module_key, target_key, loader in module_loaders:
            if module_key not in selected_modules:
                continue
            if not is_a_share and module_key in {
                "business_structure",
                "shareholder_structure",
                "analyst_expectations",
            }:
                module_statuses[module_key] = self._module_status(
                    module_key, "not_applicable", required=False
                )
                continue
            self._notify(
                progress_callback,
                module_key,
                f"正在核验{self._module_label(module_key)}…",
            )
            packet = self._load_module(
                evidence=evidence,
                reusable=reusable,
                target_key=target_key,
                module_key=module_key,
                loader=loader,
                required=module_key in required_modules,
                max_age_hours=self._max_age(plan, module_key),
                reusable_generated_at=reusable_generated_at,
                statuses=module_statuses,
            )
            if not packet:
                continue
            if (
                module_key == "analyst_expectations"
                and packet.get("status") == "available"
            ):
                missing = evidence.get("research_frame", {}).get(
                    "missing_information", []
                )
                evidence["research_frame"]["missing_information"] = [
                    item
                    for item in missing
                    if not item.startswith("行业供需与一致预期")
                ]
                fundamentals_packet = evidence.get("fundamentals") or {}
                summary = fundamentals_packet.get("summary") or {}
                summary["missing_context"] = [
                    item
                    for item in summary.get("missing_context") or []
                    if not item.startswith("分析师一致预期")
                ]
            elif module_key == "peer_comparison":
                fundamentals_packet = evidence.get("fundamentals") or {}
                summary = fundamentals_packet.get("summary") or {}
                summary["missing_context"] = [
                    item
                    for item in summary.get("missing_context") or []
                    if not item.startswith("行业可比估值分位")
                ]
            elif module_key == "outlook_calibration" and packet.get("calibration"):
                evidence["conditional_outlook"] = attach_outlook_calibration(
                    evidence["conditional_outlook"],
                    packet["calibration"],
                    price_signal_label,
                )

        evidence["conditional_outlook"] = align_conditional_outlook_with_current_quote(
            evidence.get("conditional_outlook") or {},
            evidence.get("current_quote"),
        )

        evidence["research_plan"] = dict(plan or {})
        evidence["module_statuses"] = module_statuses
        unavailable_required = [
            key
            for key in required_modules
            if (module_statuses.get(key) or {}).get("status") == "unavailable"
        ]
        evidence["evidence_status"] = "partial" if unavailable_required else "ready"
        evidence["evidence_debate"] = build_evidence_debate(evidence)
        evidence["analysis_board"] = build_research_analysis_board(evidence)
        evidence["evidence_readiness"] = evidence["analysis_board"]["readiness"]
        evidence["research_claims"] = build_research_claim_ledger(evidence)
        return evidence

    @staticmethod
    def _notify(
        callback: Callable[[str, str], None] | None,
        module_key: str,
        label: str,
    ) -> None:
        if callback is not None:
            callback(module_key, label)

    @staticmethod
    def _market_fallback(reusable: dict[str, Any], canonical: str) -> dict[str, Any]:
        if not reusable.get("metrics") or not reusable.get("provenance"):
            return {}
        keys = (
            "type",
            "generated_at",
            "symbol",
            "display_name",
            "facts",
            "metrics",
            "current_quote",
            "price_levels",
            "conditional_outlook",
            "recent_bars",
            "research_frame",
            "provenance",
            "warnings",
        )
        packet = {key: reusable.get(key) for key in keys if key in reusable}
        packet["type"] = "stock_research"
        packet["symbol"] = canonical
        packet["generated_at"] = datetime.now(timezone.utc).isoformat()
        packet["warnings"] = list(packet.get("warnings") or [])
        return packet

    def _load_module(
        self,
        *,
        evidence: dict[str, Any],
        reusable: dict[str, Any],
        target_key: str,
        module_key: str,
        loader: Callable[[], dict[str, Any]],
        required: bool,
        max_age_hours: int,
        reusable_generated_at: str | None,
        statuses: dict[str, dict[str, Any]],
    ) -> dict[str, Any] | None:
        saved = reusable.get(target_key)
        if (
            saved
            and max_age_hours > 0
            and self._reusable_is_fresh(
                reusable_generated_at or reusable.get("generated_at"), max_age_hours
            )
        ):
            evidence[target_key] = saved
            statuses[module_key] = self._module_status(
                module_key, "reused", required=required
            )
            return saved
        try:
            packet = loader()
            evidence[target_key] = packet
            statuses[module_key] = self._module_status(
                module_key, "fresh", required=required
            )
            return packet
        except Exception:
            if saved:
                evidence[target_key] = saved
                statuses[module_key] = self._module_status(
                    module_key, "reused_fallback", required=required
                )
                evidence.setdefault("warnings", []).append(
                    f"最新{self._module_label(module_key)}暂未更新，当前使用已保存的最近可核验证据。"
                )
                return saved
            statuses[module_key] = self._module_status(
                module_key, "unavailable", required=required
            )
            evidence.setdefault("warnings", []).append(
                f"本轮未取得{self._module_label(module_key)}，回答会明确该项缺口。"
            )
            return None

    @staticmethod
    def _max_age(plan: dict[str, Any] | None, module_key: str) -> int:
        return int(((plan or {}).get("module_max_age_hours") or {}).get(module_key, 0))

    @staticmethod
    def _reusable_is_fresh(value: Any, max_age_hours: int) -> bool:
        if not value or max_age_hours <= 0:
            return False
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            age_hours = (
                datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)
            ).total_seconds() / 3600
            return 0 <= age_hours <= max_age_hours
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _module_label(module_key: str) -> str:
        return {
            "market": "价格与技术结构",
            "company_information": "公告、新闻与情绪",
            "fundamentals": "财务与最新估值",
            "earnings_quality": "财报质量",
            "financial_drivers": "利润与现金流驱动",
            "business_structure": "主营业务结构",
            "shareholder_structure": "股东结构",
            "analyst_expectations": "分析师预期",
            "event_timeline": "重要事件脉络",
            "peer_comparison": "同行比较",
            "outlook_calibration": "历史条件走查",
        }.get(module_key, module_key)

    @classmethod
    def _module_status(
        cls, module_key: str, status: str, *, required: bool
    ) -> dict[str, Any]:
        return {
            "module": module_key,
            "label": cls._module_label(module_key),
            "status": status,
            "required": required,
        }


class ResearchReportService:
    def __init__(
        self,
        database: Database,
        evidence_service: StockResearchEvidenceService,
        agent: AgentService,
        settings: Settings,
    ):
        self.database = database
        self.evidence_service = evidence_service
        self.agent = agent
        self.settings = settings
        self.security_master = SecurityMasterService(database)
        self.editor_user = database.ensure_system_editor()
        self.tracking = ResearchTrackingService(database)
        self._ensure_editor_targets()
        self.tracking.ensure_existing_reports()

    def _ensure_editor_targets(self) -> None:
        for symbol in self.settings.default_research_symbols:
            canonical = normalize_symbol(symbol)
            target = RESEARCH_TARGETS.get(canonical, {})
            self.database.upsert_watchlist(
                self.editor_user["id"],
                canonical,
                target.get("name") or canonical,
                target.get("market"),
                target.get("thesis") or "持续跟踪价格、基本面与风险证据变化",
            )

    def generate(
        self,
        symbol: str,
        execute_agent: bool = False,
        force: bool = False,
    ) -> dict[str, Any]:
        canonical = normalize_symbol(symbol)
        evidence = self.evidence_service.build(self.editor_user["id"], canonical)
        name = self.security_master.display_name(
            canonical,
            evidence.get("display_name"),
        )
        evidence["display_name"] = name
        fingerprint = self._fingerprint(evidence)
        latest = self.database.latest_research_report(canonical)
        if not force and latest and latest["fingerprint"] == fingerprint:
            event = self.tracking.record_report(latest)
            self._index_report_knowledge(latest, event)
            return {
                "decision": "unchanged",
                "reason": "核心证据未发生变化",
                "report": latest,
            }

        run = self.agent.run(
            user=self.editor_user,
            intent="stock_research",
            message=f"生成 {name} 的服务器预计算研究快照。",
            evidence=evidence,
            model_tier="deep",
            execute_agent=execute_agent,
        )
        date_label = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
        title = f"{name}研究快照｜{date_label}"
        report = self.database.create_research_report(
            symbol=canonical,
            name=name,
            title=title,
            summary=self._summary(run["answer"]),
            body=run["answer"],
            status=run["status"],
            fingerprint=fingerprint,
            evidence=evidence,
            run_id=run["id"],
            market_timestamp=(evidence.get("provenance") or {}).get("market_timestamp"),
        )
        event = self.tracking.record_report(report, latest)
        self._index_report_knowledge(report, event)
        return {
            "decision": "published",
            "reason": "已写入最新研究证据",
            "report": report,
        }

    def refresh_targets(self) -> dict[str, Any]:
        results = []
        symbols = sorted(
            {
                normalize_symbol(symbol)
                for symbol in (
                    *self.settings.default_research_symbols,
                    *self.database.list_distinct_watchlist_symbols(
                        exclude_user_id=self.editor_user["id"]
                    ),
                    *self.database.list_distinct_deep_stock_symbols(),
                )
            }
        )
        for symbol in symbols:
            try:
                result = self.generate(
                    symbol,
                    execute_agent=self.settings.background_use_hermes
                    and self.settings.hermes_enabled,
                )
                results.append(
                    {
                        "symbol": normalize_symbol(symbol),
                        "status": "ok",
                        "decision": result["decision"],
                        "report_id": result["report"]["id"],
                    }
                )
            except Exception as exc:
                results.append(
                    {
                        "symbol": symbol,
                        "status": "failed",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
        return {
            "requested": len(symbols),
            "completed": sum(item["status"] == "ok" for item in results),
            "results": results,
        }

    def get_latest(
        self, symbol: str, generate_if_missing: bool = True
    ) -> dict[str, Any] | None:
        canonical = normalize_symbol(symbol)
        report = self.database.latest_research_report(canonical)
        if report is None and generate_if_missing:
            report = self.generate(canonical)["report"]
        return report

    def list_latest(self, limit: int = 20) -> list[dict[str, Any]]:
        return [
            self.public_report(item)
            for item in self.database.list_latest_research_reports(limit=limit)
        ]

    def public_report(self, report: dict[str, Any]) -> dict[str, Any]:
        item = dict(report)
        symbol = normalize_symbol(str(item.get("symbol") or ""))
        original_name = str(item.get("name") or "")
        display_name = self.security_master.display_name(
            symbol,
            original_name,
            (item.get("evidence") or {}).get("display_name"),
        )
        item["name"] = display_name
        if original_name and original_name != display_name:
            for key in ("title", "summary", "body"):
                if item.get(key):
                    item[key] = str(item[key]).replace(original_name, display_name)
        for key in ("evidence", "fingerprint", "run_id"):
            item.pop(key, None)
        return item

    @staticmethod
    def _fingerprint(evidence: dict[str, Any]) -> str:
        information = evidence.get("a_share_information") or {}
        global_information = evidence.get("global_information") or {}
        fundamentals = evidence.get("fundamentals") or {}
        summary = fundamentals.get("summary") or {}
        latest_report = summary.get("latest_report") or {}
        announcements = information.get("announcements") or []
        global_news = global_information.get("news") or []
        regulatory_filings = fundamentals.get("regulatory_filings") or []
        peer_comparison = evidence.get("peer_comparison") or {}
        peer_metrics = peer_comparison.get("metrics") or {}
        peer_operating = peer_comparison.get("operating_comparison") or {}
        earnings_quality = evidence.get("earnings_quality") or {}
        financial_drivers = evidence.get("financial_drivers") or {}
        business_structure = evidence.get("business_structure") or {}
        shareholder_structure = evidence.get("shareholder_structure") or {}
        analyst_expectations = evidence.get("analyst_expectations") or {}
        event_timeline = evidence.get("event_timeline") or {}
        stable = {
            "renderer_version": "stock_report_v18_structured_claims",
            "symbol": evidence.get("symbol"),
            "market_timestamp": (evidence.get("provenance") or {}).get(
                "market_timestamp"
            ),
            "metrics": evidence.get("metrics"),
            "price_levels": evidence.get("price_levels"),
            "sentiment": {
                key: (information.get("sentiment") or {}).get(key)
                for key in (
                    "band",
                    "score",
                    "confidence",
                    "sample_size",
                    "positive_count",
                    "negative_count",
                    "neutral_count",
                )
            },
            "latest_announcement": announcements[0].get("url")
            if announcements
            else None,
            "latest_global_news": global_news[0].get("url") if global_news else None,
            "latest_regulatory_filing": (
                regulatory_filings[0].get("url") if regulatory_filings else None
            ),
            "valuation_timestamp": (fundamentals.get("valuation") or {}).get(
                "market_timestamp"
            ),
            "financial_report_date": latest_report.get("report_date"),
            "earnings_quality": {
                "report_date": (earnings_quality.get("latest_report") or {}).get(
                    "report_date"
                ),
                "overall_label": earnings_quality.get("overall_label"),
                "confidence": earnings_quality.get("confidence"),
                "supports": earnings_quality.get("supports") or [],
                "contradictions": earnings_quality.get("contradictions") or [],
                "factors": earnings_quality.get("factors") or [],
            },
            "financial_drivers": {
                "report_date": (financial_drivers.get("latest_period") or {}).get(
                    "report_date"
                ),
                "overall_label": financial_drivers.get("overall_label"),
                "confidence": financial_drivers.get("confidence"),
                "profit_bridge": financial_drivers.get("profit_bridge") or {},
                "confirmed_mechanical_drivers": financial_drivers.get(
                    "confirmed_mechanical_drivers"
                )
                or [],
                "plausible_clues": financial_drivers.get("plausible_clues") or [],
                "company_explanations": financial_drivers.get("company_explanations")
                or [],
                "filing_document": {
                    key: (
                        (financial_drivers.get("filing_evidence") or {}).get("document")
                        or {}
                    ).get(key)
                    for key in ("article_code", "report_period", "content_hash")
                },
                "unresolved_causes": financial_drivers.get("unresolved_causes") or [],
            },
            "business_structure": {
                "anchor_report_date": business_structure.get("anchor_report_date"),
                "method": business_structure.get("method"),
                "dimensions": business_structure.get("dimensions") or [],
                "key_changes": business_structure.get("key_changes") or [],
                "coverage_limits": business_structure.get("coverage_limits") or [],
            },
            "shareholder_structure": {
                "holder_count_as_of": shareholder_structure.get("holder_count_as_of"),
                "holder_count": shareholder_structure.get("holder_count"),
                "holder_count_change_pct": shareholder_structure.get(
                    "holder_count_change_pct"
                ),
                "holder_count_signal": shareholder_structure.get("holder_count_signal"),
                "top10_report_date": shareholder_structure.get("top10_report_date"),
                "top10_ratio_pct": shareholder_structure.get("top10_ratio_pct"),
                "top_holders": shareholder_structure.get("top_holders") or [],
            },
            "analyst_expectations": {
                "as_of_date": analyst_expectations.get("as_of_date"),
                "latest_report_date": analyst_expectations.get("latest_report_date"),
                "rating_organization_count": analyst_expectations.get(
                    "rating_organization_count"
                ),
                "rating_counts": analyst_expectations.get("rating_counts") or {},
                "forecast_eps": analyst_expectations.get("forecast_eps") or [],
                "revision": analyst_expectations.get("revision") or {},
                "latest_reports": [
                    {
                        "title": item.get("title"),
                        "institution": item.get("institution"),
                        "published_at": item.get("published_at"),
                        "rating": item.get("rating"),
                        "forecast_eps": item.get("forecast_eps") or [],
                    }
                    for item in (analyst_expectations.get("latest_reports") or [])[:6]
                ],
            },
            "event_timeline": {
                "as_of_date": event_timeline.get("as_of_date"),
                "themes": event_timeline.get("themes") or [],
                "events": [
                    {
                        "event_type": item.get("event_type"),
                        "title": item.get("title"),
                        "published_at": item.get("published_at"),
                        "evidence_level": item.get("evidence_level"),
                        "research_relevance": item.get("research_relevance"),
                    }
                    for item in (event_timeline.get("events") or [])[:12]
                ],
            },
            "peer_valuation": {
                key: {
                    "subject": value.get("subject_value"),
                    "median": value.get("peer_median"),
                    "sample": value.get("peer_sample_size"),
                }
                for key, value in peer_metrics.items()
            },
            "peer_operating": {
                "status": peer_operating.get("status"),
                "anchor_report_date": peer_operating.get("anchor_report_date"),
                "coverage": peer_operating.get("coverage") or {},
                "metrics": peer_operating.get("metrics") or {},
                "peers": [
                    {
                        "symbol": item.get("symbol"),
                        "status": item.get("status"),
                        "financial": item.get("financial") or {},
                        "business_profile": item.get("business_profile") or {},
                    }
                    for item in (peer_operating.get("peers") or [])
                ],
            },
            "peer_as_of": peer_comparison.get("as_of"),
            "calibration_method": (
                (evidence.get("outlook_calibration") or {}).get("calibration") or {}
            ).get("method"),
            "calibration_history_last": (evidence.get("outlook_calibration") or {}).get(
                "history_last"
            ),
        }
        return hashlib.sha256(
            json.dumps(stable, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _summary(body: str) -> str:
        paragraphs = [line.strip(" -") for line in body.splitlines() if line.strip()]
        return (" ".join(paragraphs[:3]) if paragraphs else body.strip())[:320]

    def _index_report_knowledge(
        self, report: dict[str, Any], event: dict[str, Any]
    ) -> None:
        source_key = f"research-report:{report['symbol']}"
        document_id = (
            "common-" + hashlib.sha256(source_key.encode("utf-8")).hexdigest()[:24]
        )
        payload = event.get("payload") or {}
        content = (
            f"# {report['name']}长期研究档案\n\n"
            f"证券代码：{report['symbol']}\n\n"
            f"报告时间：{report['generated_at']}\n\n"
            f"市场数据截止：{report.get('market_timestamp') or '时间待确认'}\n\n"
            f"## 最新证据变化\n\n{event.get('summary') or '尚未形成变化摘要。'}\n\n"
            f"## 当前研究报告\n\n{report['body']}\n\n"
            f"## 研究边界\n\n{payload.get('boundary') or '仅用于研究复核，不构成交易指令。'}"
        )
        self.database.upsert_knowledge_document(
            document_id=document_id,
            owner_user_id=None,
            scope="common",
            title=f"{report['name']}长期研究档案",
            original_name=f"{report['symbol']}-research-archive.md",
            mime_type="text/markdown",
            content=content,
            source_key=source_key,
        )
