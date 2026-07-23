from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
import hmac
from io import BytesIO
import logging
import re
import time
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from fastapi import FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse

from app.catalog import (
    INDEX_BY_SYMBOL,
    RESEARCH_TARGETS,
    SECURITY_NAME_ALIASES,
    normalize_symbol,
)
from app.config import PROJECT_ROOT, Settings
from app.db import Database
from app.providers.market import (
    CSIIndustryIndexProvider,
    EastmoneySectorProvider,
    EastmoneyGlobalIndexProvider,
    ProviderError,
    ResilientSectorProvider,
    SinaGoldProvider,
    SinaIndustrySectorProvider,
    SinaMarketBreadthProvider,
    TencentChinaIndexProvider,
    YahooMarketProvider,
)
from app.providers.china_info import AShareInformationProvider
from app.providers.business_structure import AShareBusinessStructureProvider
from app.providers.shareholders import AShareShareholderProvider
from app.providers.analyst_expectations import AShareAnalystExpectationsProvider
from app.providers.filings import AShareFilingProvider
from app.providers.fundamentals import AShareFundamentalsProvider
from app.providers.global_info import NasdaqCompanyNewsProvider
from app.providers.market_news import GoogleNewsMarketProvider
from app.providers.us_fundamentals import USEquityFundamentalsProvider
from app.providers.tushare import TushareClient, TushareProviderError
from app.services.agent import AgentService
from app.services.agent_stream import AgentStreamBroker
from app.services.analysis import MarketAnalysisService
from app.services.article import MarketPulseArticleService
from app.services.background import BackgroundScheduler, EventBroker
from app.services.business_structure import BusinessStructureAnalysisService
from app.services.shareholders import ShareholderStructureAnalysisService
from app.services.analyst_expectations import AnalystExpectationsService
from app.services.china_info import ChinaInformationService
from app.services.change_events import ChangeEventNotFound, ChangeEventService
from app.services.conversation_quality import ConversationQualityService
from app.services.deep_stock import DeepStockResearchService
from app.services.stock_screener import (
    StockScreenerService,
    StockScreenerUnavailable,
)
from app.services.stock_comparison import StockComparisonService
from app.services.stock_domain import (
    StockDomainInvalidState,
    StockDomainNotFound,
    StockDomainService,
    StockDomainVersionConflict,
)
from app.services.structured_ai import (
    StructuredAIConflict,
    StructuredAIInvalidState,
    StructuredAINotFound,
    StructuredAIService,
)
from app.services.observation_tasks import (
    ObservationTaskInvalidState,
    ObservationTaskNotFound,
    ObservationTaskService,
    ObservationTaskVersionConflict,
)
from app.services.stock_assets import StockAssetListService
from app.services.stock_workspace import StockWorkspaceService
from app.services.position_ledger import (
    PositionLedgerConflict,
    PositionLedgerInvalidState,
    PositionLedgerNotFound,
    PositionLedgerService,
)
from app.services.trade_workflow import (
    TradeWorkflowConflict,
    TradeWorkflowInvalidState,
    TradeWorkflowNotFound,
    TradeWorkflowService,
)
from app.services.tushare_snapshots import TushareSnapshotService
from app.services.li_zong_strategy_service import LiZongStrategyService
from app.services.today_overview import TodayOverviewService
from app.services.calibration import OutlookCalibrationService
from app.services.fundamentals import FundamentalsService
from app.services.earnings_quality import EarningsQualityService
from app.services.evidence_tasks import EvidenceTaskService
from app.services.event_timeline import EventTimelineService
from app.services.financial_drivers import FinancialDriverAnalysisService
from app.services.filings import AShareFilingService
from app.services.global_info import GlobalInformationService
from app.services.global_search import GlobalSearchService
from app.services.us_fundamentals import USEquityFundamentalsService
from app.services.peer_comparison import PeerComparisonService
from app.services.data_health import DataHealthService
from app.services.live_market import (
    LiveMarketService,
    market_quote_semantics,
    previous_market_session_date,
)
from app.services.knowledge import KnowledgeService
from app.services.market_news import MarketNewsService
from app.services.research_reports import (
    ResearchReportService,
    StockResearchEvidenceService,
)
from app.services.research_claims import build_research_claim_ledger
from app.services.research_priority import ResearchPriorityService
from app.services.research_actions import ResearchActionService
from app.services.research_outcomes import ResearchOutcomeService
from app.utils import utc_now


SESSION_COOKIE_NAME = "qingshu_session"
Image.MAX_IMAGE_PIXELS = 25_000_000
logger = logging.getLogger(__name__)


class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class LegacySessionClaim(BaseModel):
    user_id: str = Field(min_length=36, max_length=36)


class WatchlistUpsert(BaseModel):
    symbol: str = Field(min_length=1, max_length=24)
    name: str | None = Field(default=None, max_length=80)
    market: str | None = Field(default=None, max_length=40)
    thesis: str | None = Field(default=None, max_length=1000)


class MemoryCandidateCreate(BaseModel):
    kind: str = Field(default="preference", min_length=1, max_length=40)
    content: str = Field(min_length=1, max_length=2000)


class ChangeRelevanceUpdate(BaseModel):
    relevance_status: Literal["relevant", "irrelevant"]


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    symbol: str | None = Field(default=None, max_length=24)
    model_tier: Literal["economy", "deep", "vision"] = "economy"
    execute_agent: bool = True
    prefer_precomputed: bool = False
    image_id: str | None = Field(default=None, max_length=36)
    conversation_id: str | None = Field(default=None, max_length=36)
    request_id: str | None = Field(default=None, min_length=8, max_length=64)
    quality_scope: Literal["user", "evaluation"] = "user"


class ChatRefineRequest(BaseModel):
    preview_run_id: str = Field(min_length=36, max_length=36)
    conversation_id: str = Field(min_length=36, max_length=36)
    assistant_message_id: str = Field(min_length=36, max_length=36)
    model_tier: Literal["economy", "deep"] = "economy"


class ConversationCreate(BaseModel):
    title: str = Field(default="新的研究对话", min_length=1, max_length=160)
    quality_scope: Literal["user", "evaluation"] = "user"


class ConversationPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    quality_scope: Literal["user", "evaluation"] | None = None


class DeepStockEntryContext(BaseModel):
    source_kind: Literal["stock_screen", "li_zong_strategy"]
    source_label: str = Field(min_length=1, max_length=80)
    display_name: str | None = Field(default=None, max_length=80)
    profile_key: str | None = Field(default=None, max_length=60)
    as_of_date: str | None = Field(default=None, max_length=32)
    candidate_status: str | None = Field(default=None, max_length=40)
    matched_reasons: list[str] = Field(default_factory=list, max_length=8)
    missing_fields: list[str] = Field(default_factory=list, max_length=8)


class DeepStockStart(BaseModel):
    symbol: str = Field(min_length=1, max_length=24)
    conversation_id: str | None = Field(default=None, max_length=36)
    entry_context: DeepStockEntryContext | None = None


class StockRelationUpdate(BaseModel):
    base_version: int = Field(ge=1)
    relation_type: Literal["watching", "holding", "ended"]
    priority: Literal["high", "normal", "low"] | None = None
    tracking_status: Literal["active", "paused"] = "active"
    workflow_status: Literal["idle", "researching", "waiting_data"] = "idle"
    attention_tags: list[str] = Field(default_factory=list, max_length=12)


class ThesisCandidateCreate(BaseModel):
    reason_text: str = Field(min_length=1, max_length=1200)
    watch_items: list[str] = Field(default_factory=list, max_length=20)
    recheck_conditions: list[str] = Field(default_factory=list, max_length=20)
    source: Literal["user", "ai"] = "user"
    source_run_id: str | None = Field(default=None, max_length=36)
    base_version: int = Field(default=0, ge=0)


class ObservationTaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=2000)
    priority: Literal["high", "normal", "low"] = "normal"
    due_at: str | None = Field(default=None, max_length=40)
    thesis_id: str | None = Field(default=None, max_length=36)
    change_ref: str | None = Field(default=None, max_length=160)
    source_type: Literal["user", "research_action"] = "user"
    source_ref_id: str | None = Field(default=None, max_length=160)


class ObservationTaskUpdate(BaseModel):
    base_version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, min_length=1, max_length=2000)
    priority: Literal["high", "normal", "low"] | None = None
    due_at: str | None = Field(default=None, max_length=40)


class ObservationTaskTransition(BaseModel):
    base_version: int = Field(ge=1)
    status: Literal[
        "pending",
        "in_progress",
        "waiting_data",
        "completed",
        "ignored",
        "cancelled",
    ]
    result_text: str | None = Field(default=None, max_length=3000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=12)


class PositionOpeningCreate(BaseModel):
    as_of_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    quantity: str = Field(min_length=1, max_length=40)
    cost_price: str = Field(min_length=1, max_length=40)
    fees: str | None = Field(default=None, max_length=40)
    note: str | None = Field(default=None, max_length=1000)


class PositionOperationCreate(BaseModel):
    operation_type: Literal["buy", "add", "reduce", "sell"]
    operated_at: str = Field(min_length=20, max_length=40)
    price: str = Field(min_length=1, max_length=40)
    quantity: str = Field(min_length=1, max_length=40)
    fees: str | None = Field(default=None, max_length=40)
    reason_text: str = Field(min_length=1, max_length=1200)
    plan_id: str | None = Field(default=None, max_length=80)


class PositionOperationRevisionCreate(BaseModel):
    base_revision: int = Field(default=0, ge=0)
    price: str = Field(min_length=1, max_length=40)
    quantity: str = Field(min_length=1, max_length=40)
    fees: str | None = Field(default=None, max_length=40)
    reason_text: str = Field(min_length=1, max_length=1200)


class PositionAdjustmentCreate(BaseModel):
    adjustment_type: Literal[
        "quantity_correction", "cost_correction", "corporate_action", "other"
    ]
    effective_at: str = Field(min_length=20, max_length=40)
    quantity_delta: str = Field(default="0", min_length=1, max_length=40)
    cost_delta: str = Field(default="0", min_length=1, max_length=40)
    reason_text: str = Field(min_length=1, max_length=1200)
    evidence_text: str | None = Field(default=None, max_length=1200)


class ActionPlanCreate(BaseModel):
    action_type: Literal["buy", "add", "reduce", "sell", "hold"]
    trigger_text: str = Field(min_length=1, max_length=2000)
    target_quantity: str | None = Field(default=None, max_length=40)
    target_amount: str | None = Field(default=None, max_length=40)
    target_position_percent: str | None = Field(default=None, max_length=40)
    thesis_version_id: str | None = Field(default=None, max_length=36)
    expires_at: str | None = Field(default=None, max_length=40)


class ActionPlanPatch(BaseModel):
    base_version: int = Field(ge=1)
    action_type: Literal["buy", "add", "reduce", "sell", "hold"] | None = None
    trigger_text: str | None = Field(default=None, min_length=1, max_length=2000)
    target_quantity: str | None = Field(default=None, max_length=40)
    target_amount: str | None = Field(default=None, max_length=40)
    target_position_percent: str | None = Field(default=None, max_length=40)
    expires_at: str | None = Field(default=None, max_length=40)


class ActionPlanTransition(BaseModel):
    base_version: int = Field(ge=1)
    status: Literal[
        "checked",
        "saved",
        "cancelled",
        "expired",
    ]


class TradeReviewGenerateDraft(BaseModel):
    base_version: int = Field(default=0, ge=0)
    model_tier: Literal["economy", "deep"] = "economy"


class TradeReviewDraftPatch(BaseModel):
    base_version: int = Field(ge=1)
    price_result: str = Field(min_length=1, max_length=4000)
    logic_result: str = Field(min_length=1, max_length=6000)
    plan_deviation: str | None = Field(default=None, max_length=4000)
    bias_tags: list[str] = Field(default_factory=list, max_length=12)
    improvement_text: str | None = Field(default=None, max_length=4000)


class TradeReviewConfirm(BaseModel):
    base_version: int = Field(ge=1)


class StockScreenFilters(BaseModel):
    min_market_cap_yi: float | None = Field(default=None, ge=0)
    max_market_cap_yi: float | None = Field(default=None, ge=0)
    min_pe_ttm: float | None = None
    max_pe_ttm: float | None = None
    min_pb: float | None = None
    max_pb: float | None = None
    min_turnover_rate: float | None = Field(default=None, ge=0)
    max_turnover_rate: float | None = Field(default=None, ge=0)
    min_volume_ratio: float | None = Field(default=None, ge=0)
    min_return_5d: float | None = None
    min_return_20d: float | None = None
    max_return_20d: float | None = None
    min_industry_excess_20d: float | None = None
    min_revenue_yoy: float | None = None
    min_net_profit_yoy: float | None = None
    min_roe: float | None = None
    industry: str | None = Field(default=None, max_length=40)
    exclude_st: bool | None = None
    min_listed_days: int | None = Field(default=None, ge=0, le=10000)


class StockScreenRequest(BaseModel):
    profile: Literal["quality", "trend", "value", "pullback"] = "quality"
    market: Literal["all", "sh", "sz", "bj", "main", "gem", "star"] = "all"
    max_results: int = Field(default=12, ge=1, le=30)
    filters: StockScreenFilters | None = None
    force_refresh: bool = False


class TushareSymbolRefreshRequest(BaseModel):
    as_of_date: str | None = Field(default=None, pattern=r"^\d{4}-?\d{2}-?\d{2}$")


class LiZongRunRequest(BaseModel):
    symbols: list[str] = Field(min_length=1, max_length=20)
    as_of_date: str | None = Field(default=None, pattern=r"^\d{4}-?\d{2}-?\d{2}$")
    refresh_data: bool = True
    roe_min_pct: float | None = Field(default=None, ge=0, le=100)


class LiZongUniverseRunRequest(BaseModel):
    as_of_date: str | None = Field(default=None, pattern=r"^\d{4}-?\d{2}-?\d{2}$")
    batch_size: int | None = Field(default=None, ge=1, le=200)


class ArticleGenerateRequest(BaseModel):
    model_tier: Literal["economy", "deep"] = "economy"
    execute_agent: bool = False


def _public_evidence_number(
    value: Any, *, digits: int = 2, signed: bool = False
) -> str | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or abs(number) == float("inf"):
        return None
    if signed:
        return f"{number:+.{digits}f}"
    return f"{number:.{digits}f}".rstrip("0").rstrip(".")


def _external_ts_code(symbol: str) -> str:
    return symbol[:-3] + ".SH" if symbol.endswith(".SS") else symbol


def _public_li_zong_candidate(item: dict[str, Any]) -> dict[str, Any]:
    result = dict(item.get("result") or {})
    rules = list(result.get("rule_results") or item.get("rule_results") or [])
    rule_map = {str(rule.get("rule_id")): rule for rule in rules}

    def actual(rule_id: str) -> Any:
        return (rule_map.get(rule_id) or {}).get("actual_value")

    roe_values = [
        entry.get("roe_pct")
        for entry in (actual("LZ-F-02") or [])
        if isinstance(entry, dict) and entry.get("roe_pct") is not None
    ]
    shareholder = actual("LZ-F-04") or {}
    annual_limits = actual("LZ-C-01") or {}
    recent_limits = actual("LZ-C-03") or {}
    bearish = actual("LZ-C-04") or {}
    new_high = actual("LZ-VP-01") or {}
    volume = actual("LZ-VP-02") or {}
    symbol = str(item.get("symbol") or result.get("symbol") or "")
    target = RESEARCH_TARGETS.get(symbol) or {}
    stock_basic = result.get("stock_basic") or {}
    return {
        "id": item.get("id"),
        "symbol": _external_ts_code(symbol),
        "internal_symbol": symbol,
        "name": stock_basic.get("name") or target.get("name") or symbol,
        "industry": stock_basic.get("industry"),
        "market": stock_basic.get("market") or target.get("market"),
        "status": item.get("status") or result.get("status"),
        "evaluation_status": item.get("evaluation_status") or result.get("status"),
        "strategy_version": item.get("strategy_version")
        or result.get("strategy_version"),
        "parameter_version": item.get("parameter_version")
        or result.get("parameter_version"),
        "data_version": item.get("data_version"),
        "as_of_date": item.get("as_of_date") or result.get("as_of_date"),
        "previous_status": item.get("previous_status"),
        "candidate_qualified": bool(result.get("candidate_qualified")),
        "triggered_rule_ids": list(result.get("triggered_rule_ids") or []),
        "summary": {
            "market_cap_yi": (actual("LZ-F-01") or {}).get("market_cap_yi"),
            "roe_min_pct": min(roe_values) if roe_values else None,
            "annual_roe_years": len(roe_values),
            "non_natural_holder_count": shareholder.get("non_natural_holder_count"),
            "unknown_holder_count": shareholder.get("unknown_holder_count"),
            "annual_limit_up_count": annual_limits.get("limit_up_count"),
            "has_consecutive_limit_up": (
                (rule_map.get("LZ-C-02") or {}).get("status") == "passed"
            ),
            "recent_limit_up_count": recent_limits.get("limit_up_count"),
            "recent_bearish_drop_count": bearish.get("bearish_drop_count"),
            "new_high_dates": list(new_high.get("new_high_dates") or []),
            "volume_sequences": list(volume.get("sequences") or []),
        },
        "rule_results": rules,
        "matched_reasons": [
            f"{rule.get('rule_id')} 已通过"
            for rule in rules
            if rule.get("status") == "passed"
        ][:6],
        "limitations": list(result.get("limitations") or []),
        "created_at": item.get("created_at"),
        "invalidated_at": item.get("invalidated_at"),
        "boundary": result.get("boundary")
        or "仅用于确定性研究候选筛选和人工复核，不构成买卖建议。",
    }


