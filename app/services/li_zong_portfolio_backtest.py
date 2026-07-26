from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
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
from app.services.strategies.li_zong import (
    STRATEGY_ID,
    STRATEGY_VERSION,
    LiZongParameters,
    deterministic_li_zong_v1,
)
from app.utils import utc_now


class LiZongPortfolioBacktestService:
    """Point-in-time equal-weight portfolio backtest for Li Zong v1."""

    BACKTEST_VERSION = "li_zong_equal_weight_v1"
    CALENDAR_DATASET = "li_zong_backtest_calendar"
    BENCHMARK_DATASET = "li_zong_backtest_benchmark"
    RESULT_DATASET = "li_zong_portfolio_backtest"
    BENCHMARK_SYMBOL = "000300.SS"
    BENCHMARK_NAME = "沪深300"
    PERIOD_DAYS = {"3m": 63, "1y": 252, "3y": 756}
    PERIOD_LABELS = {"3m": "近3个月", "1y": "近1年", "3y": "近3年"}
    WARMUP_TRADING_DAYS = 380
    MARKET_CAP_MIN_YI = LiZongParameters().market_cap_min_yi
    COST_BPS_PER_SIDE = 10.0
    TARGET_HISTORY_MARKET_DAYS = 1150
    SOURCE = "Tushare Pro:trade_cal+daily_basic+index_daily"

    BOUNDARY = (
        "回测严格使用每个历史交易日当时已公告的财务与股东数据、当日历史市值，"
        "以及当日及以前的量价数据。候选集合发生变化后，在下一完整交易日开盘按"
        "等权组合换仓；主净值计入单边10个基点的统一摩擦成本。尚未模拟涨跌停"
        "排队、停牌后的实际成交、冲击成本、分红税和真实佣金阶梯，结果只用于"
        "验证规则历史表现，不构成收益承诺或投资建议。"
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
        market_day_batch_size: int = 12,
        symbol_batch_size: int = 12,
        input_sync_batch_size: int = 1,
        as_of_date: str | None = None,
    ) -> dict[str, Any]:
        if self.client is None:
            return {"status": "disabled", "periods": self._progress_packet()}
        market_batch = max(1, min(int(market_day_batch_size), 30))
        symbol_batch = max(1, min(int(symbol_batch_size), 50))
        sync_batch = max(0, min(int(input_sync_batch_size), 5))
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
                required_symbols = self.database.list_strategy_backtest_eligible_symbols(
                    strategy_id=STRATEGY_ID,
                    backtest_version=self.BACKTEST_VERSION,
                    start_date=required_start,
                    end_date=trade_dates[-1],
                )
                evaluated, synced = self._advance_symbol_states(
                    required_symbols,
                    trade_dates=trade_dates,
                    required_start=required_start,
                    symbol_batch_size=symbol_batch,
                    input_sync_batch_size=sync_batch,
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
        result = (snapshot or {}).get("payload") or None
        period_progress = (progress.get("periods") or {}).get(resolved) or {}
        if result is not None:
            result = {**result, "status": "ready"}
        return {
            "strategy_id": STRATEGY_ID,
            "strategy_version": STRATEGY_VERSION,
            "parameter_version": LiZongParameters().parameter_version,
            "backtest_version": self.BACKTEST_VERSION,
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
        symbol_batch_size: int,
        input_sync_batch_size: int,
    ) -> tuple[list[str], list[str]]:
        snapshots = {
            str(item["scope_key"]): item
            for item in self.database.list_latest_tushare_dataset_snapshots(
                "li_zong_inputs",
                data_status="stable",
                include_payload=True,
            )
        }
        coverage = {
            str(item["symbol"]): item
            for item in self.database.list_strategy_backtest_symbol_coverage(
                strategy_id=STRATEGY_ID,
                strategy_version=STRATEGY_VERSION,
                parameter_version=LiZongParameters().parameter_version,
                backtest_version=self.BACKTEST_VERSION,
            )
        }
        evaluated: list[str] = []
        synced: list[str] = []
        evaluate_queue: list[str] = []
        sync_queue: list[str] = []
        end_date = trade_dates[-1]
        for symbol in symbols:
            base = snapshots.get(symbol)
            state = coverage.get(symbol)
            if base is None:
                sync_queue.append(symbol)
                continue
            source_version = str(base.get("data_version") or "")
            if state is None or state.get("source_data_version") != source_version:
                evaluate_queue.append(symbol)
                continue
            if (
                str(state.get("start_date") or "9999-12-31") > required_start
                or str(state.get("end_date") or "") < end_date
            ):
                if self._snapshot_can_cover(base, required_start, end_date):
                    evaluate_queue.append(symbol)
                else:
                    sync_queue.append(symbol)

        for symbol in evaluate_queue[:symbol_batch_size]:
            base = snapshots[symbol]
            states = self._evaluate_symbol(symbol, base, trade_dates=trade_dates)
            version = self._fingerprint(
                {
                    "backtest_version": self.BACKTEST_VERSION,
                    "source_data_version": base.get("data_version"),
                    "states": states,
                }
            )
            self.database.save_strategy_backtest_symbol_states(
                strategy_id=STRATEGY_ID,
                strategy_version=STRATEGY_VERSION,
                parameter_version=LiZongParameters().parameter_version,
                backtest_version=self.BACKTEST_VERSION,
                symbol=symbol,
                source_data_version=str(base.get("data_version") or ""),
                data_version=version,
                rows=states,
                status="stable" if states else "incomplete",
            )
            evaluated.append(symbol)

        remaining_budget = max(0, symbol_batch_size - len(evaluated))
        for symbol in sync_queue[: min(input_sync_batch_size, remaining_budget or 1)]:
            try:
                result = self.snapshot_service.sync_strategy_symbol(
                    symbol,
                    as_of_date=end_date,
                )
            except Exception:
                continue
            if result.get("published") or result.get("snapshot"):
                synced.append(symbol)
        return evaluated, synced

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
        daily = self._dated_frame(strategy_input.get("daily"), "trade_date")
        if daily.empty:
            return []
        daily = daily.reset_index(drop=True)
        date_to_index = {str(row["_date"]): index for index, row in daily.iterrows()}
        target = [value for value in trade_dates if value <= str(daily.iloc[-1]["_date"])]
        if not target:
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
                if previous is not None:
                    carried = {
                        **previous,
                        "trade_date": trade_date,
                        "adjusted_open": previous.get("adjusted_close"),
                        "raw_open": previous.get("raw_close"),
                    }
                    states.append(carried)
                    previous = carried
                else:
                    states.append(
                        {
                            "trade_date": trade_date,
                            "status": "data_incomplete",
                            "candidate_qualified": False,
                            "adjusted_open": None,
                            "adjusted_close": None,
                            "raw_open": None,
                            "raw_close": None,
                        }
                    )
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
        completed = [
            symbol
            for symbol in symbols
            if symbol in coverage
            and coverage[symbol].get("status") == "stable"
            and str(coverage[symbol].get("start_date") or "9999-12-31") <= start_date
            and str(coverage[symbol].get("end_date") or "") >= end_date
        ]
        if not symbols or len(completed) != len(symbols):
            return None
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
        names = self._stock_names(candidate_symbols)
        result = self.calculate_portfolio(
            period=period,
            candidate_rows=candidate_rows,
            price_rows=price_rows,
            benchmark_rows=benchmark,
            names=names,
            eligible_symbol_count=len(symbols),
        )
        coverage_versions = [coverage[symbol].get("data_version") for symbol in symbols]
        result["data_version"] = self._fingerprint(
            {
                "period": period,
                "coverage_versions": coverage_versions,
                "result": result,
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
    ) -> dict[str, Any]:
        resolved = cls._period(period)
        benchmark_by_date = {
            str(item["trade_date"]): float(item["close"])
            for item in benchmark_rows
            if cls._number(item.get("close")) is not None
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

        pending_rebalances: dict[str, dict[str, Any]] = {}
        prior_selection: set[str] = set()
        for index, trade_date in enumerate(dates[:-1]):
            selection = candidates.get(trade_date, set())
            if selection != prior_selection:
                pending_rebalances[dates[index + 1]] = {
                    "signal_date": trade_date,
                    "symbols": set(selection),
                }
            prior_selection = set(selection)

        units: dict[str, float] = {}
        cash = 1.0
        previous_close: dict[str, float] = {}
        points: list[dict[str, Any]] = []
        rebalances: list[dict[str, Any]] = []
        deferred = 0
        total_cost = 0.0
        total_turnover = 0.0
        benchmark_base = benchmark_by_date[dates[0]]
        pending: dict[str, Any] | None = None

        for trade_date in dates:
            if trade_date in pending_rebalances:
                pending = pending_rebalances[trade_date]
            if pending is not None:
                desired = set(pending["symbols"])
                involved = set(units) | desired
                day_prices = {symbol: prices.get((trade_date, symbol)) for symbol in involved}
                tradable = all(
                    item is not None
                    and cls._number(item.get("open")) is not None
                    and cls._number(item.get("close")) is not None
                    for item in day_prices.values()
                )
                if tradable:
                    values_at_open = {
                        symbol: units[symbol] * float(day_prices[symbol]["open"])
                        for symbol in units
                    }
                    pre_trade_nav = cash + sum(values_at_open.values())
                    target_weight = 1.0 / len(desired) if desired else 0.0
                    target_values = {
                        symbol: pre_trade_nav * target_weight for symbol in desired
                    }
                    turnover_amount = sum(
                        abs(target_values.get(symbol, 0.0) - values_at_open.get(symbol, 0.0))
                        for symbol in involved
                    )
                    cost = turnover_amount * cls.COST_BPS_PER_SIDE / 10_000.0
                    investable_nav = max(0.0, pre_trade_nav - cost)
                    target_value = investable_nav / len(desired) if desired else 0.0
                    old_symbols = set(units)
                    units = {
                        symbol: target_value / float(day_prices[symbol]["open"])
                        for symbol in desired
                    }
                    cash = investable_nav - target_value * len(desired)
                    turnover_ratio = (
                        turnover_amount / pre_trade_nav if pre_trade_nav else 0.0
                    )
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
                            "cost_pct_of_nav": round(
                                cost / pre_trade_nav * 100.0 if pre_trade_nav else 0.0,
                                4,
                            ),
                        }
                    )
                    pending = None
                else:
                    deferred += 1

            nav = cash
            for symbol, quantity in units.items():
                item = prices.get((trade_date, symbol)) or {}
                close = cls._number(item.get("close")) or previous_close.get(symbol)
                if close is None:
                    continue
                previous_close[symbol] = close
                nav += quantity * close
            benchmark_nav = benchmark_by_date[trade_date] / benchmark_base
            points.append(
                {
                    "trade_date": trade_date,
                    "nav": round(nav, 8),
                    "return_pct": round((nav - 1.0) * 100.0, 4),
                    "benchmark_nav": round(benchmark_nav, 8),
                    "benchmark_return_pct": round((benchmark_nav - 1.0) * 100.0, 4),
                    "holding_count": len(units),
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
        return {
            "period": resolved,
            "period_label": cls.PERIOD_LABELS[resolved],
            "start_date": dates[0],
            "end_date": dates[-1],
            "trading_days": len(dates),
            "eligible_symbol_count": int(eligible_symbol_count),
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
            "points": points,
            "rebalances": rebalances,
            "generated_at": utc_now(),
            "assumptions": cls._assumptions(),
            "boundary": cls.BOUNDARY,
            "debug": {"return_observation_count": len(returns)},
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
            completed = sum(
                item.get("status") == "stable"
                and str(item.get("start_date") or "9999-12-31") <= str(start_date)
                and str(item.get("end_date") or "") >= str(end_date)
                and str(item.get("symbol")) in eligible
                for item in coverage
            )
            snapshot = self.database.latest_tushare_dataset_snapshot(
                self.RESULT_DATASET,
                period,
                stable_only=True,
            )
            periods[period] = {
                "label": self.PERIOD_LABELS[period],
                "status": "ready" if snapshot else "building",
                "required_market_days": days,
                "available_market_days": available_market_days,
                "market_data_ratio": round(available_market_days / days, 6),
                "eligible_symbols": len(eligible),
                "evaluated_symbols": completed,
                "symbol_coverage_ratio": (
                    round(completed / len(eligible), 6) if eligible else 0.0
                ),
                "start_date": start_date,
                "end_date": end_date,
                "result_as_of_date": (snapshot or {}).get("as_of_date"),
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
        if (
            payload.get("rows")
            and str(payload.get("start_date") or "") <= start_date
            and str(payload.get("end_date") or "") >= end_date
        ):
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
        benchmark_payload = {
            "symbol": self.BENCHMARK_SYMBOL,
            "name": self.BENCHMARK_NAME,
            "start_date": start_date,
            "end_date": end_date,
            "rows": rows,
            "source": "Tushare Pro:index_daily",
            "generated_at": utc_now(),
        }
        self.database.save_tushare_dataset_snapshot(
            dataset=self.BENCHMARK_DATASET,
            scope_key=self.BENCHMARK_SYMBOL,
            as_of_date=end_date,
            report_period=None,
            source_updated_at=benchmark_payload["generated_at"],
            sync_run_id=sync_run_id,
            data_version=self._fingerprint(benchmark_payload),
            data_status="stable" if rows else "incomplete",
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
            else datetime.now(ZoneInfo("Asia/Shanghai")).date()
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
        if dates[-1] < end_date:
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
            "rebalance": "候选集合变化后，下一完整交易日开盘换仓。",
            "weighting": "每次换仓后对可成交候选等资金配置。",
            "cost_bps_per_side": cls.COST_BPS_PER_SIDE,
            "benchmark": cls.BENCHMARK_NAME,
            "price_basis": "复权因子调整后的开盘价和收盘价。",
            "cash_policy": "候选为空时持有现金，现金收益按0计。",
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
