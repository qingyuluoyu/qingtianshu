from __future__ import annotations

import json
from queue import Empty, Full, Queue
import threading
import time
from typing import Any, Callable, Iterator

from app.config import Settings
from app.db import Database
from app.services.article import MarketPulseArticleService
from app.services.china_info import ChinaInformationService
from app.services.business_structure import BusinessStructureAnalysisService
from app.services.shareholders import ShareholderStructureAnalysisService
from app.services.analyst_expectations import AnalystExpectationsService
from app.services.calibration import OutlookCalibrationService
from app.services.fundamentals import FundamentalsService
from app.services.earnings_quality import EarningsQualityService
from app.services.evidence_tasks import EvidenceTaskService
from app.services.event_timeline import EventTimelineService
from app.services.financial_drivers import FinancialDriverAnalysisService
from app.services.filings import AShareFilingService
from app.services.us_fundamentals import USEquityFundamentalsService
from app.services.peer_comparison import PeerComparisonService
from app.services.data_health import DataHealthService
from app.services.live_market import LiveMarketService
from app.services.analysis import MarketAnalysisService
from app.services.market_news import MarketNewsService
from app.services.research_reports import ResearchReportService
from app.services.research_outcomes import ResearchOutcomeService
from app.services.tushare_snapshots import TushareSnapshotService
from app.services.li_zong_strategy_service import LiZongStrategyService
from app.catalog import normalize_symbol
from app.utils import utc_now


class EventBroker:
    def __init__(self):
        self._subscribers: set[Queue[dict[str, Any]]] = set()
        self._lock = threading.Lock()

    def publish(self, event: dict[str, Any]) -> None:
        with self._lock:
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            try:
                subscriber.put_nowait(event)
            except Full:
                try:
                    subscriber.get_nowait()
                    subscriber.put_nowait(event)
                except (Empty, Full):
                    continue

    def stream(self) -> Iterator[str]:
        subscriber: Queue[dict[str, Any]] = Queue(maxsize=20)
        with self._lock:
            self._subscribers.add(subscriber)
        try:
            yield f"data: {json.dumps({'type': 'connected', 'time': utc_now()}, ensure_ascii=False)}\n\n"
            while True:
                try:
                    event = subscriber.get(timeout=15)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                except Empty:
                    yield ": heartbeat\n\n"
        finally:
            with self._lock:
                self._subscribers.discard(subscriber)


