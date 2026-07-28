from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta
import hashlib
import json
import math
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

import pandas as pd

from app.catalog import normalize_symbol
from app.db import Database
from app.providers.tushare import TushareClient
from app.services.li_zong_strategy_service import LiZongStrategyService
from app.services.tushare_snapshots import TushareSnapshotService
from app.services.strategies.li_zong import (
    STRATEGY_ID,
    STRATEGY_VERSION,
    LiZongParameters,
    _prepare_daily,
    _roe_rule,
    _shareholder_rule,
    deterministic_li_zong_v1,
)
from app.utils import utc_now


class LiZongPortfolioBacktestService:
    """Point-in-time equal-weight portfolio backtest for Li Zong v1."""

    BACKTEST_VERSION = "li_zong_equal_weight_v1"
    CALENDAR_DATASET = "li_zong_backtest_calendar"
    BENCHMARK_DATASET = "li_zong_backtest_benchmark"
    RESULT_DATASET = "li_zong_portfolio_backtest"
    STABLE_INPUT_DATASET = "li_zong_inputs"
    INCOMPLETE_INPUT_DATASET = "li_zong_inputs_incomplete"
    BENCHMARK_SYMBOL = "000300.SS"
    BENCHMARK_NAME = "沪深300"
    PERIOD_DAYS = {"3m": 63, "1y": 252, "3y": 756}
    PERIOD_LABELS = {"3m": "近3个月", "1y": "近1年", "3y": "近3年"}
    WARMUP_TRADING_DAYS = 380
    MARKET_CAP_MIN_YI = LiZongParameters().market_cap_min_yi
    COST_BPS_PER_SIDE = 0.0
    MIN_REBALANCE_TRADING_DAYS = 10
    PORTFOLIO_VERSION = "li_zong_2w_no_cost_same_exposure_v4"
    TARGET_HISTORY_MARKET_DAYS = 1150
    STATE_INPUT_VERSION = "ready_market_window_v3_tail_gap_strict"
    DEFAULT_MARKET_DAY_BATCH_SIZE = 30
    DEFAULT_SYMBOL_BATCH_SIZE = 100
    DEFAULT_INPUT_SYNC_BATCH_SIZE = 12
    MAX_INPUT_SYNC_WORKERS = 4
    COMPLETE_SESSION_CUTOFF = time(16, 30)
    MIN_MARKET_CAP_UNIVERSE_COUNT = 1_000
    MIN_MARKET_CAP_VALUE_COVERAGE = 0.95
    SOURCE = "Tushare Pro:trade_cal+daily_basic+index_daily"

    BOUNDARY = (
        "回测严格使用每个历史交易日当时已公告的财务与股东数据、当日历史市值，"
        "以及当日及以前的量价数据。候选集合变化后，最早在下一完整交易日开盘"
        "执行，但任意两次实际换仓至少间隔10个交易日；冷却期内只保留最新候选"
        "集合。本版不计交易成本。沪深300只在策略实际持仓期间保持同等市场暴露，"
        "策略空仓期间基准同步冻结，不计入相对收益比较。尚未模拟涨跌停"
        "排队、停牌后的实际成交、冲击"
        "成本、分红税和真实佣金阶梯；已明确退市的股票使用最后可得复权收盘价"
        "作为强制退出代理。结果只用于验证规则历史表现，不构成收益承诺或投资建议。"
    )

    def __init__(
        self,
        database: Database,
        snapshot_service: Any,
        strategy_service: LiZongStrategyService,
    ) -> None:
        self.database = database
        self.snapshot_service = snapshot_service
        self.strategy_service = strategy_service

    @property
    def client(self) -> Any | None:
        return getattr(self.snapshot_service, "client", None)

    def refresh(
        self,
        *,
        market_day_batch_size: int = DEFAULT_MARKET_DAY_BATCH_SIZE,
        symbol_batch_size: int = DEFAULT_SYMBOL_BATCH_SIZE,
        input_sync_batch_size: int = DEFAULT_INPUT_SYNC_BATCH_SIZE,
        as_of_date: str | None = None,
    ) -> dict[str, Any]:
        if self.client is None:
            return {"status": "disabled", "periods": self._progress_packet()}
        market_batch = max(1, min(int(market_day_batch_size), 30))
        symbol_batch = max(1, min(int(symbol_batch_size), 200))
        sync_batch = max(0, min(int(input_sync_batch_size), 12))
        trade_dates = self._target_trade_dates(as_of_date)
        if not trade_dates:
            return {"status": "unavailable", "periods": self._progress_packet()}

        sync_run = self.database.start_tushare_sync_run(
            job_scope="li_zong_portfolio_backtest",
            as_of_date=trade_dates[-1],
            datasets=[
                self.CALENDAR_DATASET,
                "strategy_backtest_market_caps",
                "strategy_backtest_symbol_states",
                self.BENCHMARK_DATASET,
                self.RESULT_DATASET,
            ],
        )
        run_id = str(sync_run["id"])
        summary: dict[str, Any] = {
            "market_cap_days_added": 0,
            "symbols_evaluated": [],
            "symbols_synced": [],
            "periods_published": [],
        }
        try:
            self._save_calendar(trade_dates, sync_run_id=run_id)
            summary["market_cap_days_added"] = self._refresh_market_cap_days(
                trade_dates,
                batch_size=market_batch,
            )
            ready_windows = self._ready_period_windows(trade_dates)
            if ready_windows:
                required_start = min(window[0] for window in ready_windows.values())
                required_end = trade_dates[-1]
                evaluation_trade_dates = [
                    value
                    for value in trade_dates
                    if required_start <= value <= required_end
                ]
                market_cap_data_version = self._market_cap_window_version(
                    evaluation_trade_dates
                )
                priority_windows: list[dict[str, Any]] = []
                required_symbols: list[str] = []
                seen_symbols: set[str] = set()
                for period in self.PERIOD_DAYS:
                    window = ready_windows.get(period)
                    if window is None:
                        continue
                    window_symbols = (
                        self.database.list_strategy_backtest_eligible_symbols(
                            strategy_id=STRATEGY_ID,
                            backtest_version=self.BACKTEST_VERSION,
                            start_date=window[0],
                            end_date=window[1],
                        )
                    )
                    priority_windows.append(
                        {
                            "period": period,
                            "start_date": window[0],
                            "end_date": window[1],
                            "symbols": set(window_symbols),
                        }
                    )
                    for symbol in window_symbols:
                        if symbol in seen_symbols:
                            continue
                        seen_symbols.add(symbol)
                        required_symbols.append(symbol)
                evaluated, synced = self._advance_symbol_states(
                    required_symbols,
                    trade_dates=evaluation_trade_dates,
                    required_start=required_start,
                    market_cap_data_version=market_cap_data_version,
                    symbol_batch_size=symbol_batch,
                    input_sync_batch_size=sync_batch,
                    priority_windows=priority_windows,
                )
                summary["symbols_evaluated"] = evaluated
                summary["symbols_synced"] = synced
                self._ensure_benchmark(trade_dates, sync_run_id=run_id)
                for period, (start_date, end_date) in ready_windows.items():
                    result = self._publish_period_if_complete(
                        period,
                        start_date=start_date,
                        end_date=end_date,
                        sync_run_id=run_id,
                    )
                    if result is not None:
                        summary["periods_published"].append(period)
            packet = self._progress_packet()
            status = (
                "stable"
                if all(
                    item.get("status") == "ready"
                    for item in (packet.get("periods") or {}).values()
                )
                else "partial"
            )
            version = self._fingerprint({"summary": summary, "packet": packet})
            self.database.finish_tushare_sync_run(
                run_id,
                status=status,
                data_version=version,
                summary=summary,
            )
            return {"status": status, **summary, **packet}
        except Exception as exc:
            self.database.finish_tushare_sync_run(
                run_id,
                status="failed",
                data_version=None,
                summary=summary,
                error=f"{type(exc).__name__}: portfolio backtest refresh unavailable",
            )
            return {
                "status": "failed",
                "error_type": type(exc).__name__,
                **summary,
                **self._progress_packet(),
            }

    def packet(self, *, period: str = "1y") -> dict[str, Any]:
        resolved = self._period(period)
        progress = self._progress_packet()
        snapshot = self.database.latest_tushare_dataset_snapshot(
            self.RESULT_DATASET,
            resolved,
            stable_only=True,
        )
        stored_result = (snapshot or {}).get("payload") or None
        result = (
            stored_result
            if stored_result
            and stored_result.get("state_input_version") == self.STATE_INPUT_VERSION
            and stored_result.get("portfolio_version") == self.PORTFOLIO_VERSION
            else None
        )
        period_progress = (progress.get("periods") or {}).get(resolved) or {}
        if result is not None:
            result = {**result, "status": "ready"}
        return {
            "strategy_id": STRATEGY_ID,
            "strategy_version": STRATEGY_VERSION,
            "parameter_version": LiZongParameters().parameter_version,
            "backtest_version": self.BACKTEST_VERSION,
            "portfolio_version": self.PORTFOLIO_VERSION,
            "selected_period": resolved,
            "period_label": self.PERIOD_LABELS[resolved],
            "status": "ready" if result is not None else "building",
            "result": result,
            "progress": period_progress,
            "periods": progress.get("periods") or {},
            "assumptions": self._assumptions(),
            "boundary": self.BOUNDARY,
        }

    def _refresh_market_cap_days(
        self,
        trade_dates: Sequence[str],
        *,
        batch_size: int,
    ) -> int:
        existing = {
            str(item["trade_date"])
            for item in self.database.list_strategy_backtest_market_cap_days(
                strategy_id=STRATEGY_ID,
                backtest_version=self.BACKTEST_VERSION,
            )
        }
        pending = [value for value in reversed(trade_dates) if value not in existing]
        completed = 0
        for trade_date in pending[:batch_size]:
            frame = self.client.daily_basic(
                trade_date=trade_date.replace("-", ""),
                fields="ts_code,trade_date,total_mv,circ_mv",
            )
            records = self._records(frame)
            valid_market_cap_count = sum(
                self._number(item.get("total_mv")) is not None for item in records
            )
            market_cap_coverage = (
                valid_market_cap_count / len(records) if records else 0.0
            )
            if (
                len(records) < self.MIN_MARKET_CAP_UNIVERSE_COUNT
                or market_cap_coverage < self.MIN_MARKET_CAP_VALUE_COVERAGE
            ):
                continue
            rows: list[dict[str, Any]] = []
            for item in records:
                total_mv = self._number(item.get("total_mv"))
                if total_mv is None:
                    continue
                total_mv_yi = total_mv / 10_000.0
                if total_mv_yi <= self.MARKET_CAP_MIN_YI:
                    continue
                symbol = normalize_symbol(
                    TushareClient.from_tushare_symbol(str(item.get("ts_code") or ""))
                )
                if not symbol.endswith((".SS", ".SZ", ".BJ")):
                    continue
                rows.append({"symbol": symbol, "total_mv_yi": total_mv_yi})
            version = self._fingerprint(
                {"trade_date": trade_date, "rows": rows, "source": self.SOURCE}
            )
            self.database.save_strategy_backtest_market_cap_day(
                strategy_id=STRATEGY_ID,
                backtest_version=self.BACKTEST_VERSION,
                trade_date=trade_date,
                universe_count=len(records),
                rows=rows,
                data_version=version,
                source="Tushare Pro:daily_basic",
            )
            completed += 1
        return completed

    def _advance_symbol_states(
        self,
        symbols: Sequence[str],
        *,
        trade_dates: Sequence[str],
        required_start: str,
        market_cap_data_version: str,
        symbol_batch_size: int,
        input_sync_batch_size: int,
        priority_windows: Sequence[Mapping[str, Any]] = (),
    ) -> tuple[list[str], list[str]]:
        snapshot_metadata = self._snapshot_metadata()
        coverage = {
            str(item["symbol"]): item
            for item in self.database.list_strategy_backtest_symbol_coverage(
                strategy_id=STRATEGY_ID,
                strategy_version=STRATEGY_VERSION,
                parameter_version=LiZongParameters().parameter_version,
                backtest_version=self.BACKTEST_VERSION,
            )
        }
        end_date = trade_dates[-1]
        current_symbols: set[str] = set()
        market_cap_version_cache: dict[tuple[str, str], str] = {}
        for symbol, state in coverage.items():
            base = snapshot_metadata.get(symbol)
            if (
                base is not None
                and self._snapshot_requested_through(base, end_date)
                and state.get("status") in {"stable", "incomplete"}
                and self._coverage_is_current(
                    state,
                    base,
                    market_cap_version_cache=market_cap_version_cache,
                )
            ):
                current_symbols.add(symbol)
        ordered_symbols = self._prioritize_symbols_for_windows(
            symbols,
            coverage=coverage,
            current_symbols=current_symbols,
            priority_windows=priority_windows,
        )
        evaluated: list[str] = []
        synced: list[str] = []
        evaluate_queue: list[str] = []
        sync_queue: list[str] = []
        for symbol in ordered_symbols:
            base = snapshot_metadata.get(symbol)
            state = coverage.get(symbol)
            if base is None:
                sync_queue.append(symbol)
                continue
            if not self._snapshot_requested_through(base, end_date):
                sync_queue.append(symbol)
                continue
            source_version = self._state_source_version(
                snapshot_data_version=str(base.get("data_version") or ""),
                market_cap_data_version=market_cap_data_version,
                start_date=required_start,
                end_date=end_date,
            )
            if state is None or state.get("source_data_version") != source_version:
                evaluate_queue.append(symbol)
                continue
            if (
                str(state.get("start_date") or "9999-12-31") > required_start
                or str(state.get("end_date") or "") < end_date
            ):
                evaluate_queue.append(symbol)

        for symbol in evaluate_queue:
            if len(evaluated) >= symbol_batch_size:
                break
            base = self._load_input_snapshot(snapshot_metadata.get(symbol), symbol)
            if base is None:
                sync_queue.append(symbol)
                continue
            input_complete = str(base.get("dataset") or "") == self.STABLE_INPUT_DATASET
            best_available_history = False
            if input_complete and not self._snapshot_can_cover(
                base, required_start, end_date
            ):
                if not self._history_extension_attempted(base, end_date=end_date):
                    sync_queue.append(symbol)
                    continue
                best_available_history = True
            source_version = self._state_source_version(
                snapshot_data_version=str(base.get("data_version") or ""),
                market_cap_data_version=market_cap_data_version,
                start_date=required_start,
                end_date=end_date,
            )
            try:
                states = self._evaluate_symbol(symbol, base, trade_dates=trade_dates)
            except Exception:
                if input_complete:
                    raise
                states = []
            forced_incomplete = False
            if not states and (not input_complete or best_available_history):
                states = self._incomplete_states(trade_dates)
                forced_incomplete = True
            post_listing_gap = self._states_have_post_listing_gap(states)
            version = self._fingerprint(
                {
                    "backtest_version": self.BACKTEST_VERSION,
                    "source_data_version": source_version,
                    "states": states,
                }
            )
            self.database.save_strategy_backtest_symbol_states(
                strategy_id=STRATEGY_ID,
                strategy_version=STRATEGY_VERSION,
                parameter_version=LiZongParameters().parameter_version,
                backtest_version=self.BACKTEST_VERSION,
                symbol=symbol,
                source_data_version=source_version,
                data_version=version,
                rows=states,
                status=(
                    "stable"
                    if states
                    and input_complete
                    and not forced_incomplete
                    and not best_available_history
                    and not post_listing_gap
                    else "incomplete"
                ),
            )
            evaluated.append(symbol)

        sync_symbols = self._ordered_sync_batch(
            sync_queue,
            ordered_symbols=ordered_symbols,
            limit=input_sync_batch_size,
        )

        def sync_symbol(symbol: str) -> str | None:
            market_caps = self.database.strategy_backtest_market_caps_for_symbol(
                strategy_id=STRATEGY_ID,
                backtest_version=self.BACKTEST_VERSION,
                symbol=symbol,
                start_date=trade_dates[0],
                end_date=end_date,
            )
            latest_market_cap_date = max(market_caps) if market_caps else None
            universe_item = (
                {
                    "symbol": symbol,
                    "trade_date": latest_market_cap_date,
                    "total_mv_yi": market_caps[latest_market_cap_date],
                }
                if latest_market_cap_date
                else None
            )
            try:
                result = self.snapshot_service.sync_strategy_symbol(
                    symbol,
                    as_of_date=end_date,
                    universe_item=universe_item,
                    extend_market_history_only=True,
                )
            except Exception:
                return None
            return symbol if result.get("published") else None

        workers = min(self.MAX_INPUT_SYNC_WORKERS, len(sync_symbols))
        if workers > 1:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                synced = [
                    symbol
                    for symbol in executor.map(sync_symbol, sync_symbols)
                    if symbol is not None
                ]
        else:
            synced = [
                symbol
                for symbol in (sync_symbol(item) for item in sync_symbols)
                if symbol is not None
            ]
        return evaluated, synced

    @staticmethod
    def _prioritize_symbols_for_windows(
        symbols: Sequence[str],
        *,
        coverage: Mapping[str, Mapping[str, Any]],
        current_symbols: set[str],
        priority_windows: Sequence[Mapping[str, Any]],
    ) -> list[str]:
        """Prioritize the earliest incomplete user-visible period.

        A stock that only needs a three-year expansion must not delay another
        stock that still blocks publication of the three-month result. Python's
        stable sort preserves deterministic symbol order inside each group.
        """

        window_symbol_sets = [
            set(window.get("symbols") or ()) for window in priority_windows
        ]

        def priority(symbol: str) -> int:
            state = coverage.get(symbol) or {}
            is_current = symbol in current_symbols
            for index, window in enumerate(priority_windows):
                if symbol not in window_symbol_sets[index]:
                    continue
                if (
                    not is_current
                    or str(state.get("start_date") or "9999-12-31")
                    > str(window.get("start_date") or "")
                    or str(state.get("end_date") or "")
                    < str(window.get("end_date") or "")
                ):
                    return index
            return len(priority_windows)

        return sorted(symbols, key=priority)

    @staticmethod
    def _ordered_sync_batch(
        sync_queue: Sequence[str],
        *,
        ordered_symbols: Sequence[str],
        limit: int,
    ) -> list[str]:
        """Preserve period priority after coverage checks add late sync work.

        Some stable snapshots are only discovered to have an insufficient
        warm-up window during the evaluation pass.  Those symbols are appended
        after the initial sync queue, so deduplicating by insertion order alone
        could let one- or three-year work run ahead of a three-month blocker.
        Reapply the already computed user-visible period order before taking the
        external-data batch.
        """

        if limit <= 0:
            return []
        order = {symbol: index for index, symbol in enumerate(ordered_symbols)}
        unique = dict.fromkeys(sync_queue)
        return sorted(
            unique,
            key=lambda symbol: (order.get(symbol, len(order)), symbol),
        )[:limit]

    def _evaluate_symbol(
        self,
        symbol: str,
        base_snapshot: Mapping[str, Any],
        *,
        trade_dates: Sequence[str],
    ) -> list[dict[str, Any]]:
        packet = {
            "status": "stable",
            "data_version": base_snapshot.get("data_version"),
            "snapshot": dict(base_snapshot.get("payload") or {}),
        }
        strategy_input = self.strategy_service._build_input(
            symbol,
            packet,
            supplemental_roe_rows=self._published_supplemental_roe(symbol),
        )
        end_date = str(trade_dates[-1])
        daily = _prepare_daily(strategy_input.get("daily"), end_date)
        if daily.empty:
            return []
        daily = daily.reset_index(drop=True)
        if daily["_suspended"].any():
            return self._evaluate_symbol_reference(
                symbol,
                base_snapshot,
                trade_dates=trade_dates,
            )
        date_to_index = {str(row["_date"]): index for index, row in daily.iterrows()}
        actual_latest_daily_date = str(daily.iloc[-1]["_date"])
        delist_date = self._snapshot_delist_date(base_snapshot)
        target = list(trade_dates)
        if not target or str(daily.iloc[0]["_date"]) > target[-1]:
            return []
        market_caps = self.database.strategy_backtest_market_caps_for_symbol(
            strategy_id=STRATEGY_ID,
            backtest_version=self.BACKTEST_VERSION,
            symbol=symbol,
            start_date=target[0],
            end_date=target[-1],
        )
        params = LiZongParameters()
        roe_status = self._event_rule_statuses(
            strategy_input.get("roe_history"),
            target,
            evaluator=_roe_rule,
            parameters=params,
            event_columns=("ann_date", "announcement_date"),
        )
        holder_status = self._event_rule_statuses(
            strategy_input.get("shareholders"),
            target,
            evaluator=_shareholder_rule,
            parameters=params,
            event_columns=("ann_date", "announcement_date"),
        )

        limit_known = daily["_limit_known"].fillna(False).astype(bool)
        limit_up = daily["_limit_up"].fillna(False).astype(bool)
        numeric_column = lambda name: pd.to_numeric(  # noqa: E731
            daily[name]
            if name in daily
            else pd.Series(float("nan"), index=daily.index),
            errors="coerce",
        )
        open_price = numeric_column("open")
        close_price = numeric_column("close")
        pct_change = numeric_column("pct_chg")
        adjusted_high = pd.to_numeric(daily["_adjusted_high"], errors="coerce")
        volume = numeric_column("volume")

        known_240 = limit_known.astype(int).rolling(240, min_periods=240).sum()
        limit_count_240 = limit_up.astype(int).rolling(240, min_periods=240).sum()
        known_10 = limit_known.astype(int).rolling(10, min_periods=10).sum()
        limit_count_10 = limit_up.astype(int).rolling(10, min_periods=10).sum()
        bearish_valid = open_price.notna() & close_price.notna() & pct_change.notna()
        bearish_hit = (close_price < open_price) & (pct_change <= -5.0)
        bearish_valid_10 = bearish_valid.astype(int).rolling(10, min_periods=10).sum()
        bearish_count_10 = bearish_hit.astype(int).rolling(10, min_periods=10).sum()
        adjusted_valid_379 = (
            adjusted_high.notna().astype(int).rolling(379, min_periods=379).sum()
        )
        rolling_high = adjusted_high.rolling(360, min_periods=360).max()
        new_high_hit = adjusted_high >= rolling_high - 1e-12
        new_high_count_20 = (
            new_high_hit.astype(int).rolling(20, min_periods=20).sum()
        )
        volume_valid = volume.notna() & (volume > 0)
        volume_valid_380 = (
            volume_valid.astype(int).rolling(380, min_periods=380).sum()
        )
        volume_baseline = volume.rolling(20, min_periods=20).mean().shift(1)
        volume_hit_start = [False] * len(daily)
        for index in range(20, max(20, len(daily) - 2)):
            baseline = self._number(volume_baseline.iloc[index])
            sequence = volume.iloc[index : index + 3]
            if (
                baseline is not None
                and baseline > 0
                and len(sequence) == 3
                and sequence.notna().all()
                and bool((sequence + 1e-12 >= baseline * params.volume_multiple).all())
            ):
                volume_hit_start[index] = True
        volume_hit_prefix = [0]
        for hit in volume_hit_start:
            volume_hit_prefix.append(volume_hit_prefix[-1] + int(hit))
        consecutive_hit = [False] * len(daily)
        for index in range(1, len(daily)):
            consecutive_hit[index] = bool(limit_up.iloc[index - 1] and limit_up.iloc[index])
        consecutive_prefix = [0]
        for hit in consecutive_hit:
            consecutive_prefix.append(consecutive_prefix[-1] + int(hit))

        states: list[dict[str, Any]] = []
        previous: dict[str, Any] | None = None
        for trade_date in target:
            daily_index = date_to_index.get(trade_date)
            if daily_index is None:
                is_trailing_gap = trade_date > actual_latest_daily_date
                forced_exit = bool(delist_date and trade_date >= delist_date)
                if previous is not None and (not is_trailing_gap or forced_exit):
                    carried = self._carried_state(
                        previous,
                        trade_date=trade_date,
                        forced_exit=forced_exit,
                    )
                    states.append(carried)
                    previous = carried
                else:
                    incomplete = self._incomplete_state(trade_date)
                    states.append(incomplete)
                    previous = incomplete
                continue
            row = daily.iloc[daily_index]
            raw_open = self._number(row.get("open"))
            raw_close = self._number(row.get("close"))
            factor = self._number(row.get("adj_factor"))
            state = {
                "trade_date": trade_date,
                "status": "data_incomplete",
                "candidate_qualified": False,
                "adjusted_open": (
                    raw_open * factor
                    if raw_open is not None and factor is not None
                    else None
                ),
                "adjusted_close": (
                    raw_close * factor
                    if raw_close is not None and factor is not None
                    else None
                ),
                "raw_open": raw_open,
                "raw_close": raw_close,
            }
            if daily_index + 1 >= self.WARMUP_TRADING_DAYS:
                rule_statuses = [
                    (
                        "passed"
                        if (market_caps.get(trade_date) or 0.0)
                        > self.MARKET_CAP_MIN_YI
                        else "failed"
                    ),
                    roe_status[trade_date],
                    holder_status[trade_date],
                    (
                        "data_incomplete"
                        if known_240.iloc[daily_index] < 240
                        else "passed"
                        if limit_count_240.iloc[daily_index]
                        >= params.annual_limit_up_min_count
                        else "failed"
                    ),
                    (
                        "data_incomplete"
                        if known_240.iloc[daily_index] < 240
                        else "passed"
                        if consecutive_prefix[daily_index + 1]
                        - consecutive_prefix[daily_index - 238]
                        > 0
                        else "failed"
                    ),
                    (
                        "data_incomplete"
                        if known_10.iloc[daily_index] < 10
                        else "passed"
                        if limit_count_10.iloc[daily_index] >= 1
                        else "failed"
                    ),
                    (
                        "data_incomplete"
                        if bearish_valid_10.iloc[daily_index] < 10
                        else "failed"
                        if bearish_count_10.iloc[daily_index] > 0
                        else "passed"
                    ),
                    (
                        "data_incomplete"
                        if adjusted_valid_379.iloc[daily_index] < 379
                        else "passed"
                        if new_high_count_20.iloc[daily_index] > 0
                        else "failed"
                    ),
                    self._volume_rule_status(
                        daily_index,
                        volume_valid_380=volume_valid_380,
                        volume_hit_prefix=volume_hit_prefix,
                    ),
                ]
                has_failed = "failed" in rule_statuses
                has_incomplete = "data_incomplete" in rule_statuses
                if has_failed:
                    state["status"] = "not_qualified"
                elif has_incomplete:
                    state["status"] = "data_incomplete"
                else:
                    state["candidate_qualified"] = True
                    state["status"] = self._trigger_status(
                        row,
                        limit_known=bool(limit_known.iloc[daily_index]),
                        limit_up=bool(limit_up.iloc[daily_index]),
                        parameters=params,
                    )
            states.append(state)
            previous = state
        return states

    @classmethod
    def _event_rule_statuses(
        cls,
        value: Any,
        trade_dates: Sequence[str],
        *,
        evaluator: Any,
        parameters: LiZongParameters,
        event_columns: Sequence[str],
    ) -> dict[str, str]:
        frame = value.copy() if isinstance(value, pd.DataFrame) else pd.DataFrame(value)
        event_column = next((column for column in event_columns if column in frame), None)
        events = sorted(
            {
                normalized
                for normalized in (
                    cls._iso_date(item)
                    for item in (frame[event_column] if event_column else [])
                )
                if normalized is not None
            }
        )
        statuses: dict[str, str] = {}
        event_index = 0
        current: str | None = None
        for trade_date in trade_dates:
            changed = current is None
            while event_index < len(events) and events[event_index] <= trade_date:
                event_index += 1
                changed = True
            if changed:
                current = str(evaluator(frame, trade_date, parameters).status)
            statuses[trade_date] = current or "data_incomplete"
        return statuses

    @staticmethod
    def _volume_rule_status(
        daily_index: int,
        *,
        volume_valid_380: pd.Series,
        volume_hit_prefix: Sequence[int],
    ) -> str:
        if daily_index < 379 or volume_valid_380.iloc[daily_index] < 380:
            return "data_incomplete"
        first_start = daily_index - 359
        last_start = daily_index - 2
        hits = volume_hit_prefix[last_start + 1] - volume_hit_prefix[first_start]
        return "passed" if hits > 0 else "failed"

    @classmethod
    def _trigger_status(
        cls,
        row: Mapping[str, Any],
        *,
        limit_known: bool,
        limit_up: bool,
        parameters: LiZongParameters,
    ) -> str:
        triggers: list[str] = [
            "passed" if limit_up else "failed" if limit_known else "data_incomplete"
        ]
        open_price = cls._number(row.get("open"))
        close_price = cls._number(row.get("close"))
        high_price = cls._number(row.get("high"))
        low_price = cls._number(row.get("low"))
        pre_close = cls._number(row.get("pre_close"))
        if (
            open_price is None
            or close_price is None
            or pre_close is None
            or pre_close <= 0
        ):
            triggers.append("data_incomplete")
        else:
            gap = (open_price / pre_close - 1.0) * 100.0
            triggers.append(
                "passed"
                if gap + 1e-12 >= parameters.gap_open_min_pct
                and close_price > open_price
                else "failed"
            )
        if (
            open_price is None
            or close_price is None
            or high_price is None
            or low_price is None
            or pre_close is None
            or pre_close <= 0
        ):
            triggers.append("data_incomplete")
        else:
            amplitude = (high_price - low_price) / pre_close * 100.0
            triggers.append(
                "passed"
                if amplitude > parameters.amplitude_min_pct
                and close_price > open_price
                else "failed"
            )
        if "passed" in triggers:
            return "triggered"
        if "data_incomplete" in triggers:
            return "data_incomplete"
        return "qualified"

    def _evaluate_symbol_reference(
        self,
        symbol: str,
        base_snapshot: Mapping[str, Any],
        *,
        trade_dates: Sequence[str],
    ) -> list[dict[str, Any]]:
        packet = {
            "status": "stable",
            "data_version": base_snapshot.get("data_version"),
            "snapshot": dict(base_snapshot.get("payload") or {}),
        }
        strategy_input = self.strategy_service._build_input(
            symbol,
            packet,
            supplemental_roe_rows=self._published_supplemental_roe(symbol),
        )
        daily = self._dated_frame(strategy_input.get("daily"), "trade_date")
        if daily.empty:
            return []
        daily = daily.reset_index(drop=True)
        date_to_index = {str(row["_date"]): index for index, row in daily.iterrows()}
        actual_latest_daily_date = str(daily.iloc[-1]["_date"])
        delist_date = self._snapshot_delist_date(base_snapshot)
        target = list(trade_dates)
        if not target or str(daily.iloc[0]["_date"]) > target[-1]:
            return []
        market_caps = self.database.strategy_backtest_market_caps_for_symbol(
            strategy_id=STRATEGY_ID,
            backtest_version=self.BACKTEST_VERSION,
            symbol=symbol,
            start_date=target[0],
            end_date=target[-1],
        )
        states: list[dict[str, Any]] = []
        previous: dict[str, Any] | None = None
        previous_daily_index: int | None = None
        for trade_date in target:
            daily_index = date_to_index.get(trade_date)
            if daily_index is None:
                is_trailing_gap = trade_date > actual_latest_daily_date
                forced_exit = bool(delist_date and trade_date >= delist_date)
                if previous is not None and (not is_trailing_gap or forced_exit):
                    carried = self._carried_state(
                        previous,
                        trade_date=trade_date,
                        forced_exit=forced_exit,
                    )
                    states.append(carried)
                    previous = carried
                else:
                    incomplete = self._incomplete_state(trade_date)
                    states.append(incomplete)
                    previous = incomplete
                continue
            if daily_index + 1 < self.WARMUP_TRADING_DAYS:
                row = daily.iloc[daily_index]
                raw_open = self._number(row.get("open"))
                raw_close = self._number(row.get("close"))
                factor = self._number(row.get("adj_factor"))
                state = {
                    "trade_date": trade_date,
                    "status": "data_incomplete",
                    "candidate_qualified": False,
                    "adjusted_open": (
                        raw_open * factor
                        if raw_open is not None and factor is not None
                        else None
                    ),
                    "adjusted_close": (
                        raw_close * factor
                        if raw_close is not None and factor is not None
                        else None
                    ),
                    "raw_open": raw_open,
                    "raw_close": raw_close,
                }
                states.append(state)
                previous = state
                continue
            row = daily.iloc[daily_index]
            market_cap_yi = market_caps.get(trade_date)
            if market_cap_yi is None:
                market_cap_yi = 0.0
            evaluation = deterministic_li_zong_v1(
                {
                    **strategy_input,
                    "as_of_date": trade_date,
                    "daily": daily.iloc[: daily_index + 1].drop(
                        columns=["_date"], errors="ignore"
                    ),
                    "daily_basic": [
                        {
                            "trade_date": trade_date,
                            "total_mv_yi": market_cap_yi,
                            "source": "Tushare Pro:daily_basic historical cross-section",
                        }
                    ],
                },
                parameters=LiZongParameters(),
            )
            raw_open = self._number(row.get("open"))
            raw_close = self._number(row.get("close"))
            factor = self._number(row.get("adj_factor"))
            state = {
                "trade_date": trade_date,
                "status": str(evaluation.get("status") or "data_incomplete"),
                "candidate_qualified": bool(evaluation.get("candidate_qualified")),
                "adjusted_open": (
                    raw_open * factor
                    if raw_open is not None and factor is not None
                    else None
                ),
                "adjusted_close": (
                    raw_close * factor
                    if raw_close is not None and factor is not None
                    else None
                ),
                "raw_open": raw_open,
                "raw_close": raw_close,
            }
            states.append(state)
            previous = state
            previous_daily_index = daily_index
        del previous_daily_index
        return states

    def _publish_period_if_complete(
        self,
        period: str,
        *,
        start_date: str,
        end_date: str,
        sync_run_id: str,
    ) -> dict[str, Any] | None:
        symbols = self.database.list_strategy_backtest_eligible_symbols(
            strategy_id=STRATEGY_ID,
            backtest_version=self.BACKTEST_VERSION,
            start_date=start_date,
            end_date=end_date,
        )
        coverage = {
            str(item["symbol"]): item
            for item in self.database.list_strategy_backtest_symbol_coverage(
                strategy_id=STRATEGY_ID,
                strategy_version=STRATEGY_VERSION,
                parameter_version=LiZongParameters().parameter_version,
                backtest_version=self.BACKTEST_VERSION,
            )
        }
        snapshot_metadata = self._snapshot_metadata()
        market_cap_version_cache: dict[tuple[str, str], str] = {}
        processed = [
            symbol
            for symbol in symbols
            if symbol in coverage
            and coverage[symbol].get("status") in {"stable", "incomplete"}
            and str(coverage[symbol].get("start_date") or "9999-12-31") <= start_date
            and str(coverage[symbol].get("end_date") or "") >= end_date
            and self._coverage_is_current(
                coverage[symbol],
                snapshot_metadata.get(symbol),
                market_cap_version_cache=market_cap_version_cache,
            )
        ]
        if not symbols or len(processed) != len(symbols):
            return None
        incomplete_symbols = [
            symbol
            for symbol in symbols
            if coverage[symbol].get("status") == "incomplete"
        ]
        candidate_rows = self.database.list_strategy_backtest_candidate_states(
            strategy_id=STRATEGY_ID,
            strategy_version=STRATEGY_VERSION,
            parameter_version=LiZongParameters().parameter_version,
            backtest_version=self.BACKTEST_VERSION,
            start_date=start_date,
            end_date=end_date,
        )
        candidate_symbols = sorted({str(item["symbol"]) for item in candidate_rows})
        price_rows = self.database.list_strategy_backtest_symbol_states(
            strategy_id=STRATEGY_ID,
            strategy_version=STRATEGY_VERSION,
            parameter_version=LiZongParameters().parameter_version,
            backtest_version=self.BACKTEST_VERSION,
            symbols=candidate_symbols,
            start_date=start_date,
            end_date=end_date,
        )
        benchmark = self._benchmark_rows(start_date=start_date, end_date=end_date)
        benchmark_dates = sorted(
            {
                str(item.get("trade_date") or "")
                for item in benchmark
                if item.get("trade_date")
            }
        )
        if (
            len(benchmark_dates) != self.PERIOD_DAYS[period]
            or benchmark_dates[0] != start_date
            or benchmark_dates[-1] != end_date
        ):
            return None
        names = self._stock_names(candidate_symbols)
        result = self.calculate_portfolio(
            period=period,
            candidate_rows=candidate_rows,
            price_rows=price_rows,
            benchmark_rows=benchmark,
            names=names,
            eligible_symbol_count=len(symbols),
            complete_symbol_count=len(symbols) - len(incomplete_symbols),
            incomplete_symbols=incomplete_symbols,
        )
        result["state_input_version"] = self.STATE_INPUT_VERSION
        coverage_versions = [coverage[symbol].get("data_version") for symbol in symbols]
        stable_result = {
            key: value
            for key, value in result.items()
            if key not in {"generated_at", "data_version"}
        }
        result["data_version"] = self._fingerprint(
            {
                "period": period,
                "coverage_versions": coverage_versions,
                "result": stable_result,
            }
        )
        existing = self.database.latest_tushare_dataset_snapshot(
            self.RESULT_DATASET,
            period,
            stable_only=True,
        )
        if (existing or {}).get("data_version") == result["data_version"]:
            return (existing or {}).get("payload") or result
        self.database.save_tushare_dataset_snapshot(
            dataset=self.RESULT_DATASET,
            scope_key=period,
            as_of_date=result.get("end_date"),
            report_period=period,
            source_updated_at=result.get("generated_at"),
            sync_run_id=sync_run_id,
            data_version=result["data_version"],
            data_status="stable",
            payload=result,
        )
        return result

    @classmethod
    def calculate_portfolio(
        cls,
        *,
        period: str,
        candidate_rows: Sequence[Mapping[str, Any]],
        price_rows: Sequence[Mapping[str, Any]],
        benchmark_rows: Sequence[Mapping[str, Any]],
        names: Mapping[str, str] | None = None,
        eligible_symbol_count: int,
        complete_symbol_count: int | None = None,
        incomplete_symbols: Sequence[str] = (),
    ) -> dict[str, Any]:
        resolved = cls._period(period)
        benchmark_by_date: dict[str, dict[str, float | None]] = {}
        for item in benchmark_rows:
            close = cls._number(item.get("close"))
            if close is None:
                continue
            benchmark_by_date[str(item["trade_date"])] = {
                "open": cls._number(item.get("open")),
                "close": close,
            }
        dates = sorted(benchmark_by_date)
        if not dates:
            raise ValueError("benchmark rows are empty")
        candidates: dict[str, set[str]] = defaultdict(set)
        for item in candidate_rows:
            candidates[str(item["trade_date"])].add(str(item["symbol"]))
        prices: dict[tuple[str, str], dict[str, float | None]] = {}
        for item in price_rows:
            prices[(str(item["trade_date"]), str(item["symbol"]))] = {
                "open": cls._number(item.get("adjusted_open")),
                "close": cls._number(item.get("adjusted_close")),
            }

        units: dict[str, float] = {}
        cash = 1.0
        points: list[dict[str, Any]] = []
        rebalances: list[dict[str, Any]] = []
        deferred = 0
        cooldown_deferred = 0
        total_cost = 0.0
        total_turnover = 0.0
        benchmark_units = 0.0
        benchmark_cash = 1.0
        pending: dict[str, Any] | None = None
        last_rebalance_index: int | None = None

        for index, trade_date in enumerate(dates):
            if index > 0:
                signal_date = dates[index - 1]
                latest_selection = set(candidates.get(signal_date, set()))
                if latest_selection == set(units):
                    pending = None
                else:
                    # During the minimum holding period, newer signals replace
                    # older pending targets instead of forming a stale queue.
                    pending = {
                        "signal_date": signal_date,
                        "symbols": latest_selection,
                    }
            if pending is not None:
                desired = set(pending["symbols"])
                cooldown_ready = (
                    last_rebalance_index is None
                    or index - last_rebalance_index
                    >= cls.MIN_REBALANCE_TRADING_DAYS
                )
                if not cooldown_ready:
                    cooldown_deferred += 1
                else:
                    involved = set(units) | desired
                    day_prices = {
                        symbol: prices.get((trade_date, symbol)) for symbol in involved
                    }
                    tradable = all(
                        item is not None
                        and cls._number(item.get("open")) is not None
                        and cls._number(item.get("close")) is not None
                        for item in day_prices.values()
                    )
                    if tradable:
                        old_symbols = set(units)
                        old_exposed = bool(old_symbols)
                        values_at_open = {
                            symbol: units[symbol] * float(day_prices[symbol]["open"])
                            for symbol in old_symbols
                        }
                        pre_trade_nav = cash + sum(values_at_open.values())
                        target_weight = 1.0 / len(desired) if desired else 0.0
                        target_values = {
                            symbol: pre_trade_nav * target_weight for symbol in desired
                        }
                        turnover_amount = sum(
                            abs(
                                target_values.get(symbol, 0.0)
                                - values_at_open.get(symbol, 0.0)
                            )
                            for symbol in involved
                        )
                        cost = 0.0
                        target_value = pre_trade_nav / len(desired) if desired else 0.0
                        units = {
                            symbol: target_value / float(day_prices[symbol]["open"])
                            for symbol in desired
                        }
                        cash = pre_trade_nav - target_value * len(desired)
                        turnover_ratio = (
                            turnover_amount / pre_trade_nav if pre_trade_nav else 0.0
                        )
                        new_exposed = bool(desired)
                        benchmark_open = benchmark_by_date[trade_date]["open"]
                        if benchmark_open is None:
                            raise ValueError(
                                f"benchmark has no open price on {trade_date}"
                            )
                        if not old_exposed and new_exposed:
                            benchmark_units = benchmark_cash / benchmark_open
                            benchmark_cash = 0.0
                        elif old_exposed and not new_exposed:
                            benchmark_cash += benchmark_units * benchmark_open
                            benchmark_units = 0.0
                        total_cost += cost
                        total_turnover += turnover_ratio
                        rebalances.append(
                            {
                                "signal_date": pending["signal_date"],
                                "trade_date": trade_date,
                                "symbols": sorted(desired),
                                "names": [
                                    (names or {}).get(symbol, symbol)
                                    for symbol in sorted(desired)
                                ],
                                "added": sorted(desired - old_symbols),
                                "removed": sorted(old_symbols - desired),
                                "holding_count": len(desired),
                                "turnover_pct": round(turnover_ratio * 100.0, 4),
                                "cost_pct_of_nav": 0.0,
                            }
                        )
                        last_rebalance_index = index
                        pending = None
                    else:
                        deferred += 1

            nav = cash
            for symbol, quantity in units.items():
                item = prices.get((trade_date, symbol)) or {}
                close = cls._number(item.get("close"))
                if close is None:
                    raise ValueError(
                        f"held symbol {symbol} has no close price on {trade_date}"
                    )
                nav += quantity * close
            benchmark_nav = (
                benchmark_cash
                + benchmark_units * benchmark_by_date[trade_date]["close"]
            )
            points.append(
                {
                    "trade_date": trade_date,
                    "nav": round(nav, 8),
                    "return_pct": round((nav - 1.0) * 100.0, 4),
                    "benchmark_nav": round(benchmark_nav, 8),
                    "benchmark_return_pct": round((benchmark_nav - 1.0) * 100.0, 4),
                    "holding_count": len(units),
                    "benchmark_exposed": bool(benchmark_units),
                }
            )

        end_nav = float(points[-1]["nav"])
        benchmark_end = float(points[-1]["benchmark_nav"])
        calendar_days = max(
            1,
            (date.fromisoformat(dates[-1]) - date.fromisoformat(dates[0])).days,
        )
        annualized = (end_nav ** (365.0 / calendar_days) - 1.0) * 100.0
        benchmark_annualized = (
            benchmark_end ** (365.0 / calendar_days) - 1.0
        ) * 100.0
        returns = [float(item["return_pct"]) / 100.0 for item in points]
        daily_returns = [
            points[index]["nav"] / points[index - 1]["nav"] - 1.0
            for index in range(1, len(points))
            if points[index - 1]["nav"]
        ]
        volatility = (
            pd.Series(daily_returns).std(ddof=1) * math.sqrt(252.0) * 100.0
            if len(daily_returns) >= 2
            else 0.0
        )
        max_drawdown = cls._max_drawdown([float(item["nav"]) for item in points])
        complete_count = (
            int(complete_symbol_count)
            if complete_symbol_count is not None
            else int(eligible_symbol_count) - len(incomplete_symbols)
        )
        incomplete_count = max(0, int(eligible_symbol_count) - complete_count)
        exposure_trading_days = sum(
            int(item.get("holding_count") or 0) > 0 for item in points
        )
        return {
            "portfolio_version": cls.PORTFOLIO_VERSION,
            "period": resolved,
            "period_label": cls.PERIOD_LABELS[resolved],
            "start_date": dates[0],
            "end_date": dates[-1],
            "trading_days": len(dates),
            "eligible_symbol_count": int(eligible_symbol_count),
            "complete_symbol_count": complete_count,
            "incomplete_symbol_count": incomplete_count,
            "data_coverage_ratio": round(
                complete_count / int(eligible_symbol_count), 6
            )
            if eligible_symbol_count
            else 0.0,
            "incomplete_symbols": sorted(set(incomplete_symbols)),
            "data_coverage_boundary": (
                "数据缺口股票的逐日状态按数据不完整保存，不会被当作候选；"
                "收益率代表当前可判定历史范围，页面同时披露完整数据覆盖率。"
            ),
            "ever_selected_symbol_count": len({
                str(item["symbol"]) for item in candidate_rows
            }),
            "selection_update_count": len(rebalances),
            "period_return_pct": round((end_nav - 1.0) * 100.0, 4),
            "annualized_return_pct": round(annualized, 4),
            "benchmark_return_pct": round((benchmark_end - 1.0) * 100.0, 4),
            "benchmark_annualized_return_pct": round(benchmark_annualized, 4),
            "excess_return_pct": round((end_nav - benchmark_end) * 100.0, 4),
            "max_drawdown_pct": round(max_drawdown * 100.0, 4),
            "annualized_volatility_pct": round(float(volatility), 4),
            "total_turnover_pct": round(total_turnover * 100.0, 4),
            "total_cost_pct_of_initial_nav": round(total_cost * 100.0, 4),
            "deferred_rebalance_days": deferred,
            "cooldown_deferred_days": cooldown_deferred,
            "minimum_rebalance_trading_days": cls.MIN_REBALANCE_TRADING_DAYS,
            "exposure_trading_days": exposure_trading_days,
            "benchmark_policy": "same_exposure_only",
            "benchmark_trading_days": exposure_trading_days,
            "trading_cost_bps_per_side": cls.COST_BPS_PER_SIDE,
            "points": points,
            "rebalances": rebalances,
            "generated_at": utc_now(),
            "assumptions": cls._assumptions(),
            "boundary": cls.BOUNDARY,
            "debug": {
                "return_observation_count": len(returns),
                "benchmark_policy": "same_exposure_only",
            },
        }

    def _progress_packet(self) -> dict[str, Any]:
        calendar = self.database.latest_tushare_dataset_snapshot(
            self.CALENDAR_DATASET,
            "a_share",
            stable_only=True,
        )
        trade_dates = list(((calendar or {}).get("payload") or {}).get("trade_dates") or [])
        cap_days = {
            str(item["trade_date"])
            for item in self.database.list_strategy_backtest_market_cap_days(
                strategy_id=STRATEGY_ID,
                backtest_version=self.BACKTEST_VERSION,
            )
        }
        coverage = self.database.list_strategy_backtest_symbol_coverage(
            strategy_id=STRATEGY_ID,
            strategy_version=STRATEGY_VERSION,
            parameter_version=LiZongParameters().parameter_version,
            backtest_version=self.BACKTEST_VERSION,
        )
        snapshot_metadata = self._snapshot_metadata()
        market_cap_version_cache: dict[tuple[str, str], str] = {}
        periods: dict[str, dict[str, Any]] = {}
        for period, days in self.PERIOD_DAYS.items():
            target = trade_dates[-days:] if len(trade_dates) >= days else trade_dates
            available_market_days = sum(value in cap_days for value in target)
            market_ready = len(target) == days and available_market_days == days
            start_date = target[0] if market_ready and target else None
            end_date = target[-1] if market_ready and target else None
            eligible = (
                self.database.list_strategy_backtest_eligible_symbols(
                    strategy_id=STRATEGY_ID,
                    backtest_version=self.BACKTEST_VERSION,
                    start_date=start_date,
                    end_date=end_date,
                )
                if start_date and end_date
                else []
            )
            completed_items = [
                item
                for item in coverage
                if item.get("status") in {"stable", "incomplete"}
                and str(item.get("start_date") or "9999-12-31") <= str(start_date)
                and str(item.get("end_date") or "") >= str(end_date)
                and str(item.get("symbol")) in eligible
                and self._coverage_is_current(
                    item,
                    snapshot_metadata.get(str(item.get("symbol") or "")),
                    market_cap_version_cache=market_cap_version_cache,
                )
            ]
            completed = len(completed_items)
            incomplete = sum(
                item.get("status") == "incomplete" for item in completed_items
            )
            snapshot = self.database.latest_tushare_dataset_snapshot(
                self.RESULT_DATASET,
                period,
                stable_only=True,
            )
            result_payload = (snapshot or {}).get("payload") or {}
            result_ready = bool(
                snapshot
                and result_payload.get("state_input_version")
                == self.STATE_INPUT_VERSION
                and result_payload.get("portfolio_version")
                == self.PORTFOLIO_VERSION
                and (end_date is None or snapshot.get("as_of_date") == end_date)
            )
            remaining_symbols = max(0, len(eligible) - completed)
            periods[period] = {
                "label": self.PERIOD_LABELS[period],
                "status": "ready" if result_ready else "building",
                "phase": (
                    "ready"
                    if result_ready
                    else "symbol_evaluation"
                    if market_ready
                    else "market_cap_sync"
                ),
                "required_market_days": days,
                "available_market_days": available_market_days,
                "market_data_ratio": round(available_market_days / days, 6),
                "eligible_symbols": len(eligible),
                "evaluated_symbols": completed,
                "complete_symbols": completed - incomplete,
                "incomplete_symbols": incomplete,
                "remaining_symbols": remaining_symbols,
                "estimated_evaluation_batches": math.ceil(
                    remaining_symbols / self.DEFAULT_SYMBOL_BATCH_SIZE
                ),
                "symbol_coverage_ratio": (
                    round(completed / len(eligible), 6) if eligible else 0.0
                ),
                "start_date": start_date,
                "end_date": end_date,
                "result_as_of_date": (
                    (snapshot or {}).get("as_of_date") if result_ready else None
                ),
            }
        return {"periods": periods}

    def _ready_period_windows(
        self, trade_dates: Sequence[str]
    ) -> dict[str, tuple[str, str]]:
        cap_days = {
            str(item["trade_date"])
            for item in self.database.list_strategy_backtest_market_cap_days(
                strategy_id=STRATEGY_ID,
                backtest_version=self.BACKTEST_VERSION,
            )
        }
        result: dict[str, tuple[str, str]] = {}
        for period, days in self.PERIOD_DAYS.items():
            if len(trade_dates) < days:
                continue
            window = list(trade_dates[-days:])
            if all(value in cap_days for value in window):
                result[period] = (window[0], window[-1])
        return result

    def _snapshot_metadata(self) -> dict[str, dict[str, Any]]:
        candidates = [
            *self.database.list_latest_tushare_dataset_snapshots(
                self.STABLE_INPUT_DATASET,
                data_status="stable",
                include_payload=False,
            ),
            *self.database.list_latest_tushare_dataset_snapshots(
                self.INCOMPLETE_INPUT_DATASET,
                data_status="incomplete",
                include_payload=False,
            ),
        ]
        selected: dict[str, dict[str, Any]] = {}
        for item in candidates:
            symbol = str(item["scope_key"])
            current = selected.get(symbol)
            if current is None or self._input_metadata_rank(item) > self._input_metadata_rank(
                current
            ):
                selected[symbol] = item
        return selected

    def _load_input_snapshot(
        self, metadata: Mapping[str, Any] | None, symbol: str
    ) -> dict[str, Any] | None:
        if metadata is None:
            return None
        dataset = str(metadata.get("dataset") or self.STABLE_INPUT_DATASET)
        return self.database.latest_tushare_dataset_snapshot(
            dataset,
            symbol,
            stable_only=dataset == self.STABLE_INPUT_DATASET,
        )

    @classmethod
    def _input_metadata_rank(cls, item: Mapping[str, Any]) -> tuple[str, int, str, str]:
        requested = cls._iso_date(
            item.get("requested_as_of_date") or item.get("as_of_date")
        ) or ""
        complete = int(str(item.get("dataset") or "") == cls.STABLE_INPUT_DATASET)
        actual = cls._iso_date(item.get("as_of_date")) or ""
        return requested, complete, actual, str(item.get("created_at") or "")

    def _market_cap_window_version(self, trade_dates: Sequence[str]) -> str:
        dates = list(trade_dates)
        if not dates:
            return self._fingerprint({"method": "market_cap_window_v1", "days": []})
        rows = self.database.list_strategy_backtest_market_cap_days(
            strategy_id=STRATEGY_ID,
            backtest_version=self.BACKTEST_VERSION,
            start_date=dates[0],
            end_date=dates[-1],
        )
        by_date = {str(item["trade_date"]): item for item in rows}
        return self._fingerprint(
            {
                "method": "market_cap_window_v1",
                "days": [
                    {
                        "trade_date": trade_date,
                        "data_version": (by_date.get(trade_date) or {}).get(
                            "data_version"
                        ),
                    }
                    for trade_date in dates
                ],
            }
        )

    def _state_source_version(
        self,
        *,
        snapshot_data_version: str,
        market_cap_data_version: str,
        start_date: str,
        end_date: str,
    ) -> str:
        return json.dumps(
            {
                "state_input_version": self.STATE_INPUT_VERSION,
                "snapshot_data_version": snapshot_data_version,
                "market_cap_data_version": market_cap_data_version,
                "start_date": start_date,
                "end_date": end_date,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def _coverage_is_current(
        self,
        coverage: Mapping[str, Any],
        snapshot_metadata: Mapping[str, Any] | None,
        *,
        market_cap_version_cache: dict[tuple[str, str], str],
    ) -> bool:
        if snapshot_metadata is None:
            return False
        try:
            source = json.loads(str(coverage.get("source_data_version") or ""))
        except (TypeError, ValueError, json.JSONDecodeError):
            return False
        start_date = str(coverage.get("start_date") or "")
        end_date = str(coverage.get("end_date") or "")
        if not start_date or not end_date:
            return False
        if source.get("state_input_version") != self.STATE_INPUT_VERSION:
            return False
        if source.get("snapshot_data_version") != snapshot_metadata.get(
            "data_version"
        ):
            return False
        if source.get("start_date") != start_date or source.get("end_date") != end_date:
            return False
        window = (start_date, end_date)
        if window not in market_cap_version_cache:
            calendar = self.database.latest_tushare_dataset_snapshot(
                self.CALENDAR_DATASET,
                "a_share",
                stable_only=True,
            )
            trade_dates = [
                value
                for value in (
                    ((calendar or {}).get("payload") or {}).get("trade_dates") or []
                )
                if start_date <= str(value) <= end_date
            ]
            market_cap_version_cache[window] = self._market_cap_window_version(
                trade_dates
            )
        return source.get("market_cap_data_version") == market_cap_version_cache[
            window
        ]

    def _ensure_benchmark(
        self,
        trade_dates: Sequence[str],
        *,
        sync_run_id: str,
    ) -> None:
        start_date, end_date = trade_dates[0], trade_dates[-1]
        cached = self.database.latest_tushare_dataset_snapshot(
            self.BENCHMARK_DATASET,
            self.BENCHMARK_SYMBOL,
            stable_only=True,
        )
        payload = (cached or {}).get("payload") or {}
        cached_dates = {
            str(item.get("trade_date") or "")
            for item in (payload.get("rows") or [])
            if item.get("trade_date")
        }
        required_dates = set(trade_dates)
        if required_dates and required_dates.issubset(cached_dates):
            return
        frame = self.client.index_daily(
            ts_code=TushareClient.to_tushare_symbol(self.BENCHMARK_SYMBOL),
            start_date=start_date.replace("-", ""),
            end_date=end_date.replace("-", ""),
            fields="ts_code,trade_date,open,high,low,close,pre_close,pct_chg",
        )
        rows = self._records(frame)
        for item in rows:
            item["trade_date"] = self._iso_date(item.get("trade_date"))
        rows = sorted(
            [item for item in rows if item.get("trade_date")],
            key=lambda item: str(item["trade_date"]),
        )
        actual_dates = {str(item["trade_date"]) for item in rows}
        complete = bool(required_dates) and required_dates.issubset(actual_dates)
        benchmark_payload = {
            "symbol": self.BENCHMARK_SYMBOL,
            "name": self.BENCHMARK_NAME,
            "start_date": rows[0]["trade_date"] if rows else None,
            "end_date": rows[-1]["trade_date"] if rows else None,
            "requested_start_date": start_date,
            "requested_end_date": end_date,
            "rows": rows,
            "source": "Tushare Pro:index_daily",
            "generated_at": utc_now(),
        }
        self.database.save_tushare_dataset_snapshot(
            dataset=self.BENCHMARK_DATASET,
            scope_key=self.BENCHMARK_SYMBOL,
            as_of_date=(rows[-1]["trade_date"] if rows else None),
            report_period=None,
            source_updated_at=benchmark_payload["generated_at"],
            sync_run_id=sync_run_id,
            data_version=self._fingerprint(benchmark_payload),
            data_status="stable" if complete else "incomplete",
            payload=benchmark_payload,
        )

    def _benchmark_rows(
        self, *, start_date: str, end_date: str
    ) -> list[dict[str, Any]]:
        cached = self.database.latest_tushare_dataset_snapshot(
            self.BENCHMARK_DATASET,
            self.BENCHMARK_SYMBOL,
            stable_only=True,
        )
        rows = ((cached or {}).get("payload") or {}).get("rows") or []
        return [
            item
            for item in rows
            if start_date <= str(item.get("trade_date") or "") <= end_date
        ]

    def _save_calendar(
        self,
        trade_dates: Sequence[str],
        *,
        sync_run_id: str,
    ) -> None:
        payload = {
            "market": "A股",
            "trade_dates": list(trade_dates),
            "start_date": trade_dates[0],
            "end_date": trade_dates[-1],
            "trading_days": len(trade_dates),
            "generated_at": utc_now(),
            "source": "Tushare Pro:trade_cal",
        }
        self.database.save_tushare_dataset_snapshot(
            dataset=self.CALENDAR_DATASET,
            scope_key="a_share",
            as_of_date=trade_dates[-1],
            report_period=None,
            source_updated_at=payload["generated_at"],
            sync_run_id=sync_run_id,
            data_version=self._fingerprint(payload),
            data_status="stable",
            payload=payload,
        )

    def _target_trade_dates(self, as_of_date: str | None) -> list[str]:
        end = (
            date.fromisoformat(str(as_of_date)[:10])
            if as_of_date
            else self._default_as_of_date()
        )
        start = end - timedelta(days=1700)
        frame = self.client.trade_cal(
            exchange="",
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
            is_open="1",
            fields="exchange,cal_date,is_open,pretrade_date",
        )
        dates = sorted(
            {
                value
                for value in (self._iso_date(item) for item in frame.get("cal_date", []))
                if value is not None
            }
        )
        return dates[-max(self.PERIOD_DAYS.values()) :]

    @classmethod
    def _default_as_of_date(cls, now: datetime | None = None) -> date:
        current = now or datetime.now(ZoneInfo("Asia/Shanghai"))
        if current.tzinfo is None:
            current = current.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
        current = current.astimezone(ZoneInfo("Asia/Shanghai"))
        if current.time() < cls.COMPLETE_SESSION_CUTOFF:
            return current.date() - timedelta(days=1)
        return current.date()

    def _snapshot_can_cover(
        self,
        snapshot: Mapping[str, Any],
        required_start: str,
        end_date: str,
    ) -> bool:
        rows = (
            (((snapshot.get("payload") or {}).get("datasets") or {}).get("daily") or {})
            .get("rows")
            or []
        )
        dates = sorted(
            value
            for value in (self._iso_date(item.get("trade_date")) for item in rows)
            if value is not None
        )
        if not dates:
            return False
        if dates[-1] < end_date:
            delist_date = self._snapshot_delist_date(snapshot)
            if delist_date is None or delist_date > end_date:
                return False
        stock_rows = (
            (((snapshot.get("payload") or {}).get("datasets") or {}).get("stock_basic") or {})
            .get("rows")
            or []
        )
        listed = self._iso_date((stock_rows[0] if stock_rows else {}).get("list_date"))
        if listed is not None and dates[0] <= listed <= required_start:
            return True
        if listed is not None and listed > required_start:
            return True
        if len(dates) < self.WARMUP_TRADING_DAYS:
            return False
        first_valid = dates[self.WARMUP_TRADING_DAYS - 1]
        return first_valid <= required_start

    @classmethod
    def _history_extension_attempted(
        cls, snapshot: Mapping[str, Any], *, end_date: str
    ) -> bool:
        payload = snapshot.get("payload") or {}
        return bool(
            payload.get("market_history_version")
            == TushareSnapshotService.MARKET_HISTORY_VERSION
            and cls._snapshot_requested_through(snapshot, end_date)
        )

    @classmethod
    def _snapshot_requested_through(
        cls, snapshot: Mapping[str, Any], end_date: str
    ) -> bool:
        payload = snapshot.get("payload") or {}
        requested = cls._iso_date(
            snapshot.get("requested_as_of_date")
            or payload.get("requested_as_of_date")
        )
        actual = cls._iso_date(snapshot.get("as_of_date") or payload.get("as_of_date"))
        return bool((requested and requested >= end_date) or (actual and actual >= end_date))

    @classmethod
    def _snapshot_delist_date(cls, snapshot: Mapping[str, Any]) -> str | None:
        rows = (
            (((snapshot.get("payload") or {}).get("datasets") or {}).get("stock_basic") or {})
            .get("rows")
            or []
        )
        values = sorted(
            value
            for value in (cls._iso_date(item.get("delist_date")) for item in rows)
            if value is not None
        )
        return values[-1] if values else None

    @staticmethod
    def _carried_state(
        previous: Mapping[str, Any], *, trade_date: str, forced_exit: bool
    ) -> dict[str, Any]:
        return {
            **previous,
            "trade_date": trade_date,
            "status": "not_qualified" if forced_exit else previous.get("status"),
            "candidate_qualified": (
                False if forced_exit else bool(previous.get("candidate_qualified"))
            ),
            "adjusted_open": previous.get("adjusted_close"),
            "raw_open": previous.get("raw_close"),
        }

    @staticmethod
    def _incomplete_state(trade_date: str) -> dict[str, Any]:
        return {
            "trade_date": trade_date,
            "status": "data_incomplete",
            "candidate_qualified": False,
            "adjusted_open": None,
            "adjusted_close": None,
            "raw_open": None,
            "raw_close": None,
        }

    @classmethod
    def _states_have_post_listing_gap(
        cls, states: Sequence[Mapping[str, Any]]
    ) -> bool:
        """Distinguish pre-listing calendar days from real input gaps.

        A stock that lists inside the backtest window naturally has no price
        before its first trading day.  Once a real adjusted close has appeared,
        however, any later ``data_incomplete`` state means the rule or market
        input was not decisive and the symbol must be disclosed as incomplete.
        """

        observed_price = False
        for state in states:
            if cls._number(state.get("adjusted_close")) is not None:
                observed_price = True
            if observed_price and state.get("status") == "data_incomplete":
                return True
        return False

    @staticmethod
    def _incomplete_states(trade_dates: Sequence[str]) -> list[dict[str, Any]]:
        return [
            LiZongPortfolioBacktestService._incomplete_state(trade_date)
            for trade_date in trade_dates
        ]

    def _published_supplemental_roe(self, symbol: str) -> list[dict[str, Any]]:
        candidate = self.database.latest_strategy_candidate_snapshot(
            strategy_id=STRATEGY_ID,
            strategy_version=STRATEGY_VERSION,
            parameter_version=LiZongParameters().parameter_version,
            symbol=symbol,
        )
        if candidate is None:
            return []
        rule = next(
            (
                item
                for item in (candidate.get("result") or {}).get("rule_results") or []
                if item.get("rule_id") == "LZ-F-02"
            ),
            None,
        )
        return [
            {
                "ts_code": symbol,
                "end_date": item.get("report_period"),
                "ann_date": item.get("announcement_date"),
                "roe": item.get("roe_pct"),
                "source": item.get("source"),
                "source_url": item.get("source_url"),
                "fallback_reason": item.get("fallback_reason"),
            }
            for item in (rule or {}).get("actual_value") or []
            if item.get("fallback_reason")
        ]

    def _stock_names(self, symbols: Sequence[str]) -> dict[str, str]:
        if not symbols:
            return {}
        wanted = set(symbols)
        result: dict[str, str] = {}
        snapshots = self.database.list_latest_tushare_dataset_snapshots(
            "li_zong_inputs",
            data_status="stable",
            include_payload=True,
        )
        for item in snapshots:
            symbol = str(item.get("scope_key") or "")
            if symbol not in wanted:
                continue
            rows = (
                ((((item.get("payload") or {}).get("datasets") or {}).get("stock_basic") or {})
                .get("rows")
                or [])
            )
            result[symbol] = str((rows[0] if rows else {}).get("name") or symbol)
        return result

    @classmethod
    def _assumptions(cls) -> dict[str, Any]:
        return {
            "selection": "李总策略9条候选规则全部通过；触发规则只改变人工复核层级，不改变持仓资格。",
            "rebalance": (
                "候选集合变化后，最早于下一完整交易日开盘换仓；任意两次实际"
                "换仓至少间隔10个交易日，冷却期内只执行最新候选集合。"
            ),
            "weighting": "每次换仓后对可成交候选等资金配置。",
            "cost_bps_per_side": cls.COST_BPS_PER_SIDE,
            "benchmark": (
                f"{cls.BENCHMARK_NAME}（只在策略持仓期保持同等市场暴露；"
                "策略空仓期同步冻结）"
            ),
            "price_basis": "复权因子调整后的开盘价和收盘价。",
            "cash_policy": "候选为空时持有现金，现金收益按0计。",
            "delisting_policy": (
                "已明确退市且不再有交易日数据时，于候选状态退出后的下一市场日，"
                "按最后可得复权收盘价作为强制退出代理。"
            ),
        }

    @staticmethod
    def _max_drawdown(values: Sequence[float]) -> float:
        peak = 0.0
        drawdown = 0.0
        for value in values:
            peak = max(peak, float(value))
            if peak > 0:
                drawdown = min(drawdown, float(value) / peak - 1.0)
        return drawdown

    @staticmethod
    def _period(value: str) -> str:
        resolved = str(value or "1y").lower()
        if resolved not in LiZongPortfolioBacktestService.PERIOD_DAYS:
            raise ValueError("period must be one of: 3m, 1y, 3y")
        return resolved

    @staticmethod
    def _dated_frame(value: Any, column: str) -> pd.DataFrame:
        frame = value.copy() if isinstance(value, pd.DataFrame) else pd.DataFrame(value)
        if frame.empty or column not in frame:
            return pd.DataFrame()
        frame = frame.copy()
        frame["_date"] = frame[column].map(LiZongPortfolioBacktestService._iso_date)
        frame = frame[frame["_date"].notna()]
        return frame.sort_values("_date").drop_duplicates("_date", keep="last")

    @staticmethod
    def _records(frame: Any) -> list[dict[str, Any]]:
        if not isinstance(frame, pd.DataFrame):
            frame = pd.DataFrame(frame)
        if frame.empty:
            return []
        clean = frame.where(pd.notna(frame), None)
        return [dict(item) for item in clean.to_dict(orient="records")]

    @staticmethod
    def _number(value: Any) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    @staticmethod
    def _iso_date(value: Any) -> str | None:
        if value is None or value == "":
            return None
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        text = str(value).strip().replace("/", "-")
        if len(text) >= 10 and text[4] == "-" and text[7] == "-":
            return text[:10]
        digits = "".join(character for character in text if character.isdigit())
        if len(digits) >= 8:
            return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
        return None

    @staticmethod
    def _fingerprint(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode(
                "utf-8"
            )
        ).hexdigest()


__all__ = ["LiZongPortfolioBacktestService"]
