from __future__ import annotations

import json
import os
from queue import Empty, Full, Queue
import socket
import threading
import time
from typing import Any, Callable, Iterator
from uuid import uuid4

from app.config import Settings
from app.catalog import TODAY_INDEX_HISTORY_SYMBOLS
from app.db import Database
from app.operational_db import ClaimedJob, OperationalDatabase
from app.services.article import MarketPulseArticleService
from app.services.china_info import ChinaInformationService
from app.services.business_structure import BusinessStructureAnalysisService
from app.services.shareholders import ShareholderStructureAnalysisService
from app.services.analyst_expectations import AnalystExpectationsService
from app.services.calibration import OutlookCalibrationService
from app.services.fundamentals import FundamentalsService
from app.services.global_info import GlobalInformationService
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
from app.services.li_zong_history import LiZongHistoryService
from app.services.li_zong_portfolio_backtest import LiZongPortfolioBacktestService
from app.services.li_zong_strategy_service import LiZongStrategyService
from app.utils import utc_now


class EventBroker:
    def __init__(self):
        self._subscribers: set[Queue[dict[str, Any]]] = set()
        self._lock = threading.Lock()
        self._store: OperationalDatabase | None = None
        self._sequence_id = 0
        self._poll_stop = threading.Event()
        self._poll_thread: threading.Thread | None = None

    def attach_store(self, store: OperationalDatabase) -> None:
        self._store = store
        self._sequence_id = store.latest_event_sequence()

    def close(self) -> None:
        self._poll_stop.set()
        if self._poll_thread and self._poll_thread.is_alive():
            self._poll_thread.join(timeout=3)
        self._poll_thread = None

    def publish(self, event: dict[str, Any]) -> None:
        persisted = event
        if self._store is not None:
            try:
                persisted = self._store.publish_event(event)
            except Exception:
                persisted = event
        with self._lock:
            self._sequence_id = max(
                self._sequence_id, int(persisted.get("_sequence_id") or 0)
            )
        self._fanout(persisted)

    def _fanout(self, event: dict[str, Any]) -> None:
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

    def _ensure_poller(self) -> None:
        with self._lock:
            if self._store is None or (
                self._poll_thread is not None and self._poll_thread.is_alive()
            ):
                return
            self._poll_stop.clear()
            thread = threading.Thread(
                target=self._poll_events,
                name="qingshu-persistent-event-poller",
                daemon=True,
            )
            self._poll_thread = thread
        thread.start()

    def _poll_events(self) -> None:
        while not self._poll_stop.wait(timeout=1):
            with self._lock:
                has_subscribers = bool(self._subscribers)
                sequence_id = self._sequence_id
            if not has_subscribers or self._store is None:
                continue
            try:
                events = self._store.events_after(sequence_id)
            except Exception:
                continue
            for event in events:
                with self._lock:
                    self._sequence_id = max(
                        self._sequence_id, int(event["_sequence_id"])
                    )
                self._fanout(event)

    def stream(self) -> Iterator[str]:
        subscriber: Queue[dict[str, Any]] = Queue(maxsize=20)
        with self._lock:
            self._subscribers.add(subscriber)
        self._ensure_poller()
        try:
            yield f"data: {json.dumps({'type': 'connected', 'time': utc_now()}, ensure_ascii=False)}\n\n"
            while True:
                try:
                    event = subscriber.get(timeout=15)
                    public_event = dict(event)
                    public_event.pop("_sequence_id", None)
                    yield (f"data: {json.dumps(public_event, ensure_ascii=False)}\n\n")
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
        global_info: GlobalInformationService,
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
        stock_screener: Any | None = None,
        li_zong_strategy: LiZongStrategyService | None = None,
        li_zong_history: LiZongHistoryService | None = None,
        li_zong_backtest: LiZongPortfolioBacktestService | None = None,
        trade_workflow: Any | None = None,
        change_events: Any | None = None,
        fund_products: Any | None = None,
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
        self.global_info = global_info
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
        self.stock_screener = stock_screener
        self.li_zong_strategy = li_zong_strategy
        self.li_zong_history = li_zong_history
        self.li_zong_backtest = li_zong_backtest
        self.trade_workflow = trade_workflow
        self.change_events = change_events
        self.fund_products = fund_products
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._threads: list[threading.Thread] = []
        self._registered_worker_ids: set[str] = set()
        self._registered_worker_lock = threading.Lock()
        self.worker_id = (
            f"{socket.gethostname()}-{os.getpid()}-{str(uuid4()).split('-')[0]}"
        )
        self.job_store = OperationalDatabase(settings.operational_database_url)
        self.job_store.initialize()
        self.broker.attach_store(self.job_store)
        self.job_store.prune_events(retention_hours=48)
        self.job_store.prune_workers(retention_hours=168)
        self.job_store.recover_dead_local_workers()
        self._register_schedules()
        self.database.repair_background_job_runs_from_queue()

    def start(self) -> None:
        if (
            not self.settings.background_jobs_enabled
            or self.settings.background_worker_mode != "embedded"
            or self.is_running
        ):
            return
        self._stop.clear()
        self._threads = []
        for index in range(self.settings.job_worker_concurrency):
            thread = threading.Thread(
                target=self._worker_loop,
                args=(f"{self.worker_id}-t{index + 1}",),
                name=f"qingshu-persistent-worker-{index + 1}",
                daemon=True,
            )
            self._threads.append(thread)
            thread.start()
        self._thread = self._threads[0] if self._threads else None

    def run_forever(self) -> None:
        """Run the durable scheduler/worker loop in a dedicated process."""

        if (
            not self.settings.background_jobs_enabled
            or self.settings.background_worker_mode == "disabled"
        ):
            raise RuntimeError("Background jobs are disabled")
        self._stop.clear()
        self._register_schedules()
        if self.settings.job_worker_concurrency == 1:
            self._worker_loop(self.worker_id)
            return
        self._threads = []
        for index in range(self.settings.job_worker_concurrency):
            thread = threading.Thread(
                target=self._worker_loop,
                args=(f"{self.worker_id}-t{index + 1}",),
                name=f"qingshu-persistent-worker-{index + 1}",
                daemon=True,
            )
            self._threads.append(thread)
            thread.start()
        try:
            for thread in self._threads:
                thread.join()
        finally:
            self.stop()

    def run_once(self, worker_id: str | None = None) -> bool:
        """Schedule due work and execute at most one job."""

        self._register_schedules()
        self.job_store.enqueue_due_schedules()
        resolved_worker = worker_id or self.worker_id
        self._register_worker(resolved_worker)
        try:
            claimed = self.job_store.claim(
                resolved_worker,
                queue_name="background",
                lease_seconds=self.settings.job_lease_seconds,
            )
            if claimed is None:
                return False
            function = self._job_functions().get(claimed.job_name)
            if function is None:
                self.job_store.fail(
                    claimed.id,
                    resolved_worker,
                    f"unregistered_job:{claimed.job_name}",
                    retry_base_seconds=self.settings.job_retry_base_seconds,
                    retry_max_seconds=self.settings.job_retry_max_seconds,
                )
                self.job_store.mark_worker_job_finished(
                    resolved_worker, succeeded=False
                )
                return True
            self._execute_claimed_job(claimed, function, resolved_worker)
            return True
        finally:
            self._stop_worker(resolved_worker)

    def enqueue(
        self,
        job_name: str,
        *,
        payload: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        if job_name not in self._job_functions():
            raise KeyError(job_name)
        return self.job_store.enqueue(
            job_name,
            payload,
            queue_name="background",
            priority=100,
            max_attempts=self.settings.job_max_attempts,
            idempotency_key=idempotency_key,
        )

    def list_jobs(
        self, *, status: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        return self.job_store.list_jobs(status=status, limit=limit)

    def stop(self) -> None:
        self._stop.set()
        current = threading.current_thread()
        for thread in self._threads:
            if thread is not current and thread.is_alive():
                thread.join(timeout=10)
        self._threads = []
        self._thread = None
        with self._registered_worker_lock:
            worker_ids = list(self._registered_worker_ids)
        for worker_id in worker_ids:
            self._stop_worker(worker_id)

    @property
    def is_running(self) -> bool:
        return any(thread.is_alive() for thread in self._threads)

    def status(self) -> dict[str, Any]:
        queue_health = self.job_store.health(
            worker_stale_seconds=self.settings.job_worker_stale_seconds
        )
        active_workers = int(queue_health["workers"]["active"])
        return {
            "enabled": self.settings.background_jobs_enabled,
            "running": self.is_running or active_workers > 0,
            "worker_mode": self.settings.background_worker_mode,
            "worker_id": self.worker_id if self.is_running else None,
            "worker_concurrency": self.settings.job_worker_concurrency,
            "active_worker_count": active_workers,
            "persistent_queue": queue_health,
            "market_refresh_seconds": self.settings.background_market_refresh_seconds,
            "today_market_warmup_seconds": max(
                60, self.settings.background_market_refresh_seconds * 6
            ),
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
            "trade_review_refresh_seconds": self.settings.background_research_refresh_seconds,
            "change_event_refresh_seconds": self.settings.background_research_refresh_seconds,
            "market_news_refresh_seconds": self.settings.background_market_news_refresh_seconds,
            "fund_product_refresh_seconds": self.settings.background_fund_product_refresh_seconds,
            "evidence_task_refresh_seconds": self.settings.background_research_refresh_seconds,
            "calibration_refresh_seconds": self.settings.background_calibration_refresh_seconds,
            "data_quality_seconds": self.settings.background_data_quality_seconds,
            "article_uses_hermes": self.settings.background_use_hermes
            and self.settings.hermes_enabled,
            "li_zong_strategy_enabled": bool(self._li_zong_enabled),
            "stock_screener_snapshot_enabled": bool(
                self._stock_screener_snapshot_enabled
            ),
            "stock_screener_snapshot_refresh_seconds": (
                self.settings.background_stock_screener_snapshot_refresh_seconds
            ),
            "li_zong_worker_running": bool(
                (self.is_running or active_workers > 0) and self._li_zong_enabled
            ),
            "li_zong_refresh_seconds": self.settings.li_zong_refresh_seconds,
            "latest_jobs": self.database.latest_background_jobs(),
        }

    def _job_functions(self) -> dict[str, Callable[[], dict[str, Any]]]:
        functions: dict[str, Callable[[], dict[str, Any]]] = {
            "market_intraday_refresh": self._refresh_markets,
            "today_market_warmup": self._warm_today_markets,
            "market_pulse_article": self._refresh_article,
            "a_share_information_refresh": self._refresh_a_share_information,
            "a_share_filing_refresh": self._refresh_a_share_filings,
            "business_structure_refresh": self._refresh_business_structure,
            "shareholder_structure_refresh": self._refresh_shareholders,
            "analyst_expectations_refresh": self._refresh_analyst_expectations,
            "a_share_fundamentals_refresh": self._refresh_a_share_fundamentals,
            "us_equity_fundamentals_refresh": self._refresh_us_equity_fundamentals,
            "earnings_quality_refresh": self._refresh_earnings_quality,
            "financial_driver_refresh": self._refresh_financial_drivers,
            "peer_valuation_refresh": self._refresh_peer_valuations,
            "outlook_calibration_refresh": self._refresh_outlook_calibrations,
            "stock_research_reports_refresh": self._refresh_research_reports,
            "research_outcomes_backfill": self._refresh_research_outcomes,
            "market_news_refresh": self._refresh_market_news,
            "evidence_tasks_process": self._process_evidence_tasks,
            "data_quality_audit": self._refresh_data_health,
            "li_zong_strategy_refresh": self._refresh_li_zong_strategy,
            "li_zong_backtest_refresh": self._refresh_li_zong_backtest,
        }
        if self._stock_screener_snapshot_enabled:
            functions["stock_screener_market_snapshot_refresh"] = (
                self._refresh_stock_screener_market_snapshot
            )
        if self.trade_workflow is not None:
            functions["trade_reviews_readiness_refresh"] = (
                self.trade_workflow.refresh_pending_reviews
            )
        if self.fund_products is not None:
            functions["fund_product_refresh"] = self._refresh_fund_products
        return functions

    def _schedule_specs(self) -> list[tuple[str, int, int, bool]]:
        fundamentals = max(300, self.settings.background_fundamentals_refresh_seconds)
        research = max(300, self.settings.background_research_refresh_seconds)
        return [
            (
                "market_intraday_refresh",
                max(10, self.settings.background_market_refresh_seconds),
                100,
                True,
            ),
            (
                "today_market_warmup",
                max(60, self.settings.background_market_refresh_seconds * 6),
                85,
                True,
            ),
            (
                "market_pulse_article",
                max(60, self.settings.background_article_check_seconds),
                40,
                True,
            ),
            (
                "a_share_information_refresh",
                max(60, self.settings.background_info_refresh_seconds),
                70,
                True,
            ),
            ("a_share_filing_refresh", fundamentals, 50, True),
            ("business_structure_refresh", fundamentals, 45, True),
            ("shareholder_structure_refresh", fundamentals, 45, True),
            ("analyst_expectations_refresh", fundamentals, 45, True),
            ("a_share_fundamentals_refresh", fundamentals, 60, True),
            ("us_equity_fundamentals_refresh", fundamentals, 55, True),
            ("earnings_quality_refresh", fundamentals, 40, True),
            ("financial_driver_refresh", fundamentals, 40, True),
            ("peer_valuation_refresh", fundamentals, 40, True),
            (
                "outlook_calibration_refresh",
                max(1800, self.settings.background_calibration_refresh_seconds),
                30,
                True,
            ),
            ("stock_research_reports_refresh", research, 65, True),
            ("research_outcomes_backfill", research, 35, True),
            (
                "trade_reviews_readiness_refresh",
                max(60, self.settings.background_research_refresh_seconds),
                55,
                self.trade_workflow is not None,
            ),
            (
                "market_news_refresh",
                max(300, self.settings.background_market_news_refresh_seconds),
                75,
                True,
            ),
            (
                "fund_product_refresh",
                max(300, self.settings.background_fund_product_refresh_seconds),
                50,
                self.fund_products is not None,
            ),
            (
                "evidence_tasks_process",
                max(60, self.settings.background_research_refresh_seconds),
                70,
                True,
            ),
            (
                "data_quality_audit",
                max(30, self.settings.background_data_quality_seconds),
                90,
                True,
            ),
            (
                "li_zong_strategy_refresh",
                max(10, self.settings.li_zong_refresh_seconds),
                80,
                self._li_zong_enabled,
            ),
            (
                "stock_screener_market_snapshot_refresh",
                self.settings.background_stock_screener_snapshot_refresh_seconds,
                75,
                self._stock_screener_snapshot_enabled,
            ),
            (
                "li_zong_backtest_refresh",
                max(30, self.settings.li_zong_refresh_seconds * 2),
                35,
                self._li_zong_enabled and self.li_zong_backtest is not None,
            ),
        ]

    def _register_schedules(self) -> None:
        for job_name, interval, priority, enabled in self._schedule_specs():
            self.job_store.register_schedule(
                name=job_name,
                job_name=job_name,
                interval_seconds=interval,
                queue_name="background",
                priority=priority,
                max_attempts=self.settings.job_max_attempts,
                enabled=enabled
                and self.settings.background_jobs_enabled
                and self.settings.background_worker_mode != "disabled",
                run_immediately=True,
            )

    def _worker_loop(self, worker_id: str) -> None:
        functions = self._job_functions()
        self._register_worker(worker_id)
        last_worker_heartbeat = 0.0
        try:
            while not self._stop.is_set():
                current_monotonic = time.monotonic()
                if (
                    current_monotonic - last_worker_heartbeat
                    >= self.settings.job_worker_heartbeat_seconds
                ):
                    self.job_store.heartbeat_worker(worker_id)
                    last_worker_heartbeat = current_monotonic
                self.job_store.recover_dead_local_workers()
                self.job_store.enqueue_due_schedules()
                self.database.repair_background_job_runs_from_queue()
                claimed = self.job_store.claim(
                    worker_id,
                    queue_name="background",
                    lease_seconds=self.settings.job_lease_seconds,
                )
                if claimed is None:
                    self._stop.wait(timeout=self.settings.job_queue_poll_seconds)
                    continue
                function = functions.get(claimed.job_name)
                if function is None:
                    self.job_store.fail(
                        claimed.id,
                        worker_id,
                        f"unregistered_job:{claimed.job_name}",
                        retry_base_seconds=self.settings.job_retry_base_seconds,
                        retry_max_seconds=self.settings.job_retry_max_seconds,
                    )
                    self.job_store.mark_worker_job_finished(worker_id, succeeded=False)
                    continue
                self._execute_claimed_job(claimed, function, worker_id)
        finally:
            self._stop_worker(worker_id)

    def _register_worker(self, worker_id: str) -> None:
        self.job_store.register_worker(
            worker_id,
            queue_name="background",
            metadata={
                "mode": self.settings.background_worker_mode,
                "concurrency": self.settings.job_worker_concurrency,
            },
        )
        with self._registered_worker_lock:
            self._registered_worker_ids.add(worker_id)

    def _stop_worker(self, worker_id: str) -> None:
        self.job_store.stop_worker(worker_id)
        with self._registered_worker_lock:
            self._registered_worker_ids.discard(worker_id)

    def _execute_claimed_job(
        self,
        claimed: ClaimedJob,
        function: Callable[[], dict[str, Any]],
        worker_id: str,
    ) -> None:
        run_id = self.database.start_background_job(
            claimed.job_name,
            queue_job_id=claimed.id,
            worker_id=worker_id,
        )
        heartbeat_stop = threading.Event()
        self.job_store.mark_worker_job_started(worker_id, claimed.id)

        def keep_lease_alive() -> None:
            interval = min(
                max(1.0, self.settings.job_lease_seconds / 3),
                float(self.settings.job_worker_heartbeat_seconds),
            )
            while not heartbeat_stop.wait(timeout=interval):
                if not self.job_store.heartbeat(
                    claimed.id,
                    worker_id,
                    lease_seconds=self.settings.job_lease_seconds,
                ):
                    return
                self.job_store.heartbeat_worker(worker_id, current_job_id=claimed.id)

        heartbeat = threading.Thread(
            target=keep_lease_alive,
            name=f"qingshu-job-heartbeat-{claimed.id[:8]}",
            daemon=True,
        )
        heartbeat.start()
        try:
            summary = function()
            self.database.finish_background_job(run_id, "completed", summary=summary)
            if not self.job_store.complete(claimed.id, worker_id, summary):
                raise RuntimeError("job_lease_lost_before_completion")
            self.job_store.mark_worker_job_finished(worker_id, succeeded=True)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            self.database.finish_background_job(run_id, "failed", error=error)
            self.job_store.fail(
                claimed.id,
                worker_id,
                error,
                retry_base_seconds=self.settings.job_retry_base_seconds,
                retry_max_seconds=self.settings.job_retry_max_seconds,
            )
            self.job_store.mark_worker_job_finished(worker_id, succeeded=False)
        finally:
            heartbeat_stop.set()
            heartbeat.join(timeout=2)

    @property
    def _li_zong_enabled(self) -> bool:
        return bool(
            self.tushare_snapshots is not None
            and self.tushare_snapshots.client is not None
            and self.li_zong_strategy is not None
        )

    @property
    def _stock_screener_snapshot_enabled(self) -> bool:
        return bool(
            self.stock_screener is not None
            and getattr(self.stock_screener, "client", None) is not None
        )

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

    def _warm_today_markets(self) -> dict[str, Any]:
        """提前填充今日观察页依赖的行情缓存，让用户请求只读缓存。

        单个数据源失败只记入 errors，不让整个任务重试；缓存语义与
        对应 HTTP 端点一致（同一 service 方法、同一 provider 缓存键）。
        """

        analysis = self.market_analysis
        warmed: list[str] = []
        errors: list[str] = []

        def capture(label: str, fetch: Callable[[], dict[str, Any]]) -> None:
            try:
                fetch()
            except Exception as exc:  # noqa: BLE001 - 单项失败不阻塞其他预热
                errors.append(f"{label}: {exc}")
            else:
                warmed.append(label)

        capture("indices_china", lambda: analysis.get_indices(scope="all", group="china"))
        capture("indices_us", lambda: analysis.get_indices(scope="all", group="us"))
        for symbol in TODAY_INDEX_HISTORY_SYMBOLS:
            capture(
                f"index_history:{symbol}",
                lambda symbol=symbol: analysis.get_index_history(
                    symbol, range_name="1mo"
                ),
            )
        capture("sectors_hot", lambda: analysis.hot_sectors(limit=10))
        capture("market_anomalies", lambda: analysis.market_anomalies(limit=10))
        capture("capital_flow", analysis.capital_flow)
        return {
            "warmed": warmed,
            "warmed_count": len(warmed),
            "errors": errors,
            "time": utc_now(),
        }

    def _refresh_fund_products(self) -> dict[str, Any]:
        if self.fund_products is None:
            return {"status": "disabled"}
        result = self.fund_products.refresh_codes(
            list(self.settings.default_fund_product_codes)
        )
        self.broker.publish(
            {
                "type": "fund_products_updated",
                "time": utc_now(),
                "completed": result.get("completed", 0),
                "failed": result.get("failed", 0),
            }
        )
        return result

    def _refresh_li_zong_strategy(self) -> dict[str, Any]:
        if self.tushare_snapshots is None or self.li_zong_strategy is None:
            return {"status": "disabled"}
        strategy = self.li_zong_strategy.run_universe_batch(
            batch_size=self.settings.li_zong_universe_batch_size
        )
        history: dict[str, Any] | None = None
        if self.li_zong_history:
            active_symbols = list(strategy.get("selected_symbols") or [])
            history = self.li_zong_history.run_batch(
                batch_size=min(
                    2 if active_symbols else 5,
                    self.settings.li_zong_universe_batch_size,
                )
            )
        coverage = strategy.get("coverage") or {}
        counts = coverage.get("counts") or {}
        self.broker.publish(
            {
                "type": "stock_strategy_updated",
                "strategy_id": "li_zong",
                "time": utc_now(),
                "counts": counts,
                "coverage": coverage,
            }
        )
        return {
            "status": strategy.get("status"),
            "processed": len(strategy.get("selected_symbols") or []),
            "counts": counts,
            "coverage": coverage,
            "sync_results": strategy.get("sync_results") or [],
            "history": history,
        }

    def _refresh_stock_screener_market_snapshot(self) -> dict[str, Any]:
        if self.stock_screener is None:
            return {"status": "disabled", "published": False}
        result = self.stock_screener.refresh_persisted_market_snapshot()
        self.broker.publish(
            {
                "type": "stock_screener_snapshot_updated",
                "time": utc_now(),
                "status": result.get("status"),
                "published": bool(result.get("published")),
                "data_version": result.get("data_version"),
            }
        )
        return result

    def _refresh_li_zong_backtest(self) -> dict[str, Any]:
        if self.li_zong_backtest is None:
            return {"status": "disabled"}
        result = self.li_zong_backtest.refresh()
        self.broker.publish(
            {
                "type": "stock_strategy_backtest_updated",
                "strategy_id": "li_zong",
                "time": utc_now(),
                "status": result.get("status"),
                "periods": result.get("periods") or {},
            }
        )
        return result

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
            for symbol in self.settings.default_research_symbols
            if symbol.endswith((".SS", ".SZ"))
        )
        symbols.extend(
            symbol
            for symbol in self.database.list_distinct_watchlist_symbols()
            if symbol.endswith((".SS", ".SZ"))
        )
        symbols = sorted(set(symbols))
        result = self.china_info.refresh_symbols(symbols)
        timeline_result = self.event_timeline.refresh_symbols(
            symbols, refresh_sources=False
        )
        change_result = (
            self.change_events.refresh_all_users()
            if self.change_events is not None
            else None
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
            "information_results": [
                {
                    "symbol": item.get("symbol"),
                    "status": item.get("status"),
                    "refreshed_at": item.get("refreshed_at"),
                    "counts": item.get("counts") or {},
                    "sources": item.get("sources") or {},
                    "warning_count": len(item.get("warnings") or []),
                }
                for item in result["results"]
            ],
            "event_timelines": {
                "requested": timeline_result["requested"],
                "completed": timeline_result["completed"],
            },
            "change_events": (
                {
                    "requested_users": change_result["requested_users"],
                    "completed_users": change_result["completed_users"],
                }
                if change_result is not None
                else {"status": "not_configured"}
            ),
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
            "rows": sum(int(item.get("rows_saved") or 0) for item in result["results"]),
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
                ((snapshot.get("points") or [{}])[-1]).get("market_date") or ""
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
                    item.get("status") == "available" for item in industry_results
                ),
                "items": [
                    {
                        "industry_name": item.get("industry_name"),
                        "index_code": item.get("index_code"),
                        "status": item.get("status"),
                        "mapping_type": (item.get("industry_mapping") or {}).get(
                            "match_type"
                        ),
                        "component_status": (item.get("component_analysis") or {}).get(
                            "status"
                        ),
                        "component_coverage": (
                            (item.get("component_analysis") or {}).get("coverage") or {}
                        ),
                        "component_failures": [
                            {
                                "symbol": failure.get("symbol"),
                                "name": failure.get("name"),
                                "reason_code": failure.get("reason_code"),
                                "reason": failure.get("reason"),
                            }
                            for failure in (
                                (item.get("component_analysis") or {}).get("failures")
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
        symbols = sorted(set(symbols))
        result = self.us_fundamentals.refresh_symbols(symbols)
        fundamentals_by_symbol = {
            item.get("symbol"): item for item in result["results"]
        }
        information_results = []
        for symbol in symbols:
            fundamental_result = fundamentals_by_symbol.get(symbol) or {}
            sources = dict(fundamental_result.get("sources") or {})
            try:
                global_result = self.global_info.refresh_symbol(symbol)
                sources.update(global_result.get("sources") or {})
            except Exception as exc:
                sources["global_news"] = {
                    "status": "failed",
                    "items": 0,
                    "polled_at": utc_now(),
                    "error_type": type(exc).__name__,
                }
            source_states = [
                str((sources.get(key) or {}).get("status") or "missing")
                for key in ("regulatory_filing", "global_news")
            ]
            information_results.append(
                {
                    "symbol": symbol,
                    "status": (
                        "ok"
                        if all(state == "ok" for state in source_states)
                        else "partial"
                        if any(state == "ok" for state in source_states)
                        else "failed"
                    ),
                    "refreshed_at": utc_now(),
                    "sources": sources,
                    "warning_count": sum(state != "ok" for state in source_states),
                }
            )
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
            "information_completed": sum(
                item["status"] == "ok" for item in information_results
            ),
            "information_results": information_results,
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
        change_result = (
            self.change_events.refresh_all_users()
            if self.change_events is not None
            else None
        )
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
            "change_events": (
                {
                    "requested_users": change_result["requested_users"],
                    "completed_users": change_result["completed_users"],
                }
                if change_result is not None
                else {"status": "not_configured"}
            ),
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
        packets = [
            self.market_news.get_packet(query, limit=12, force_refresh=True)
            for query in queries
        ]
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
        pruned_events = self.job_store.prune_events(retention_hours=48)
        pruned_workers = self.job_store.prune_workers(retention_hours=168)
        pruned_jobs = self.job_store.prune_terminal_jobs(
            succeeded_retention_hours=(self.settings.job_succeeded_retention_hours),
            failed_retention_hours=self.settings.job_failed_retention_hours,
            cancelled_retention_hours=(self.settings.job_cancelled_retention_hours),
        )
        pruned_domain_history = self.database.prune_background_history(
            completed_retention_hours=(
                self.settings.background_run_completed_retention_hours
            ),
            failed_retention_hours=(
                self.settings.background_run_failed_retention_hours
            ),
            data_health_retention_hours=(self.settings.data_health_retention_hours),
        )
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
            "events_pruned": pruned_events,
            "workers_pruned": pruned_workers,
            "terminal_jobs_pruned": pruned_jobs,
            "domain_history_pruned": pruned_domain_history,
            **snapshot["summary"],
        }
