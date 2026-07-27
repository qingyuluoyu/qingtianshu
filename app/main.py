from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
import hmac
from io import BytesIO
import logging
import os
import re
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from fastapi import FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse

from app.api_models import (
    ActionPlanCreate,
    ActionPlanPatch,
    ActionPlanTransition,
    ArticleGenerateRequest,
    BackgroundJobEnqueueRequest,
    ChangeRelevanceUpdate,
    ChatRefineRequest,
    ChatRequest,
    ConversationCreate,
    ConversationPatch,
    DeepStockStart,
    LegacySessionClaim,
    LiZongBacktestRunRequest,
    LiZongHistoryRunRequest,
    LiZongRunRequest,
    LiZongUniverseRunRequest,
    MemoryCandidateCreate,
    ObservationTaskCreate,
    ObservationTaskTransition,
    ObservationTaskUpdate,
    PositionAdjustmentCreate,
    PositionOpeningCreate,
    PositionOperationCreate,
    PositionOperationRevisionCreate,
    StockRelationUpdate,
    StockScreenRequest,
    ThesisCandidateCreate,
    TradeReviewConfirm,
    TradeReviewDraftPatch,
    TradeReviewFollowupCreate,
    TradeReviewGenerateDraft,
    TushareSymbolRefreshRequest,
    UserCreate,
    WatchlistUpsert,
)
from app.catalog import (
    INDEX_BY_SYMBOL,
    RESEARCH_TARGETS,
    normalize_symbol,
)
from app.config import PROJECT_ROOT, Settings
from app.db import Database
from app.operations import build_operations_report
from app.static_assets import STATIC_ASSET_MEDIA_TYPES
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
from app.services.chat_routing import (  # noqa: F401 - compatibility exports
    _conversation_title,
    _extract_symbol,
    _extract_symbols,
    _extract_industry_topic,
    _extract_thesis,
    _intent_from_history,
    _is_analyst_expectations_query,
    _is_business_structure_query,
    _is_contextual_followup,
    _is_deep_stock_coverage_query,
    _is_earnings_quality_query,
    _is_event_timeline_query,
    _is_financial_driver_query,
    _is_li_zong_strategy_followup,
    _is_market_query,
    _is_peer_comparison_query,
    _is_research_action_query,
    _is_research_outcome_query,
    _is_research_priority_query,
    _is_research_tracking_query,
    _is_shareholder_query,
    _is_stock_screen_query,
    _is_watchlist_daily_query,
    _market_date,
    _market_key_from_history,
    _market_question_focus,
    _needs_research_object_clarification,
    _needs_stock_market_context,
    _prefers_stock_context_followup,
    _question_market_date,
    _question_price_direction,
    _stock_screen_profile_from_history,
    _stock_screen_parameters,
    _symbol_from_history,
    _symbols_from_history,
)
from app.services.chat_persistence import ChatResponsePersistence
from app.services.chat_context import (
    ChatRequestContextService,
)
from app.services.chat_execution import ChatAgentExecutionService
from app.services.chat_orchestration import ChatOrchestrationService
from app.services.chat_refinement import ChatRefinementService
from app.services.chat_market_evidence import ChatMarketEvidenceService
from app.services.chat_stock_context import (  # noqa: F401 - compatibility export
    _compact_stock_workspace_context,
)
from app.services.chat_screening_evidence import ChatScreeningEvidenceService
from app.services.chat_company_evidence import ChatCompanyEvidenceService
from app.services.chat_knowledge_context import (  # noqa: F401 - compatibility export
    _filter_knowledge_context,
)
from app.services.chat_stock_research_evidence import (
    ChatStockResearchEvidenceService,
)
from app.services.deep_stock import (
    DeepStockConversationConflict,
    DeepStockResearchService,
)
from app.services.stock_screener import (
    StockScreenerService,
    StockScreenerUnavailable,
)
from app.services.evidence_presentation import (
    agent_evidence_progress as _agent_evidence_progress,  # noqa: F401
    build_visible_evidence_sources as _build_visible_evidence_sources,  # noqa: F401
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
from app.services.stock_page import StockPageService
from app.services.stock_market_context import (  # noqa: F401 - compatibility exports
    _build_stock_market_context,
    _stock_analysis_target,
)
from app.services.security_master import SecurityMasterService
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
from app.services.li_zong_history import LiZongHistoryService
from app.services.li_zong_portfolio_backtest import LiZongPortfolioBacktestService
from app.services.li_zong_presentation import (
    external_ts_code as _external_ts_code,
    public_li_zong_candidate as _public_li_zong_candidate,
    public_li_zong_observation as _public_li_zong_observation,
)
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
from app.services.live_market import LiveMarketService
from app.services.knowledge import KnowledgeService
from app.services.market_news import MarketNewsService
from app.services.research_reports import (
    ResearchReportService,
    StockResearchEvidenceService,
)
from app.services.research_plan import ResearchPlanService
from app.services.research_priority import ResearchPriorityService
from app.services.research_actions import ResearchActionService
from app.services.research_outcomes import ResearchOutcomeService
from app.services.run_review_presentation import _public_run_review
from app.utils import utc_now


SESSION_COOKIE_NAME = "qingshu_session"
Image.MAX_IMAGE_PIXELS = 25_000_000
logger = logging.getLogger(__name__)


def _public_strategy_screen_run(run: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return the small run summary needed by user-facing strategy APIs.

    Full screen runs retain a per-symbol ``data_versions`` map for deterministic
    invalidation and audit.  That map can contain several thousand entries and
    is internal worker state, so sending it to the browser adds latency without
    improving the user-visible progress display.
    """

    if not run:
        return None
    return {
        key: run.get(key)
        for key in (
            "id",
            "strategy_id",
            "strategy_version",
            "parameter_version",
            "data_version",
            "as_of_date",
            "run_scope",
            "universe_count",
            "prefiltered_count",
            "coverage_ratio",
            "status",
            "requested_count",
            "processed_count",
            "qualified_count",
            "triggered_count",
            "incomplete_count",
            "invalidated_count",
            "error",
            "started_at",
            "finished_at",
            "warnings",
        )
    }


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
    database = Database(
        settings.workspace_root,
        settings.database_url,
    )
    database.initialize()
    security_master = SecurityMasterService(database)
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
    chat_market_evidence = ChatMarketEvidenceService(
        analysis=analysis,
        market_news=market_news,
        live_markets=live_markets,
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
    chat_persistence = ChatResponsePersistence(database, conversation_quality)
    chat_context = ChatRequestContextService(database, knowledge)
    deep_stock = DeepStockResearchService(database)
    stock_domain = StockDomainService(database)
    observation_tasks = ObservationTaskService(database)
    position_ledger = PositionLedgerService(database)
    trade_workflow = TradeWorkflowService(database)
    structured_ai = StructuredAIService(
        database, stock_domain, observation_tasks, trade_workflow
    )
    chat_execution = ChatAgentExecutionService(
        agent=agent,
        structured_ai=structured_ai,
        deep_stock=deep_stock,
        evidence_tasks=evidence_tasks,
    )
    chat_refinement = ChatRefinementService(
        database=database,
        knowledge=knowledge,
        agent=agent,
        evidence_tasks=evidence_tasks,
        deep_stock=deep_stock,
        structured_ai=structured_ai,
        conversation_quality=conversation_quality,
    )
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
        database=database,
        snapshot_ttl_seconds=settings.market_cache_seconds,
    )
    tushare_snapshots = TushareSnapshotService(database, resolved_tushare_client)
    li_zong_strategy = LiZongStrategyService(
        database,
        tushare_snapshots,
        fundamentals_provider=a_share_fundamentals_provider,
    )
    li_zong_history = LiZongHistoryService(
        database,
        tushare_snapshots,
        li_zong_strategy,
    )
    li_zong_backtest = LiZongPortfolioBacktestService(
        database,
        tushare_snapshots,
        li_zong_strategy,
    )
    chat_screening_evidence = ChatScreeningEvidenceService(
        stock_screener=stock_screener,
        li_zong_strategy=li_zong_strategy,
        li_zong_history=li_zong_history,
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
    stock_page = StockPageService(
        stock_workspace=stock_workspace,
        analysis=analysis,
        fundamentals=fundamentals,
        us_fundamentals=us_fundamentals,
        earnings_quality=earnings_quality,
        financial_drivers=financial_drivers,
        shareholders=shareholders,
        analyst_expectations=analyst_expectations,
        event_timeline=event_timeline,
        china_info=china_info,
    )
    chat_company_evidence = ChatCompanyEvidenceService(
        database=database,
        event_timeline=event_timeline,
        analyst_expectations=analyst_expectations,
        shareholders=shareholders,
        business_structure=business_structure,
        fundamentals=fundamentals,
        china_info=china_info,
        us_fundamentals=us_fundamentals,
        global_info=global_info,
        financial_drivers=financial_drivers,
        earnings_quality=earnings_quality,
        filings=filings,
    )
    research_plan = ResearchPlanService()
    chat_stock_research_evidence = ChatStockResearchEvidenceService(
        database=database,
        research_plan=research_plan,
        research_reports=research_reports,
        research_evidence=research_evidence,
        li_zong_strategy=li_zong_strategy,
        analysis=analysis,
        deep_stock=deep_stock,
        research_tracking=research_tracking,
        stock_workspace=stock_workspace,
    )
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
    chat_orchestration = ChatOrchestrationService(
        event_broker=event_broker,
        agent_streams=agent_streams,
        chat_context=chat_context,
        chat_persistence=chat_persistence,
        articles=articles,
        database=database,
        chat_screening_evidence=chat_screening_evidence,
        stock_comparison=stock_comparison,
        stock_assets=stock_assets,
        analysis=analysis,
        research_actions=research_actions,
        research_priority=research_priority,
        research_outcomes=research_outcomes,
        research_reports=research_reports,
        research_tracking=research_tracking,
        chat_company_evidence=chat_company_evidence,
        chat_market_evidence=chat_market_evidence,
        chat_stock_research_evidence=chat_stock_research_evidence,
        chat_execution=chat_execution,
    )
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
        global_info,
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
        li_zong_history=li_zong_history,
        li_zong_backtest=li_zong_backtest,
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
            event_broker.close()
            background.job_store.close()
            database.close()

    app = FastAPI(
        title="清数智算 Agent Demo",
        version="0.1.0",
        description="后端优先的金融研究 Agent：确定性行情分析 + Hermes 解释 + 用户确认记忆。",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.database = database
    app.state.security_master = security_master
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
    app.state.chat_context = chat_context
    app.state.chat_execution = chat_execution
    app.state.chat_orchestration = chat_orchestration
    app.state.chat_refinement = chat_refinement
    app.state.chat_market_evidence = chat_market_evidence
    app.state.chat_persistence = chat_persistence
    app.state.deep_stock = deep_stock
    app.state.stock_domain = stock_domain
    app.state.structured_ai = structured_ai
    app.state.observation_tasks = observation_tasks
    app.state.position_ledger = position_ledger
    app.state.trade_workflow = trade_workflow
    app.state.global_search = global_search
    app.state.stock_workspace = stock_workspace
    app.state.stock_assets = stock_assets
    app.state.stock_page = stock_page
    app.state.chat_company_evidence = chat_company_evidence
    app.state.research_plan = research_plan
    app.state.chat_stock_research_evidence = chat_stock_research_evidence
    app.state.stock_screener = stock_screener
    app.state.tushare_snapshots = tushare_snapshots
    app.state.li_zong_strategy = li_zong_strategy
    app.state.li_zong_history = li_zong_history
    app.state.li_zong_backtest = li_zong_backtest
    app.state.chat_screening_evidence = chat_screening_evidence
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
                "last_intent",
                "research_targets",
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
        return RedirectResponse(url="/today")

    @app.get("/demo", include_in_schema=False)
    def demo_page() -> FileResponse:
        return FileResponse(
            Path(__file__).resolve().parent / "static" / "demo.html",
            headers={
                "Cache-Control": "no-store, max-age=0",
                "Pragma": "no-cache",
            },
        )

    @app.get("/static/{asset_name}", include_in_schema=False)
    def static_asset(asset_name: str) -> FileResponse:
        if asset_name not in STATIC_ASSET_MEDIA_TYPES:
            raise HTTPException(status_code=404, detail="静态资源不存在")
        return FileResponse(
            Path(__file__).resolve().parent / "static" / asset_name,
            media_type=STATIC_ASSET_MEDIA_TYPES[asset_name],
            headers={"Cache-Control": "no-store, max-age=0"},
        )

    @app.get("/today", include_in_schema=False)
    @app.get("/search", include_in_schema=False)
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
        queue_status = background.status()
        return {
            "status": "ok",
            "time": utc_now(),
            "hermes_enabled": settings.hermes_enabled,
            "storage": {
                "domain_database": database.schema_status(),
                "operational_database": {
                    "backend": queue_status["persistent_queue"]["backend"],
                    "schema_version": queue_status["persistent_queue"][
                        "schema_version"
                    ],
                },
            },
            "data_health": data_health.public_summary(data_health.latest()),
            "background_jobs": queue_status,
        }

    @app.get("/ready", include_in_schema=False)
    def readiness(response: Response) -> dict[str, Any]:
        report = build_operations_report(
            database,
            background.job_store,
            settings,
            require_postgres=settings.background_worker_mode == "external",
            minimum_active_workers=(
                1
                if settings.background_jobs_enabled
                and settings.background_worker_mode != "disabled"
                else 0
            ),
            check_backup=False,
        )
        if report["status"] != "ok":
            response.status_code = 503
        return report

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

    @app.get("/admin/job-queue")
    def job_queue_list(
        request: Request,
        status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
        | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        require_admin_api(request)
        return {
            "queue": background.job_store.health(),
            "jobs": background.list_jobs(status=status, limit=limit),
        }

    @app.get("/admin/operations/health")
    def operations_health(request: Request) -> dict[str, Any]:
        require_admin_api(request)
        return build_operations_report(
            database,
            background.job_store,
            settings,
            require_postgres=settings.background_worker_mode == "external",
            minimum_active_workers=(
                1
                if settings.background_jobs_enabled
                and settings.background_worker_mode != "disabled"
                else 0
            ),
        )

    @app.post("/admin/job-queue/enqueue", status_code=202)
    def job_queue_enqueue(
        payload: BackgroundJobEnqueueRequest, request: Request
    ) -> dict[str, Any]:
        require_admin_api(request)
        try:
            return background.enqueue(
                payload.job_name,
                payload=payload.payload,
                idempotency_key=payload.idempotency_key,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="后台任务类型不存在") from exc

    @app.post("/admin/job-queue/{job_id}/retry", status_code=202)
    def job_queue_retry(job_id: UUID, request: Request) -> dict[str, Any]:
        require_admin_api(request)
        if not background.job_store.retry(str(job_id)):
            raise HTTPException(status_code=409, detail="任务当前状态不可重试")
        return {"status": "queued", "job_id": str(job_id)}

    @app.post("/admin/job-queue/{job_id}/cancel")
    def job_queue_cancel(job_id: UUID, request: Request) -> dict[str, Any]:
        require_admin_api(request)
        if not background.job_store.cancel(str(job_id)):
            raise HTTPException(status_code=409, detail="仅等待中的任务可取消")
        return {"status": "cancelled", "job_id": str(job_id)}

    @app.get("/admin/job-schedules")
    def job_schedule_list(
        request: Request,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        require_admin_api(request)
        return {
            "queue": background.job_store.health(
                worker_stale_seconds=settings.job_worker_stale_seconds
            ),
            "schedules": background.job_store.list_schedules(limit=limit),
        }

    @app.post("/admin/job-schedules/{schedule_name}/pause")
    def job_schedule_pause(schedule_name: str, request: Request) -> dict[str, Any]:
        require_admin_api(request)
        schedule = background.job_store.pause_schedule(schedule_name)
        if schedule is None:
            raise HTTPException(status_code=404, detail="周期任务不存在")
        return schedule

    @app.post("/admin/job-schedules/{schedule_name}/resume")
    def job_schedule_resume(schedule_name: str, request: Request) -> dict[str, Any]:
        require_admin_api(request)
        schedule = background.job_store.resume_schedule(schedule_name)
        if schedule is None:
            raise HTTPException(status_code=404, detail="周期任务不存在")
        return schedule

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
        public_coverage = {
            **coverage,
            "latest_run": _public_strategy_screen_run(coverage.get("latest_run")),
        }
        return {
            "strategy_id": "li_zong",
            "run": public_coverage.get("latest_run"),
            "coverage": public_coverage,
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
        coverage, funnel = li_zong_strategy.coverage_and_funnel_packet()
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
            "funnel": funnel,
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
                "latest_run": _public_strategy_screen_run(
                    coverage.get("latest_run")
                ),
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

    @app.get("/v1/stock-strategies/li-zong/observation-pool")
    def list_li_zong_observation_pool(
        request: Request,
        band: Literal["near_8_of_9", "watch_6_7_of_9"] | None = None,
        limit: int = Query(default=200, ge=1, le=1000),
    ) -> dict[str, Any]:
        require_session_user(request)
        try:
            packet = li_zong_strategy.observation_pool_packet(
                band=band,
                limit=limit,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        coverage = packet.get("coverage") or {}
        return {
            "strategy": li_zong_strategy.get_definition(),
            "status": packet.get("status"),
            "items": [
                _public_li_zong_observation(item) for item in packet.get("items") or []
            ],
            "counts": coverage.get("counts") or {},
            "observation_counts": packet.get("counts") or {},
            "data_meta": {
                "universe_status": coverage.get("status"),
                "latest_as_of_date": packet.get("as_of_date"),
                "evaluated_symbols": coverage.get("evaluated_symbols") or 0,
                "universe_count": coverage.get("universe_count") or 0,
                "deep_check_eligible_count": (
                    coverage.get("deep_check_eligible_count") or 0
                ),
                "deep_processed_symbols": (coverage.get("deep_processed_symbols") or 0),
                "deep_remaining_symbols": (coverage.get("deep_remaining_symbols") or 0),
                "deep_processing_ratio": (coverage.get("deep_processing_ratio") or 0),
                "deep_decisive_symbols": (coverage.get("deep_decisive_symbols") or 0),
                "complete_observation_rule_states": (
                    packet.get("complete_rule_states") or 0
                ),
                "full_market_coverage": bool(coverage.get("full_market_coverage")),
                "deep_check_complete": bool(coverage.get("deep_check_complete")),
            },
            "boundary": packet.get("boundary"),
        }

    @app.get("/v1/stock-strategies/li-zong/history")
    def list_li_zong_history(
        request: Request,
        symbol: str | None = Query(default=None, max_length=24),
        limit: int = Query(default=30, ge=1, le=200),
    ) -> dict[str, Any]:
        require_session_user(request)
        try:
            return li_zong_history.history_packet(symbol=symbol, limit=limit)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/v1/stock-strategies/li-zong/history/runs")
    def run_li_zong_history(
        payload: LiZongHistoryRunRequest, request: Request
    ) -> dict[str, Any]:
        require_admin_api(request)
        return li_zong_history.run_batch(
            batch_size=payload.batch_size,
            symbols=payload.symbols,
            lookback_days=payload.lookback_days,
        )

    @app.get("/v1/stock-strategies/li-zong/backtest")
    def get_li_zong_backtest(
        request: Request,
        period: Literal["3m", "1y", "3y"] = Query(default="1y"),
    ) -> dict[str, Any]:
        require_session_user(request)
        return li_zong_backtest.packet(period=period)

    @app.post("/v1/stock-strategies/li-zong/backtest/runs")
    def run_li_zong_backtest(
        payload: LiZongBacktestRunRequest, request: Request
    ) -> dict[str, Any]:
        require_admin_api(request)
        return li_zong_backtest.refresh(
            market_day_batch_size=payload.market_day_batch_size,
            symbol_batch_size=payload.symbol_batch_size,
            input_sync_batch_size=payload.input_sync_batch_size,
            as_of_date=payload.as_of_date,
        )

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
        except DeepStockConversationConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
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

    @app.get("/api/v1/stocks/{symbol}/page", include_in_schema=False)
    @app.get("/v1/stocks/{symbol}/page")
    def get_my_stock_page(
        symbol: str,
        request: Request,
        range_name: Literal["3mo", "6mo", "1y"] = Query(default="1y", alias="range"),
    ) -> dict[str, Any]:
        user = require_session_user(request)
        try:
            return stock_page.get_page(
                user["id"],
                symbol,
                range_name=range_name,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

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
            return structured_ai.create_review_draft_writeback(
                user_id=user["id"],
                run=run,
                evidence=evidence,
                draft=draft,
                base_version=payload.base_version,
            )
        except StructuredAINotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except StructuredAIConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except StructuredAIInvalidState as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
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

    @app.post("/v1/trade-reviews/{review_id}/followups", status_code=201)
    def create_my_trade_review_followup(
        review_id: str, payload: TradeReviewFollowupCreate, request: Request
    ) -> dict[str, Any]:
        user = require_session_user(request)
        try:
            return structured_ai.create_review_followup(
                user_id=user["id"],
                review_id=review_id,
                target=payload.target,
                title=payload.title,
                priority=payload.priority,
            )
        except StructuredAINotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except StructuredAIConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except StructuredAIInvalidState as exc:
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
        content = knowledge.localize_document_text(
            document, str(document.get("content") or "")
        )
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
            display_name = security_master.display_name(
                str(report.get("symbol")),
                RESEARCH_TARGETS.get(str(report.get("symbol")), {}).get("name"),
                report.get("name"),
                evidence.get("display_name"),
            )
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
        user = require_user(request, user_id)
        return chat_orchestration.handle(user, payload)

    @app.post("/me/chat")
    def my_chat(payload: ChatRequest, request: Request) -> dict[str, Any]:
        user = require_session_user(request)
        return chat_orchestration.handle(user, payload)

    @app.post("/me/chat/refine")
    def refine_my_chat(payload: ChatRefineRequest, request: Request) -> dict[str, Any]:
        user = require_session_user(request)
        return chat_refinement.refine(user, payload)

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


app = None if os.getenv("QINGSHU_APP_FACTORY_ONLY") == "1" else create_app()