class BackgroundScheduler:
    def __init__(
        self,
        database: Database,
        live_markets: LiveMarketService,
        market_analysis: MarketAnalysisService,
        articles: MarketPulseArticleService,
        china_info: ChinaInformationService,
        event_timeline: EventTimelineService,
        filings: AShareFilingService,
        business_structure: BusinessStructureAnalysisService,
        shareholders: ShareholderStructureAnalysisService,
        analyst_expectations: AnalystExpectationsService,
        fundamentals: FundamentalsService,
        us_fundamentals: USEquityFundamentalsService,
        earnings_quality: EarningsQualityService,
        financial_drivers: FinancialDriverAnalysisService,
        peer_comparison: PeerComparisonService,
        outlook_calibration: OutlookCalibrationService,
        research_reports: ResearchReportService,
        research_outcomes: ResearchOutcomeService,
        market_news: MarketNewsService,
        evidence_tasks: EvidenceTaskService,
        data_health: DataHealthService,
        broker: EventBroker,
        settings: Settings,
        tushare_snapshots: TushareSnapshotService | None = None,
        li_zong_strategy: LiZongStrategyService | None = None,
    ):
        self.database = database
        self.live_markets = live_markets
        self.market_analysis = market_analysis
        self.articles = articles
        self.china_info = china_info
        self.event_timeline = event_timeline
        self.filings = filings
        self.business_structure = business_structure
        self.shareholders = shareholders
        self.analyst_expectations = analyst_expectations
        self.fundamentals = fundamentals
        self.us_fundamentals = us_fundamentals
        self.earnings_quality = earnings_quality
        self.financial_drivers = financial_drivers
        self.peer_comparison = peer_comparison
        self.outlook_calibration = outlook_calibration
        self.research_reports = research_reports
        self.research_outcomes = research_outcomes
        self.market_news = market_news
        self.evidence_tasks = evidence_tasks
        self.data_health = data_health
        self.broker = broker
        self.settings = settings
        self.tushare_snapshots = tushare_snapshots
        self.li_zong_strategy = li_zong_strategy
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not self.settings.background_jobs_enabled or self.is_running:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name="qingshu-background-scheduler",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10)

    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.settings.background_jobs_enabled,
            "running": self.is_running,
            "market_refresh_seconds": self.settings.background_market_refresh_seconds,
            "article_check_seconds": self.settings.background_article_check_seconds,
            "a_share_info_refresh_seconds": self.settings.background_info_refresh_seconds,
            "a_share_filing_refresh_seconds": self.settings.background_fundamentals_refresh_seconds,
            "business_structure_refresh_seconds": self.settings.background_fundamentals_refresh_seconds,
            "shareholder_structure_refresh_seconds": self.settings.background_fundamentals_refresh_seconds,
            "analyst_expectations_refresh_seconds": self.settings.background_fundamentals_refresh_seconds,
            "fundamentals_refresh_seconds": self.settings.background_fundamentals_refresh_seconds,
            "us_fundamentals_refresh_seconds": self.settings.background_fundamentals_refresh_seconds,
            "earnings_quality_refresh_seconds": self.settings.background_fundamentals_refresh_seconds,
            "financial_driver_refresh_seconds": self.settings.background_fundamentals_refresh_seconds,
            "peer_valuation_refresh_seconds": self.settings.background_fundamentals_refresh_seconds,
            "research_refresh_seconds": self.settings.background_research_refresh_seconds,
            "research_outcome_refresh_seconds": self.settings.background_research_refresh_seconds,
            "market_news_refresh_seconds": self.settings.background_market_news_refresh_seconds,
            "evidence_task_refresh_seconds": self.settings.background_research_refresh_seconds,
            "calibration_refresh_seconds": self.settings.background_calibration_refresh_seconds,
            "data_quality_seconds": self.settings.background_data_quality_seconds,
            "article_uses_hermes": self.settings.background_use_hermes
            and self.settings.hermes_enabled,
            "li_zong_strategy_enabled": bool(
                self.tushare_snapshots is not None
                and self.tushare_snapshots.client is not None
                and self.li_zong_strategy is not None
            ),
            "li_zong_refresh_seconds": self.settings.background_fundamentals_refresh_seconds,
            "latest_jobs": self.database.latest_background_jobs(),
        }

    def _loop(self) -> None:
        next_market = 0.0
        next_article = 0.0
        next_info = 0.0
        next_filings = 0.0
        next_business_structure = 0.0
        next_shareholders = 0.0
        next_analyst_expectations = 0.0
        next_fundamentals = 0.0
        next_us_fundamentals = 0.0
        next_earnings_quality = 0.0
        next_financial_drivers = 0.0
        next_peer_valuation = 0.0
        next_research = 0.0
        next_research_outcomes = 0.0
        next_market_news = 0.0
        next_evidence_tasks = 0.0
        next_calibration = 0.0
        next_data_quality = 0.0
        next_li_zong = (
            0.0
            if self.tushare_snapshots is not None
            and self.tushare_snapshots.client is not None
            and self.li_zong_strategy is not None
            else float("inf")
        )
        while not self._stop.is_set():
            now = time.monotonic()
            if now >= next_market:
                self._run_job("market_intraday_refresh", self._refresh_markets)
                next_market = time.monotonic() + max(
                    10, self.settings.background_market_refresh_seconds
                )
            if now >= next_article:
                self._run_job("market_pulse_article", self._refresh_article)
                next_article = time.monotonic() + max(
                    60, self.settings.background_article_check_seconds
                )
            if now >= next_info:
                self._run_job("a_share_information_refresh", self._refresh_a_share_information)
                next_info = time.monotonic() + max(
                    60, self.settings.background_info_refresh_seconds
                )
            if now >= next_filings:
                self._run_job(
                    "a_share_filing_refresh", self._refresh_a_share_filings
                )
                next_filings = time.monotonic() + max(
                    300, self.settings.background_fundamentals_refresh_seconds
                )
            if now >= next_business_structure:
                self._run_job(
                    "business_structure_refresh",
                    self._refresh_business_structure,
                )
                next_business_structure = time.monotonic() + max(
                    300, self.settings.background_fundamentals_refresh_seconds
                )
            if now >= next_shareholders:
                self._run_job(
                    "shareholder_structure_refresh",
                    self._refresh_shareholders,
                )
                next_shareholders = time.monotonic() + max(
                    300, self.settings.background_fundamentals_refresh_seconds
                )
            if now >= next_analyst_expectations:
                self._run_job(
                    "analyst_expectations_refresh",
                    self._refresh_analyst_expectations,
                )
                next_analyst_expectations = time.monotonic() + max(
                    300, self.settings.background_fundamentals_refresh_seconds
                )
            if now >= next_fundamentals:
                self._run_job(
                    "a_share_fundamentals_refresh", self._refresh_a_share_fundamentals
                )
                next_fundamentals = time.monotonic() + max(
                    300, self.settings.background_fundamentals_refresh_seconds
                )
            if now >= next_us_fundamentals:
                self._run_job(
                    "us_equity_fundamentals_refresh",
                    self._refresh_us_equity_fundamentals,
                )
                next_us_fundamentals = time.monotonic() + max(
                    300, self.settings.background_fundamentals_refresh_seconds
                )
            if now >= next_earnings_quality:
                self._run_job(
                    "earnings_quality_refresh", self._refresh_earnings_quality
                )
                next_earnings_quality = time.monotonic() + max(
                    300, self.settings.background_fundamentals_refresh_seconds
                )
            if now >= next_financial_drivers:
                self._run_job(
                    "financial_driver_refresh", self._refresh_financial_drivers
                )
                next_financial_drivers = time.monotonic() + max(
                    300, self.settings.background_fundamentals_refresh_seconds
                )
            if now >= next_peer_valuation:
                self._run_job(
                    "peer_valuation_refresh", self._refresh_peer_valuations
                )
                next_peer_valuation = time.monotonic() + max(
                    300, self.settings.background_fundamentals_refresh_seconds
                )
            if now >= next_calibration:
                self._run_job(
                    "outlook_calibration_refresh", self._refresh_outlook_calibrations
                )
                next_calibration = time.monotonic() + max(
                    1800, self.settings.background_calibration_refresh_seconds
                )
            if now >= next_research:
                self._run_job(
                    "stock_research_reports_refresh", self._refresh_research_reports
                )
                next_research = time.monotonic() + max(
                    300, self.settings.background_research_refresh_seconds
                )
            if now >= next_research_outcomes:
                self._run_job(
                    "research_outcomes_backfill", self._refresh_research_outcomes
                )
                next_research_outcomes = time.monotonic() + max(
                    300, self.settings.background_research_refresh_seconds
                )
            if now >= next_market_news:
                self._run_job("market_news_refresh", self._refresh_market_news)
                next_market_news = time.monotonic() + max(
                    300, self.settings.background_market_news_refresh_seconds
                )
            if now >= next_evidence_tasks:
                self._run_job(
                    "evidence_tasks_process", self._process_evidence_tasks
                )
                next_evidence_tasks = time.monotonic() + max(
                    60, self.settings.background_research_refresh_seconds
                )
            if now >= next_data_quality:
                self._run_job("data_quality_audit", self._refresh_data_health)
                next_data_quality = time.monotonic() + max(
                    30, self.settings.background_data_quality_seconds
                )
            if (
                now >= next_li_zong
                and self.tushare_snapshots is not None
                and self.tushare_snapshots.client is not None
                and self.li_zong_strategy is not None
            ):
                self._run_job(
                    "li_zong_strategy_refresh", self._refresh_li_zong_strategy
                )
                next_li_zong = time.monotonic() + max(
                    1800, self.settings.background_fundamentals_refresh_seconds
                )
            next_due = min(
                next_market,
                next_article,
                next_info,
                next_filings,
                next_business_structure,
                next_shareholders,
                next_analyst_expectations,
                next_fundamentals,
                next_us_fundamentals,
                next_earnings_quality,
                next_financial_drivers,
                next_peer_valuation,
                next_calibration,
                next_research,
                next_research_outcomes,
                next_market_news,
                next_evidence_tasks,
                next_data_quality,
                next_li_zong,
            )
            self._stop.wait(timeout=max(0.5, min(5.0, next_due - time.monotonic())))

    def _run_job(self, job_name: str, function: Callable[[], dict[str, Any]]) -> None:
        job_id = self.database.start_background_job(job_name)
        try:
            summary = function()
            self.database.finish_background_job(job_id, "completed", summary=summary)
        except Exception as exc:
            self.database.finish_background_job(
                job_id,
                "failed",
                error=f"{type(exc).__name__}: {exc}",
            )

    def _refresh_markets(self) -> dict[str, Any]:
        result = self.live_markets.snapshot()
        breadth = self.market_analysis.market_breadth()
        self.broker.publish(
            {
                "type": "market_updated",
                "time": result["generated_at"],
                "coverage": result["coverage"],
            }
        )
        return {
            **result["coverage"],
            "a_share_breadth_status": breadth.get("status"),
            "a_share_breadth": breadth.get("breadth") or {},
            "a_share_turnover": breadth.get("turnover") or {},
            "a_share_distribution": breadth.get("distribution") or {},
        }

    def _refresh_li_zong_strategy(self) -> dict[str, Any]:
        if self.tushare_snapshots is None or self.li_zong_strategy is None:
            return {"status": "disabled"}
        symbols: list[str] = []
        for raw in (
            *self.settings.default_a_share_symbols,
            *self.settings.default_research_symbols,
        ):
            try:
                symbol = normalize_symbol(raw)
            except ValueError:
                continue
            if symbol.endswith((".SS", ".SZ")) and symbol not in symbols:
                symbols.append(symbol)
        if not symbols:
            return {"status": "empty", "processed": 0}
        sync_results = []
        for symbol in symbols:
            try:
                result = self.tushare_snapshots.sync_symbol(symbol)
                sync_results.append(
                    {
                        "symbol": symbol,
                        "status": (result.get("run") or {}).get("status"),
                        "published": bool(result.get("published")),
                        "previous_stable_retained": bool(
                            result.get("previous_stable_retained")
                        ),
                    }
                )
            except Exception as exc:
                sync_results.append(
                    {
                        "symbol": symbol,
                        "status": "unavailable",
                        "error_type": type(exc).__name__,
                    }
                )
        strategy = self.li_zong_strategy.run_symbols(symbols)
        self.broker.publish(
            {
                "type": "stock_strategy_updated",
                "strategy_id": "li_zong",
                "time": utc_now(),
                "counts": strategy.get("counts") or {},
            }
        )
        return {
            "status": (strategy.get("run") or {}).get("status"),
            "processed": (strategy.get("counts") or {}).get("processed", 0),
            "counts": strategy.get("counts") or {},
            "sync_results": sync_results,
        }

    def _refresh_article(self) -> dict[str, Any]:
        result = self.articles.generate(
            model_tier="economy",
            execute_agent=self.settings.background_use_hermes
            and self.settings.hermes_enabled,
            force=False,
        )
        article = result.get("article") or {}
        if result["decision"] == "published":
            self.broker.publish(
                {
                    "type": "article_published",
                    "time": article.get("created_at") or utc_now(),
                    "article": {
                        "id": article.get("id"),
                        "title": article.get("title"),
                        "summary": article.get("summary"),
                    },
                }
            )
        return {
            "decision": result["decision"],
            "reason": result["reason"],
            "article_id": article.get("id"),
            "quality": result.get("quality"),
        }

    def _refresh_a_share_information(self) -> dict[str, Any]:
        symbols = list(self.settings.default_a_share_symbols)
        symbols.extend(
            symbol
            for symbol in self.database.list_distinct_watchlist_symbols()
            if symbol.endswith((".SS", ".SZ"))
        )
        result = self.china_info.refresh_symbols(symbols)
        timeline_result = self.event_timeline.refresh_symbols(
            symbols, refresh_sources=False
        )
        self.broker.publish(
            {
                "type": "a_share_information_updated",
                "time": utc_now(),
                "completed": result["completed"],
                "requested": result["requested"],
            }
        )
        return {
            "requested": result["requested"],
            "completed": result["completed"],
            "symbols": [item.get("symbol") for item in result["results"]],
            "event_timelines": {
                "requested": timeline_result["requested"],
                "completed": timeline_result["completed"],
            },
        }

    def _refresh_a_share_fundamentals(self) -> dict[str, Any]:
        symbols = list(self.settings.default_a_share_symbols)
        symbols.extend(
            symbol
            for symbol in self.database.list_distinct_watchlist_symbols()
            if symbol.endswith((".SS", ".SZ"))
        )
        result = self.fundamentals.refresh_symbols(symbols)
        self.broker.publish(
            {
                "type": "a_share_fundamentals_updated",
                "time": utc_now(),
                "completed": result["completed"],
                "requested": result["requested"],
            }
        )
        return {
            "requested": result["requested"],
            "completed": result["completed"],
            "symbols": [item.get("symbol") for item in result["results"]],
        }

    def _refresh_business_structure(self) -> dict[str, Any]:
        symbols = list(self.settings.default_a_share_symbols)
        symbols.extend(
            symbol
            for symbol in self.settings.default_research_symbols
            if symbol.endswith((".SS", ".SZ"))
        )
        symbols.extend(
            symbol
            for symbol in self.database.list_distinct_watchlist_symbols()
            if symbol.endswith((".SS", ".SZ"))
        )
        result = self.business_structure.refresh_symbols(symbols)
        self.broker.publish(
            {
                "type": "business_structure_updated",
                "time": utc_now(),
                "completed": result["completed"],
                "requested": result["requested"],
            }
        )
        return {
            "requested": result["requested"],
            "completed": result["completed"],
            "symbols": [item.get("symbol") for item in result["results"]],
            "rows": sum(
                int(item.get("rows_saved") or 0) for item in result["results"]
            ),
        }

    def _refresh_shareholders(self) -> dict[str, Any]:
        symbols = list(self.settings.default_a_share_symbols)
        symbols.extend(
            symbol
            for symbol in self.settings.default_research_symbols
            if symbol.endswith((".SS", ".SZ"))
        )
        symbols.extend(
            symbol
            for symbol in self.database.list_distinct_watchlist_symbols()
            if symbol.endswith((".SS", ".SZ"))
        )
        result = self.shareholders.refresh_symbols(symbols)
        self.broker.publish(
            {
                "type": "shareholder_structure_updated",
                "time": utc_now(),
                "completed": result["completed"],
                "requested": result["requested"],
            }
        )
        return {
            "requested": result["requested"],
            "completed": result["completed"],
            "symbols": [item.get("symbol") for item in result["results"]],
        }

    def _refresh_analyst_expectations(self) -> dict[str, Any]:
        symbols = list(self.settings.default_a_share_symbols)
        symbols.extend(
            symbol
            for symbol in self.settings.default_research_symbols
            if symbol.endswith((".SS", ".SZ"))
        )
        symbols.extend(
            symbol
            for symbol in self.database.list_distinct_watchlist_symbols()
            if symbol.endswith((".SS", ".SZ"))
        )
        result = self.analyst_expectations.refresh_symbols(symbols)
        industries = set()
        for symbol in sorted(set(symbols)):
            snapshot = self.database.latest_analyst_expectation_snapshot(symbol)
            industry = str(
                ((snapshot or {}).get("payload") or {}).get("industry") or ""
            ).strip()
            if industry:
                industries.add(industry)
        industry_results = []
        for industry in sorted(industries):
            snapshot = self.market_analysis.industry_snapshot(industry)
            latest_market_date = str(
                ((snapshot.get("points") or [{}])[-1]).get("market_date")
                or ""
            ).strip()
            if snapshot.get("status") == "available" and latest_market_date:
                snapshot = self.market_analysis.industry_snapshot(
                    industry, market_date=latest_market_date
                )
            industry_results.append(snapshot)
        self.broker.publish(
            {
                "type": "analyst_expectations_updated",
                "time": utc_now(),
                "completed": result["completed"],
                "requested": result["requested"],
            }
        )
        return {
            "requested": result["requested"],
            "completed": result["completed"],
            "symbols": [item.get("symbol") for item in result["results"]],
            "industry_indices": {
                "requested": len(industry_results),
                "available": sum(
                    item.get("status") == "available"
                    for item in industry_results
                ),
                "items": [
                    {
                        "industry_name": item.get("industry_name"),
                        "index_code": item.get("index_code"),
                        "status": item.get("status"),
                        "mapping_type": (
                            item.get("industry_mapping") or {}
                        ).get("match_type"),
                        "component_status": (
                            item.get("component_analysis") or {}
                        ).get("status"),
                        "component_coverage": (
                            (item.get("component_analysis") or {}).get(
                                "coverage"
                            )
                            or {}
                        ),
                        "component_failures": [
                            {
                                "symbol": failure.get("symbol"),
                                "name": failure.get("name"),
                                "reason_code": failure.get("reason_code"),
                                "reason": failure.get("reason"),
                            }
                            for failure in (
                                (item.get("component_analysis") or {}).get(
                                    "failures"
                                )
                                or []
                            )[:5]
                        ],
                    }
                    for item in industry_results
                ],
            },
        }

    def _refresh_a_share_filings(self) -> dict[str, Any]:
        symbols = list(self.settings.default_a_share_symbols)
        symbols.extend(
            symbol
            for symbol in self.settings.default_research_symbols
            if symbol.endswith((".SS", ".SZ"))
        )
        symbols.extend(
            symbol
            for symbol in self.database.list_distinct_watchlist_symbols()
            if symbol.endswith((".SS", ".SZ"))
        )
        result = self.filings.refresh_symbols(symbols, limit=3)
        self.broker.publish(
            {
                "type": "a_share_filings_updated",
                "time": utc_now(),
                "completed": result["completed"],
                "requested": result["requested"],
            }
        )
        return {
            "requested": result["requested"],
            "completed": result["completed"],
            "symbols": [item.get("symbol") for item in result["results"]],
            "documents": sum(
                int(item.get("completed") or 0) for item in result["results"]
            ),
        }

    def _refresh_us_equity_fundamentals(self) -> dict[str, Any]:
        symbols = [
            symbol
            for symbol in self.settings.default_research_symbols
            if not symbol.endswith((".SS", ".SZ"))
        ]
        symbols.extend(
            symbol
            for symbol in self.database.list_distinct_watchlist_symbols()
            if not symbol.endswith((".SS", ".SZ"))
        )
        result = self.us_fundamentals.refresh_symbols(symbols)
        self.broker.publish(
            {
                "type": "us_equity_fundamentals_updated",
                "time": utc_now(),
                "completed": result["completed"],
                "requested": result["requested"],
            }
        )
        return {
            "requested": result["requested"],
            "completed": result["completed"],
            "symbols": [item.get("symbol") for item in result["results"]],
        }

    def _refresh_peer_valuations(self) -> dict[str, Any]:
        result = self.peer_comparison.refresh_symbols(
            list(self.settings.default_research_symbols)
        )
        operating_completed = sum(
            item.get("operating_status") in {"available", "partial"}
            for item in result["results"]
        )
        self.broker.publish(
            {
                "type": "peer_valuations_updated",
                "time": utc_now(),
                "completed": result["completed"],
                "requested": result["requested"],
                "operating_completed": operating_completed,
            }
        )
        return {
            "requested": result["requested"],
            "completed": result["completed"],
            "operating_completed": operating_completed,
            "symbols": [item.get("symbol") for item in result["results"]],
        }

    def _refresh_earnings_quality(self) -> dict[str, Any]:
        symbols = list(self.settings.default_research_symbols)
        symbols.extend(self.database.list_distinct_watchlist_symbols())
        result = self.earnings_quality.refresh_symbols(symbols)
        self.broker.publish(
            {
                "type": "earnings_quality_updated",
                "time": utc_now(),
                "completed": result["completed"],
                "requested": result["requested"],
            }
        )
        return {
            "requested": result["requested"],
            "completed": result["completed"],
            "symbols": [item.get("symbol") for item in result["results"]],
        }

    def _refresh_financial_drivers(self) -> dict[str, Any]:
        symbols = list(self.settings.default_research_symbols)
        symbols.extend(self.database.list_distinct_watchlist_symbols())
        result = self.financial_drivers.refresh_symbols(symbols)
        self.broker.publish(
            {
                "type": "financial_drivers_updated",
                "time": utc_now(),
                "completed": result["completed"],
                "requested": result["requested"],
            }
        )
        return {
            "requested": result["requested"],
            "completed": result["completed"],
            "symbols": [item.get("symbol") for item in result["results"]],
        }

    def _refresh_research_reports(self) -> dict[str, Any]:
        result = self.research_reports.refresh_targets()
        self.broker.publish(
            {
                "type": "research_reports_updated",
                "time": utc_now(),
                "completed": result["completed"],
                "requested": result["requested"],
            }
        )
        return {
            "requested": result["requested"],
            "completed": result["completed"],
            "symbols": [item.get("symbol") for item in result["results"]],
        }

    def _refresh_research_outcomes(self) -> dict[str, Any]:
        result = self.research_outcomes.backfill(limit=1000)
        self.broker.publish(
            {
                "type": "research_outcomes_updated",
                "time": result["generated_at"],
                "updated": result["updated"],
                "available": result["available"],
            }
        )
        return {
            "reports_scanned": result["reports_scanned"],
            "outcomes_scanned": result["outcomes_scanned"],
            "updated": result["updated"],
            "available": result["available"],
            "pending": result["pending"],
            "unavailable": result["unavailable"],
            "data_as_of": result.get("data_as_of"),
        }

    def _refresh_outlook_calibrations(self) -> dict[str, Any]:
        result = self.outlook_calibration.refresh_symbols(
            list(self.settings.default_research_symbols)
        )
        self.broker.publish(
            {
                "type": "outlook_calibrations_updated",
                "time": utc_now(),
                "completed": result["completed"],
                "requested": result["requested"],
            }
        )
        return {
            "requested": result["requested"],
            "completed": result["completed"],
            "symbols": [item.get("symbol") for item in result["results"]],
        }

    def _refresh_market_news(self) -> dict[str, Any]:
        queries = (
            "美股收盘怎么样",
            "A股今天市场怎么样",
            "港股恒生指数怎么样",
            "日经指数怎么样",
            "KOSPI 韩国股市怎么样",
            "欧洲股市 STOXX 怎么样",
            "伦敦金现在怎么样",
        )
        packets = [self.market_news.get_packet(query, limit=12) for query in queries]
        completed = sum(bool(packet.get("items")) for packet in packets)
        self.broker.publish(
            {
                "type": "market_news_updated",
                "time": utc_now(),
                "completed": completed,
                "requested": len(queries),
            }
        )
        return {
            "requested": len(queries),
            "completed": completed,
            "markets": [packet.get("market_key") for packet in packets],
            "items": sum(len(packet.get("items") or []) for packet in packets),
        }

    def _process_evidence_tasks(self) -> dict[str, Any]:
        result = self.evidence_tasks.process_pending(limit=20)
        summary = result["summary"]
        if summary["processed"]:
            self.broker.publish(
                {
                    "type": "evidence_tasks_updated",
                    "time": result["generated_at"],
                    **summary,
                }
            )
        return summary

    def _refresh_data_health(self) -> dict[str, Any]:
        snapshot = self.data_health.audit()
        public = self.data_health.public_summary(snapshot)
        self.broker.publish(
            {
                "type": "data_health_updated",
                "time": snapshot["created_at"],
                "data_health": public,
            }
        )
        return {
            "status": snapshot["status"],
            **snapshot["summary"],
        }