def _build_visible_evidence_sources(
    evidence: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Build a small, user-facing index of the structured evidence sent to Agent."""

    packet = evidence or {}
    display_name = str(packet.get("display_name") or "研究对象").strip()
    generated_at = packet.get("generated_at")
    sources: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add(
        kind: str,
        title: str,
        summary: str | None = None,
        *,
        as_of: Any = None,
        source: str | None = None,
        url: str | None = None,
    ) -> None:
        clean_title = str(title or "").strip()
        if not clean_title:
            return
        key = (kind, clean_title)
        if key in seen:
            return
        seen.add(key)
        item: dict[str, Any] = {"kind": kind, "title": clean_title}
        if summary:
            item["summary"] = str(summary).strip()
        if as_of:
            item["as_of"] = str(as_of)
        if source:
            item["source"] = source
        if url and re.match(r"^https?://", str(url).strip(), re.IGNORECASE):
            item["url"] = str(url).strip()
        sources.append(item)

    if packet.get("type") == "stock_comparison":
        for comparison_item in (packet.get("items") or [])[:5]:
            name = str(
                comparison_item.get("name")
                or comparison_item.get("symbol")
                or "研究对象"
            )
            if comparison_item.get("status") != "available":
                add(
                    "比较边界",
                    f"{name}本轮证据状态",
                    "本轮未形成可比较的确定性证据。",
                    as_of=generated_at,
                    source="多股统一口径研究",
                )
                continue
            snapshot = comparison_item.get("snapshot") or {}
            financial = snapshot.get("financial") or {}
            if financial.get("report_date"):
                add(
                    "财务口径",
                    f"{name}财务报告期",
                    (
                        f"{financial.get('report_date_name') or financial.get('report_date')}；"
                        f"{financial.get('period_basis_label') or financial.get('period_basis') or '口径待确认'}"
                    ),
                    as_of=financial.get("notice_date")
                    or financial.get("report_date"),
                    source="结构化财务披露",
                )
            for child in _build_visible_evidence_sources(
                comparison_item.get("evidence") or {}
            )[:3]:
                add(
                    str(child.get("kind") or "研究证据"),
                    f"{name}｜{child.get('title')}",
                    child.get("summary"),
                    as_of=child.get("as_of"),
                    source=child.get("source"),
                    url=child.get("url"),
                )
        return sources[:16]

    quote = packet.get("current_quote") or {}
    quote_price = _public_evidence_number(quote.get("price"))
    quote_change = _public_evidence_number(quote.get("pct_change"), signed=True)
    if quote_price is not None:
        currency = str(quote.get("currency") or "").strip()
        quote_label = str(quote.get("quote_label") or "最新报价").strip()
        quote_summary = f"{quote_label} {quote_price}"
        if currency:
            quote_summary += f" {currency}"
        if quote_change is not None:
            quote_summary += f"；涨跌幅 {quote_change}%"
        add(
            "行情事实",
            f"{str(quote.get('name') or display_name).strip()}最新报价",
            quote_summary,
            as_of=quote.get("market_timestamp"),
            source="实时行情快照",
        )

    metrics = packet.get("metrics") or {}
    provenance = packet.get("provenance") or {}
    daily_close = _public_evidence_number(metrics.get("latest_close"))
    if daily_close is not None:
        daily_parts = [f"最近完整日线收盘 {daily_close}"]
        trend_state = str(metrics.get("trend_state") or "").strip()
        if trend_state:
            daily_parts.append(f"趋势结构 {trend_state}")
        return_20d = _public_evidence_number(metrics.get("return_20d_pct"), signed=True)
        if return_20d is not None:
            daily_parts.append(f"近20日 {return_20d}%")
        volatility = _public_evidence_number(
            metrics.get("volatility_20d_annualized_pct")
        )
        if volatility is not None:
            daily_parts.append(f"20日年化波动 {volatility}%")
        add(
            "历史行情",
            f"{display_name}最近完整日线与技术结构",
            "；".join(daily_parts),
            as_of=provenance.get("market_timestamp"),
            source="复权历史日线与确定性指标",
        )

    earnings_quality = packet.get("earnings_quality") or {}
    if earnings_quality.get("status") == "available":
        latest_report = earnings_quality.get("latest_report") or {}
        report_name = str(
            latest_report.get("report_date_name")
            or latest_report.get("report_date")
            or "最新财报"
        )
        add(
            "财务证据",
            f"{display_name}{report_name}财报质量",
            earnings_quality.get("summary"),
            as_of=latest_report.get("notice_date") or latest_report.get("report_date"),
            source="定期报告与确定性财务分析",
        )

    financial_drivers = packet.get("financial_drivers") or {}
    if financial_drivers.get("status") == "available":
        latest_period = financial_drivers.get("latest_period") or {}
        period_name = str(
            latest_period.get("report_date_name")
            or latest_period.get("report_date")
            or "最新报告期"
        )
        add(
            "财务拆解",
            f"{display_name}{period_name}利润与现金流拆解",
            financial_drivers.get("summary"),
            as_of=latest_period.get("notice_date") or latest_period.get("report_date"),
            source="三表科目与财报原文",
        )

    information = packet.get("a_share_information") or {}
    for item in (information.get("announcements") or [])[:1]:
        if not isinstance(item, dict):
            continue
        add(
            "公司公告",
            str(item.get("title") or "公司公告"),
            item.get("summary"),
            as_of=item.get("published_at"),
            source="公司披露",
            url=item.get("url"),
        )
    news_items = [
        item
        for item in (information.get("news") or [])
        if isinstance(item, dict)
        and not re.search(
            r"走势预测|后市是否|买入机会|目标价|人气排名|涨停又炸板|主力.*扫货",
            str(item.get("title") or ""),
        )
    ]
    news_items = [
        item
        for _, item in sorted(
            enumerate(news_items),
            key=lambda pair: (
                0
                if re.search(
                    r"超节点|WAIC|OEX|算力|订单|中标|合同|回购|减持|增持|监管|财报",
                    str(pair[1].get("title") or ""),
                    re.IGNORECASE,
                )
                else 1,
                pair[0],
            ),
        )
    ]
    for item in news_items[:2]:
        if not isinstance(item, dict):
            continue
        add(
            "新闻线索",
            str(item.get("title") or "公司新闻"),
            item.get("summary"),
            as_of=item.get("published_at"),
            source="公开资讯线索",
            url=item.get("url"),
        )

    fundamentals = packet.get("fundamentals") or {}
    for item in (fundamentals.get("regulatory_filings") or [])[:2]:
        if not isinstance(item, dict):
            continue
        add(
            "监管文件",
            str(item.get("title") or item.get("form") or "监管文件"),
            item.get("summary"),
            as_of=item.get("filed_at") or item.get("published_at"),
            source="监管披露",
            url=item.get("url") or item.get("source_url"),
        )

    indices = [
        item
        for item in (packet.get("indices") or [])
        if isinstance(item, dict) and item.get("status") == "available"
    ]
    index_parts: list[str] = []
    for item in indices[:4]:
        metrics_item = item.get("metrics") or {}
        change = _public_evidence_number(metrics_item.get("return_1d_pct"), signed=True)
        if change is not None:
            index_parts.append(f"{item.get('name') or item.get('symbol')} {change}%")
    if index_parts:
        add(
            "大盘行情",
            "代表性指数最近完整交易日",
            "；".join(index_parts),
            as_of=generated_at,
            source="指数历史行情",
        )

    breadth = packet.get("market_breadth") or {}
    breadth_values = breadth.get("breadth") or {}
    if breadth.get("status") == "available" and breadth_values:
        add(
            "市场广度",
            "A股全市场上涨与下跌家数",
            (
                f"上涨 {breadth_values.get('advancers')} 家；"
                f"下跌 {breadth_values.get('decliners')} 家；"
                f"平盘 {breadth_values.get('unchanged')} 家"
            ),
            as_of=breadth.get("market_date"),
            source="沪深京全市场快照",
        )

    hot_sectors = packet.get("hot_sectors") or {}
    sector_parts: list[str] = []
    for item in (hot_sectors.get("sectors") or [])[:4]:
        if not isinstance(item, dict):
            continue
        change = _public_evidence_number(item.get("pct_change"), signed=True)
        if change is not None:
            sector_parts.append(f"{item.get('name')} {change}%")
    if sector_parts:
        add(
            "板块行情",
            "A股热门板块",
            "；".join(sector_parts),
            as_of=hot_sectors.get("market_timestamp"),
            source="板块涨跌幅榜",
        )

    if packet.get("type") == "stock_screen":
        screen_date = (packet.get("data_meta") or {}).get("latest_completed_trade_date")
        for item in (packet.get("items") or [])[:6]:
            reasons = "；".join(
                str(value) for value in (item.get("matched_reasons") or [])[:2]
            )
            add(
                "选股证据",
                f"{item.get('name')}（{item.get('internal_symbol')}）",
                reasons or "命中当前透明筛选规则",
                as_of=screen_date,
                source="确定性研究候选筛选",
            )

    li_zong = packet.get("li_zong_strategy") or {}
    if li_zong:
        passed = [
            str(item.get("rule_id"))
            for item in (li_zong.get("rule_results") or [])
            if item.get("status") == "passed"
        ]
        add(
            "策略证据",
            f"{display_name}李总策略逐规则快照",
            (
                f"状态 {li_zong.get('status') or '待核验'}；"
                f"通过规则 {', '.join(passed[:6]) or '无'}"
            ),
            as_of=li_zong.get("as_of_date"),
            source="Tushare稳定快照与确定性规则引擎",
        )

    market_drivers = packet.get("market_drivers") or {}
    for item in (market_drivers.get("items") or [])[:3]:
        if not isinstance(item, dict):
            continue
        add(
            "市场资讯",
            str(item.get("title") or "市场资讯"),
            item.get("summary"),
            as_of=item.get("published_at"),
            source="市场资讯线索",
            url=item.get("url"),
        )

    return sources[:12]


def create_app(
    settings: Settings | None = None,
    market_provider: Any | None = None,
    sector_provider: Any | None = None,
    gold_provider: Any | None = None,
    china_info_provider: Any | None = None,
    fundamentals_provider: Any | None = None,
    global_info_provider: Any | None = None,
    us_fundamentals_provider: Any | None = None,
    market_news_provider: Any | None = None,
    filing_provider: Any | None = None,
    business_structure_provider: Any | None = None,
    shareholder_provider: Any | None = None,
    analyst_expectations_provider: Any | None = None,
    breadth_provider: Any | None = None,
    industry_index_provider: Any | None = None,
    tushare_client: Any | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.ensure_directories()
    database = Database(settings.database_path, settings.workspace_root)
    database.initialize()
    knowledge = KnowledgeService(
        database, PROJECT_ROOT / "app" / "knowledge" / "common"
    )
    knowledge.seed_common_documents()
    supplied_market_provider = market_provider
    market_provider = market_provider or YahooMarketProvider(
        database, ttl_seconds=settings.market_cache_seconds
    )
    live_market_provider = supplied_market_provider or YahooMarketProvider(
        database, ttl_seconds=settings.intraday_cache_seconds
    )
    global_index_intraday_provider = (
        None
        if supplied_market_provider is not None
        else EastmoneyGlobalIndexProvider(
            database, ttl_seconds=settings.intraday_cache_seconds
        )
    )
    sector_provider = sector_provider or ResilientSectorProvider(
        EastmoneySectorProvider(database, ttl_seconds=settings.sector_cache_seconds),
        SinaIndustrySectorProvider(database, ttl_seconds=settings.sector_cache_seconds),
    )
    breadth_provider = breadth_provider or (
        None
        if supplied_market_provider is not None
        else SinaMarketBreadthProvider(
            database,
            ttl_seconds=max(300, settings.sector_cache_seconds),
        )
    )
    industry_index_provider = industry_index_provider or (
        None
        if supplied_market_provider is not None
        else CSIIndustryIndexProvider(
            database,
            ttl_seconds=max(3600, settings.sector_cache_seconds * 10),
        )
    )
    china_index_provider = (
        None
        if supplied_market_provider is not None
        else TencentChinaIndexProvider(
            database,
            ttl_seconds=settings.market_cache_seconds,
        )
    )
    analysis = MarketAnalysisService(
        database,
        market_provider,
        sector_provider,
        breadth_provider=breadth_provider,
        industry_index_provider=industry_index_provider,
        china_index_provider=china_index_provider,
    )
    agent = AgentService(database, settings)
    articles = MarketPulseArticleService(database, analysis, agent, settings)
    china_info = ChinaInformationService(
        database, china_info_provider or AShareInformationProvider()
    )
    event_timeline = EventTimelineService(database, china_info)
    change_events = ChangeEventService(database)
    a_share_fundamentals_provider = (
        fundamentals_provider or AShareFundamentalsProvider()
    )
    fundamentals = FundamentalsService(database, a_share_fundamentals_provider)
    global_info = GlobalInformationService(
        database, global_info_provider or NasdaqCompanyNewsProvider()
    )
    us_equity_fundamentals_provider = (
        us_fundamentals_provider
        or USEquityFundamentalsProvider(sec_user_agent=settings.sec_user_agent)
    )
    us_fundamentals = USEquityFundamentalsService(
        database, us_equity_fundamentals_provider
    )
    filings = AShareFilingService(database, filing_provider or AShareFilingProvider())
    business_structure = BusinessStructureAnalysisService(
        database,
        business_structure_provider or AShareBusinessStructureProvider(),
    )
    shareholders = ShareholderStructureAnalysisService(
        database,
        shareholder_provider or AShareShareholderProvider(),
    )
    analyst_expectations = AnalystExpectationsService(
        database,
        analyst_expectations_provider or AShareAnalystExpectationsProvider(),
    )
    earnings_quality = EarningsQualityService(database)
    financial_drivers = FinancialDriverAnalysisService(database, filings)
    peer_comparison = PeerComparisonService(
        database,
        a_share_fundamentals_provider,
        us_equity_fundamentals_provider,
        fundamentals_service=fundamentals,
        us_fundamentals_service=us_fundamentals,
        business_structure_service=business_structure,
    )
    outlook_calibration = OutlookCalibrationService(database, market_provider)
    research_evidence = StockResearchEvidenceService(
        analysis,
        china_info,
        fundamentals,
        global_info,
        us_fundamentals,
        peer_comparison,
        outlook_calibration,
        earnings_quality,
        financial_drivers,
        business_structure,
        shareholders,
        analyst_expectations,
        event_timeline,
    )
    stock_comparison = StockComparisonService(research_evidence)
    research_reports = ResearchReportService(
        database, research_evidence, agent, settings
    )
    research_tracking = research_reports.tracking
    research_priority = ResearchPriorityService(database)
    research_actions = ResearchActionService(database, research_priority)
    research_outcomes = ResearchOutcomeService(database)
    live_markets = LiveMarketService(
        database,
        live_market_provider,
        gold_provider
        or SinaGoldProvider(database, ttl_seconds=settings.intraday_cache_seconds),
        global_index_provider=global_index_intraday_provider,
    )
    data_health = DataHealthService(database, settings)
    market_news = MarketNewsService(
        database, market_news_provider or GoogleNewsMarketProvider()
    )
    evidence_tasks = EvidenceTaskService(
        database,
        research_evidence=research_evidence,
        analysis=analysis,
        china_info=china_info,
        filings=filings,
        market_news=market_news,
    )
    conversation_quality = ConversationQualityService(database)
    deep_stock = DeepStockResearchService(database)
    stock_domain = StockDomainService(database)
    structured_ai = StructuredAIService(database, stock_domain)
    observation_tasks = ObservationTaskService(database)
    position_ledger = PositionLedgerService(database)
    trade_workflow = TradeWorkflowService(database)
    global_search = GlobalSearchService(database, trade_workflow)
    resolved_tushare_client = tushare_client
    if resolved_tushare_client is None and settings.tushare_enabled:
        try:
            resolved_tushare_client = TushareClient.from_settings(settings)
        except TushareProviderError:
            # The rest of the product remains usable while the screener shows a
            # neutral preparation state. Credentials and provider details are
            # deliberately not surfaced to users.
            resolved_tushare_client = None
    stock_screener = StockScreenerService(
        resolved_tushare_client,
        snapshot_ttl_seconds=settings.market_cache_seconds,
    )
    tushare_snapshots = TushareSnapshotService(database, resolved_tushare_client)
    li_zong_strategy = LiZongStrategyService(
        database,
        tushare_snapshots,
        fundamentals_provider=a_share_fundamentals_provider,
    )
    stock_workspace = StockWorkspaceService(
        database,
        deep_stock,
        research_tracking,
        research_actions,
        observation_tasks=observation_tasks,
        li_zong_strategy=li_zong_strategy,
        position_ledger=position_ledger,
        trade_workflow=trade_workflow,
        change_events=change_events,
    )
    stock_assets = StockAssetListService(database, stock_workspace)
    today_overview = TodayOverviewService(
        database,
        analysis,
        observation_tasks,
        research_actions,
        research_tracking,
        structured_ai,
        trade_workflow=trade_workflow,
        change_events=change_events,
    )
    event_broker = EventBroker()
    agent_streams = AgentStreamBroker()
    background = BackgroundScheduler(
        database,
        live_markets,
        analysis,
        articles,
        china_info,
        event_timeline,
        filings,
        business_structure,
        shareholders,
        analyst_expectations,
        fundamentals,
        us_fundamentals,
        earnings_quality,
        financial_drivers,
        peer_comparison,
        outlook_calibration,
        research_reports,
        research_outcomes,
        market_news,
        evidence_tasks,
        data_health,
        event_broker,
        settings,
        tushare_snapshots=tushare_snapshots,
        li_zong_strategy=li_zong_strategy,
        trade_workflow=trade_workflow,
        change_events=change_events,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        background.start()
        try:
            yield
        finally:
            background.stop()

    app = FastAPI(
        title="清数智算 Agent Demo",
        version="0.1.0",
        description="后端优先的金融研究 Agent：确定性行情分析 + Hermes 解释 + 用户确认记忆。",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.database = database
    app.state.analysis = analysis
    app.state.agent = agent
    app.state.articles = articles
    app.state.china_info = china_info
    app.state.event_timeline = event_timeline
    app.state.change_events = change_events
    app.state.fundamentals = fundamentals
    app.state.global_info = global_info
    app.state.us_fundamentals = us_fundamentals
    app.state.earnings_quality = earnings_quality
    app.state.filings = filings
    app.state.business_structure = business_structure
    app.state.shareholders = shareholders
    app.state.analyst_expectations = analyst_expectations
    app.state.financial_drivers = financial_drivers
    app.state.peer_comparison = peer_comparison
    app.state.outlook_calibration = outlook_calibration
    app.state.research_evidence = research_evidence
    app.state.stock_comparison = stock_comparison
    app.state.research_reports = research_reports
    app.state.research_tracking = research_tracking
    app.state.research_priority = research_priority
    app.state.research_actions = research_actions
    app.state.research_outcomes = research_outcomes
    app.state.live_markets = live_markets
    app.state.data_health = data_health
    app.state.knowledge = knowledge
    app.state.market_news = market_news
    app.state.evidence_tasks = evidence_tasks
    app.state.conversation_quality = conversation_quality
    app.state.deep_stock = deep_stock
    app.state.stock_domain = stock_domain
    app.state.structured_ai = structured_ai
    app.state.observation_tasks = observation_tasks
    app.state.position_ledger = position_ledger
    app.state.trade_workflow = trade_workflow
    app.state.global_search = global_search
    app.state.stock_workspace = stock_workspace
    app.state.stock_assets = stock_assets
    app.state.stock_screener = stock_screener
    app.state.tushare_snapshots = tushare_snapshots
    app.state.li_zong_strategy = li_zong_strategy
    app.state.today_overview = today_overview
    app.state.event_broker = event_broker
    app.state.agent_streams = agent_streams
    app.state.background = background

    def seed_demo_watchlist(user: dict[str, Any]) -> None:
        if user.get("name") != "网页体验用户":
            return
        for symbol in settings.default_research_symbols:
            canonical = normalize_symbol(symbol)
            if database.get_watchlist_item(user["id"], canonical) is not None:
                continue
            target = RESEARCH_TARGETS.get(canonical, {})
            database.upsert_watchlist(
                user["id"],
                canonical,
                target.get("name") or canonical,
                target.get("market"),
                target.get("thesis") or "持续跟踪价格、基本面与风险证据变化",
            )

    def public_user(user: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": user["id"],
            "name": user["name"],
            "created_at": user["created_at"],
            "session_expires_at": user.get("session_expires_at"),
        }

    def public_upload(upload: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": upload["id"],
            "kind": upload["kind"],
            "original_name": upload["original_name"],
            "mime_type": upload["mime_type"],
            "size_bytes": upload["size_bytes"],
            "width": upload["width"],
            "height": upload["height"],
            "created_at": upload["created_at"],
        }

    def public_conversation(conversation: dict[str, Any]) -> dict[str, Any]:
        return {
            key: conversation.get(key)
            for key in (
                "id",
                "title",
                "quality_scope",
                "status",
                "message_count",
                "last_message_preview",
                "created_at",
                "updated_at",
                "archived_at",
            )
        }

    def public_conversation_message(message: dict[str, Any]) -> dict[str, Any]:
        return {
            key: message.get(key)
            for key in (
                "id",
                "role",
                "content",
                "intent",
                "run_id",
                "metadata",
                "created_at",
            )
        }

    def set_session_cookie(response: Response, session: dict[str, Any]) -> None:
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=session["token"],
            max_age=settings.session_ttl_days * 24 * 60 * 60,
            httponly=True,
            secure=settings.session_cookie_secure,
            samesite="strict",
            path="/",
        )

    def require_session_user(request: Request) -> dict[str, Any]:
        user = database.get_user_by_session(request.cookies.get(SESSION_COOKIE_NAME))
        if user is None:
            raise HTTPException(status_code=401, detail="需要有效个人会话")
        return user

    def require_idempotency_key(request: Request) -> str:
        value = str(request.headers.get("Idempotency-Key") or "").strip()
        if not 8 <= len(value) <= 128:
            raise HTTPException(
                status_code=422,
                detail="写入事实记录时必须提供 8—128 位 Idempotency-Key",
            )
        return value

    def require_admin_api(request: Request) -> dict[str, Any]:
        user = require_session_user(request)
        configured = settings.admin_api_token
        provided = request.headers.get("x-qingshu-admin-token", "")
        if not configured or not hmac.compare_digest(provided, configured):
            raise HTTPException(
                status_code=403,
                detail="该数据重算操作仅限后台任务或管理员",
            )
        return user

    def require_user(request: Request, user_id: str) -> dict[str, Any]:
        user = require_session_user(request)
        if user["id"] != user_id:
            raise HTTPException(status_code=404, detail="用户不存在")
        return user

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse(url="/demo")

    @app.get("/demo", include_in_schema=False)
    def demo_page() -> FileResponse:
        return FileResponse(
            Path(__file__).resolve().parent / "static" / "demo.html",
            headers={
                "Cache-Control": "no-store, max-age=0",
                "Pragma": "no-cache",
            },
        )

    @app.get("/today", include_in_schema=False)
    @app.get("/watchlist", include_in_schema=False)
    @app.get("/research", include_in_schema=False)
    @app.get("/research/{conversation_id}", include_in_schema=False)
    @app.get("/reviews", include_in_schema=False)
    @app.get("/account", include_in_schema=False)
    @app.get("/knowledge", include_in_schema=False)
    @app.get("/stocks/{symbol}", include_in_schema=False)
    def demo_route(
        conversation_id: str | None = None, symbol: str | None = None
    ) -> FileResponse:
        del conversation_id, symbol
        return demo_page()

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "time": utc_now(),
            "hermes_enabled": settings.hermes_enabled,
            "data_health": data_health.public_summary(data_health.latest()),
            "background_jobs": background.status(),
        }

    @app.get("/events", include_in_schema=False)
    def events() -> StreamingResponse:
        return StreamingResponse(
            event_broker.stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    @app.get("/me/chat/stream/{request_id}", include_in_schema=False)
    def chat_stream(request_id: str, request: Request) -> StreamingResponse:
        user = require_session_user(request)
        if not re.fullmatch(r"[A-Za-z0-9-]{8,64}", request_id):
            raise HTTPException(status_code=404, detail="实时回答不存在")
        try:
            agent_streams.open(request_id, user["id"])
        except PermissionError as exc:
            raise HTTPException(status_code=404, detail="实时回答不存在") from exc
        return StreamingResponse(
            agent_streams.stream(request_id, user["id"]),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    @app.get("/system/background")
    def background_status() -> dict[str, Any]:
        return background.status()

    @app.get("/system/data-health")
    def data_health_status() -> dict[str, Any]:
        return data_health.latest(generate_if_missing=True)  # type: ignore[return-value]

    @app.post("/users", status_code=201)
    def create_user(payload: UserCreate, response: Response) -> dict[str, Any]:
        user = database.create_user(payload.name)
        seed_demo_watchlist(user)
        session = database.create_user_session(user["id"], settings.session_ttl_days)
        set_session_cookie(response, session)
        return public_user({**user, "session_expires_at": session["expires_at"]})

    @app.post("/sessions/claim")
    def claim_legacy_session(
        payload: LegacySessionClaim, response: Response
    ) -> dict[str, Any]:
        try:
            UUID(payload.user_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="旧个人空间不存在") from exc
        user = database.get_user(payload.user_id)
        if user is None or user.get("name") != "网页体验用户":
            raise HTTPException(status_code=404, detail="旧个人空间不存在")
        if database.user_has_session_history(user["id"]):
            raise HTTPException(status_code=409, detail="该个人空间已完成安全迁移")
        session = database.create_user_session(user["id"], settings.session_ttl_days)
        set_session_cookie(response, session)
        seed_demo_watchlist(user)
        return public_user({**user, "session_expires_at": session["expires_at"]})

    @app.get("/session")
    def get_session(request: Request) -> dict[str, Any]:
        return public_user(require_session_user(request))

    @app.delete("/session", status_code=204)
    def delete_session(request: Request) -> Response:
        database.revoke_user_session(request.cookies.get(SESSION_COOKIE_NAME))
        response = Response(status_code=204)
        response.delete_cookie(
            SESSION_COOKIE_NAME,
            path="/",
            secure=settings.session_cookie_secure,
            httponly=True,
            samesite="strict",
        )
        return response

    @app.get("/me")
    def get_me(request: Request) -> dict[str, Any]:
        return public_user(require_session_user(request))

    @app.post("/me/uploads/images", status_code=201)
    async def upload_my_image(
        request: Request, file: UploadFile = File(...)
    ) -> dict[str, Any]:
        user = require_session_user(request)
        raw = await file.read(settings.max_image_upload_bytes + 1)
        await file.close()
        if not raw:
            raise HTTPException(status_code=422, detail="图片内容为空")
        if len(raw) > settings.max_image_upload_bytes:
            raise HTTPException(status_code=413, detail="图片超过上传大小限制")

        try:
            image = Image.open(BytesIO(raw))
            image.load()
            image_format = image.format
            image = ImageOps.exif_transpose(image)
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise HTTPException(status_code=422, detail="无法识别为有效图片") from exc
        if image_format not in {"PNG", "JPEG", "WEBP"}:
            raise HTTPException(status_code=415, detail="仅支持 PNG、JPEG 和 WebP 图片")
        if image.width * image.height > settings.max_image_pixels:
            raise HTTPException(status_code=413, detail="图片像素尺寸过大")

        image.thumbnail((4096, 4096), Image.Resampling.LANCZOS)
        upload_id = str(uuid4())
        original_name = Path(file.filename or "research-image").name[:160]
        upload_dir = Path(user["workspace_path"]) / "uploads" / "images"
        upload_dir.mkdir(parents=True, exist_ok=True)
        if image_format == "JPEG" and image.mode not in {"RGBA", "LA"}:
            image = image.convert("RGB")
            mime_type = "image/jpeg"
            output_path = upload_dir / f"{upload_id}.jpg"
            image.save(output_path, format="JPEG", quality=90, optimize=True)
        else:
            if image.mode not in {"RGB", "RGBA", "L", "LA"}:
                image = image.convert("RGBA" if "transparency" in image.info else "RGB")
            mime_type = "image/png"
            output_path = upload_dir / f"{upload_id}.png"
            image.save(output_path, format="PNG", optimize=True)

        upload = database.create_user_upload(
            upload_id=upload_id,
            user_id=user["id"],
            kind="image",
            original_name=original_name,
            mime_type=mime_type,
            size_bytes=output_path.stat().st_size,
            width=image.width,
            height=image.height,
            workspace_path=output_path,
        )
        return public_upload(upload)

    @app.get("/me/conversations")
    def list_my_conversations(
        request: Request, limit: int = Query(default=100, ge=1, le=200)
    ) -> dict[str, Any]:
        user = require_session_user(request)
        return {
            "items": [
                public_conversation(item)
                for item in database.list_conversations(user["id"], limit=limit)
            ]
        }

    @app.get("/v1/search")
    def search_my_workspace(
        request: Request,
        q: str = Query(min_length=1, max_length=120),
        limit: int = Query(default=8, ge=1, le=20),
    ) -> dict[str, Any]:
        user = require_session_user(request)
        return global_search.search(user["id"], q, limit=limit)

    @app.post("/me/conversations", status_code=201)
    def create_my_conversation(
        payload: ConversationCreate, request: Request
    ) -> dict[str, Any]:
        user = require_session_user(request)
        return public_conversation(
            database.create_conversation(
                user["id"], payload.title, quality_scope=payload.quality_scope
            )
        )

    @app.get("/me/conversations/{conversation_id}")
    def get_my_conversation(conversation_id: str, request: Request) -> dict[str, Any]:
        user = require_session_user(request)
        conversation = database.get_conversation(user["id"], conversation_id)
        if conversation is None or conversation.get("status") != "active":
            raise HTTPException(status_code=404, detail="研究对话不存在")
        messages = database.list_conversation_messages(
            user["id"], conversation_id, limit=500
        )
        return {
            **public_conversation(conversation),
            "messages": [public_conversation_message(item) for item in messages],
        }

    @app.patch("/me/conversations/{conversation_id}")
    def rename_my_conversation(
        conversation_id: str, payload: ConversationPatch, request: Request
    ) -> dict[str, Any]:
        user = require_session_user(request)
        conversation = database.get_conversation(user["id"], conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="研究对话不存在")
        if payload.title is not None:
            conversation = database.rename_conversation(
                user["id"], conversation_id, payload.title
            )
        if payload.quality_scope is not None:
            conversation = database.set_conversation_quality_scope(
                user["id"], conversation_id, payload.quality_scope
            )
        if conversation is None:
            raise HTTPException(status_code=404, detail="研究对话不存在")
        return public_conversation(conversation)

    @app.delete("/me/conversations/{conversation_id}", status_code=204)
    def archive_my_conversation(conversation_id: str, request: Request) -> Response:
        user = require_session_user(request)
        if not database.archive_conversation(user["id"], conversation_id):
            raise HTTPException(status_code=404, detail="研究对话不存在")
        return Response(status_code=204)

    @app.get("/stock-screener/profiles")
    def list_stock_screener_profiles() -> dict[str, Any]:
        return {
            "items": stock_screener.profiles(),
            "boundary": "选股功能用于生成可解释的研究候选，不构成推荐或交易建议。",
        }

    @app.post("/me/stock-screener")
    def screen_my_stocks(
        payload: StockScreenRequest, request: Request
    ) -> dict[str, Any]:
        require_session_user(request)
        try:
            return stock_screener.screen(
                profile=payload.profile,
                market=payload.market,
                max_results=payload.max_results,
                filters=(
                    payload.filters.model_dump(exclude_none=True)
                    if payload.filters is not None
                    else None
                ),
                force_refresh=payload.force_refresh,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except StockScreenerUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/v1/data/tushare/stocks/{symbol}/snapshot")
    def get_tushare_symbol_snapshot(symbol: str, request: Request) -> dict[str, Any]:
        require_session_user(request)
        try:
            result = tushare_snapshots.get_symbol_snapshot(symbol)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        internal_symbol = str(result.get("symbol") or normalize_symbol(symbol))
        result["internal_symbol"] = internal_symbol
        result["symbol"] = _external_ts_code(internal_symbol)
        snapshot = result.get("snapshot")
        if isinstance(snapshot, dict):
            snapshot["internal_symbol"] = internal_symbol
            snapshot["symbol"] = _external_ts_code(internal_symbol)
        return result

    @app.post("/v1/data/tushare/stocks/{symbol}/refresh")
    def refresh_tushare_symbol_snapshot(
        symbol: str,
        payload: TushareSymbolRefreshRequest,
        request: Request,
    ) -> dict[str, Any]:
        require_session_user(request)
        try:
            result = tushare_snapshots.sync_symbol(
                symbol, as_of_date=payload.as_of_date
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            return {
                "symbol": _external_ts_code(normalize_symbol(symbol)),
                "status": "unavailable",
                "error_type": type(exc).__name__,
                "boundary": "数据刷新未完成，上一稳定版本（如有）继续保留。",
            }
        return {
            "symbol": _external_ts_code(normalize_symbol(symbol)),
            "status": (result.get("run") or {}).get("status"),
            "published": bool(result.get("published")),
            "previous_stable_retained": bool(result.get("previous_stable_retained")),
            "run": result.get("run"),
            "snapshot": result.get("snapshot"),
        }

    @app.get("/v1/stock-strategies")
    def list_stock_strategies(request: Request) -> dict[str, Any]:
        require_session_user(request)
        return {
            "items": li_zong_strategy.list_strategies(),
            "boundary": "策略只产生研究候选和人工复核事实，不执行交易。",
        }

    @app.get("/v1/stock-strategies/li-zong")
    def get_li_zong_strategy(request: Request) -> dict[str, Any]:
        require_session_user(request)
        return li_zong_strategy.get_definition()

    @app.post("/v1/stock-strategies/li-zong/runs")
    def run_li_zong_strategy(
        payload: LiZongRunRequest, request: Request
    ) -> dict[str, Any]:
        require_admin_api(request)
        sync_results: list[dict[str, Any]] = []
        if payload.refresh_data:
            for symbol in payload.symbols:
                try:
                    sync = tushare_snapshots.sync_symbol(
                        symbol, as_of_date=payload.as_of_date
                    )
                    sync_results.append(
                        {
                            "symbol": _external_ts_code(normalize_symbol(symbol)),
                            "status": (sync.get("run") or {}).get("status"),
                            "published": bool(sync.get("published")),
                            "previous_stable_retained": bool(
                                sync.get("previous_stable_retained")
                            ),
                        }
                    )
                except Exception as exc:
                    sync_results.append(
                        {
                            "symbol": _external_ts_code(normalize_symbol(symbol)),
                            "status": "unavailable",
                            "error_type": type(exc).__name__,
                        }
                    )
        parameters = None
        if payload.roe_min_pct is not None:
            slug = f"{payload.roe_min_pct:g}".replace(".", "p")
            parameters = {
                "roe_min_pct": payload.roe_min_pct,
                "parameter_version": f"li_zong_v1_roe_{slug}",
            }
        try:
            result = li_zong_strategy.run_symbols(
                payload.symbols, parameters=parameters
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            **result,
            "items": [
                _public_li_zong_candidate(item) for item in result.get("items", [])
            ],
            "sync_results": sync_results,
        }

    @app.post("/v1/stock-strategies/li-zong/universe-runs")
    def run_li_zong_universe_batch(
        payload: LiZongUniverseRunRequest, request: Request
    ) -> dict[str, Any]:
        require_admin_api(request)
        return li_zong_strategy.run_universe_batch(
            batch_size=payload.batch_size or settings.li_zong_universe_batch_size,
            as_of_date=payload.as_of_date,
        )

    @app.get("/v1/stock-strategies/li-zong/runs/latest")
    def get_latest_li_zong_run(request: Request) -> dict[str, Any]:
        require_session_user(request)
        coverage = li_zong_strategy.coverage_packet()
        return {
            "strategy_id": "li_zong",
            "run": coverage.get("latest_run"),
            "coverage": coverage,
            "boundary": (
                "普通用户只能读取后台批任务状态；"
                "不能从页面触发全市场或逐股多年数据重算。"
            ),
        }

    @app.get("/v1/stock-strategies/li-zong/candidates")
    def list_li_zong_candidates(
        request: Request,
        status: Literal[
            "qualified",
            "triggered",
            "not_qualified",
            "data_incomplete",
            "invalidated",
        ]
        | None = None,
        limit: int = Query(default=200, ge=1, le=1000),
    ) -> dict[str, Any]:
        require_session_user(request)
        items = [
            _public_li_zong_candidate(item)
            for item in li_zong_strategy.list_candidates(status=status, limit=limit)
        ]
        visible_counts = {
            key: sum(item.get("status") == key for item in items)
            for key in (
                "qualified",
                "triggered",
                "not_qualified",
                "data_incomplete",
                "invalidated",
            )
        }
        as_of_dates = sorted(
            {str(item.get("as_of_date")) for item in items if item.get("as_of_date")},
            reverse=True,
        )
        coverage = li_zong_strategy.coverage_packet()
        has_universe = bool(coverage.get("universe_count"))
        counts = coverage.get("counts") if has_universe else visible_counts
        published_status = (
            "ready" if items or coverage.get("status") == "stable" else "preparing"
        )
        return {
            "strategy": li_zong_strategy.get_definition(),
            "status": published_status,
            "items": items,
            "counts": counts,
            "data_meta": {
                "universe_status": coverage.get("status"),
                "latest_as_of_date": (
                    coverage.get("as_of_date")
                    if has_universe
                    else as_of_dates[0]
                    if as_of_dates
                    else None
                ),
                "evaluated_symbols": (
                    coverage.get("evaluated_symbols") if has_universe else len(items)
                ),
                "universe_count": coverage.get("universe_count") or 0,
                "market_cap_eligible_count": (
                    coverage.get("market_cap_eligible_count") or 0
                ),
                "market_cap_rejected_count": (
                    coverage.get("market_cap_rejected_count") or 0
                ),
                "missing_market_cap_count": (
                    coverage.get("missing_market_cap_count") or 0
                ),
                "deep_check_eligible_count": (
                    coverage.get("deep_check_eligible_count") or 0
                ),
                "history_insufficient_count": (
                    coverage.get("history_insufficient_count") or 0
                ),
                "history_unknown_count": (coverage.get("history_unknown_count") or 0),
                "deep_processed_symbols": (coverage.get("deep_processed_symbols") or 0),
                "deep_remaining_symbols": (coverage.get("deep_remaining_symbols") or 0),
                "deep_processing_ratio": (coverage.get("deep_processing_ratio") or 0),
                "deep_decisive_symbols": (coverage.get("deep_decisive_symbols") or 0),
                "deep_data_incomplete_symbols": (
                    coverage.get("deep_data_incomplete_symbols") or 0
                ),
                "decisive_status_count": (coverage.get("decisive_status_count") or 0),
                "decisive_coverage_ratio": (
                    coverage.get("decisive_coverage_ratio") or 0
                ),
                "remaining_symbols": coverage.get("remaining_symbols") or 0,
                "coverage_ratio": coverage.get("coverage_ratio") or 0,
                "scope": (
                    coverage.get("scope") if has_universe else "published_research_pool"
                ),
                "full_market_coverage": bool(coverage.get("full_market_coverage")),
                "deep_check_complete": bool(coverage.get("deep_check_complete")),
                "latest_run": coverage.get("latest_run"),
            },
            "boundary": (
                "当前页面只读取后台已发布快照；全市场名单先执行市值与上市历史"
                "预筛，历史明确不足的股票不发起逐股深度请求，其余股票再分批补齐"
                "多年ROE、股东和量价证据。"
                "候选不构成推荐或交易建议。"
            ),
        }

    @app.get("/v1/stock-strategies/li-zong/candidates/{symbol}")
    def get_li_zong_candidate(symbol: str, request: Request) -> dict[str, Any]:
        require_session_user(request)
        try:
            item = li_zong_strategy.get_candidate(symbol)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if item is None:
            raise HTTPException(status_code=404, detail="该股票尚无李总策略快照")
        public = _public_li_zong_candidate(item)
        public["trigger_events"] = item.get("trigger_events") or []
        return public

    @app.get("/v1/stock-strategies/li-zong/triggers")
    def list_li_zong_triggers(
        request: Request,
        symbol: str | None = Query(default=None, max_length=24),
        limit: int = Query(default=200, ge=1, le=1000),
    ) -> dict[str, Any]:
        require_session_user(request)
        try:
            items = li_zong_strategy.get_triggers(symbol=symbol, limit=limit)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "items": items,
            "boundary": "触发只进入重点关注和人工复核，不代表自动买入。",
        }

    @app.get("/me/deep-stock")
    def list_my_deep_stock_sessions(
        request: Request, limit: int = Query(default=50, ge=1, le=200)
    ) -> dict[str, Any]:
        user = require_session_user(request)
        return deep_stock.list_sessions(user["id"], limit=limit)

    @app.post("/me/deep-stock", status_code=201)
    def start_my_deep_stock_session(
        payload: DeepStockStart, request: Request
    ) -> dict[str, Any]:
        user = require_session_user(request)
        try:
            return deep_stock.get_or_create(
                user["id"],
                payload.symbol,
                payload.conversation_id,
                entry_context=(
                    payload.entry_context.model_dump()
                    if payload.entry_context is not None
                    else None
                ),
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/me/deep-stock/{symbol}")
    def get_my_deep_stock_session(symbol: str, request: Request) -> dict[str, Any]:
        user = require_session_user(request)
        try:
            session = deep_stock.get(user["id"], symbol)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if session is None:
            raise HTTPException(status_code=404, detail="个股研究会话尚未建立")
        return session

    @app.get("/api/v1/stocks/{symbol}/workspace", include_in_schema=False)
    @app.get("/v1/stocks/{symbol}/workspace")
    def get_my_stock_workspace(symbol: str, request: Request) -> dict[str, Any]:
        user = require_session_user(request)
        try:
            return stock_workspace.get_workspace(user["id"], symbol)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/v1/stock-workspaces")
    def list_my_stock_workspaces(request: Request) -> dict[str, Any]:
        user = require_session_user(request)
        return stock_assets.list_assets(user["id"])

    @app.get("/v1/stocks/{symbol}/workspace/evidence")
    def get_my_stock_workspace_evidence(
        symbol: str, request: Request
    ) -> dict[str, Any]:
        user = require_session_user(request)
        try:
            return stock_workspace.get_evidence_workspace(user["id"], symbol)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/v1/stocks/{symbol}/workspace/timeline")
    def get_my_stock_workspace_timeline(
        symbol: str, request: Request
    ) -> dict[str, Any]:
        user = require_session_user(request)
        try:
            return stock_workspace.get_timeline_workspace(user["id"], symbol)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/v1/stocks/{symbol}/workspace/actions")
    def get_my_stock_workspace_actions(symbol: str, request: Request) -> dict[str, Any]:
        user = require_session_user(request)
        try:
            return stock_workspace.get_actions_workspace(user["id"], symbol)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/v1/stocks/{symbol}/position")
    def get_my_stock_position(symbol: str, request: Request) -> dict[str, Any]:
        user = require_session_user(request)
        try:
            return position_ledger.get_position(user["id"], symbol)
        except PositionLedgerNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PositionLedgerInvalidState as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/v1/stocks/{symbol}/position/opening", status_code=201)
    def create_my_position_opening(
        symbol: str, payload: PositionOpeningCreate, request: Request
    ) -> dict[str, Any]:
        user = require_session_user(request)
        try:
            return position_ledger.create_opening(
                user_id=user["id"],
                symbol=symbol,
                as_of_date=payload.as_of_date,
                quantity=payload.quantity,
                cost_price=payload.cost_price,
                fees=payload.fees,
                note=payload.note,
                idempotency_key=require_idempotency_key(request),
            )
        except PositionLedgerNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PositionLedgerConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except PositionLedgerInvalidState as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/v1/stocks/{symbol}/operations", status_code=201)
    def record_my_position_operation(
        symbol: str, payload: PositionOperationCreate, request: Request
    ) -> dict[str, Any]:
        user = require_session_user(request)
        try:
            return position_ledger.record_operation(
                user_id=user["id"],
                symbol=symbol,
                operation_type=payload.operation_type,
                operated_at=payload.operated_at,
                price=payload.price,
                quantity=payload.quantity,
                fees=payload.fees,
                reason_text=payload.reason_text,
                plan_id=payload.plan_id,
                idempotency_key=require_idempotency_key(request),
            )
        except PositionLedgerNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PositionLedgerConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except PositionLedgerInvalidState as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.patch("/v1/operations/{operation_id}")
    def revise_my_position_operation(
        operation_id: str,
        payload: PositionOperationRevisionCreate,
        request: Request,
    ) -> dict[str, Any]:
        user = require_session_user(request)
        try:
            return position_ledger.revise_operation(
                user_id=user["id"],
                operation_id=operation_id,
                base_revision=payload.base_revision,
                price=payload.price,
                quantity=payload.quantity,
                fees=payload.fees,
                reason_text=payload.reason_text,
                idempotency_key=require_idempotency_key(request),
            )
        except PositionLedgerNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PositionLedgerConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except PositionLedgerInvalidState as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/v1/stocks/{symbol}/position-adjustments", status_code=201)
    def record_my_position_adjustment(
        symbol: str, payload: PositionAdjustmentCreate, request: Request
    ) -> dict[str, Any]:
        user = require_session_user(request)
        try:
            return position_ledger.record_adjustment(
                user_id=user["id"],
                symbol=symbol,
                adjustment_type=payload.adjustment_type,
                effective_at=payload.effective_at,
                quantity_delta=payload.quantity_delta,
                cost_delta=payload.cost_delta,
                reason_text=payload.reason_text,
                evidence_text=payload.evidence_text,
                idempotency_key=require_idempotency_key(request),
            )
        except PositionLedgerNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PositionLedgerConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except PositionLedgerInvalidState as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/v1/stocks/{symbol}/action-plans")
    def list_my_action_plans(symbol: str, request: Request) -> dict[str, Any]:
        user = require_session_user(request)
        try:
            return trade_workflow.list_action_plans(user["id"], symbol)
        except TradeWorkflowNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except TradeWorkflowInvalidState as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/v1/stocks/{symbol}/action-plans", status_code=201)
    def create_my_action_plan(
        symbol: str, payload: ActionPlanCreate, request: Request
    ) -> dict[str, Any]:
        user = require_session_user(request)
        try:
            return trade_workflow.create_action_plan(
                user_id=user["id"],
                symbol=symbol,
                action_type=payload.action_type,
                trigger_text=payload.trigger_text,
                target_quantity=payload.target_quantity,
                target_amount=payload.target_amount,
                target_position_percent=payload.target_position_percent,
                thesis_version_id=payload.thesis_version_id,
                expires_at=payload.expires_at,
                idempotency_key=require_idempotency_key(request),
            )
        except TradeWorkflowNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except TradeWorkflowConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except TradeWorkflowInvalidState as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/v1/action-plans/{plan_id}")
    def get_my_action_plan(plan_id: str, request: Request) -> dict[str, Any]:
        user = require_session_user(request)
        try:
            return trade_workflow.get_action_plan(user["id"], plan_id)
        except TradeWorkflowNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/v1/action-plans/{plan_id}/history")
    def get_my_action_plan_history(plan_id: str, request: Request) -> dict[str, Any]:
        user = require_session_user(request)
        try:
            plan = trade_workflow.get_action_plan(user["id"], plan_id)
            return {
                "plan_id": plan_id,
                "version": plan["version"],
                "items": plan.get("history") or [],
            }
        except TradeWorkflowNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.patch("/v1/action-plans/{plan_id}")
    def update_my_action_plan(
        plan_id: str, payload: ActionPlanPatch, request: Request
    ) -> dict[str, Any]:
        user = require_session_user(request)
        fields = payload.model_dump(exclude={"base_version"}, exclude_unset=True)
        try:
            return trade_workflow.update_action_plan(
                user_id=user["id"],
                plan_id=plan_id,
                base_version=payload.base_version,
                fields=fields,
            )
        except TradeWorkflowNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except TradeWorkflowConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except TradeWorkflowInvalidState as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/v1/action-plans/{plan_id}/transition")
    def transition_my_action_plan(
        plan_id: str, payload: ActionPlanTransition, request: Request
    ) -> dict[str, Any]:
        user = require_session_user(request)
        try:
            return trade_workflow.transition_action_plan(
                user_id=user["id"],
                plan_id=plan_id,
                base_version=payload.base_version,
                status=payload.status,
            )
        except TradeWorkflowNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except TradeWorkflowConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except TradeWorkflowInvalidState as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/v1/operations/{operation_id}/context")
    def get_my_operation_context(operation_id: str, request: Request) -> dict[str, Any]:
        user = require_session_user(request)
        try:
            return trade_workflow.get_operation_context(user["id"], operation_id)
        except TradeWorkflowNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/v1/stocks/{symbol}/trade-reviews")
    def list_my_trade_reviews(symbol: str, request: Request) -> dict[str, Any]:
        user = require_session_user(request)
        try:
            return trade_workflow.list_trade_reviews(user["id"], symbol)
        except TradeWorkflowNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except TradeWorkflowInvalidState as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/v1/trade-reviews")
    def list_my_trade_review_center(
        request: Request,
        status: str | None = Query(default=None, max_length=24),
        symbol: str | None = Query(default=None, max_length=24),
        q: str | None = Query(default=None, max_length=120),
        limit: int = Query(default=100, ge=1, le=200),
    ) -> dict[str, Any]:
        user = require_session_user(request)
        try:
            return trade_workflow.list_user_trade_reviews(
                user["id"], status=status, symbol=symbol, query=q, limit=limit
            )
        except TradeWorkflowNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except TradeWorkflowInvalidState as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/v1/trade-reviews/{review_id}")
    def get_my_trade_review(review_id: str, request: Request) -> dict[str, Any]:
        user = require_session_user(request)
        try:
            return trade_workflow.get_trade_review(user["id"], review_id)
        except TradeWorkflowNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except TradeWorkflowInvalidState as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/v1/trade-reviews/{review_id}/generate-draft", status_code=201)
    def generate_my_trade_review_draft(
        review_id: str, payload: TradeReviewGenerateDraft, request: Request
    ) -> dict[str, Any]:
        user = require_session_user(request)
        try:
            evidence = trade_workflow.prepare_review_agent_evidence(
                user["id"], review_id
            )
            run = agent.run(
                user=user,
                intent="trade_review",
                message=(
                    "请复盘这次真实操作。价格结果由系统确定性计算；请分别输出逻辑结果、"
                    "计划偏离、候选偏差标签和下一步改进。不要把盈利等同于逻辑正确，"
                    "也不要把亏损等同于逻辑错误。"
                ),
                evidence=evidence,
                model_tier=payload.model_tier,
                execute_agent=True,
            )
            if run.get("status") != "completed":
                raise HTTPException(
                    status_code=503,
                    detail="复盘草稿暂未生成，请稍后重试。已记录的操作和快照不受影响。",
                )
            draft = trade_workflow.parse_review_agent_answer(run.get("answer") or "")
            return trade_workflow.save_ai_draft(
                user_id=user["id"],
                review_id=review_id,
                source_run_id=str(run["id"]),
                base_version=payload.base_version,
                logic_result=draft["logic_result"],
                plan_deviation=draft["plan_deviation"],
                bias_tags=draft["bias_tags"],
                improvement_text=draft["improvement_text"],
            )
        except TradeWorkflowNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except TradeWorkflowConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except TradeWorkflowInvalidState as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.patch("/v1/trade-reviews/{review_id}/draft")
    def update_my_trade_review_draft(
        review_id: str, payload: TradeReviewDraftPatch, request: Request
    ) -> dict[str, Any]:
        user = require_session_user(request)
        try:
            return trade_workflow.save_user_draft(
                user_id=user["id"],
                review_id=review_id,
                base_version=payload.base_version,
                price_result=payload.price_result,
                logic_result=payload.logic_result,
                plan_deviation=payload.plan_deviation,
                bias_tags=payload.bias_tags,
                improvement_text=payload.improvement_text,
            )
        except TradeWorkflowNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except TradeWorkflowConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except TradeWorkflowInvalidState as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/v1/trade-reviews/{review_id}/confirm")
    def confirm_my_trade_review(
        review_id: str, payload: TradeReviewConfirm, request: Request
    ) -> dict[str, Any]:
        user = require_session_user(request)
        try:
            return trade_workflow.confirm_trade_review(
                user_id=user["id"],
                review_id=review_id,
                base_version=payload.base_version,
            )
        except TradeWorkflowNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except TradeWorkflowConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except TradeWorkflowInvalidState as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/v1/trade-reviews/{review_id}/archive")
    def archive_my_trade_review(
        review_id: str, payload: TradeReviewConfirm, request: Request
    ) -> dict[str, Any]:
        user = require_session_user(request)
        try:
            return trade_workflow.archive_trade_review(
                user_id=user["id"],
                review_id=review_id,
                base_version=payload.base_version,
            )
        except TradeWorkflowNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except TradeWorkflowConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except TradeWorkflowInvalidState as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/v1/observation-tasks")
    def list_my_observation_tasks(
        request: Request,
        symbol: str | None = Query(default=None, max_length=24),
        status: str | None = Query(default=None, max_length=24),
        limit: int = Query(default=100, ge=1, le=200),
    ) -> dict[str, Any]:
        user = require_session_user(request)
        try:
            return observation_tasks.list_tasks(
                user_id=user["id"], symbol=symbol, status=status, limit=limit
            )
        except ObservationTaskInvalidState as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/v1/stocks/{symbol}/observation-tasks")
    def list_my_stock_observation_tasks(
        symbol: str,
        request: Request,
        status: str | None = Query(default=None, max_length=24),
        limit: int = Query(default=100, ge=1, le=200),
    ) -> dict[str, Any]:
        user = require_session_user(request)
        try:
            return observation_tasks.list_tasks(
                user_id=user["id"], symbol=symbol, status=status, limit=limit
            )
        except ObservationTaskInvalidState as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/v1/stocks/{symbol}/observation-tasks", status_code=201)
    def create_my_observation_task(
        symbol: str, payload: ObservationTaskCreate, request: Request
    ) -> dict[str, Any]:
        user = require_session_user(request)
        try:
            return observation_tasks.create_task(
                user_id=user["id"],
                symbol=symbol,
                title=payload.title,
                description=payload.description,
                priority=payload.priority,
                due_at=payload.due_at,
                thesis_id=payload.thesis_id,
                change_ref=payload.change_ref,
                source_type=payload.source_type,
                source_ref_id=payload.source_ref_id,
            )
        except ObservationTaskInvalidState as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/v1/observation-tasks/{task_id}")
    def get_my_observation_task(task_id: str, request: Request) -> dict[str, Any]:
        user = require_session_user(request)
        try:
            return observation_tasks.get_task(user_id=user["id"], task_id=task_id)
        except ObservationTaskNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.patch("/v1/observation-tasks/{task_id}")
    def update_my_observation_task(
        task_id: str, payload: ObservationTaskUpdate, request: Request
    ) -> dict[str, Any]:
        user = require_session_user(request)
        try:
            return observation_tasks.update_task(
                user_id=user["id"],
                task_id=task_id,
                base_version=payload.base_version,
                title=payload.title,
                description=payload.description,
                priority=payload.priority,
                due_at=payload.due_at,
                due_at_provided="due_at" in payload.model_fields_set,
            )
        except ObservationTaskNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ObservationTaskVersionConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ObservationTaskInvalidState as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/v1/observation-tasks/{task_id}/transition")
    def transition_my_observation_task(
        task_id: str, payload: ObservationTaskTransition, request: Request
    ) -> dict[str, Any]:
        user = require_session_user(request)
        try:
            return observation_tasks.transition_task(
                user_id=user["id"],
                task_id=task_id,
                base_version=payload.base_version,
                status=payload.status,
                result_text=payload.result_text,
                evidence_refs=payload.evidence_refs,
            )
        except ObservationTaskNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ObservationTaskVersionConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ObservationTaskInvalidState as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/v1/stocks/{symbol}/relation")
    def get_my_stock_relation(symbol: str, request: Request) -> dict[str, Any]:
        user = require_session_user(request)
        try:
            return stock_domain.get_workspace(user["id"], symbol)
        except StockDomainNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except StockDomainInvalidState as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.patch("/v1/stocks/{symbol}/relation")
    def update_my_stock_relation(
        symbol: str, payload: StockRelationUpdate, request: Request
    ) -> dict[str, Any]:
        user = require_session_user(request)
        try:
            return stock_domain.update_relation(
                user_id=user["id"],
                symbol=symbol,
                base_version=payload.base_version,
                relation_type=payload.relation_type,
                priority=payload.priority,
                tracking_status=payload.tracking_status,
                workflow_status=payload.workflow_status,
                attention_tags=payload.attention_tags,
            )
        except StockDomainNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except StockDomainVersionConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except StockDomainInvalidState as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/v1/stocks/{symbol}/theses")
    def list_my_stock_theses(symbol: str, request: Request) -> dict[str, Any]:
        user = require_session_user(request)
        try:
            return stock_domain.list_theses(user["id"], symbol)
        except StockDomainNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/v1/stocks/{symbol}/theses", status_code=201)
    def create_my_stock_thesis_candidate(
        symbol: str, payload: ThesisCandidateCreate, request: Request
    ) -> dict[str, Any]:
        user = require_session_user(request)
        try:
            return stock_domain.create_thesis_candidate(
                user_id=user["id"],
                symbol=symbol,
                reason_text=payload.reason_text,
                watch_items=payload.watch_items,
                recheck_conditions=payload.recheck_conditions,
                source=payload.source,
                source_run_id=payload.source_run_id,
                base_version=payload.base_version,
            )
        except StockDomainNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except StockDomainVersionConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except StockDomainInvalidState as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/v1/stocks/{symbol}/theses/{thesis_id}/confirm")
    def confirm_my_stock_thesis(
        symbol: str, thesis_id: str, request: Request
    ) -> dict[str, Any]:
        user = require_session_user(request)
        try:
            return stock_domain.confirm_thesis(
                user_id=user["id"], symbol=symbol, thesis_id=thesis_id
            )
        except StockDomainNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except StockDomainVersionConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except StockDomainInvalidState as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/v1/stocks/{symbol}/theses/{thesis_id}/reject")
    def reject_my_stock_thesis(
        symbol: str, thesis_id: str, request: Request
    ) -> dict[str, Any]:
        user = require_session_user(request)
        try:
            return stock_domain.reject_thesis(
                user_id=user["id"], symbol=symbol, thesis_id=thesis_id
            )
        except StockDomainNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except StockDomainInvalidState as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/v1/ai-writebacks")
    def list_my_ai_writebacks(
        request: Request,
        status: str | None = Query(default=None, max_length=32),
        limit: int = Query(default=100, ge=1, le=300),
    ) -> dict[str, Any]:
        user = require_session_user(request)
        try:
            return structured_ai.list_writebacks(
                user_id=user["id"], status=status, limit=limit
            )
        except StructuredAIInvalidState as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/v1/ai-writebacks/{candidate_id}")
    def get_my_ai_writeback(candidate_id: str, request: Request) -> dict[str, Any]:
        user = require_session_user(request)
        try:
            return structured_ai.get_writeback(
                user_id=user["id"], candidate_id=candidate_id
            )
        except StructuredAINotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/v1/ai-writebacks/{candidate_id}/confirm")
    def confirm_my_ai_writeback(candidate_id: str, request: Request) -> dict[str, Any]:
        user = require_session_user(request)
        try:
            return structured_ai.confirm_writeback(
                user_id=user["id"], candidate_id=candidate_id
            )
        except StructuredAINotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except StructuredAIConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except StructuredAIInvalidState as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except StockDomainVersionConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except StockDomainInvalidState as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/v1/ai-writebacks/{candidate_id}/reject")
    def reject_my_ai_writeback(candidate_id: str, request: Request) -> dict[str, Any]:
        user = require_session_user(request)
        try:
            return structured_ai.reject_writeback(
                user_id=user["id"], candidate_id=candidate_id
            )
        except StructuredAINotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except StructuredAIInvalidState as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/me/knowledge")
    def list_my_knowledge(request: Request) -> dict[str, Any]:
        user = require_session_user(request)
        items = database.list_knowledge_documents(user["id"])
        return {
            "items": [knowledge.public_document(item) for item in items],
            "summary": {
                "common": sum(item.get("scope") == "common" for item in items),
                "user": sum(item.get("scope") == "user" for item in items),
            },
        }

    @app.get("/me/knowledge/{document_id}")
    def get_my_knowledge_document(document_id: str, request: Request) -> dict[str, Any]:
        user = require_session_user(request)
        document = database.get_knowledge_document(user["id"], document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="资料不存在")
        content = str(document.get("content") or "")
        return {
            **knowledge.public_document({**document, "content_chars": len(content)}),
            "content": content,
        }

    @app.post("/me/knowledge", status_code=201)
    async def upload_my_knowledge(
        request: Request, file: UploadFile = File(...)
    ) -> dict[str, Any]:
        user = require_session_user(request)
        original_name = Path(file.filename or "research-note.txt").name[:180]
        suffix = Path(original_name).suffix.casefold()
        if suffix not in {".txt", ".md", ".markdown", ".csv", ".json"}:
            raise HTTPException(
                status_code=415,
                detail="资料库当前支持 TXT、Markdown、CSV 和 JSON 文本",
            )
        raw = await file.read(settings.max_document_upload_bytes + 1)
        await file.close()
        if not raw:
            raise HTTPException(status_code=422, detail="资料内容为空")
        if len(raw) > settings.max_document_upload_bytes:
            raise HTTPException(status_code=413, detail="资料超过上传大小限制")
        try:
            document = knowledge.create_user_document(
                user_id=user["id"],
                original_name=original_name,
                mime_type=file.content_type or "text/plain",
                raw=raw,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        knowledge_dir = Path(user["workspace_path"]) / "knowledge"
        knowledge_dir.mkdir(parents=True, exist_ok=True)
        (knowledge_dir / f"{document['id']}.txt").write_text(
            document["content"], encoding="utf-8"
        )
        public = knowledge.public_document(
            {**document, "content_chars": len(document["content"])}
        )
        return public

    @app.delete("/me/knowledge/{document_id}", status_code=204)
    def delete_my_knowledge(document_id: str, request: Request) -> Response:
        user = require_session_user(request)
        document = database.get_knowledge_document(user["id"], document_id)
        if document is None or document.get("scope") != "user":
            raise HTTPException(status_code=404, detail="个人资料不存在")
        if not database.delete_user_knowledge_document(user["id"], document_id):
            raise HTTPException(status_code=404, detail="个人资料不存在")
        stored_path = Path(user["workspace_path"]) / "knowledge" / f"{document_id}.txt"
        stored_path.unlink(missing_ok=True)
        return Response(status_code=204)

    @app.get("/users/{user_id}")
    def get_user(user_id: str, request: Request) -> dict[str, Any]:
        return public_user(require_user(request, user_id))

    @app.get("/indices")
    def get_indices(
        scope: Literal["core", "all"] = "core",
        group: str | None = None,
    ) -> dict[str, Any]:
        return analysis.get_indices(scope=scope, group=group)

    @app.get("/markets/live")
    def get_live_markets() -> dict[str, Any]:
        return live_markets.snapshot()

    @app.get("/indices/{symbol}/history")
    def get_index_history(
        symbol: str,
        range_name: Literal["1mo", "3mo", "6mo", "1y", "2y", "5y", "max"] = Query(
            default="1y", alias="range"
        ),
    ) -> dict[str, Any]:
        normalized = normalize_symbol(symbol)
        if normalized not in INDEX_BY_SYMBOL:
            raise HTTPException(status_code=404, detail="指数不在当前可审计目录中")
        try:
            return analysis.get_index_history(normalized, range_name=range_name)
        except ProviderError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/stocks/{symbol}/history")
    def get_stock_history(
        symbol: str,
        range_name: Literal["1mo", "3mo", "6mo", "1y", "2y", "5y", "max"] = Query(
            default="3mo", alias="range"
        ),
    ) -> dict[str, Any]:
        try:
            normalized = normalize_symbol(symbol)
            if normalized in INDEX_BY_SYMBOL or normalized.startswith("^"):
                raise ValueError("该接口用于个股，指数请使用指数历史接口")
            history = analysis.get_index_history(normalized, range_name=range_name)
            target = RESEARCH_TARGETS.get(normalized) or {}
            if target.get("name"):
                history["display_name"] = target["name"]
            return history
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ProviderError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/stocks/{symbol}/intraday")
    def get_stock_intraday(symbol: str) -> dict[str, Any]:
        try:
            normalized = normalize_symbol(symbol)
            if normalized in INDEX_BY_SYMBOL or normalized.startswith("^"):
                raise ValueError("该接口用于个股，指数请使用实时市场接口")
            history = live_market_provider.fetch_history(
                normalized,
                range_name="1d",
                interval="1m",
            )
            points = history.get("points") or []
            if not points:
                raise ProviderError("没有可用的个股分时数据")
            latest = points[-1]
            previous_close = history.get("previous_close")
            pct_change = None
            if previous_close not in (None, 0):
                pct_change = round(
                    (float(latest["close"]) / float(previous_close) - 1) * 100,
                    4,
                )
            target = RESEARCH_TARGETS.get(normalized) or {}
            return {
                **history,
                "display_name": target.get("name")
                or history.get("display_name")
                or normalized,
                "latest_price": latest.get("close"),
                "pct_change": pct_change,
                "market_timestamp": latest.get("timestamp"),
            }
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ProviderError as exc:
            normalized = normalize_symbol(symbol)
            stored = database.get_market_bars(normalized, "1m", limit=800)
            if not stored:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
            latest = stored[-1]
            return {
                "symbol": normalized,
                "display_name": (RESEARCH_TARGETS.get(normalized) or {}).get("name")
                or normalized,
                "status": "stored",
                "data_granularity": "1m",
                "points": stored,
                "latest_price": latest.get("close"),
                "pct_change": None,
                "market_timestamp": latest.get("timestamp"),
                "fetched_at": latest.get("fetched_at"),
            }

    @app.get("/sectors/hot")
    def hot_sectors(limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
        return analysis.hot_sectors(limit=limit)

    @app.get("/markets/breadth")
    def market_breadth() -> dict[str, Any]:
        return analysis.market_breadth()

    @app.get("/api/v1/today/overview", include_in_schema=False)
    @app.get("/v1/today/overview")
    def get_today_overview(request: Request) -> dict[str, Any]:
        user = require_session_user(request)
        return today_overview.get_overview(user["id"])

    @app.get("/api/v1/changes", include_in_schema=False)
    @app.get("/v1/changes")
    def list_my_change_events(
        request: Request,
        symbol: str | None = Query(default=None, max_length=24),
        relevance_status: Literal["pending", "relevant", "irrelevant"] | None = Query(
            default=None
        ),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict[str, Any]:
        user = require_session_user(request)
        try:
            return change_events.get_user_packet(
                user["id"],
                symbol=symbol,
                relevance_status=relevance_status,
                limit=limit,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/v1/changes/{link_id}")
    def get_my_change_event(link_id: str, request: Request) -> dict[str, Any]:
        user = require_session_user(request)
        try:
            return change_events.get_user_change(user["id"], link_id)
        except ChangeEventNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/v1/user-changes/{link_id}/read")
    def mark_my_change_event_read(link_id: str, request: Request) -> dict[str, Any]:
        user = require_session_user(request)
        try:
            return change_events.mark_read(user["id"], link_id)
        except ChangeEventNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/v1/user-changes/{link_id}/relevance")
    def set_my_change_event_relevance(
        link_id: str, payload: ChangeRelevanceUpdate, request: Request
    ) -> dict[str, Any]:
        user = require_session_user(request)
        try:
            return change_events.set_relevance(
                user["id"], link_id, payload.relevance_status
            )
        except ChangeEventNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/a-share/{symbol}/information")
    def get_a_share_information(symbol: str) -> dict[str, Any]:
        try:
            return china_info.get_packet(symbol)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/a-share/{symbol}/fundamentals")
    def get_a_share_fundamentals(symbol: str) -> dict[str, Any]:
        try:
            return fundamentals.get_packet(symbol)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/a-share/{symbol}/filings")
    def get_a_share_filings(symbol: str) -> dict[str, Any]:
        try:
            return filings.get_overview(symbol)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/a-share/{symbol}/business-structure")
    def get_a_share_business_structure(symbol: str) -> dict[str, Any]:
        try:
            return business_structure.get_packet(symbol)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/a-share/{symbol}/shareholders")
    def get_a_share_shareholders(symbol: str) -> dict[str, Any]:
        try:
            return shareholders.get_packet(symbol)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/a-share/{symbol}/analyst-expectations")
    def get_a_share_analyst_expectations(symbol: str) -> dict[str, Any]:
        try:
            return analyst_expectations.get_packet(symbol)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ProviderError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/stocks/{symbol}/event-timeline")
    def get_stock_event_timeline(symbol: str) -> dict[str, Any]:
        try:
            return event_timeline.get_packet(symbol)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/us-equity/{symbol}/fundamentals")
    def get_us_equity_fundamentals(symbol: str) -> dict[str, Any]:
        try:
            return us_fundamentals.get_packet(symbol)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/stocks/{symbol}/earnings-quality")
    def get_earnings_quality(symbol: str) -> dict[str, Any]:
        try:
            canonical = normalize_symbol(symbol)
            if canonical.endswith((".SS", ".SZ")):
                fundamentals.get_packet(canonical)
            else:
                us_fundamentals.get_packet(canonical)
            return earnings_quality.get_packet(canonical)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/stocks/{symbol}/financial-drivers")
    def get_financial_drivers(symbol: str) -> dict[str, Any]:
        try:
            canonical = normalize_symbol(symbol)
            if canonical.endswith((".SS", ".SZ")):
                fundamentals.get_packet(canonical)
            else:
                us_fundamentals.get_packet(canonical)
            return financial_drivers.get_packet(canonical)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/peer-comparisons/{symbol}")
    def get_peer_comparison(symbol: str) -> dict[str, Any]:
        try:
            return peer_comparison.get_packet(symbol)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/a-share/news")
    def get_latest_a_share_news(
        limit: int = Query(default=30, ge=1, le=100),
    ) -> dict[str, Any]:
        return {
            "items": database.list_news(
                limit=limit, categories=("announcement", "news")
            )
        }

    @app.get("/users/{user_id}/watchlist")
    def list_watchlist(user_id: str, request: Request) -> dict[str, Any]:
        require_user(request, user_id)
        return {"items": database.list_watchlist(user_id)}

    @app.post("/users/{user_id}/watchlist")
    def upsert_watchlist(
        user_id: str, payload: WatchlistUpsert, request: Request
    ) -> dict[str, Any]:
        require_user(request, user_id)
        try:
            symbol = normalize_symbol(payload.symbol)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return database.upsert_watchlist(
            user_id=user_id,
            symbol=symbol,
            name=payload.name,
            market=payload.market,
            thesis=payload.thesis,
        )

    @app.get("/users/{user_id}/watchlist/brief")
    def watchlist_brief(user_id: str, request: Request) -> dict[str, Any]:
        require_user(request, user_id)
        return analysis.watchlist_brief(user_id)

    @app.get("/me/watchlist")
    def list_my_watchlist(request: Request) -> dict[str, Any]:
        user = require_session_user(request)
        return {"items": database.list_watchlist(user["id"])}

    @app.post("/me/watchlist")
    def upsert_my_watchlist(
        payload: WatchlistUpsert, request: Request
    ) -> dict[str, Any]:
        user = require_session_user(request)
        try:
            symbol = normalize_symbol(payload.symbol)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return database.upsert_watchlist(
            user_id=user["id"],
            symbol=symbol,
            name=payload.name,
            market=payload.market,
            thesis=payload.thesis,
        )

    @app.delete("/me/watchlist/{symbol}", status_code=204)
    def delete_my_watchlist(symbol: str, request: Request) -> Response:
        user = require_session_user(request)
        try:
            normalized = normalize_symbol(symbol)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if not database.delete_watchlist_item(user["id"], normalized):
            raise HTTPException(status_code=404, detail="自选股不存在")
        return Response(status_code=204)

    @app.get("/me/watchlist/brief")
    def my_watchlist_brief(request: Request) -> dict[str, Any]:
        user = require_session_user(request)
        return analysis.watchlist_brief(user["id"])

    @app.post("/users/{user_id}/memories/candidates", status_code=201)
    def create_memory_candidate(
        user_id: str, payload: MemoryCandidateCreate, request: Request
    ) -> dict[str, Any]:
        require_user(request, user_id)
        return database.create_memory(user_id, payload.kind, payload.content)

    @app.get("/users/{user_id}/memories")
    def list_memories(
        user_id: str,
        request: Request,
        status: Literal["candidate", "confirmed", "rejected"] = "confirmed",
    ) -> dict[str, Any]:
        require_user(request, user_id)
        return {"items": database.list_memories(user_id, status=status)}

    @app.post("/users/{user_id}/memories/{memory_id}/confirm")
    def confirm_memory(
        user_id: str, memory_id: str, request: Request
    ) -> dict[str, Any]:
        require_user(request, user_id)
        memory = database.confirm_memory(user_id, memory_id)
        if memory is None:
            raise HTTPException(status_code=404, detail="记忆候选不存在或已处理")
        return memory

    @app.post("/users/{user_id}/memories/{memory_id}/reject")
    def reject_memory(user_id: str, memory_id: str, request: Request) -> dict[str, Any]:
        require_user(request, user_id)
        memory = database.reject_memory(user_id, memory_id)
        if memory is None:
            raise HTTPException(status_code=404, detail="记忆候选不存在或已处理")
        return memory

    @app.post("/me/memories/candidates", status_code=201)
    def create_my_memory_candidate(
        payload: MemoryCandidateCreate, request: Request
    ) -> dict[str, Any]:
        user = require_session_user(request)
        return database.create_memory(user["id"], payload.kind, payload.content)

    @app.get("/me/memories")
    def list_my_memories(
        request: Request,
        status: Literal["candidate", "confirmed", "rejected"] = "confirmed",
    ) -> dict[str, Any]:
        user = require_session_user(request)
        return {"items": database.list_memories(user["id"], status=status)}

    @app.post("/me/memories/{memory_id}/confirm")
    def confirm_my_memory(memory_id: str, request: Request) -> dict[str, Any]:
        user = require_session_user(request)
        memory = database.confirm_memory(user["id"], memory_id)
        if memory is None:
            raise HTTPException(status_code=404, detail="记忆候选不存在或已处理")
        return memory

    @app.post("/me/memories/{memory_id}/reject")
    def reject_my_memory(memory_id: str, request: Request) -> dict[str, Any]:
        user = require_session_user(request)
        memory = database.reject_memory(user["id"], memory_id)
        if memory is None:
            raise HTTPException(status_code=404, detail="记忆候选不存在或已处理")
        return memory

    @app.post("/articles/market-pulse")
    def generate_market_pulse(payload: ArticleGenerateRequest) -> dict[str, Any]:
        return articles.generate(
            model_tier=payload.model_tier,
            execute_agent=payload.execute_agent,
            force=False,
        )

    @app.get("/articles")
    def list_articles(limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
        return {"items": articles.list_articles(limit=limit)}

    @app.get("/research-reports")
    def list_research_reports(
        limit: int = Query(default=20, ge=1, le=100),
    ) -> dict[str, Any]:
        return {"items": research_reports.list_latest(limit=limit)}

    @app.get("/research-method")
    def get_research_method(
        limit: int = Query(default=4, ge=1, le=12),
    ) -> dict[str, Any]:
        recent = []
        for report in database.list_latest_research_reports(limit=limit):
            evidence = report.get("evidence") or {}
            board = evidence.get("analysis_board") or {}
            display_name = RESEARCH_TARGETS.get(str(report.get("symbol")), {}).get(
                "name"
            ) or report.get("name")
            report_title = str(report.get("title") or "")
            if report.get("name") and display_name:
                report_title = report_title.replace(
                    str(report.get("name")), str(display_name), 1
                )
            modules = [
                {
                    "key": item.get("key"),
                    "label": item.get("label"),
                    "status": item.get("status"),
                    "evidence_count": item.get("evidence_count", 0),
                }
                for item in (board.get("modules") or [])
            ]
            recent.append(
                {
                    "symbol": report.get("symbol"),
                    "name": display_name,
                    "title": report_title,
                    "summary": report.get("summary"),
                    "generated_at": report.get("generated_at"),
                    "market_timestamp": report.get("market_timestamp"),
                    "framework": board.get("framework")
                    or "deterministic_multi_analyst_board_v1",
                    "module_coverage": {
                        "ready": board.get("ready_modules", 0),
                        "total": board.get("total_modules", len(modules)),
                    },
                    "modules": modules,
                }
            )
        return {
            "pipeline": [
                {
                    "title": "识别研究对象与上下文",
                    "detail": "先区分整体市场、个股、跟踪变化或资料型问题，并继承同一历史对话里的市场和证券上下文。",
                },
                {
                    "title": "构建确定性证据包",
                    "detail": "代码读取行情、K线、公告新闻、财报全文、主营构成、股东户数与十大股东、分析师一致预期与研报、情绪样本、财务、估值和同行数据，并计算技术结构、波动、回撤、同类报告期财报质量、详细三表利润现金流驱动、业务与毛利来源及条件展望。",
                },
                {
                    "title": "七模块交叉审查",
                    "detail": "行情结构、公告新闻与事件脉络、情绪分歧、基本面现金流、分析师预期与研报、同行估值、多空与风险委员会分别产出证据和反证。",
                },
                {
                    "title": "检索用户与通用资料库",
                    "detail": "按当前问题检索个人资料、已确认偏好、通用研究材料和服务器预计算报告，未确认记忆不会进入长期个性化。",
                },
                {
                    "title": "AI 综合表达",
                    "detail": "Agent 只能引用已取得的证据，负责解释因果候选、指出反方证据与失效条件，不负责凭空生成行情数字。",
                },
                {
                    "title": "保存报告与证据变化",
                    "detail": "研究快照、对话、引用资料、连续两次报告之间的变化和用户研究行动都会写入数据库与资料库，供后续对话长期复用。",
                },
                {
                    "title": "回填研究结果",
                    "detail": "后台只用已存复权日线按 T+3/T+5/T+10 回看条件是否触发、区间路径和反方证据；未到期样本只显示进度。",
                },
            ],
            "tools": [
                {
                    "name": "全球行情与 K 线",
                    "role": "中日韩美和伦敦金分钟行情；指数与个股历史日线；收益、均线、波动率和最大回撤。",
                },
                {
                    "name": "技术结构计算器",
                    "role": "RSI14、MACD(12,26,9)、20日布林带、ATR14和5/20日量比，只描述已发生结构。",
                },
                {
                    "name": "A股信息与情绪",
                    "role": "公司公告、公司相关资讯和社区样本；情绪只作为弱证据，不替代价格与基本面。",
                },
                {
                    "name": "重要事件脉络分析器",
                    "role": "把已落库的公告、监管文件和媒体报道按财报、订单、回购、股东变化、监管诉讼等主题组织为长期时间线；不估算发生概率或股价影响。",
                },
                {
                    "name": "财务、监管与估值",
                    "role": "结构化财务期、现金流、估值快照和美股监管文件，用于核验叙事是否有基本面支撑。",
                },
                {
                    "name": "财报质量对比器",
                    "role": "只比较上一年度同类报告期，检查增长速度、利润率、现金流覆盖、杠杆与矛盾证据，并生成静态毛利率敏感性而不冒充利润归因。",
                },
                {
                    "name": "利润与现金流驱动拆解器",
                    "role": "比较上一年度同类报告期的利润表、资产负债表和现金流量表，量化毛利桥、费用率、应收存货、销售收现和现金流变化，并区分机械影响、公司财报原文解释、可疑线索与未确认因果。",
                },
                {
                    "name": "A股财报全文证据器",
                    "role": "保存财报完整正文，按报告期提取毛利、财务费用、汇兑、存货、回款、现金流、减值等原文原因；公司解释作为一手披露，但不冒充独立因果证明。",
                },
                {
                    "name": "主营业务与毛利来源拆解器",
                    "role": "读取公司年报和中报的产品、地区、行业收入与毛利构成，只做同类报告期比较；最新收入期缺少分部毛利率时，单列最近可用参考期，不能混写。",
                },
                {
                    "name": "股东户数与十大股东分析器",
                    "role": "保存股东户数历史和最近一期十大股东，区分高频户数披露与季度存量；只输出集中或分散线索，不把户数变化写成机构吸筹、资金流或涨跌预测。",
                },
                {
                    "name": "分析师一致预期与研报跟踪器",
                    "role": "保存A股券商评级分布、A/E每股收益预测和近期研报，只有存在历史快照时才计算同财年EPS上修或下修，并同步报告覆盖机构变化；不输出目标价。",
                },
                {
                    "name": "同行与历史校准",
                    "role": "固定同行样本、相对估值和历史条件走查，用于约束条件展望，不输出确定性概率。",
                },
                {
                    "name": "研究优先级与变化归档",
                    "role": "按证据变化、价格异动、回撤波动、基本面反证和覆盖缺口排列复核顺序，并保存长期快照；不按预期收益排序。",
                },
                {
                    "name": "研究行动与观察条件",
                    "role": "把研究报告、变化事件、回撤波动、均线量能和资料缺口转换成已触发、待补证与继续观察的工作清单；只决定下一步核验什么。",
                },
                {
                    "name": "研究结果回填",
                    "role": "按固定 T+3/T+5/T+10 交易日复盘原条件、上下边界和价格路径；只核验研究过程，不计算荐股胜率。",
                },
                {
                    "name": "资料库、研究工具与 AI 引擎",
                    "role": "按问题检索用户与通用资料，选择对应金融分析工具，再由 AI 引擎进行有边界的综合回答。",
                },
            ],
            "recent_analyses": recent,
            "boundaries": [
                "价格、目标价、概率和交易指令不得由模型编造。",
                "新闻标题只能提供驱动线索，不能单独证明涨跌的唯一因果。",
                "条件展望必须同时给出触发条件、反方证据和失效条件。",
                "页面不展示密钥、内部提示词、供应商故障或后台任务细节。",
            ],
        }

    @app.get("/me/research-changes")
    def list_my_research_changes(
        request: Request,
        symbol: str | None = Query(default=None, max_length=24),
        limit: int = Query(default=20, ge=1, le=100),
    ) -> dict[str, Any]:
        user = require_session_user(request)
        try:
            return research_tracking.get_packet(user["id"], symbol=symbol, limit=limit)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/me/research-priority")
    def get_my_research_priority(request: Request) -> dict[str, Any]:
        user = require_session_user(request)
        return research_priority.get_packet(user["id"])

    @app.get("/me/research-actions")
    def get_my_research_actions(request: Request) -> dict[str, Any]:
        user = require_session_user(request)
        return research_actions.get_packet(user["id"])

    @app.get("/me/conversation-quality")
    def get_my_conversation_quality(request: Request) -> dict[str, Any]:
        user = require_session_user(request)
        return conversation_quality.analyze(user["id"])

    @app.post("/me/conversation-quality/refresh")
    def refresh_my_conversation_quality(request: Request) -> dict[str, Any]:
        user = require_session_user(request)
        return conversation_quality.analyze(user["id"])

    @app.get("/me/run-reviews")
    def list_my_run_reviews(
        request: Request,
        status: str | None = Query(default=None, max_length=24),
        repaired: bool | None = Query(default=None),
        q: str | None = Query(default=None, max_length=120),
        days: int = Query(default=7, ge=1, le=365),
        limit: int = Query(default=50, ge=1, le=100),
    ) -> dict[str, Any]:
        user = require_session_user(request)
        allowed_statuses = {"completed", "guarded", "degraded", "failed"}
        if status is not None and status not in allowed_statuses:
            raise HTTPException(status_code=422, detail="不支持的 Run 状态")

        conversations = database.list_conversations(
            user["id"], include_archived=True, limit=500
        )
        conversation_titles = {
            str(item["id"]): str(item.get("title") or "研究对话")
            for item in conversations
            if item.get("quality_scope") != "evaluation"
        }
        cutoff = datetime.now(tz=ZoneInfo("UTC")).timestamp() - days * 86400
        reviews: list[dict[str, Any]] = []
        for run in database.list_user_runs(user["id"], limit=500):
            input_data = run.get("input") or {}
            conversation_id = str(input_data.get("conversation_id") or "")
            if conversation_id not in conversation_titles:
                continue
            if str(run.get("status") or "") not in allowed_statuses:
                continue
            try:
                created_timestamp = datetime.fromisoformat(
                    str(run.get("created_at"))
                ).timestamp()
            except (TypeError, ValueError):
                created_timestamp = 0.0
            if created_timestamp < cutoff:
                continue
            reviews.append(
                _public_run_review(
                    run,
                    conversation_title=conversation_titles[conversation_id],
                    include_answer=False,
                )
            )

        summary_source = reviews
        query = str(q or "").strip().casefold()
        filtered = [
            item
            for item in reviews
            if (status is None or item["status"] == status)
            and (repaired is None or item["guard"]["repaired"] is repaired)
            and (
                not query
                or query
                in " ".join(
                    str(item.get(key) or "")
                    for key in (
                        "question",
                        "display_name",
                        "symbol",
                        "conversation_title",
                    )
                ).casefold()
            )
        ]
        status_counts = {
            key: sum(1 for item in summary_source if item["status"] == key)
            for key in sorted(allowed_statuses)
        }
        return {
            "items": filtered[:limit],
            "summary": {
                "total": len(summary_source),
                "filtered": len(filtered),
                "repaired": sum(
                    1 for item in summary_source if item["guard"]["repaired"]
                ),
                "statuses": status_counts,
                "days": days,
            },
        }

    @app.get("/me/run-reviews/{run_id}")
    def get_my_run_review(run_id: str, request: Request) -> dict[str, Any]:
        user = require_session_user(request)
        run = database.get_run(run_id, user["id"])
        if run is None:
            raise HTTPException(status_code=404, detail="复盘记录不存在")
        input_data = run.get("input") or {}
        conversation_id = str(input_data.get("conversation_id") or "")
        conversation = (
            database.get_conversation(user["id"], conversation_id)
            if conversation_id
            else None
        )
        if (
            conversation is None
            or conversation.get("quality_scope") == "evaluation"
            or str(run.get("status") or "")
            not in {"completed", "guarded", "degraded", "failed"}
        ):
            raise HTTPException(status_code=404, detail="复盘记录不存在")
        return _public_run_review(
            run,
            conversation_title=str(conversation.get("title") or "研究对话"),
            include_answer=True,
        )

    @app.get("/me/evidence-tasks")
    def get_my_evidence_tasks(
        request: Request,
        status: str | None = Query(default=None, max_length=32),
        limit: int = Query(default=100, ge=1, le=300),
    ) -> dict[str, Any]:
        user = require_session_user(request)
        allowed = {
            "pending",
            "collecting",
            "resolved",
            "pending_external",
            "failed",
        }
        if status is not None and status not in allowed:
            raise HTTPException(status_code=422, detail="未知的补证任务状态")
        return evidence_tasks.get_packet(user["id"], status=status, limit=limit)

    @app.post("/me/evidence-tasks/process")
    def process_my_evidence_tasks(
        request: Request,
        limit: int = Query(default=10, ge=1, le=30),
    ) -> dict[str, Any]:
        user = require_session_user(request)
        result = evidence_tasks.process_pending(user_id=user["id"], limit=limit)
        if result["summary"]["processed"]:
            event_broker.publish(
                {
                    "type": "evidence_tasks_updated",
                    "time": result["generated_at"],
                    **result["summary"],
                }
            )
        return result

    @app.get("/me/research-outcomes")
    def get_my_research_outcomes(
        request: Request,
        symbol: str | None = Query(default=None, max_length=24),
        limit: int = Query(default=120, ge=1, le=500),
    ) -> dict[str, Any]:
        user = require_session_user(request)
        try:
            return research_outcomes.get_packet(user["id"], symbol=symbol, limit=limit)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/outlook-calibrations/{symbol}")
    def get_outlook_calibration(symbol: str) -> dict[str, Any]:
        try:
            return outlook_calibration.get_packet(symbol)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ProviderError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/research-reports/{symbol}")
    def get_research_report(symbol: str) -> dict[str, Any]:
        try:
            report = research_reports.get_latest(symbol, generate_if_missing=True)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ProviderError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        if report is None:
            raise HTTPException(status_code=404, detail="研究报告尚未生成")
        return research_reports.public_report(report)

    @app.post("/users/{user_id}/chat")
    def chat(user_id: str, payload: ChatRequest, request: Request) -> dict[str, Any]:
        request_started = time.perf_counter()
        user = require_user(request, user_id)
        if payload.request_id and payload.execute_agent:
            try:
                agent_streams.open(payload.request_id, user_id)
            except PermissionError as exc:
                raise HTTPException(status_code=404, detail="实时回答不存在") from exc

        def publish_agent_progress(
            phase: str,
            label: str,
            **details: Any,
        ) -> None:
            if not payload.request_id or not payload.execute_agent:
                return
            event = {
                "type": "agent_progress",
                "request_id": payload.request_id,
                "phase": phase,
                "label": label,
                "elapsed_seconds": round(time.perf_counter() - request_started, 3),
                "time": utc_now(),
                **details,
            }
            event_broker.publish(event)
            agent_streams.publish(payload.request_id, user_id, event)

        publish_agent_progress(
            "routing_started",
            "正在识别问题，并检索实时证据与资料库…",
        )
        message = payload.message.strip()
        if payload.conversation_id:
            conversation = database.get_conversation(user_id, payload.conversation_id)
            if conversation is None or conversation.get("status") != "active":
                raise HTTPException(status_code=404, detail="研究对话不存在")
        else:
            conversation = database.create_conversation(
                user_id,
                _conversation_title(message),
                quality_scope=payload.quality_scope,
            )
        conversation_id = str(conversation["id"])
        history = database.list_conversation_messages(
            user_id, conversation_id, limit=40
        )
        if not history and conversation.get("title") == "新的研究对话":
            conversation = (
                database.rename_conversation(
                    user_id, conversation_id, _conversation_title(message)
                )
                or conversation
            )
        symbols = _extract_symbols(
            payload.symbol,
            message,
            watchlist=database.list_watchlist(user_id),
        )
        symbol = symbols[0] if len(symbols) == 1 else None
        prior_intent = _intent_from_history(history)
        contextual_followup = _is_contextual_followup(message)
        if not symbols and prior_intent == "stock_comparison" and contextual_followup:
            symbols = _symbols_from_history(history)
            symbol = symbols[0] if len(symbols) == 1 else None
        explicit_market_query = _is_market_query(message)
        explicit_industry_topic = _extract_industry_topic(message)
        explicit_stock_screen_query = _is_stock_screen_query(message)
        prior_screen_profile = _stock_screen_profile_from_history(history)
        stock_screen_query = explicit_stock_screen_query or (
            prior_intent == "stock_screen" and contextual_followup
        )
        explicit_li_zong_query = "李总" in message and any(
            keyword in message for keyword in ("策略", "选股", "候选", "触发", "规则")
        )
        li_zong_query = explicit_li_zong_query or (
            prior_intent == "stock_screen"
            and prior_screen_profile == "li_zong"
            and contextual_followup
        )
        peer_comparison_query = _is_peer_comparison_query(message)
        stock_comparison_query = (
            len(symbols) >= 2
            and not explicit_stock_screen_query
            and not explicit_li_zong_query
        )
        financial_driver_query = (
            _is_financial_driver_query(message) and not peer_comparison_query
        )
        earnings_quality_query = (
            _is_earnings_quality_query(message) and not peer_comparison_query
        )
        business_structure_query = (
            _is_business_structure_query(message) and not peer_comparison_query
        )
        shareholder_query = _is_shareholder_query(message)
        analyst_expectations_query = _is_analyst_expectations_query(message)
        event_timeline_query = _is_event_timeline_query(message)
        analyst_expectations_context = analyst_expectations_query or (
            prior_intent == "analyst_expectations" and contextual_followup
        )
        event_timeline_context = event_timeline_query or (
            prior_intent == "event_timeline" and contextual_followup
        )
        if (
            symbol is None
            and not explicit_market_query
            and prior_intent
            in {
                "stock_research",
                "research_tracking",
                "research_outcome",
                "earnings_quality",
                "financial_drivers",
                "business_structure",
                "shareholder_structure",
                "analyst_expectations",
                "event_timeline",
                "stock_screen",
            }
            and (
                contextual_followup
                or earnings_quality_query
                or financial_driver_query
                or business_structure_query
                or shareholder_query
                or analyst_expectations_query
                or event_timeline_query
            )
        ):
            symbol = _symbol_from_history(history)
        upload: dict[str, Any] | None = None
        image_path: str | None = None
        model_tier = payload.model_tier
        if payload.image_id:
            upload = database.get_user_upload(user_id, payload.image_id)
            if upload is None:
                raise HTTPException(
                    status_code=404, detail="图片不存在或不属于当前用户"
                )
            image_path = upload["workspace_path"]
            if not Path(image_path).is_file():
                raise HTTPException(
                    status_code=410, detail="图片文件已失效，请重新上传"
                )
            database.mark_user_upload_used(user_id, payload.image_id)
            model_tier = "vision"

        knowledge_query = message
        required_knowledge_sources: list[str] | None = None
        if explicit_market_query or (
            prior_intent == "market_brief" and contextual_followup
        ):
            question_focus = _market_question_focus(message)
            knowledge_query = (
                f"{message} 市场涨跌原因 证据规则 清数智算证据层级 "
                f"市场趋势与风险分析规则 {question_focus['label']}"
            )
            required_knowledge_sources = [
                "builtin:evidence-hierarchy.md",
                "builtin:market-causality.md",
                "builtin:market-trend-risk.md",
            ]
        elif li_zong_query:
            knowledge_query = (
                f"{message} 李总策略 确定性规则 基本面 股性 量价 "
                "真实涨停价 复权新高 三日放量 数据缺失 人工复核"
            )
        elif stock_screen_query:
            knowledge_query = (
                f"{message} 透明选股 研究候选 财务质量 估值约束 "
                "相对行业表现 反方证据 风险边界"
            )
        elif stock_comparison_query:
            knowledge_query = (
                f"{message} 多股统一口径比较 报告期可比性 盈利质量 估值 "
                "业务差异 反方证据 风险边界"
            )
        elif analyst_expectations_context:
            knowledge_query = (
                f"{message} 分析师一致预期 券商研报 EPS修订 评级覆盖 "
                "预测不是公司指引 评级不是交易建议"
            )
        elif event_timeline_context:
            knowledge_query = (
                f"{message} 公司公告 监管文件 重要事件 催化风险 "
                "官方披露 媒体线索 原文复核"
            )
        knowledge_context = knowledge.retrieve(
            user_id,
            knowledge_query,
            max_results=5,
            required_source_keys=required_knowledge_sources,
        )
        database.add_conversation_message(
            user_id=user_id,
            conversation_id=conversation_id,
            role="user",
            content=message,
            metadata={
                "image_id": payload.image_id,
                "model_tier": model_tier,
            },
        )

        def persist_response(
            response_payload: dict[str, Any],
            *,
            assistant_content: str,
            response_intent: str,
            response_symbol: str | None = None,
            run_id: str | None = None,
            evidence_payload: dict[str, Any] | None = None,
            structured_answer: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            sources = [
                {
                    "document_id": item.get("document_id"),
                    "title": item.get("title"),
                    "scope": item.get("scope"),
                }
                for item in knowledge_context.get("items", [])
            ]
            market_sources = [
                {
                    "title": item.get("title"),
                    "published_at": item.get("published_at"),
                }
                for item in (evidence_payload or {})
                .get("market_drivers", {})
                .get("items", [])[:6]
            ]
            market_key = (
                (evidence_payload or {}).get("market_drivers", {}).get("market_key")
            )
            research_targets: list[dict[str, str]] = []
            if response_intent == "stock_comparison":
                for target in (evidence_payload or {}).get("targets") or []:
                    target_symbol = str(target.get("symbol") or "").strip()
                    if not target_symbol:
                        continue
                    research_targets.append(
                        {
                            "symbol": target_symbol,
                            "name": str(target.get("name") or target_symbol),
                        }
                    )
            elif response_intent == "stock_screen":
                screen_evidence = evidence_payload or {}
                requested_targets = list(screen_evidence.get("requested_symbols") or [])
                if not requested_targets and screen_evidence.get("requested_symbol"):
                    requested_targets = [screen_evidence["requested_symbol"]]
                item_targets = {
                    str(item.get("internal_symbol") or item.get("symbol")): item
                    for item in screen_evidence.get("items") or []
                    if item.get("internal_symbol") or item.get("symbol")
                }
                for target_symbol in requested_targets[:10]:
                    target = item_targets.get(str(target_symbol)) or {}
                    research_targets.append(
                        {
                            "symbol": str(target_symbol),
                            "name": str(target.get("name") or target_symbol),
                        }
                    )
            evidence_sources = _build_visible_evidence_sources(evidence_payload)
            assistant_message = database.add_conversation_message(
                user_id=user_id,
                conversation_id=conversation_id,
                role="assistant",
                content=assistant_content,
                intent=response_intent,
                run_id=run_id,
                metadata={
                    "symbol": response_symbol,
                    "market_key": market_key,
                    "knowledge_sources": sources,
                    "market_sources": market_sources,
                    "evidence_sources": evidence_sources,
                    "research_targets": research_targets,
                    "structured_answer": structured_answer,
                    "model_tier": model_tier,
                    "stock_screen_profile": (
                        ((evidence_payload or {}).get("profile") or {}).get("key")
                        if response_intent == "stock_screen"
                        else None
                    ),
                },
            )
            try:
                conversation_quality.analyze(user_id)
            except Exception:
                pass
            return {
                **response_payload,
                "conversation_id": conversation_id,
                "conversation_title": conversation.get("title"),
                "assistant_message_id": assistant_message.get("id"),
                "knowledge": {
                    "items": sources,
                    "coverage": knowledge_context.get("coverage", {}),
                },
                "evidence_sources": evidence_sources,
                "research_targets": research_targets,
                "structured_answer": structured_answer,
            }

        if any(
            keyword in message
            for keyword in ("行情文章", "市场文章", "市场脉冲", "生成文章")
        ):
            if upload is not None:
                raise HTTPException(
                    status_code=422, detail="图片不用于全站市场文章生成"
                )
            result = articles.generate(
                model_tier=payload.model_tier
                if payload.model_tier != "vision"
                else "economy",
                execute_agent=payload.execute_agent,
                force=False,
            )
            article = result.get("article") or {}
            assistant_content = (
                article.get("summary")
                or article.get("body")
                or result.get("reason")
                or "市场文章任务已完成。"
            )
            return persist_response(
                {"intent": "market_pulse_article", **result},
                assistant_content=assistant_content,
                response_intent="market_pulse_article",
            )
        if any(keyword in message for keyword in ("加入自选", "添加自选", "加到自选")):
            if symbol is None:
                raise HTTPException(
                    status_code=422, detail="没有识别到要添加的证券代码"
                )
            item = database.upsert_watchlist(
                user_id,
                symbol,
                name=None,
                market=None,
                thesis=_extract_thesis(message),
            )
            intent = "watchlist_update"
            evidence = {
                "type": intent,
                "generated_at": utc_now(),
                "item": item,
                "warnings": [],
            }
        elif message.startswith("记住") or "请记住" in message:
            content = re.sub(r"^请?记住[：:\s]*", "", message).strip() or message
            memory = database.create_memory(user_id, "user_statement", content)
            intent = "memory_candidate"
            evidence = {
                "type": intent,
                "generated_at": utc_now(),
                "memory": memory,
                "warnings": ["该内容只是候选记忆，确认后才会用于长期个性化。"],
            }
        elif li_zong_query and upload is None:
            intent = "stock_screen"
            coverage = li_zong_strategy.coverage_packet()
            requested_symbols = li_zong_strategy.resolve_universe_mentions(message)
            if symbol is not None and symbol not in requested_symbols:
                requested_symbols.insert(0, symbol)
            if requested_symbols:
                candidates = []
                for requested in requested_symbols:
                    try:
                        candidates.append(li_zong_strategy.get_candidate(requested))
                    except ValueError:
                        candidates.append(None)
                selection_mode = (
                    "symbol_check"
                    if len(requested_symbols) == 1
                    else "symbol_comparison"
                )
                if len(requested_symbols) == 1:
                    symbol = requested_symbols[0]
            else:
                candidates = li_zong_strategy.list_actionable_candidates(limit=50)
                selection_mode = "candidate_pool"
            public_items = [
                _public_li_zong_candidate(item)
                for item in candidates
                if item is not None
            ]
            evaluated = int(coverage.get("evaluated_symbols") or 0)
            universe_count = int(coverage.get("universe_count") or 0)
            if not universe_count:
                evaluated = max(evaluated, len(public_items))
            full_coverage = bool(coverage.get("full_market_coverage"))
            deep_eligible = int(coverage.get("deep_check_eligible_count") or 0)
            deep_processed = int(coverage.get("deep_processed_symbols") or 0)
            deep_complete = bool(coverage.get("deep_check_complete"))
            history_insufficient = int(coverage.get("history_insufficient_count") or 0)
            history_unknown = int(coverage.get("history_unknown_count") or 0)
            warnings: list[str] = []
            if coverage.get("status") != "stable":
                warnings.append("全市场名单和市值快照尚未达到稳定发布门槛。")
            elif not full_coverage:
                warnings.append(
                    f"当前已有 {evaluated}/{universe_count} 只股票形成预筛或规则状态；"
                    "未处理股票不能推断为通过或不通过。"
                )
            if coverage.get("status") == "stable" and not deep_complete:
                warnings.append(
                    f"当前已深度处理 {deep_processed}/{deep_eligible} 只可核验股票；"
                    "尚未深度处理的股票不能推断为通过或不通过。"
                )
            if history_insufficient:
                warnings.append(
                    f"另有 {history_insufficient} 只市值达标股票因上市后量价历史不足，"
                    "已明确标记为数据不完整，未消耗逐股深度请求。"
                )
            if history_unknown:
                warnings.append(
                    f"另有 {history_unknown} 只股票不能仅凭上市日期确认五年ROE是否可得，"
                    "已纳入深度查询，不代表财务历史已经完整。"
                )
            if selection_mode == "candidate_pool" and not public_items:
                warnings.append(
                    "当前已评估范围内尚无进入候选池或触发池的股票。"
                    if not (full_coverage and deep_complete)
                    else "本期全市场预筛与深度处理完成，尚无股票进入候选池或触发池。"
                )
            if selection_mode == "symbol_check" and not public_items:
                warnings.append("该股票尚未形成可用的李总策略快照。")
            missing_requested_symbols = (
                [
                    requested
                    for requested, candidate in zip(requested_symbols, candidates)
                    if candidate is None
                ]
                if requested_symbols
                else []
            )
            if missing_requested_symbols:
                warnings.append(
                    "以下股票尚未形成可用的李总策略快照："
                    + "、".join(missing_requested_symbols)
                    + "。"
                )
            strategy_counts = coverage.get("counts") or {}
            actionable_candidate_count = int(
                strategy_counts.get("qualified") or 0
            ) + int(strategy_counts.get("triggered") or 0)
            evidence = {
                "type": "stock_screen",
                "status": (
                    "ready"
                    if selection_mode in {"symbol_check", "symbol_comparison"}
                    and requested_symbols
                    and len(public_items) == len(requested_symbols)
                    else "complete"
                    if selection_mode == "candidate_pool"
                    and full_coverage
                    and deep_complete
                    else "partial"
                ),
                "strategy": li_zong_strategy.get_definition(),
                "profile": {
                    "key": "li_zong",
                    "label": "李总策略",
                    "description": "基本面、股性、量价与盘后触发的确定性规则。",
                },
                "selection_mode": selection_mode,
                "requested_symbol": (
                    requested_symbols[0] if len(requested_symbols) == 1 else None
                ),
                "requested_symbols": requested_symbols,
                "missing_requested_symbols": missing_requested_symbols,
                "items": public_items,
                "data_meta": {
                    "universe_status": coverage.get("status"),
                    "latest_completed_trade_date": coverage.get("as_of_date")
                    or max(
                        (
                            str(item.get("as_of_date"))
                            for item in public_items
                            if item.get("as_of_date")
                        ),
                        default=None,
                    ),
                    "universe_count": universe_count,
                    "evaluated_symbols": evaluated,
                    "remaining_symbols": int(coverage.get("remaining_symbols") or 0),
                    "coverage_ratio": float(coverage.get("coverage_ratio") or 0),
                    "full_market_coverage": full_coverage,
                    "deep_check_eligible_count": deep_eligible,
                    "history_insufficient_count": history_insufficient,
                    "history_unknown_count": history_unknown,
                    "deep_processed_symbols": deep_processed,
                    "deep_remaining_symbols": int(
                        coverage.get("deep_remaining_symbols") or 0
                    ),
                    "deep_processing_ratio": float(
                        coverage.get("deep_processing_ratio") or 0
                    ),
                    "deep_decisive_symbols": int(
                        coverage.get("deep_decisive_symbols") or 0
                    ),
                    "deep_data_incomplete_symbols": int(
                        coverage.get("deep_data_incomplete_symbols") or 0
                    ),
                    "deep_check_complete": deep_complete,
                    "actionable_candidate_count": actionable_candidate_count,
                },
                "user_question": message,
                "warnings": warnings,
                "boundary": ("该策略只生成研究候选和人工复核触发，不构成买卖建议。"),
            }
        elif stock_screen_query and upload is None:
            intent = "stock_screen"
            screen_parameters = _stock_screen_parameters(message)
            try:
                evidence = stock_screener.screen(**screen_parameters)
            except StockScreenerUnavailable:
                evidence = {
                    "type": "stock_screen",
                    "status": "unavailable",
                    "profile": {
                        "key": screen_parameters["profile"],
                        "label": "研究候选筛选",
                    },
                    "data_meta": {},
                    "items": [],
                    "warnings": ["完整市场截面仍在准备。"],
                    "boundary": "系统不会在缺少确定性数据时生成临时候选。",
                }
        elif stock_comparison_query and upload is None:
            intent = "stock_comparison"
            try:
                evidence = stock_comparison.build(
                    user_id,
                    symbols,
                    question=message,
                )
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        elif _is_research_action_query(message) and symbol is None:
            intent = "research_actions"
            evidence = research_actions.get_packet(user_id)
        elif _is_research_priority_query(message):
            intent = "research_priority"
            evidence = research_priority.get_packet(user_id)
        elif _is_research_outcome_query(message):
            intent = "research_outcome"
            targets = (
                [symbol]
                if symbol
                else [item["symbol"] for item in database.list_watchlist(user_id)]
            )
            refresh_warnings = []
            for target in targets[:10]:
                if database.latest_research_report(target) is not None:
                    continue
                try:
                    research_reports.generate(target, execute_agent=False)
                except Exception as exc:
                    refresh_warnings.append(f"{target}: {type(exc).__name__}")
            evidence = research_outcomes.get_packet(user_id, symbol=symbol)
            evidence["warnings"] = refresh_warnings
        elif _is_research_tracking_query(message) and not _is_deep_stock_coverage_query(
            message
        ):
            intent = "research_tracking"
            targets = (
                [symbol]
                if symbol
                else [item["symbol"] for item in database.list_watchlist(user_id)]
            )
            refresh_warnings = []
            for target in targets[:10]:
                if database.latest_research_report(target) is not None:
                    continue
                try:
                    research_reports.generate(target, execute_agent=False)
                except Exception as exc:
                    refresh_warnings.append(f"{target}: {type(exc).__name__}")
            evidence = research_tracking.get_packet(user_id, symbol=symbol)
            evidence["watchlist_snapshot"] = analysis.watchlist_brief(user_id)
            evidence["warnings"] = refresh_warnings
        elif event_timeline_context:
            if symbol is None:
                clarification = {
                    "run_id": None,
                    "status": "clarification",
                    "intent": "clarification",
                    "model_tier": model_tier,
                    "answer": (
                        "请告诉我具体公司或证券代码，例如“中兴通讯最近有什么重要事件”"
                        "“中际旭创有哪些催化和风险事件”或“NVDA 最新事件脉络”。"
                    ),
                    "evidence": {
                        "type": "clarification",
                        "generated_at": utc_now(),
                    },
                    "error": None,
                }
                return persist_response(
                    clarification,
                    assistant_content=clarification["answer"],
                    response_intent="clarification",
                )
            intent = "event_timeline"
            evidence = event_timeline.get_packet(symbol)
            evidence["user_question"] = message
            watchlist_item = database.get_watchlist_item(user_id, symbol)
            evidence["user_thesis"] = (
                watchlist_item.get("thesis") if watchlist_item else None
            )
        elif analyst_expectations_context:
            if symbol is None:
                clarification = {
                    "run_id": None,
                    "status": "clarification",
                    "intent": "clarification",
                    "model_tier": model_tier,
                    "answer": (
                        "请告诉我具体 A 股公司或证券代码，例如“中兴通讯一致预期怎么样”"
                        "“分析师最近上修中际旭创了吗”或“000063 最新研报有哪些”。"
                    ),
                    "evidence": {
                        "type": "clarification",
                        "generated_at": utc_now(),
                    },
                    "error": None,
                }
                return persist_response(
                    clarification,
                    assistant_content=clarification["answer"],
                    response_intent="clarification",
                )
            if not symbol.endswith((".SS", ".SZ")):
                clarification = {
                    "run_id": None,
                    "status": "clarification",
                    "intent": "clarification",
                    "model_tier": model_tier,
                    "answer": (
                        "当前一致预期与个股研报跟踪先覆盖 A 股；"
                        "美股需要接入独立的分析师一致预期口径后再比较。"
                    ),
                    "evidence": {
                        "type": "clarification",
                        "generated_at": utc_now(),
                    },
                    "error": None,
                }
                return persist_response(
                    clarification,
                    assistant_content=clarification["answer"],
                    response_intent="clarification",
                )
            intent = "analyst_expectations"
            try:
                evidence = analyst_expectations.get_packet(symbol)
            except ProviderError:
                evidence = analyst_expectations.get_packet(
                    symbol, refresh_if_missing=False
                )
            evidence["user_question"] = message
            watchlist_item = database.get_watchlist_item(user_id, symbol)
            evidence["user_thesis"] = (
                watchlist_item.get("thesis") if watchlist_item else None
            )
        elif shareholder_query:
            if symbol is None:
                clarification = {
                    "run_id": None,
                    "status": "clarification",
                    "intent": "clarification",
                    "model_tier": model_tier,
                    "answer": (
                        "请告诉我具体 A 股公司或证券代码，例如“中兴通讯股东户数怎么变了”"
                        "“中兴通讯股东结构怎么样”或“000063 的十大股东是谁”。"
                    ),
                    "evidence": {
                        "type": "clarification",
                        "generated_at": utc_now(),
                    },
                    "error": None,
                }
                return persist_response(
                    clarification,
                    assistant_content=clarification["answer"],
                    response_intent="clarification",
                )
            if not symbol.endswith((".SS", ".SZ")):
                clarification = {
                    "run_id": None,
                    "status": "clarification",
                    "intent": "clarification",
                    "model_tier": model_tier,
                    "answer": "当前股东户数和十大股东明细先覆盖 A 股；美股机构持仓需要接入 13F 等监管披露后再分析。",
                    "evidence": {
                        "type": "clarification",
                        "generated_at": utc_now(),
                    },
                    "error": None,
                }
                return persist_response(
                    clarification,
                    assistant_content=clarification["answer"],
                    response_intent="clarification",
                )
            intent = "shareholder_structure"
            evidence = shareholders.get_packet(symbol)
            evidence["user_question"] = message
            watchlist_item = database.get_watchlist_item(user_id, symbol)
            evidence["user_thesis"] = (
                watchlist_item.get("thesis") if watchlist_item else None
            )
        elif business_structure_query:
            if symbol is None:
                clarification = {
                    "run_id": None,
                    "status": "clarification",
                    "intent": "clarification",
                    "model_tier": model_tier,
                    "answer": (
                        "请告诉我具体 A 股公司或证券代码，例如“中兴通讯靠什么业务赚钱”"
                        "“中际旭创收入来自哪里”或“贵州茅台产品收入结构怎么变了”。"
                    ),
                    "evidence": {
                        "type": "clarification",
                        "generated_at": utc_now(),
                    },
                    "error": None,
                }
                return persist_response(
                    clarification,
                    assistant_content=clarification["answer"],
                    response_intent="clarification",
                )
            if not symbol.endswith((".SS", ".SZ")):
                clarification = {
                    "run_id": None,
                    "status": "clarification",
                    "intent": "clarification",
                    "model_tier": model_tier,
                    "answer": "当前主营构成明细先覆盖 A 股；美股分部收入需要接入 SEC 分部披露后再分析。",
                    "evidence": {
                        "type": "clarification",
                        "generated_at": utc_now(),
                    },
                    "error": None,
                }
                return persist_response(
                    clarification,
                    assistant_content=clarification["answer"],
                    response_intent="clarification",
                )
            intent = "business_structure"
            evidence = business_structure.get_packet(symbol)
            evidence["user_question"] = message
            watchlist_item = database.get_watchlist_item(user_id, symbol)
            evidence["user_thesis"] = (
                watchlist_item.get("thesis") if watchlist_item else None
            )
        elif financial_driver_query:
            if symbol is None:
                clarification = {
                    "run_id": None,
                    "status": "clarification",
                    "intent": "clarification",
                    "model_tier": model_tier,
                    "answer": (
                        "请告诉我具体公司或证券代码，例如“中兴通讯利润为什么下降”"
                        "“分析中际旭创的应收和现金流”或“拆解 NVDA 最新利润驱动”。"
                    ),
                    "evidence": {
                        "type": "clarification",
                        "generated_at": utc_now(),
                    },
                    "error": None,
                }
                return persist_response(
                    clarification,
                    assistant_content=clarification["answer"],
                    response_intent="clarification",
                )
            related_information = []
            try:
                if symbol.endswith((".SS", ".SZ")):
                    fundamentals.get_packet(symbol)
                    information_packet = china_info.get_packet(symbol)
                    related_information = [
                        {
                            "category": item.get("category"),
                            "title": item.get("title"),
                            "published_at": item.get("published_at"),
                        }
                        for item in (
                            (information_packet.get("announcements") or [])[:4]
                            + (information_packet.get("news") or [])[:2]
                        )
                    ]
                else:
                    fundamentals_packet = us_fundamentals.get_packet(symbol)
                    related_information = [
                        {
                            "category": item.get("category"),
                            "title": item.get("title"),
                            "published_at": item.get("published_at"),
                        }
                        for item in (
                            fundamentals_packet.get("regulatory_filings") or []
                        )[:5]
                    ]
            except Exception:
                pass
            intent = "financial_drivers"
            evidence = financial_drivers.get_packet(symbol)
            evidence["user_question"] = message
            evidence["related_information"] = related_information
            watchlist_item = database.get_watchlist_item(user_id, symbol)
            evidence["user_thesis"] = (
                watchlist_item.get("thesis") if watchlist_item else None
            )
        elif earnings_quality_query:
            if symbol is None:
                clarification = {
                    "run_id": None,
                    "status": "clarification",
                    "intent": "clarification",
                    "model_tier": model_tier,
                    "answer": (
                        "请告诉我具体公司或证券代码，例如“中兴通讯财报质量怎么样”"
                        "“为什么中际旭创利润增长但现金流偏弱”或“分析 NVDA 最新财报”。"
                    ),
                    "evidence": {
                        "type": "clarification",
                        "generated_at": utc_now(),
                    },
                    "error": None,
                }
                return persist_response(
                    clarification,
                    assistant_content=clarification["answer"],
                    response_intent="clarification",
                )
            related_information = []
            fundamental_packet: dict[str, Any] = {}
            try:
                if symbol.endswith((".SS", ".SZ")):
                    fundamental_packet = fundamentals.get_packet(symbol)
                    information_packet = china_info.get_packet(symbol)
                    related_information = [
                        {
                            "category": item.get("category"),
                            "title": item.get("title"),
                            "published_at": item.get("published_at"),
                        }
                        for item in (
                            (information_packet.get("announcements") or [])[:3]
                            + (information_packet.get("news") or [])[:3]
                        )
                    ]
                else:
                    fundamental_packet = us_fundamentals.get_packet(symbol)
                    information_packet = global_info.get_packet(symbol)
                    related_information = [
                        {
                            "category": item.get("category"),
                            "title": item.get("title"),
                            "published_at": item.get("published_at"),
                        }
                        for item in (
                            (fundamental_packet.get("regulatory_filings") or [])[:3]
                            + (information_packet.get("news") or [])[:3]
                        )
                    ]
            except Exception:
                pass
            intent = "earnings_quality"
            evidence = earnings_quality.get_packet(symbol)
            evidence["fundamental_summary"] = fundamental_packet.get("summary") or {}
            evidence["related_information"] = related_information
            if symbol.endswith((".SS", ".SZ")):
                report_period = (evidence.get("latest_report") or {}).get("report_date")
                try:
                    filing_evidence = filings.get_packet(
                        symbol, report_period=report_period
                    )
                    if filing_evidence.get("status") != "available" and report_period:
                        filing_evidence = filings.ensure_report(symbol, report_period)
                    evidence["filing_evidence"] = filing_evidence
                    evidence["company_explanations"] = (
                        filing_evidence.get("explicit_company_explanations") or []
                    )
                except Exception:
                    evidence["company_explanations"] = []
            watchlist_item = database.get_watchlist_item(user_id, symbol)
            evidence["user_thesis"] = (
                watchlist_item.get("thesis") if watchlist_item else None
            )
        elif "自选" in message:
            intent = "watchlist_brief"
            evidence = analysis.watchlist_brief(user_id)
        elif (
            explicit_market_query
            or (prior_intent == "market_brief" and contextual_followup)
        ) and symbol is None:
            intent = "market_brief"
            question_focus = _market_question_focus(message)
            focused_market_key = (
                _market_key_from_history(history)
                if not explicit_market_query
                else MarketNewsService.infer_market(message)
            )
            evidence = analysis.market_brief(market_key=focused_market_key)
            evidence["user_question"] = message
            evidence["question_focus"] = question_focus
            evidence["market_drivers"] = market_news.get_packet(
                message,
                market_key=focused_market_key,
                focus_key=question_focus["key"],
            )
            if explicit_industry_topic:
                target_market_date = (
                    str(
                        (evidence.get("analysis_target") or {}).get("market_date") or ""
                    ).strip()
                    or None
                )
                evidence["industry_focus"] = {
                    "name": explicit_industry_topic,
                    "market_scope": "A股",
                    "requested_by_user": True,
                }
                evidence["industry_snapshot"] = analysis.industry_snapshot(
                    explicit_industry_topic,
                    market_date=target_market_date,
                )
            if evidence["market_drivers"].get("market_key") == "gold":
                try:
                    live_snapshot = live_markets.snapshot()
                    evidence["focused_live_market"] = next(
                        (
                            item
                            for item in live_snapshot.get("markets", [])
                            if item.get("key") == "london_gold"
                        ),
                        None,
                    )
                except Exception:
                    evidence["focused_live_market"] = None
        else:
            if symbol is None:
                if upload is None and _needs_research_object_clarification(
                    message, history
                ):
                    clarification = {
                        "run_id": None,
                        "status": "clarification",
                        "intent": "clarification",
                        "model_tier": model_tier,
                        "answer": (
                            "我还没识别到具体的研究对象。你可以直接说“中兴通讯为什么大跌”"
                            "“分析英伟达”或输入证券代码；询问整体行情时可以说“今天大盘怎么样”。"
                        ),
                        "evidence": {
                            "type": "clarification",
                            "generated_at": utc_now(),
                        },
                        "error": None,
                    }
                    return persist_response(
                        clarification,
                        assistant_content=clarification["answer"],
                        response_intent="clarification",
                    )
                if upload is not None:
                    intent = "visual_research"
                    evidence = {
                        "type": intent,
                        "generated_at": utc_now(),
                        "image": public_upload(upload),
                        "user_question": message,
                        "analysis_boundary": [
                            "只做定性图像观察，不把模糊的坐标、价格或百分比当作可验证事实。",
                            "不仅凭图片识别公司、时间或证券代码。",
                            "需要数值分析时，请用户补充证券代码并调用确定性行情工具。",
                        ],
                    }
                else:
                    intent = "general_research"
                    evidence = {
                        "type": intent,
                        "generated_at": utc_now(),
                        "knowledge_context": knowledge_context,
                        "research_capabilities": [
                            "连续对话上下文",
                            "已确认用户记忆",
                            "用户与通用资料库检索",
                            "金融研究工具",
                        ],
                    }
            else:
                intent = "stock_research"
                latest_report = (
                    research_reports.get_latest(symbol, generate_if_missing=False)
                    if payload.prefer_precomputed
                    else None
                )
                if latest_report is not None and latest_report.get("evidence"):
                    evidence = dict(latest_report["evidence"])
                    evidence["generated_at"] = utc_now()
                    evidence["precomputed_report"] = {
                        "title": latest_report.get("title"),
                        "generated_at": latest_report.get("generated_at"),
                        "market_timestamp": latest_report.get("market_timestamp"),
                    }
                    evidence.setdefault("warnings", []).append(
                        "当前研究使用服务器最新预生成证据。"
                    )
                else:
                    try:
                        evidence = research_evidence.build(user_id, symbol)
                    except ProviderError as exc:
                        latest_report = research_reports.get_latest(
                            symbol, generate_if_missing=False
                        )
                        if latest_report is None or not latest_report.get("evidence"):
                            raise HTTPException(
                                status_code=502, detail=str(exc)
                            ) from exc
                        evidence = dict(latest_report["evidence"])
                        evidence["generated_at"] = utc_now()
                        evidence["precomputed_report"] = {
                            "title": latest_report.get("title"),
                            "generated_at": latest_report.get("generated_at"),
                            "market_timestamp": latest_report.get("market_timestamp"),
                        }
                        evidence.setdefault("warnings", []).append(
                            "当前研究使用服务器最新预生成证据。"
                        )
                watchlist_item = database.get_watchlist_item(user_id, symbol)
                evidence["research_claims"] = build_research_claim_ledger(evidence)
                evidence["user_thesis"] = (
                    watchlist_item.get("thesis") if watchlist_item else None
                )
                evidence["confirmed_user_memories"] = [
                    {"kind": item["kind"], "content": item["content"]}
                    for item in database.list_memories(user_id, status="confirmed")
                ]
                if symbol.endswith((".SS", ".SZ")):
                    try:
                        candidate = li_zong_strategy.get_candidate(symbol)
                    except ValueError:
                        candidate = None
                    if candidate is not None:
                        evidence["li_zong_strategy"] = _public_li_zong_candidate(
                            candidate
                        )
                if symbol.endswith((".SS", ".SZ")):
                    valuation = (evidence.get("fundamentals") or {}).get(
                        "valuation"
                    ) or {}
                    if valuation.get("price") is not None and valuation.get(
                        "market_timestamp"
                    ):
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
                            market_quote_semantics(
                                "china", valuation.get("market_timestamp")
                            )
                        )
                    if _needs_stock_market_context(message):
                        try:
                            industry_name = str(
                                (evidence.get("analyst_expectations") or {}).get(
                                    "industry"
                                )
                                or ""
                            )
                            analysis_target = _stock_analysis_target(message, evidence)
                            evidence["stock_market_context"] = (
                                _build_stock_market_context(
                                    message,
                                    evidence,
                                    analysis.market_brief(market_key="china"),
                                    analysis.industry_snapshot(
                                        industry_name,
                                        market_date=analysis_target.get("market_date"),
                                    ),
                                )
                            )
                        except Exception as exc:
                            evidence.setdefault("warnings", []).append(
                                f"个股市场对照证据刷新未完成：{type(exc).__name__}"
                            )
                evidence["deep_stock_coverage"] = deep_stock.evidence_coverage_packet(
                    evidence,
                    intent="stock_research",
                )
                if _is_deep_stock_coverage_query(message):
                    tracking_packet = research_tracking.get_packet(
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

        evidence.setdefault("user_question", message)
        knowledge_context = _filter_knowledge_context(
            knowledge_context,
            intent=intent,
            symbol=symbol,
            evidence=evidence,
        )
        if knowledge_context.get("items") and "knowledge_context" not in evidence:
            evidence["knowledge_context"] = knowledge_context

        publish_agent_progress(
            "evidence_ready",
            "证据与资料已准备，AI 正在组织针对性回答…",
        )

        progress_labels = {
            "model_started": "证据与资料已准备，AI 正在生成回答…",
            "guard_started": "回答已生成，正在校验数字、来源与证据边界…",
            "fallback_started": "正在整理当前可确认的证据摘要…",
            "completed": "校验完成，正在保存回答与研究记录…",
        }

        def forward_agent_progress(update: dict[str, Any]) -> None:
            phase = str(update.get("phase") or "")
            label = progress_labels.get(phase)
            if label is None:
                return
            publish_agent_progress(
                phase,
                label,
                timings={key: value for key, value in update.items() if key != "phase"},
            )

        def forward_agent_stream(update: dict[str, Any]) -> None:
            if not payload.request_id or not payload.execute_agent:
                return
            event_type = str(update.get("type") or "")
            if event_type == "delta":
                agent_streams.publish(
                    payload.request_id,
                    user_id,
                    {
                        "type": "agent_delta",
                        "draft": str(update.get("draft") or ""),
                        "elapsed_seconds": update.get("elapsed_seconds"),
                        "event_index": update.get("event_index"),
                        "withheld_segments": update.get("withheld_segments", 0),
                        "is_unverified": update.get("is_unverified", True),
                        "is_final": update.get("is_final", False),
                    },
                )
            elif event_type == "reset":
                agent_streams.publish(
                    payload.request_id,
                    user_id,
                    {
                        "type": "agent_stream_status",
                        "label": str(
                            update.get("label")
                            or "实时生成连接已中断，正在恢复完整回答…"
                        ),
                    },
                )

        run = agent.run(
            user=user,
            intent=intent,
            message=message,
            evidence=evidence,
            model_tier=model_tier,
            execute_agent=payload.execute_agent,
            image_path=image_path,
            conversation_id=conversation_id,
            conversation_history=history,
            knowledge_context=knowledge_context,
            pre_run_timings={
                "routing_and_evidence_seconds": round(
                    time.perf_counter() - request_started, 3
                )
            },
            progress_callback=forward_agent_progress,
            stream_callback=(
                forward_agent_stream
                if payload.request_id and payload.execute_agent
                else None
            ),
        )
        structured_answer = None
        structured_answer_failed = False
        try:
            structured_answer = structured_ai.build_and_persist(
                user_id=user_id,
                run=run,
                evidence=evidence,
                answer=str(run.get("answer") or ""),
                message=message,
                conversation_id=conversation_id,
                symbol=symbol,
            )
        except Exception:
            # Structured cards and writeback candidates must never hide an
            # otherwise valid financial answer. The Run and evidence remain
            # available for diagnosis and a later retry.
            logger.exception(
                "Failed to persist structured AI answer for run %s",
                run.get("id"),
            )
            structured_answer_failed = True
            structured_answer = None
        if payload.request_id and payload.execute_agent and structured_answer:
            for citation in structured_answer.get("citations") or []:
                agent_streams.publish(
                    payload.request_id,
                    user_id,
                    {
                        "type": "agent_citation",
                        "citation": citation,
                    },
                )
            for candidate in structured_answer.get("candidate_writebacks") or []:
                agent_streams.publish(
                    payload.request_id,
                    user_id,
                    {
                        "type": "agent_writeback_candidate",
                        "candidate": candidate,
                    },
                )
            if structured_answer.get("status") != "complete":
                agent_streams.publish(
                    payload.request_id,
                    user_id,
                    {
                        "type": "agent_structured_partial",
                        "status": structured_answer.get("status"),
                    },
                )
        elif payload.request_id and payload.execute_agent and structured_answer_failed:
            agent_streams.publish(
                payload.request_id,
                user_id,
                {
                    "type": "agent_structured_failed",
                    "status": "failed",
                },
            )
        deep_stock_session = deep_stock.observe_chat(
            user_id=user_id,
            conversation_id=conversation_id,
            symbol=symbol,
            intent=intent,
            message=message,
            run=run,
            evidence=evidence,
        )
        captured_evidence_tasks = evidence_tasks.capture_from_chat(
            user_id=user_id,
            conversation_id=conversation_id,
            run_id=run["id"],
            intent=intent,
            message=message,
            evidence=evidence,
            symbol=symbol,
        )
        response_payload = {
            "run_id": run["id"],
            "status": run["status"],
            "intent": intent,
            "model_tier": model_tier,
            "answer": run["answer"],
            "evidence": evidence,
            "evidence_tasks": captured_evidence_tasks,
            "deep_stock_session": deep_stock_session,
            "structured_answer": structured_answer,
            "error": run["error"],
        }
        result = persist_response(
            response_payload,
            assistant_content=run["answer"],
            response_intent=intent,
            response_symbol=symbol,
            run_id=run["id"],
            evidence_payload=evidence,
            structured_answer=structured_answer,
        )
        if payload.request_id and payload.execute_agent:
            agent_streams.publish(
                payload.request_id,
                user_id,
                {
                    "type": "agent_stream_complete",
                    "status": run["status"],
                    "run_id": run["id"],
                },
            )
        return result

    @app.post("/me/chat")
    def my_chat(payload: ChatRequest, request: Request) -> dict[str, Any]:
        user = require_session_user(request)
        return chat(user["id"], payload, request)

    @app.post("/me/chat/refine")
    def refine_my_chat(payload: ChatRefineRequest, request: Request) -> dict[str, Any]:
        user = require_session_user(request)
        allowed_intents = {
            "market_brief",
            "stock_screen",
            "stock_research",
            "stock_comparison",
            "earnings_quality",
            "financial_drivers",
            "business_structure",
            "shareholder_structure",
            "analyst_expectations",
            "event_timeline",
            "research_tracking",
            "research_priority",
            "research_actions",
            "research_outcome",
            "watchlist_brief",
            "general_research",
        }
        conversation = database.get_conversation(user["id"], payload.conversation_id)
        if conversation is None or conversation.get("status") != "active":
            raise HTTPException(status_code=404, detail="研究对话不存在")
        preview_run = database.get_run(payload.preview_run_id, user["id"])
        if preview_run is None or preview_run.get("intent") not in allowed_intents:
            raise HTTPException(status_code=404, detail="待深化研究不存在")
        assistant_message = database.get_conversation_message(
            user["id"], payload.assistant_message_id
        )
        if (
            assistant_message is None
            or assistant_message.get("conversation_id") != payload.conversation_id
            or assistant_message.get("role") != "assistant"
        ):
            raise HTTPException(status_code=404, detail="待深化回答不存在")
        if assistant_message.get("run_id") != payload.preview_run_id:
            return {
                "status": "already_refined",
                "intent": assistant_message.get("intent"),
                "answer": assistant_message.get("content"),
                "conversation_id": payload.conversation_id,
                "assistant_message_id": payload.assistant_message_id,
                "run_id": assistant_message.get("run_id"),
                "structured_answer": (assistant_message.get("metadata") or {}).get(
                    "structured_answer"
                ),
            }

        evidence = preview_run.get("evidence") or {}
        input_data = preview_run.get("input") or {}
        message = str(input_data.get("message") or "").strip()
        if not message or not evidence:
            raise HTTPException(status_code=422, detail="待深化研究缺少可复用证据")
        history = database.list_conversation_messages(
            user["id"], payload.conversation_id, limit=80
        )
        preview_index = next(
            (
                index
                for index, item in enumerate(history)
                if item.get("id") == payload.assistant_message_id
            ),
            len(history),
        )
        conversation_history = history[:preview_index]
        knowledge_context = evidence.get("knowledge_context") or knowledge.retrieve(
            user["id"], message, max_results=5
        )
        refine_symbol = (
            evidence.get("symbol")
            or (evidence.get("item") or {}).get("symbol")
            or (assistant_message.get("metadata") or {}).get("symbol")
        )
        knowledge_context = _filter_knowledge_context(
            knowledge_context,
            intent=str(preview_run["intent"]),
            symbol=str(refine_symbol) if refine_symbol else None,
            evidence=evidence,
        )
        run = agent.run(
            user=user,
            intent=str(preview_run["intent"]),
            message=message,
            evidence=evidence,
            model_tier=payload.model_tier,
            execute_agent=True,
            conversation_id=payload.conversation_id,
            conversation_history=conversation_history,
            knowledge_context=knowledge_context,
        )
        if run.get("status") != "completed":
            return {
                "status": "kept_preview",
                "intent": preview_run.get("intent"),
                "answer": assistant_message.get("content"),
                "conversation_id": payload.conversation_id,
                "assistant_message_id": payload.assistant_message_id,
                "run_id": payload.preview_run_id,
            }

        evidence_tasks.capture_from_chat(
            user_id=user["id"],
            conversation_id=payload.conversation_id,
            run_id=run["id"],
            intent=str(preview_run["intent"]),
            message=message,
            evidence=evidence,
            symbol=str(refine_symbol) if refine_symbol else None,
        )
        deep_stock_session = deep_stock.observe_chat(
            user_id=user["id"],
            conversation_id=payload.conversation_id,
            symbol=str(refine_symbol) if refine_symbol else None,
            intent=str(preview_run["intent"]),
            message=message,
            run=run,
            evidence=evidence,
        )

        structured_answer = None
        try:
            structured_answer = structured_ai.build_and_persist(
                user_id=user["id"],
                run=run,
                evidence=evidence,
                answer=str(run.get("answer") or ""),
                message=message,
                conversation_id=payload.conversation_id,
                symbol=str(refine_symbol) if refine_symbol else None,
            )
        except Exception:
            logger.exception(
                "Failed to persist refined structured AI answer for run %s",
                run.get("id"),
            )

        metadata = {
            **(assistant_message.get("metadata") or {}),
            "model_tier": payload.model_tier,
            "refined": True,
            "structured_answer": structured_answer,
        }
        updated = database.update_assistant_conversation_message(
            user_id=user["id"],
            conversation_id=payload.conversation_id,
            message_id=payload.assistant_message_id,
            content=run["answer"],
            intent=str(preview_run["intent"]),
            run_id=run["id"],
            metadata=metadata,
        )
        if updated is None:
            raise HTTPException(status_code=409, detail="回答已发生变化，请刷新对话")
        try:
            conversation_quality.analyze(user["id"])
        except Exception:
            pass
        return {
            "status": "completed",
            "intent": preview_run.get("intent"),
            "answer": run["answer"],
            "conversation_id": payload.conversation_id,
            "assistant_message_id": payload.assistant_message_id,
            "run_id": run["id"],
            "deep_stock_session": deep_stock_session,
            "structured_answer": structured_answer,
        }

    @app.get("/runs/{run_id}")
    def get_run(
        run_id: str, request: Request, user_id: str = Query(min_length=1)
    ) -> dict[str, Any]:
        require_user(request, user_id)
        run = database.get_run(run_id, user_id)
        if run is None:
            raise HTTPException(status_code=404, detail="运行不存在或不属于该用户")
        return run

    @app.get("/me/runs/{run_id}")
    def get_my_run(run_id: str, request: Request) -> dict[str, Any]:
        user = require_session_user(request)
        run = database.get_run(run_id, user["id"])
        if run is None:
            raise HTTPException(status_code=404, detail="运行不存在或不属于当前用户")
        return run

    return app


def _public_run_review(
    run: dict[str, Any],
    *,
    conversation_title: str,
    include_answer: bool,
) -> dict[str, Any]:
    input_data = run.get("input") or {}
    evidence = run.get("evidence") or {}
    usage = run.get("usage") or {}
    timings = usage.get("timings") or {}
    streaming = usage.get("streaming") or {}
    output_guard = usage.get("output_guard") or {}
    repair = output_guard.get("repair") or {}

    repair_groups = {
        "numbers": repair.get("original_unsupported_numbers") or [],
        "market": repair.get("original_unsupported_market_inferences") or [],
        "internal": repair.get("original_private_operational_patterns") or [],
        "semantic": repair.get("original_semantic_conflicts") or [],
    }
    repaired = bool(repair) or any(repair_groups.values())
    repair_summary: list[str] = []
    if repair_groups["numbers"]:
        repair_summary.append(
            f"移除或改写 {len(repair_groups['numbers'])} 处无法由证据核验的数字"
        )
    if repair_groups["market"]:
        repair_summary.append(
            f"修正 {len(repair_groups['market'])} 处行情口径或数据时点表述"
        )
    if repair_groups["internal"]:
        repair_summary.append(
            f"移除 {len(repair_groups['internal'])} 处不应面向用户的运行措辞"
        )
    if repair_groups["semantic"]:
        repair_summary.append(f"修正 {len(repair_groups['semantic'])} 处证据与结论冲突")
    if repaired and not repair_summary:
        repair_summary.append("回答在展示前经过了守卫修复")
    if not repair_summary:
        repair_summary.append("未发现需要修复的数字、时点或内部措辞")

    current_quote = evidence.get("current_quote") or {}
    provenance = evidence.get("provenance") or {}
    knowledge_context = evidence.get("knowledge_context") or {}
    knowledge_coverage = knowledge_context.get("coverage") or {}
    information = evidence.get("a_share_information") or {}
    analysis_board = evidence.get("analysis_board") or {}
    modules = [
        {
            "label": str(item.get("label") or item.get("name") or "分析模块"),
            "evidence_count": int(item.get("evidence_count") or 0),
            "status": str(item.get("status") or "ready"),
        }
        for item in (analysis_board.get("modules") or [])
        if isinstance(item, dict)
    ]
    knowledge_items = [
        {
            "title": str(item.get("title") or "研究资料"),
            "scope": "个人资料" if item.get("scope") == "user" else "通用资料",
        }
        for item in (knowledge_context.get("items") or [])[:8]
        if isinstance(item, dict)
    ]

    duration_seconds: float | None = None
    if timings.get("request_total_seconds") is not None:
        try:
            duration_seconds = round(float(timings["request_total_seconds"]), 3)
        except (TypeError, ValueError):
            duration_seconds = None
    if duration_seconds is None:
        try:
            started = datetime.fromisoformat(str(run.get("created_at")))
            finished = datetime.fromisoformat(str(run.get("finished_at")))
            duration_seconds = round(max(0.0, (finished - started).total_seconds()), 3)
        except (TypeError, ValueError):
            duration_seconds = None

    status = str(run.get("status") or "unknown")
    if status == "guarded" and not repaired:
        repair_summary = ["模型原始回答未满足展示条件，系统改用已验证证据生成回退回答"]
    elif status == "degraded" and not repaired:
        repair_summary = ["模型综合未完整完成，系统保留并展示了可验证的证据回答"]
    elif status == "failed" and not repaired:
        repair_summary = ["本轮未形成可展示回答，证据和运行记录已保留供后续复盘"]
    guard_label = (
        "守卫修复"
        if repaired
        else {
            "guarded": "守卫回退",
            "degraded": "降级完成",
            "failed": "未完成",
        }.get(status, "守卫通过")
    )
    status_labels = {
        "completed": "已完成",
        "guarded": "守卫回退",
        "degraded": "降级完成",
        "failed": "未完成",
    }
    intent = str(run.get("intent") or "general_research")
    intent_labels = {
        "market_brief": "大盘诊断",
        "stock_screen": "选股研究",
        "stock_research": "个股研究",
        "earnings_quality": "财报质量",
        "financial_drivers": "利润与现金流",
        "shareholder_structure": "股东结构",
        "analyst_expectations": "分析师预期",
        "event_timeline": "事件脉络",
        "research_tracking": "研究变化",
        "research_priority": "研究优先级",
        "research_actions": "研究行动",
        "research_outcome": "研究复盘",
        "watchlist_brief": "自选股跟踪",
        "general_research": "综合研究",
    }
    item: dict[str, Any] = {
        "id": str(run.get("id") or ""),
        "conversation_id": str(input_data.get("conversation_id") or ""),
        "conversation_title": conversation_title,
        "question": str(
            input_data.get("message") or evidence.get("user_question") or "研究问题"
        ),
        "intent": intent,
        "intent_label": intent_labels.get(intent, "综合研究"),
        "status": status,
        "status_label": status_labels.get(status, status),
        "symbol": str(evidence.get("symbol") or input_data.get("symbol") or ""),
        "display_name": str(
            evidence.get("display_name") or current_quote.get("name") or "市场研究"
        ),
        "model_tier": str(run.get("model_tier") or "economy"),
        "model_state": (
            "AI 已完成综合"
            if usage.get("model") or usage.get("provider")
            else "确定性分析已完成"
        ),
        "created_at": run.get("created_at"),
        "finished_at": run.get("finished_at"),
        "duration_seconds": duration_seconds,
        "data_as_of": (
            current_quote.get("market_timestamp")
            or provenance.get("market_timestamp")
            or evidence.get("generated_at")
        ),
        "timings": {
            "evidence_seconds": timings.get("routing_and_evidence_seconds"),
            "first_token_seconds": timings.get("first_token_seconds")
            or streaming.get("first_token_seconds"),
            "first_visible_seconds": timings.get("first_visible_seconds")
            or streaming.get("first_visible_seconds"),
            "model_seconds": timings.get("model_seconds"),
            "guard_seconds": timings.get("guard_seconds"),
            "total_seconds": duration_seconds,
        },
        "guard": {
            "passed": status == "completed" and bool(output_guard.get("passed", True)),
            "repaired": repaired,
            "label": guard_label,
            "summary": repair_summary,
        },
        "quote": {
            "price": current_quote.get("price"),
            "currency": current_quote.get("currency"),
            "pct_change": current_quote.get("pct_change"),
            "market_timestamp": current_quote.get("market_timestamp"),
            "daily_close": (evidence.get("metrics") or {}).get("latest_close"),
            "daily_timestamp": provenance.get("market_timestamp"),
        },
        "evidence": {
            "modules": modules,
            "ready_modules": int(analysis_board.get("ready_modules") or 0),
            "total_modules": int(analysis_board.get("total_modules") or len(modules)),
            "knowledge_documents": int(
                knowledge_coverage.get("matched_documents") or len(knowledge_items)
            ),
            "knowledge_items": knowledge_items,
            "announcements": len(information.get("announcements") or []),
            "news": len(information.get("news") or []),
            "social_posts": len(information.get("social_posts") or []),
            "warnings": len(evidence.get("warnings") or []),
            "market_source": str(
                current_quote.get("source") or provenance.get("source") or ""
            ),
        },
        "answer_excerpt": str(run.get("answer") or "")[:220],
    }
    if include_answer:
        item["answer"] = str(run.get("answer") or "")
    return item


def _extract_symbol(
    explicit: str | None,
    message: str,
    watchlist: list[dict[str, Any]] | None = None,
) -> str | None:
    symbols = _extract_symbols(explicit, message, watchlist=watchlist)
    return symbols[0] if symbols else None


def _extract_symbols(
    explicit: str | None,
    message: str,
    watchlist: list[dict[str, Any]] | None = None,
) -> list[str]:
    candidates: list[tuple[int, int, str]] = []
    if explicit:
        try:
            candidates.append((-1, 0, normalize_symbol(explicit)))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    for match in re.finditer(r"(?<!\d)(\d{6})(?!\d)", message):
        candidates.append((match.start(), 0, normalize_symbol(match.group(1))))
    aliases = dict(SECURITY_NAME_ALIASES)
    aliases.update(
        {
            str(target.get("name") or "").strip(): symbol
            for symbol, target in RESEARCH_TARGETS.items()
            if str(target.get("name") or "").strip()
        }
    )
    for item in watchlist or []:
        name = str(item.get("name") or "").strip()
        symbol = str(item.get("symbol") or "").strip()
        if name and symbol:
            aliases[name] = symbol
    folded_message = message.casefold()
    for alias, symbol in sorted(
        aliases.items(), key=lambda item: len(item[0]), reverse=True
    ):
        folded_alias = alias.casefold()
        if not folded_alias:
            continue
        start = 0
        while True:
            index = folded_message.find(folded_alias, start)
            if index < 0:
                break
            candidates.append((index, -len(alias), normalize_symbol(symbol)))
            start = index + max(1, len(folded_alias))
    ticker_pattern = re.compile(
        r"(?<![A-Z0-9])([A-Z]{1,5}(?:[.=-][A-Z0-9]{1,5})?)(?![A-Z0-9])"
    )
    for ticker in ticker_pattern.finditer(message):
        # T+3/T+5/T+10 are research horizons, not the NYSE ticker T.  Resolve
        # natural-language company aliases first, then skip every horizon-like
        # token while continuing to search for a real ticker later in the text.
        suffix = message[ticker.end(1) :]
        if re.match(r"\s*\+\s*\d+", suffix):
            continue
        if ticker.group(1).upper() in {
            "PE",
            "PB",
            "PS",
            "ROE",
            "ROA",
            "EPS",
            "TTM",
            "SZ",
            "SS",
            "SH",
        }:
            continue
        if not _is_market_ticker_reference(ticker.group(1), message):
            candidates.append(
                (ticker.start(1), 0, normalize_symbol(ticker.group(1)))
            )
    output: list[str] = []
    for _, _, symbol in sorted(candidates, key=lambda item: (item[0], item[1])):
        if symbol not in output:
            output.append(symbol)
    return output


def _is_stock_screen_query(message: str) -> bool:
    folded = re.sub(r"\s+", "", message).casefold()
    direct_terms = (
        "筛选股票",
        "筛股票",
        "研究候选",
        "候选股票",
        "股票候选",
        "低估值股票",
        "业绩增长股票",
        "趋势增强股票",
        "回撤企稳股票",
    )
    if re.search(r"(?<!自)选股", folded) or any(
        term in folded for term in direct_terms
    ):
        return True
    return bool(
        re.search(
            r"(?:找|挑|筛|选)(?:一些|几只|一批)?[^。；，,]{0,12}(?:股票|公司)", folded
        )
    )


def _stock_screen_parameters(message: str) -> dict[str, Any]:
    folded = re.sub(r"\s+", "", message).casefold()
    if any(term in folded for term in ("回撤", "超跌", "企稳", "跌下来")):
        profile = "pullback"
    elif any(
        term in folded for term in ("趋势", "强势", "跑赢行业", "相对行业", "动量")
    ):
        profile = "trend"
    elif any(
        term in folded
        for term in ("低估值", "估值低", "价值", "市盈率", "市净率", "pe", "pb")
    ):
        profile = "value"
    else:
        profile = "quality"

    market = "all"
    if "科创板" in folded:
        market = "star"
    elif "创业板" in folded:
        market = "gem"
    elif "北交所" in folded or "北证" in folded:
        market = "bj"
    elif "沪市" in folded or "上交所" in folded:
        market = "sh"
    elif "深市" in folded or "深交所" in folded:
        market = "sz"
    elif "主板" in folded:
        market = "main"

    count_match = re.search(r"(?:前|最多|给我|找|选|筛)?(\d{1,2})只", folded)
    max_results = min(30, max(1, int(count_match.group(1)))) if count_match else 12
    filters: dict[str, Any] = {}

    def number(pattern: str) -> float | None:
        match = re.search(pattern, folded, re.IGNORECASE)
        return float(match.group(1)) if match else None

    patterns = {
        "max_pe_ttm": r"(?:pe|市盈率)(?:ttm)?(?:低于|小于|不高于|不超过|≤|<=|<)?(\d+(?:\.\d+)?)倍?(?:以下)?",
        "max_pb": r"(?:pb|市净率)(?:低于|小于|不高于|不超过|≤|<=|<)?(\d+(?:\.\d+)?)倍?(?:以下)?",
        "min_roe": r"roe(?:高于|大于|不低于|至少|超过|≥|>=|>)?(\d+(?:\.\d+)?)%?",
        "min_revenue_yoy": r"(?:营收|营业收入)(?:同比)?(?:增长|增速)?(?:高于|大于|不低于|至少|超过|≥|>=|>)?(\d+(?:\.\d+)?)%",
        "min_net_profit_yoy": r"(?:净利润|归母净利润)(?:同比)?(?:增长|增速)?(?:高于|大于|不低于|至少|超过|≥|>=|>)?(\d+(?:\.\d+)?)%",
    }
    for key, pattern in patterns.items():
        value = number(pattern)
        if value is not None:
            filters[key] = value

    market_cap_match = re.search(
        r"(?:总)?市值(?:在)?(\d+(?:\.\d+)?)(?:亿|亿元)(?:以上|起|到(\d+(?:\.\d+)?)(?:亿|亿元))?",
        folded,
    )
    if market_cap_match:
        filters["min_market_cap_yi"] = float(market_cap_match.group(1))
        if market_cap_match.group(2):
            filters["max_market_cap_yi"] = float(market_cap_match.group(2))
    else:
        minimum_cap = number(
            r"(?:总)?市值(?:高于|大于|不低于|至少|超过|≥|>=|>)(\d+(?:\.\d+)?)(?:亿|亿元)"
        )
        maximum_cap = number(
            r"(?:总)?市值(?:低于|小于|不高于|不超过|≤|<=|<)(\d+(?:\.\d+)?)(?:亿|亿元)"
        )
        if minimum_cap is not None:
            filters["min_market_cap_yi"] = minimum_cap
        if maximum_cap is not None:
            filters["max_market_cap_yi"] = maximum_cap

    industry_match = re.search(
        r"([\u4e00-\u9fff]{2,10})(?:行业|板块)(?:里|内|中的|的)?(?:股票|公司)",
        folded,
    )
    if industry_match:
        industry = industry_match.group(1)
        industry = re.sub(r"^(?:帮我|请|找|筛选|筛|选|一些)", "", industry)
        if industry:
            filters["industry"] = industry

    return {
        "profile": profile,
        "market": market,
        "max_results": max_results,
        "filters": filters or None,
    }


def _is_market_query(message: str) -> bool:
    folded = re.sub(r"\s+", "", message).casefold()
    market_terms = (
        "大盘",
        "市场",
        "板块",
        "行业",
        "指数",
        "行情",
        "美股",
        "a股",
        "港股",
        "日股",
        "日本股市",
        "韩股",
        "韩国股市",
        "欧股",
        "欧洲股市",
        "伦敦金",
        "现货黄金",
        "黄金",
        "标普",
        "s&p",
        "纳指",
        "纳斯达克",
        "道指",
        "道琼斯",
        "上证",
        "深证",
        "创业板",
        "沪深300",
        "中证500",
        "恒生",
        "日经",
        "kospi",
        "vix",
        "dax",
    )
    # Trading-session words describe a time state, not a research object.
    # Treating “盘中/收盘” alone as an explicit market request used to switch
    # stock follow-ups such as “现在仍在盘中吗” from the current company to the
    # default A-share market.  Explicit market routing therefore requires an
    # actual market, index, sector, or asset-class reference.
    return any(term in folded for term in market_terms)


def _extract_industry_topic(message: str) -> str | None:
    folded = re.sub(r"\s+", "", str(message or ""))
    match = re.search(
        r"(?P<topic>[A-Za-z0-9\u4e00-\u9fff]{2,18}?)(?:行业|板块)",
        folded,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    topic = match.group("topic")
    topic = re.sub(
        r"^(?:请|帮我|麻烦|我想|我想看|我想了解|看看|看下|分析|研究|聊聊|说说|"
        r"当前|今天|最近|目前|A股|a股)+",
        "",
        topic,
        flags=re.IGNORECASE,
    )
    topic = topic.strip("，。！？,.!?：:")
    if topic in {"这个", "该", "什么", "哪个", "整体", "当前", "最近"}:
        return None
    return topic or None


def _market_question_focus(message: str) -> dict[str, Any]:
    folded = re.sub(r"\s+", "", message).casefold()
    counter_evidence_terms = ("反方", "反证", "相反证据")
    focus_rules = (
        (
            "market_risk",
            "市场风险与失效条件",
            (
                "风险",
                "回撤",
                "危险",
                "担心",
                "失效",
                "承压",
                "不成立",
                "推翻",
                "证据缺口",
            ),
            [
                "优先比较回撤、波动、趋势和关键均线位置",
                "说明风险已经发生的证据与仍未发生的情形",
                "不生成仓位或买卖指令",
            ],
        ),
        (
            "trend_reversal",
            "反弹与趋势确认",
            ("反弹", "反转", "企稳", "见底", "趋势", "牛市", "修复"),
            [
                "区分单日反弹、短期修复和中期趋势反转",
                "优先比较1日、5日、20日收益及均线位置",
                "给出尚未满足的确认条件和反方证据",
            ],
        ),
        (
            "sector_rotation",
            "板块轮动与市场广度",
            (
                "板块",
                "行业",
                "热点",
                "题材",
                "领涨",
                "领跌",
                "轮动",
                "普涨",
                "结构性",
                "市场广度",
                "上涨下跌家数",
                "涨跌幅分布",
            ),
            [
                "优先回答热门板块、上涨广度和结构分化",
                "区分指数上涨与少数板块拉动",
                "板块涨幅不外推为持续性或交易信号",
            ],
        ),
        (
            "volume_flows",
            "量能与资金线索",
            ("成交量", "成交额", "放量", "缩量", "量能", "资金", "北向", "etf"),
            [
                "优先解释指数5/20日量比和已取得的资金类资讯",
                "资金字段只能作为观察线索，不能写成已证明动机",
                "缺少北向或全市场成交额时明确指出缺口",
            ],
        ),
        (
            "market_cause",
            "涨跌原因与驱动证据",
            ("为什么", "原因", "驱动", "利好", "利空", "怎么回事"),
            [
                "优先组合价格事实与多条市场资讯",
                "区分反复出现的解释、单一线索和反方证据",
                "不能把相关性包装成唯一因果",
            ],
        ),
    )
    for key, label, terms, requirements in focus_rules:
        if any(term in folded for term in terms):
            return {
                "key": key,
                "label": label,
                "answer_requirements": requirements,
            }
    if any(term in folded for term in counter_evidence_terms):
        return {
            "key": "market_risk",
            "label": "市场风险与失效条件",
            "answer_requirements": [
                "优先比较回撤、波动、趋势和关键均线位置",
                "说明风险已经发生的证据与仍未发生的情形",
                "不生成仓位或买卖指令",
            ],
        }
    return {
        "key": "market_overview",
        "label": "市场全景",
        "answer_requirements": [
            "先回答当前市场状态，再给指数、板块与风险证据",
            "优先回应用户明确提到的市场",
            "不预测下一交易日方向",
        ],
    }


def _needs_stock_market_context(message: str) -> bool:
    folded = re.sub(r"\s+", "", message).casefold()
    return any(
        term in folded
        for term in (
            "为什么",
            "原因",
            "驱动",
            "怎么回事",
            "上涨",
            "下跌",
            "大涨",
            "大跌",
            "收涨",
            "收跌",
            "市场拖累",
            "大盘拖累",
            "板块拖累",
            "行业拖累",
            "跟涨",
            "跟跌",
            "逆势",
        )
    )


def _market_date(value: Any, timezone_name: str = "Asia/Shanghai") -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ZoneInfo(timezone_name))
        return parsed.astimezone(ZoneInfo(timezone_name)).date().isoformat()
    except (TypeError, ValueError):
        match = re.search(r"20\d{2}-\d{2}-\d{2}", str(value))
        return match.group(0) if match else None


def _question_price_direction(message: str) -> int:
    folded = re.sub(r"\s+", "", message).casefold()
    explicit_down = any(
        term in folded
        for term in (
            "为什么跌",
            "为何跌",
            "下跌原因",
            "大跌原因",
            "跌了怎么回事",
            "下跌怎么回事",
        )
    )
    explicit_up = any(
        term in folded
        for term in (
            "为什么涨",
            "为何涨",
            "上涨原因",
            "大涨原因",
            "涨了怎么回事",
            "上涨怎么回事",
        )
    )
    if explicit_down and not explicit_up:
        return -1
    if explicit_up and not explicit_down:
        return 1
    down = any(
        term in folded
        for term in ("下跌", "大跌", "收跌", "跌了", "走弱", "为什么跌", "为何跌")
    )
    up = any(
        term in folded
        for term in ("上涨", "大涨", "收涨", "涨了", "走强", "为什么涨", "为何涨")
    )
    if down and not up:
        return -1
    if up and not down:
        return 1
    return 0


def _question_market_date(
    message: str, reference_market_date: str | None
) -> str | None:
    iso_match = re.search(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})日?", message)
    month_day_match = re.search(r"(?<!\d)(\d{1,2})月(\d{1,2})日", message)
    year = None
    month = None
    day = None
    if iso_match:
        year, month, day = (int(value) for value in iso_match.groups())
    elif month_day_match:
        month, day = (int(value) for value in month_day_match.groups())
        reference_year = re.match(r"(20\d{2})", str(reference_market_date or ""))
        year = (
            int(reference_year.group(1))
            if reference_year
            else datetime.now(ZoneInfo("Asia/Shanghai")).year
        )
    if year is None or month is None or day is None:
        return None
    try:
        return datetime(year, month, day).date().isoformat()
    except ValueError:
        return None


def _stock_analysis_target(message: str, evidence: dict[str, Any]) -> dict[str, Any]:
    current_quote = evidence.get("current_quote") or {}
    metrics = evidence.get("metrics") or {}
    history_market_date = _market_date(
        (evidence.get("provenance") or {}).get("market_timestamp")
    )
    current_quote_date = _market_date(current_quote.get("market_timestamp"))
    question_direction = _question_price_direction(message)
    quote_change = current_quote.get("pct_change")
    history_change = metrics.get("return_1d_pct")
    quote_direction = (
        1
        if isinstance(quote_change, (int, float)) and quote_change > 0
        else -1
        if isinstance(quote_change, (int, float)) and quote_change < 0
        else 0
    )
    history_direction = (
        1
        if isinstance(history_change, (int, float)) and history_change > 0
        else -1
        if isinstance(history_change, (int, float)) and history_change < 0
        else 0
    )
    explicit_market_date = _question_market_date(
        message, current_quote_date or history_market_date
    )
    if explicit_market_date:
        return {
            "market_date": explicit_market_date,
            "basis": "explicit_question_date",
            "question_direction": question_direction,
            "current_quote_market_date": current_quote_date,
            "history_market_date": history_market_date,
        }
    target_market_date = current_quote_date or history_market_date
    target_basis = "current_quote"
    if (
        question_direction
        and quote_direction
        and question_direction != quote_direction
        and question_direction == history_direction
        and history_market_date
    ):
        target_market_date = history_market_date
        target_basis = "last_complete_daily_bar"
    return {
        "market_date": target_market_date,
        "basis": target_basis,
        "question_direction": question_direction,
        "current_quote_market_date": current_quote_date,
        "history_market_date": history_market_date,
    }


def _build_stock_market_context(
    message: str,
    evidence: dict[str, Any],
    market_brief: dict[str, Any],
    industry_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    company_industry = str(
        (evidence.get("analyst_expectations") or {}).get("industry") or ""
    ).strip()
    current_quote = evidence.get("current_quote") or {}
    metrics = evidence.get("metrics") or {}
    target = _stock_analysis_target(message, evidence)
    target_market_date = target["market_date"]
    target_basis = target["basis"]
    quote_change = current_quote.get("pct_change")
    history_change = metrics.get("return_1d_pct")
    stock_recent_bars = list(evidence.get("recent_bars") or [])
    stock_target_index = next(
        (
            index
            for index, bar in enumerate(stock_recent_bars)
            if _market_date(bar.get("timestamp")) == target_market_date
        ),
        None,
    )
    stock_target_bar = (
        stock_recent_bars[stock_target_index]
        if stock_target_index is not None
        else None
    )
    intraday_quote_target = bool(
        target_basis == "current_quote"
        and current_quote
        and stock_target_bar is None
        and target_market_date
        and target_market_date != target.get("history_market_date")
    )
    quote_basis = str(current_quote.get("quote_basis") or "")
    quote_is_post_close = quote_basis == "post_close_snapshot"
    incomplete_daily_boundary = (
        "市场已经收盘，收盘后最新报价已取得，但当天完整日线尚未入库；"
        if quote_is_post_close
        else "当前只有个股盘中最新报价，当天完整日线尚未形成；"
    )
    stock_target_return_from_bars = None
    stock_previous_bar = None
    expected_previous_market_date = previous_market_session_date(
        "china", target_market_date
    )
    if stock_target_index is not None and stock_target_index > 0:
        stock_previous_bar = stock_recent_bars[stock_target_index - 1]
        stock_previous_close = stock_previous_bar.get("close")
        stock_current_close = (
            stock_target_bar.get("close") if stock_target_bar else None
        )
        stock_previous_date = _market_date(stock_previous_bar.get("timestamp"))
        if (
            stock_previous_date == expected_previous_market_date
            and isinstance(stock_previous_close, (int, float))
            and isinstance(stock_current_close, (int, float))
            and stock_previous_close
        ):
            stock_target_return_from_bars = round(
                (float(stock_current_close) / float(stock_previous_close) - 1) * 100,
                4,
            )

    hot_sectors = market_brief.get("hot_sectors") or {}
    sectors = list(hot_sectors.get("sectors") or [])[:10]
    sector_market_date = _market_date(hot_sectors.get("market_timestamp"))
    exact_industry_matches = [
        item
        for item in sectors
        if company_industry and str(item.get("name") or "").strip() == company_industry
    ]
    industry_snapshot = industry_snapshot or {}
    industry_point = next(
        (
            point
            for point in (industry_snapshot.get("points") or [])
            if str(point.get("market_date") or "") == target_market_date
        ),
        None,
    )
    official_industry_match = bool(
        not intraday_quote_target
        and company_industry
        and industry_snapshot.get("status") == "available"
        and str(industry_snapshot.get("industry_name") or "").strip()
        == company_industry
        and industry_point
    )
    subject_constituent = next(
        (
            item
            for item in (industry_snapshot.get("constituents") or [])
            if item.get("symbol") == evidence.get("symbol")
        ),
        None,
    )
    stock_target_return = (
        stock_target_return_from_bars
        if stock_target_return_from_bars is not None
        else quote_change
        if target_basis == "current_quote"
        else None
        if stock_target_bar is not None
        else history_change
    )
    industry_return = (
        None
        if intraday_quote_target
        else industry_point.get("pct_change")
        if industry_point
        else None
    )
    stock_minus_industry = None
    if isinstance(stock_target_return, (int, float)) and isinstance(
        industry_return, (int, float)
    ):
        stock_minus_industry = round(
            float(stock_target_return) - float(industry_return), 4
        )
    component_analysis = industry_snapshot.get("component_analysis") or {}
    component_same_date = bool(
        target_market_date
        and component_analysis.get("market_date") == target_market_date
    )
    component_breadth = (
        {}
        if intraday_quote_target
        else dict(component_analysis.get("breadth") or {})
        if component_same_date
        else {}
    )
    if intraday_quote_target:
        component_breadth = {
            "status": "intraday_not_supported",
            "market_date": target_market_date,
            "boundary": (
                incomplete_daily_boundary + "行业成分的同日完整日线尚未形成；"
                "不能用少量先返回的日线样本判断行业普涨、普跌或参与面。"
            ),
        }
    elif not component_breadth:
        component_breadth = {
            "status": "unavailable_for_target_date",
            "market_date": target_market_date,
            "boundary": (
                "已取得官方样本名单，但尚未取得目标交易日全部成分股涨跌家数。"
            ),
        }
    elif component_same_date:
        component_breadth["coverage"] = dict(component_analysis.get("coverage") or {})
        component_breadth["failures"] = list(component_analysis.get("failures") or [])
        component_breadth["source_fallbacks"] = [
            {
                "symbol": item.get("symbol"),
                "name": item.get("name"),
                "public_source_label": "新浪公开日线",
                "adjustment": item.get("adjustment"),
                "fallback_reason": item.get("fallback_reason"),
            }
            for item in (component_analysis.get("components") or [])
            if item.get("adjustment") == "unadjusted"
        ]
        component_breadth["boundary"] = component_analysis.get("boundary")
    for ratio_key in ("advance_ratio", "decline_ratio"):
        ratio_value = component_breadth.get(ratio_key)
        if isinstance(ratio_value, (int, float)):
            component_breadth[f"{ratio_key}_pct"] = round(float(ratio_value) * 100, 2)
    component_contribution = (
        {
            "status": "intraday_not_supported",
            "market_date": target_market_date,
            "boundary": (
                f"{current_quote.get('quote_label') or '最新报价'}不能与尚未形成的行业完整日线"
                "做静态成分贡献归因。"
            ),
        }
        if intraday_quote_target
        else dict(component_analysis.get("contribution") or {})
        if component_same_date
        else {}
    )
    component_rows = (
        list(component_analysis.get("components") or [])
        if component_same_date and not intraday_quote_target
        else []
    )
    subject_component = next(
        (
            item
            for item in component_rows
            if item.get("symbol") == evidence.get("symbol")
        ),
        None,
    )
    indices = []
    for item in market_brief.get("indices") or []:
        recent_bars = list(item.get("recent_bars") or [])
        matching_index = next(
            (
                index
                for index, bar in enumerate(recent_bars)
                if _market_date(bar.get("timestamp")) == target_market_date
            ),
            None,
        )
        comparison_bar = (
            recent_bars[matching_index] if matching_index is not None else None
        )
        comparison_return = None
        comparison_has_adjacent_session = False
        if matching_index is not None and matching_index > 0:
            previous_close = recent_bars[matching_index - 1].get("close")
            previous_market_date = _market_date(
                recent_bars[matching_index - 1].get("timestamp")
            )
            current_close = comparison_bar.get("close") if comparison_bar else None
            comparison_has_adjacent_session = (
                previous_market_date == expected_previous_market_date
            )
            if (
                comparison_has_adjacent_session
                and isinstance(previous_close, (int, float))
                and isinstance(current_close, (int, float))
                and previous_close
            ):
                comparison_return = round(
                    (float(current_close) / float(previous_close) - 1) * 100,
                    4,
                )
        stock_minus_index = None
        if isinstance(stock_target_return, (int, float)) and isinstance(
            comparison_return, (int, float)
        ):
            stock_minus_index = round(
                float(stock_target_return) - float(comparison_return), 4
            )
        indices.append(
            {
                "symbol": item.get("symbol"),
                "name": item.get("name"),
                "status": item.get("status"),
                "comparison_status": (
                    "same_market_date"
                    if comparison_bar and comparison_has_adjacent_session
                    else "missing_previous_session"
                    if comparison_bar
                    else "unavailable_for_target_date"
                ),
                "market_date": target_market_date if comparison_bar else None,
                "close": comparison_bar.get("close") if comparison_bar else None,
                "return_1d_pct": comparison_return,
                "stock_minus_index_pct": stock_minus_index,
            }
        )
    available_index_returns = [
        item["return_1d_pct"]
        for item in indices
        if isinstance(item.get("return_1d_pct"), (int, float))
    ]
    index_advancers = sum(value > 0 for value in available_index_returns)
    index_decliners = sum(value < 0 for value in available_index_returns)
    breadth_packet = market_brief.get("market_breadth") or {}
    breadth_market_date = str(breadth_packet.get("market_date") or "") or None
    breadth_same_date = bool(
        target_market_date
        and breadth_market_date
        and target_market_date == breadth_market_date
    )
    return {
        "type": "stock_market_context",
        "generated_at": market_brief.get("generated_at"),
        "market_key": "china",
        "analysis_target": {
            **target,
        },
        "stock_target": {
            "status": (
                "same_market_date"
                if stock_target_bar is not None
                else "current_quote"
                if target_basis == "current_quote" and current_quote
                else "unavailable_for_target_date"
            ),
            "market_date": target_market_date,
            "previous_market_date": (
                _market_date(stock_previous_bar.get("timestamp"))
                if stock_previous_bar
                else None
            ),
            "previous_close": (
                stock_previous_bar.get("close") if stock_previous_bar else None
            ),
            "close": (
                stock_target_bar.get("close")
                if stock_target_bar is not None
                else current_quote.get("price")
                if target_basis == "current_quote"
                else metrics.get("latest_close")
            ),
            "return_1d_pct": stock_target_return,
            "price_label": (
                current_quote.get("quote_label") or "盘中/最新报价快照"
                if intraday_quote_target
                else "完整日线收盘"
            ),
            "is_complete_daily_close": stock_target_bar is not None,
            "quote_timestamp": (
                current_quote.get("market_timestamp") if intraday_quote_target else None
            ),
            "source": (
                (evidence.get("provenance") or {}).get("source")
                if stock_target_bar is not None
                else current_quote.get("source")
            ),
        },
        "company_industry": company_industry or None,
        "exact_industry_match_available": official_industry_match
        or (bool(exact_industry_matches) and sector_market_date == target_market_date),
        "exact_industry_matches": exact_industry_matches,
        "exact_industry_index": {
            "status": (
                "intraday_not_supported"
                if intraday_quote_target
                else "same_market_date"
                if official_industry_match
                else "unavailable_for_target_date"
            ),
            "index_code": industry_snapshot.get("index_code"),
            "name": industry_snapshot.get("index_name"),
            "full_name": industry_snapshot.get("index_full_name"),
            "description": industry_snapshot.get("index_description"),
            "market_date": target_market_date if official_industry_match else None,
            "close": industry_point.get("close") if industry_point else None,
            "return_1d_pct": industry_return,
            "stock_return_1d_pct": stock_target_return,
            "stock_minus_industry_pct": stock_minus_industry,
            "constituent_count": (industry_snapshot.get("coverage") or {}).get(
                "constituents"
            ),
            "constituents_as_of": industry_snapshot.get("constituents_as_of"),
            "weights_as_of": industry_snapshot.get("weights_as_of"),
            "subject_is_constituent": subject_constituent is not None,
            "subject_weight_pct": (
                subject_constituent.get("weight_pct") if subject_constituent else None
            ),
            "industry_mapping": industry_snapshot.get("industry_mapping") or {},
            "component_breadth": component_breadth,
            "component_contribution": {
                **component_contribution,
                "subject": subject_component,
            },
            "source_url": industry_snapshot.get("source_url"),
            "constituent_source_url": industry_snapshot.get("constituent_source_url"),
        },
        "market_state": {
            "market_date": target_market_date,
            "available_indices": len(available_index_returns),
            "advancing_indices": index_advancers,
            "declining_indices": index_decliners,
            "summary": (
                f"同日可比的 {len(available_index_returns)} 个代表性指数中，"
                f"{index_advancers} 个上涨、{index_decliners} 个下跌。"
                if available_index_returns
                else "目标交易日的代表性指数对照仍待补证。"
            ),
        },
        "indices": indices,
        "hot_sectors": {
            "source": hot_sectors.get("source"),
            "market_timestamp": hot_sectors.get("market_timestamp"),
            "market_date": sector_market_date,
            "same_date_as_target": sector_market_date == target_market_date,
            "fetched_at": hot_sectors.get("fetched_at"),
            "status": hot_sectors.get("status"),
            "coverage": hot_sectors.get("coverage") or {},
            "sectors": sectors,
        },
        "market_breadth": {
            "status": breadth_packet.get("status"),
            "market_date": breadth_packet.get("market_date"),
            "same_date_as_target": breadth_same_date,
            "latest_tick_time": breadth_packet.get("latest_tick_time"),
            "coverage": breadth_packet.get("coverage") or {},
            "breadth": breadth_packet.get("breadth") or {},
            "turnover": breadth_packet.get("turnover") or {},
            "distribution": breadth_packet.get("distribution") or {},
        },
        "boundary": (
            "只能使用与 analysis_target.market_date 相同日期的代表性指数、全市场广度和板块"
            "快照判断系统性或行业拖累；跨日期证据只能说明另一个交易日的市场环境，不能拿来"
            "解释目标日涨跌。只有板块名称与公司行业精确匹配且日期一致时，才可把热门板块榜"
            "称为该公司的行业证据。经明确映射取得的中证指数必须同时展示分类映射口径；"
            "成分广度覆盖完整时才可描述行业普涨、普跌或参与面。成分贡献度是按官方权重快照"
            "与目标日复权涨跌幅做的静态估算，不是中证官方逐日归因。没有精确匹配时必须说明"
            "行业指数与成分口径仍待补证。"
        ),
    }


def _filter_knowledge_context(
    context: dict[str, Any],
    *,
    intent: str,
    symbol: str | None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    items = list(context.get("items") or [])
    if intent == "market_brief":
        stock_research_prefixes = (
            "research-report:",
            "earnings-quality:",
            "financial-drivers:",
            "business-structure:",
            "shareholder-structure:",
            "analyst-expectations:",
            "event-timeline:",
            "filing-evidence:",
            "research-outcome:",
        )
        items = [
            item
            for item in items
            if (
                item.get("scope") == "user"
                and not str(item.get("source_key") or "").startswith(
                    stock_research_prefixes
                )
            )
            or str(item.get("source_key") or "")
            in {
                "builtin:evidence-hierarchy.md",
                "builtin:market-causality.md",
                "builtin:market-trend-risk.md",
            }
            or str(item.get("source_key") or "").startswith(("market-", "market:"))
        ]
    elif intent == "stock_screen":
        stock_specific_prefixes = (
            "research-report:",
            "earnings-quality:",
            "financial-drivers:",
            "business-structure:",
            "shareholder-structure:",
            "analyst-expectations:",
            "event-timeline:",
            "filing-evidence:",
            "research-outcome:",
            "deep-stock:",
        )
        items = [
            item
            for item in items
            if not str(item.get("source_key") or "").startswith(stock_specific_prefixes)
        ]
    elif intent in {"research_priority", "research_actions"}:
        items = [
            item
            for item in items
            if item.get("scope") == "user"
            and not str(item.get("source_key") or "").startswith(
                ("research-priority:", "research-actions:")
            )
        ]
    elif (
        intent
        in {
            "stock_research",
            "research_tracking",
            "earnings_quality",
            "financial_drivers",
            "business_structure",
            "shareholder_structure",
            "analyst_expectations",
            "event_timeline",
        }
        and symbol
    ):
        canonical = normalize_symbol(symbol)
        question = str((evidence or {}).get("user_question") or "")
        time_sensitive_question = any(
            term in question
            for term in (
                "今天",
                "今日",
                "当前",
                "现在",
                "盘中",
                "最新",
                "报价",
                "为什么涨",
                "为什么跌",
                "为什么上涨",
                "为什么下跌",
                "上涨原因",
                "下跌原因",
                "涨停",
                "跌停",
            )
        )
        if time_sensitive_question:
            snapshot_prefixes = (
                "research-report:",
                "research-outcome:",
                "research-actions:",
                "research-priority:",
                "research-change:",
            )
            items = [
                item
                for item in items
                if not str(item.get("source_key") or "").startswith(snapshot_prefixes)
            ]
        report_period = ((evidence or {}).get("latest_period") or {}).get(
            "report_date"
        ) or ((evidence or {}).get("latest_report") or {}).get("report_date")
        wanted = {
            f"research-report:{canonical}",
            f"earnings-quality:{canonical}",
            f"financial-drivers:{canonical}",
            f"business-structure:{canonical}",
            f"peer-operating:{canonical}",
            f"shareholder-structure:{canonical}",
            f"analyst-expectations:{canonical}",
            f"event-timeline:{canonical}",
        }
        items = [
            item
            for item in items
            if (
                (
                    str(item.get("source_key") or "").startswith(
                        f"filing-evidence:{canonical}:"
                    )
                    and (
                        not report_period
                        or report_period in str(item.get("title") or "")
                    )
                )
                or not str(item.get("source_key") or "").startswith(
                    (
                        "research-report:",
                        "earnings-quality:",
                        "financial-drivers:",
                        "business-structure:",
                        "peer-operating:",
                        "shareholder-structure:",
                        "analyst-expectations:",
                        "event-timeline:",
                        "filing-evidence:",
                    )
                )
                or item.get("source_key") in wanted
            )
        ]
    elif intent == "research_outcome":
        canonical = normalize_symbol(symbol) if symbol else None
        wanted = (
            {
                f"research-report:{canonical}",
                f"research-outcome:{canonical}",
            }
            if canonical
            else set()
        )
        items = [
            item
            for item in items
            if (
                item.get("source_key") in wanted
                if canonical
                else str(item.get("source_key") or "").startswith("research-outcome:")
            )
        ]
    coverage = dict(context.get("coverage") or {})
    coverage["matched_documents"] = len(items)
    return {**context, "items": items, "coverage": coverage}


def _is_market_ticker_reference(candidate: str, message: str) -> bool:
    folded = re.sub(r"\s+", "", message).casefold()
    ticker = candidate.upper()
    return (
        (ticker == "A" and "a股" in folded)
        or (ticker == "S" and "s&p" in folded)
        or (ticker in {"KOSPI", "VIX", "DAX"} and ticker.casefold() in folded)
    )


def _conversation_title(message: str) -> str:
    normalized = re.sub(r"\s+", " ", message).strip()
    if not normalized:
        return "新的研究对话"
    return normalized[:28] + ("…" if len(normalized) > 28 else "")


def _symbol_from_history(history: list[dict[str, Any]]) -> str | None:
    for item in reversed(history):
        metadata = item.get("metadata") or {}
        symbol = metadata.get("symbol")
        if symbol:
            try:
                return normalize_symbol(str(symbol))
            except ValueError:
                continue
    return None


def _symbols_from_history(history: list[dict[str, Any]]) -> list[str]:
    for item in reversed(history):
        metadata = item.get("metadata") or {}
        targets = metadata.get("research_targets") or []
        output: list[str] = []
        for target in targets:
            raw = target.get("symbol") if isinstance(target, dict) else target
            if not raw:
                continue
            try:
                canonical = normalize_symbol(str(raw))
            except ValueError:
                continue
            if canonical not in output:
                output.append(canonical)
        if len(output) >= 2:
            return output
    symbol = _symbol_from_history(history)
    return [symbol] if symbol else []


def _intent_from_history(history: list[dict[str, Any]]) -> str | None:
    for item in reversed(history):
        if item.get("role") == "assistant" and item.get("intent"):
            intent = str(item["intent"])
            if intent in {"general_research", "clarification"}:
                continue
            return intent
    return None


def _stock_screen_profile_from_history(
    history: list[dict[str, Any]],
) -> str | None:
    for item in reversed(history):
        if item.get("role") != "assistant" or item.get("intent") != "stock_screen":
            continue
        profile = (item.get("metadata") or {}).get("stock_screen_profile")
        if profile:
            return str(profile)
    return None


def _market_key_from_history(history: list[dict[str, Any]]) -> str | None:
    for item in reversed(history):
        metadata = item.get("metadata") or {}
        market_key = metadata.get("market_key")
        if market_key:
            return str(market_key)
        content = str(item.get("content") or "")
        if _is_market_query(content):
            return MarketNewsService.infer_market(content)
    return None


def _is_contextual_followup(message: str) -> bool:
    folded = re.sub(r"\s+", "", message).casefold()
    if not folded or len(folded) > 80:
        return False
    context_terms = (
        "那",
        "那么",
        "它",
        "这个",
        "这些",
        "上述",
        "刚才",
        "前面",
        "上一题",
        "上一问",
        "前一题",
        "前一问",
        "重新回答",
        "重新答",
        "重答",
        "刚刚的回答",
        "前一个回答",
        "接下来",
        "主要风险",
        "最大风险",
        "风险是什么",
        "怎么看",
        "为什么",
        "更像",
        "反弹",
        "反转",
        "企稳",
        "趋势",
        "量能",
        "成交",
        "持续性",
        "能持续",
        "普涨",
        "结构性",
        "领涨",
        "领跌",
        "驱动",
        "催化",
        "反方",
        "反证",
        "相反证据",
        "失效条件",
        "不成立",
        "推翻",
        "证据缺口",
        "还缺什么证据",
        "需要补什么证据",
        "还有呢",
        "继续",
        "再比较",
        "继续比较",
        "重点比较",
        "变化",
        "进展",
        "更新",
        "现在",
        "当前",
        "最新",
        "报价",
        "日线",
        "纠正前提",
        "后来",
        "结果",
        "准不准",
    )
    return any(term in folded for term in context_terms)


def _is_research_tracking_query(message: str) -> bool:
    folded = re.sub(r"\s+", "", message).casefold()
    tracking_terms = (
        "最近有什么变化",
        "最近有何变化",
        "发生了什么变化",
        "研究进展",
        "跟踪变化",
        "跟踪更新",
        "跟踪动态",
        "新增证据",
        "证据变化",
        "原假设变了吗",
    )
    return any(term in folded for term in tracking_terms)


def _is_deep_stock_coverage_query(message: str) -> bool:
    folded = re.sub(r"\s+", "", message).casefold()
    coverage_terms = (
        "六维证据",
        "证据六维",
        "证据覆盖",
        "覆盖状态",
        "覆盖情况",
        "覆盖缺口",
    )
    return any(term in folded for term in coverage_terms)


def _is_earnings_quality_query(message: str) -> bool:
    folded = re.sub(r"\s+", "", message).casefold()
    terms = (
        "财报质量",
        "盈利质量",
        "业绩质量",
        "利润含金量",
        "财报怎么看",
        "财务报表怎么看",
        "利润为什么下降",
        "为什么利润下降",
        "净利润为什么下降",
        "营收增长为什么利润下降",
        "现金流质量",
        "现金流怎么样",
        "经营现金流",
        "利润兑现",
    )
    return any(term in folded for term in terms)


def _is_financial_driver_query(message: str) -> bool:
    folded = re.sub(r"\s+", "", message).casefold()
    terms = (
        "利润为什么下降",
        "为什么利润下降",
        "净利润为什么下降",
        "营收增长为什么利润下降",
        "利润下降原因",
        "利润增长原因",
        "利润驱动",
        "利润拆解",
        "三表拆解",
        "毛利率为什么下降",
        "毛利率下降原因",
        "费用率变化",
        "财务费用为什么",
        "财务费用上升原因",
        "汇兑损失",
        "其他收益为什么",
        "投资收益为什么",
        "减值为什么",
        "公司怎么解释利润",
        "公司如何解释利润",
        "财报原文怎么解释",
        "报告里怎么解释",
        "销售费用变化",
        "管理费用变化",
        "研发费用变化",
        "应收账款变化",
        "应收为什么增长",
        "存货为什么增长",
        "存货占用",
        "现金流为什么变差",
        "现金流为什么下降",
        "现金流为什么转负",
        "为什么现金流转负",
        "现金流转负原因",
        "销售收现",
        "营运资金",
    )
    return any(term in folded for term in terms)


def _is_business_structure_query(message: str) -> bool:
    folded = re.sub(r"\s+", "", message).casefold()
    terms = (
        "主营构成",
        "业务结构",
        "收入结构",
        "产品结构",
        "靠什么赚钱",
        "靠什么业务赚钱",
        "收入来自哪里",
        "收入来源",
        "哪个业务占比",
        "哪个产品占比",
        "哪个业务增长",
        "分部收入",
        "分部毛利",
        "业务毛利率",
        "产品毛利率",
        "地区收入",
        "国内收入",
        "海外收入",
        "毛利来源",
    )
    return any(term in folded for term in terms)


def _is_peer_comparison_query(message: str) -> bool:
    folded = re.sub(r"\s+", "", message).casefold()
    direct_terms = (
        "固定同行",
        "同行比较",
        "同行对比",
        "同业比较",
        "同业对比",
        "公司对比",
        "横向比较",
        "同报告期经营差异",
        "分别比较",
    )
    if any(term in folded for term in direct_terms):
        return True
    comparison_terms = ("比较", "对比", "差异")
    peer_terms = (
        "同行",
        "同业",
        "竞品",
        "竞争对手",
        "烽火通信",
        "紫光股份",
        "锐捷网络",
        "新易盛",
        "天孚通信",
        "光迅科技",
    )
    return any(term in folded for term in comparison_terms) and any(
        term in folded for term in peer_terms
    )


def _is_shareholder_query(message: str) -> bool:
    folded = re.sub(r"\s+", "", message).casefold()
    terms = (
        "股东户数",
        "股东人数",
        "股东结构",
        "十大股东",
        "前十大股东",
        "主要股东",
        "筹码集中",
        "持股集中",
        "持股分散",
        "机构持仓",
        "机构股东",
        "股东变化",
        "股东怎么变",
        "股东是谁",
    )
    return any(term in folded for term in terms)


def _is_analyst_expectations_query(message: str) -> bool:
    folded = re.sub(r"\s+", "", message).casefold()
    terms = (
        "一致预期",
        "分析师预期",
        "券商预期",
        "盈利预测",
        "eps预测",
        "分析师上修",
        "分析师下修",
        "预期上修",
        "预期下修",
        "最近上修",
        "最近下修",
        "券商怎么看",
        "机构怎么看",
        "最新研报",
        "个股研报",
        "研报有哪些",
        "评级分布",
        "覆盖机构",
    )
    return any(term in folded for term in terms)


def _is_research_outcome_query(message: str) -> bool:
    folded = re.sub(r"\s+", "", message).casefold()
    outcome_terms = (
        "之前的研究后来怎么样",
        "之前研究后来怎么样",
        "上次分析后来怎么样",
        "上次研究后来怎么样",
        "研究结果复盘",
        "研究结果怎么样",
        "回看之前的分析",
        "复盘之前的研究",
        "之前判断准不准",
        "之前分析准不准",
        "过去的研究结果",
    )
    return any(term in folded for term in outcome_terms)


def _is_research_priority_query(message: str) -> bool:
    folded = re.sub(r"\s+", "", message).casefold()
    priority_terms = (
        "今天先看什么",
        "今日先看什么",
        "先研究哪只",
        "先看哪只",
        "研究优先级",
        "今日研究重点",
        "今天研究重点",
        "自选股风险排序",
        "自选股复核顺序",
        "自选股先看什么",
    )
    return any(term in folded for term in priority_terms)


def _is_research_action_query(message: str) -> bool:
    folded = re.sub(r"\s+", "", message).casefold()
    action_terms = (
        "研究行动",
        "行动清单",
        "观察条件",
        "研究条件",
        "待补证",
        "需要补什么证据",
        "哪些条件触发了",
        "什么需要复核",
        "现在要复核什么",
        "研究任务",
    )
    return any(term in folded for term in action_terms)


def _is_event_timeline_query(message: str) -> bool:
    folded = re.sub(r"\s+", "", message).casefold()
    event_terms = (
        "事件脉络",
        "重要事件",
        "最新事件",
        "最近发生了什么",
        "最近有什么大事",
        "有什么催化",
        "催化事件",
        "催化和风险",
        "风险事件",
        "公告风险",
        "重要公告",
        "最新公告讲了什么",
        "有什么需要阅读原文",
    )
    return any(term in folded for term in event_terms)


def _needs_research_object_clarification(
    message: str, history: list[dict[str, Any]]
) -> bool:
    if history:
        return False
    folded = re.sub(r"\s+", "", message).casefold()
    ambiguous_targets = (
        "这只股票",
        "这个股票",
        "这只股",
        "这家公司",
        "这个公司",
        "这个标的",
    )
    return any(term in folded for term in ambiguous_targets)


def _extract_thesis(message: str) -> str | None:
    for marker in ("关注理由是", "关注理由：", "关注理由:", "因为"):
        if marker in message:
            thesis = message.split(marker, 1)[1].strip(" 。")
            return thesis or None
    return None


app = create_app()
