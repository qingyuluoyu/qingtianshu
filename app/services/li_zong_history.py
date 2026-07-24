from __future__ import annotations

from collections import Counter
from datetime import datetime
import hashlib
import json
from typing import Any, Mapping, Sequence

import pandas as pd

from app.catalog import normalize_symbol
from app.db import Database
from app.providers.tushare import TushareClient
from app.services.li_zong_strategy_service import LiZongStrategyService
from app.services.strategies.li_zong import (
    CANDIDATE_RULE_IDS,
    STRATEGY_ID,
    STRATEGY_VERSION,
    LiZongParameters,
    deterministic_li_zong_v1,
)
from app.utils import utc_now


class LiZongHistoryService:
    """Recent point-in-time replay for the deterministic Li Zong strategy."""

    HISTORY_DATASET = "li_zong_history"
    MARKET_CAP_DATASET = "daily_basic_history"
    BENCHMARK_DATASET = "li_zong_benchmark_history"
    HISTORY_VERSION = "li_zong_history_v2"
    BENCHMARK_SYMBOL = "000300.SS"
    BENCHMARK_NAME = "沪深300"
    HORIZONS = (5, 10, 20)
    DEFAULT_LOOKBACK_DAYS = 80

    BOUNDARY = (
        "历史回放只使用信号日当时已公告的财务和股东数据、当日历史市值与"
        "信号日及以前的量价数据；信号后表现仅用于复盘，不代表未来结果，"
        "也未计入交易成本、涨跌停可成交性或实际成交价格。"
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

    def run_batch(
        self,
        *,
        batch_size: int = 5,
        symbols: Sequence[str] | None = None,
        lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    ) -> dict[str, Any]:
        if self.client is None:
            return {
                "status": "disabled",
                "processed_symbols": [],
                "coverage": self.coverage_packet(),
                "boundary": self.BOUNDARY,
            }
        size = max(1, min(int(batch_size), 20))
        lookback = max(20, min(int(lookback_days), 160))
        base_meta = self._base_snapshot_meta()
        requested = self._canonical_symbols(symbols or []) if symbols else None
        if requested is not None:
            selected_symbols = [symbol for symbol in requested if symbol in base_meta]
        else:
            selected_symbols = self._pending_symbols(base_meta)[:size]
        if not selected_symbols:
            return {
                "status": "completed",
                "processed_symbols": [],
                "coverage": self.coverage_packet(),
                "boundary": self.BOUNDARY,
            }

        base_snapshots = [
            self.database.latest_tushare_dataset_snapshot(
                "li_zong_inputs", symbol, stable_only=True
            )
            for symbol in selected_symbols
        ]
        base_snapshots = [item for item in base_snapshots if item is not None]
        if not base_snapshots:
            return {
                "status": "completed",
                "processed_symbols": [],
                "coverage": self.coverage_packet(),
                "boundary": self.BOUNDARY,
            }

        start_date, end_date = self._batch_date_range(base_snapshots, lookback)
        sync_run = self.database.start_tushare_sync_run(
            job_scope="li_zong_history_batch",
            as_of_date=self._iso_date(end_date),
            datasets=[
                self.MARKET_CAP_DATASET,
                self.BENCHMARK_DATASET,
                self.HISTORY_DATASET,
            ],
        )
        run_id = str(sync_run["id"])
        processed: list[str] = []
        failed: list[dict[str, str]] = []
        try:
            benchmark = self._benchmark_rows(
                start_date=start_date,
                end_date=end_date,
                sync_run_id=run_id,
            )
            for base in base_snapshots:
                symbol = str(base["scope_key"])
                try:
                    payload = self._replay_symbol(
                        base,
                        benchmark=benchmark,
                        lookback_days=lookback,
                        sync_run_id=run_id,
                    )
                    processed.append(symbol)
                    if payload.get("status") != "stable":
                        failed.append(
                            {
                                "symbol": symbol,
                                "error_type": str(payload.get("error_type") or "IncompleteData"),
                            }
                        )
                except Exception as exc:
                    failed.append({"symbol": symbol, "error_type": type(exc).__name__})
                    self._save_incomplete_history(
                        base,
                        sync_run_id=run_id,
                        lookback_days=lookback,
                        error_type=type(exc).__name__,
                    )
            status = "completed" if not failed else "partial"
            data_version = self._fingerprint(
                {
                    "history_version": self.HISTORY_VERSION,
                    "processed": processed,
                    "failed": failed,
                    "as_of_date": self._iso_date(end_date),
                }
            )
            self.database.finish_tushare_sync_run(
                run_id,
                status="stable" if status == "completed" else "partial",
                data_version=data_version,
                summary={
                    "processed_symbols": processed,
                    "failed": failed,
                    "lookback_days": lookback,
                },
            )
        except Exception as exc:
            self.database.finish_tushare_sync_run(
                run_id,
                status="failed",
                data_version=None,
                summary={"processed_symbols": processed, "failed": failed},
                error=f"{type(exc).__name__}: history batch unavailable",
            )
            return {
                "status": "failed",
                "processed_symbols": processed,
                "failed": [*failed, {"symbol": "benchmark", "error_type": type(exc).__name__}],
                "coverage": self.coverage_packet(),
                "boundary": self.BOUNDARY,
            }
        return {
            "status": status,
            "processed_symbols": processed,
            "failed": failed,
            "coverage": self.coverage_packet(),
            "boundary": self.BOUNDARY,
        }

    def history_packet(
        self,
        *,
        symbol: str | None = None,
        limit: int = 30,
    ) -> dict[str, Any]:
        canonical = normalize_symbol(symbol) if symbol else None
        size = max(1, min(int(limit), 200))
        base_meta = self._base_snapshot_meta()
        snapshots = self.database.list_latest_tushare_dataset_snapshots(
            self.HISTORY_DATASET,
            include_payload=True,
        )
        events: list[dict[str, Any]] = []
        for snapshot in snapshots:
            scope = str(snapshot.get("scope_key") or "")
            if canonical and scope != canonical:
                continue
            base = base_meta.get(scope)
            payload = snapshot.get("payload") or {}
            if (
                snapshot.get("data_status") != "stable"
                or base is None
                or payload.get("history_version") != self.HISTORY_VERSION
                or payload.get("base_data_version") != base.get("data_version")
            ):
                continue
            stock_basic = payload.get("stock_basic") or {}
            for event in payload.get("events") or []:
                events.append(
                    {
                        **event,
                        "symbol": scope,
                        "internal_symbol": scope,
                        "name": stock_basic.get("name") or scope,
                        "industry": stock_basic.get("industry"),
                        "market": stock_basic.get("market"),
                        "history_version": payload.get("history_version"),
                        "replay_as_of_date": payload.get("as_of_date"),
                        "source_data_version": payload.get("base_data_version"),
                    }
                )
        events.sort(
            key=lambda item: (
                str(item.get("signal_date") or ""),
                str(item.get("symbol") or ""),
            ),
            reverse=True,
        )
        coverage = self.coverage_packet()
        return {
            "strategy_id": STRATEGY_ID,
            "strategy_version": STRATEGY_VERSION,
            "history_version": self.HISTORY_VERSION,
            "status": (
                "ready"
                if events or int(coverage.get("completed_symbols") or 0) > 0
                else "preparing"
            ),
            "benchmark": {
                "symbol": self.BENCHMARK_SYMBOL,
                "name": self.BENCHMARK_NAME,
            },
            "items": events[:size],
            "coverage": coverage,
            "boundary": self.BOUNDARY,
        }

    def coverage_packet(self) -> dict[str, Any]:
        base_meta = self._base_snapshot_meta()
        history = self.database.list_latest_tushare_dataset_snapshots(
            self.HISTORY_DATASET,
            include_payload=True,
        )
        current: dict[str, dict[str, Any]] = {}
        for snapshot in history:
            symbol = str(snapshot.get("scope_key") or "")
            base = base_meta.get(symbol)
            payload = snapshot.get("payload") or {}
            if (
                base
                and payload.get("history_version") == self.HISTORY_VERSION
                and payload.get("base_data_version") == base.get("data_version")
            ):
                current[symbol] = snapshot
        completed = sum(item.get("data_status") == "stable" for item in current.values())
        incomplete = sum(
            item.get("data_status") == "incomplete" for item in current.values()
        )
        hit_events = sum(
            len((item.get("payload") or {}).get("events") or [])
            for item in current.values()
            if item.get("data_status") == "stable"
        )
        expected = len(base_meta)
        return {
            "as_of_date": max(
                (str(item.get("as_of_date") or "") for item in base_meta.values()),
                default=None,
            ),
            "expected_symbols": expected,
            "completed_symbols": completed,
            "incomplete_symbols": incomplete,
            "remaining_symbols": max(0, expected - completed - incomplete),
            "coverage_ratio": round(completed / expected, 6) if expected else 0.0,
            "hit_events": hit_events,
            "full_coverage": bool(expected and completed == expected),
            "lookback_days": self.DEFAULT_LOOKBACK_DAYS,
            "scope": "recent_point_in_time_replay",
            "boundary": (
                "覆盖率表示已有当前数据版本对应的近期历史回放，不代表多年全市场回测。"
            ),
        }

    def _replay_symbol(
        self,
        base_snapshot: Mapping[str, Any],
        *,
        benchmark: pd.DataFrame,
        lookback_days: int,
        sync_run_id: str,
    ) -> dict[str, Any]:
        symbol = str(base_snapshot["scope_key"])
        snapshot_payload = dict(base_snapshot.get("payload") or {})
        packet = {
            "status": "stable",
            "data_version": base_snapshot.get("data_version"),
            "snapshot": snapshot_payload,
        }
        supplemental_roe = self._published_supplemental_roe(symbol)
        strategy_input = self.strategy_service._build_input(
            symbol,
            packet,
            supplemental_roe_rows=supplemental_roe,
        )
        daily = self._dated_frame(strategy_input.get("daily"), "trade_date")
        if daily.empty:
            raise ValueError("published daily history is empty")
        signal_dates = list(daily["_date"].drop_duplicates().tail(lookback_days))
        if not signal_dates:
            raise ValueError("no replay dates")
        market_cap = self._market_cap_rows(
            symbol,
            start_date=signal_dates[0],
            end_date=signal_dates[-1],
            sync_run_id=sync_run_id,
        )
        evaluations: list[dict[str, Any]] = []
        events: list[dict[str, Any]] = []
        previous_status = "not_qualified"
        for signal_date in signal_dates:
            result = deterministic_li_zong_v1(
                {
                    **strategy_input,
                    "as_of_date": signal_date,
                    "daily": daily[daily["_date"] <= signal_date].drop(
                        columns=["_date"], errors="ignore"
                    ),
                    "daily_basic": market_cap,
                },
                parameters=LiZongParameters(),
            )
            status = str(result.get("status") or "data_incomplete")
            evaluations.append(
                {
                    "trade_date": signal_date,
                    "status": status,
                    "candidate_qualified": bool(result.get("candidate_qualified")),
                }
            )
            record = (
                status == "triggered" and previous_status != "triggered"
            ) or (
                status == "qualified"
                and previous_status not in {"qualified", "triggered"}
            )
            if record:
                events.append(
                    self._history_event(
                        signal_date=signal_date,
                        evaluation=result,
                        daily=daily,
                        benchmark=benchmark,
                    )
                )
            previous_status = status
        counts = Counter(item["status"] for item in evaluations)
        payload = {
            "history_version": self.HISTORY_VERSION,
            "strategy_id": STRATEGY_ID,
            "strategy_version": STRATEGY_VERSION,
            "parameter_version": LiZongParameters().parameter_version,
            "symbol": symbol,
            "stock_basic": self.strategy_service._packet_stock_basic(packet),
            "as_of_date": str(base_snapshot.get("as_of_date") or signal_dates[-1]),
            "base_data_version": str(base_snapshot.get("data_version") or ""),
            "lookback_days": lookback_days,
            "evaluated_start_date": signal_dates[0],
            "evaluated_end_date": signal_dates[-1],
            "evaluated_days": len(evaluations),
            "evaluation_counts": dict(counts),
            "events": events,
            "benchmark": {
                "symbol": self.BENCHMARK_SYMBOL,
                "name": self.BENCHMARK_NAME,
            },
            "no_lookahead": {
                "price": "每个信号日只传入该日及以前日线",
                "market_cap": "使用信号日对应 historical daily_basic",
                "financials": "ROE 规则只接受公告日不晚于信号日的数据",
                "shareholders": "股东规则只接受公告日不晚于信号日的数据",
            },
            "generated_at": utc_now(),
            "boundary": self.BOUNDARY,
        }
        version = self._fingerprint(payload)
        self.database.save_tushare_dataset_snapshot(
            dataset=self.HISTORY_DATASET,
            scope_key=symbol,
            as_of_date=payload["as_of_date"],
            report_period=None,
            source_updated_at=payload["generated_at"],
            sync_run_id=sync_run_id,
            data_version=version,
            data_status="stable",
            payload=payload,
        )
        return {"status": "stable", **payload}

    def _history_event(
        self,
        *,
        signal_date: str,
        evaluation: Mapping[str, Any],
        daily: pd.DataFrame,
        benchmark: pd.DataFrame,
    ) -> dict[str, Any]:
        performance = self._performance(
            signal_date=signal_date,
            daily=daily,
            benchmark=benchmark,
        )
        return {
            "signal_date": signal_date,
            "signal_type": str(evaluation.get("status") or "qualified"),
            "triggered_rule_ids": list(evaluation.get("triggered_rule_ids") or []),
            "rule_results": list(evaluation.get("rule_results") or []),
            "rule_summary": self._rule_summary(evaluation.get("rule_results") or []),
            "performance": performance,
            "performance_status": (
                "complete"
                if all(
                    (performance.get("horizons") or {}).get(str(day), {}).get(
                        "status"
                    )
                    == "available"
                    for day in self.HORIZONS
                )
                else "partial"
            ),
        }

    def _performance(
        self,
        *,
        signal_date: str,
        daily: pd.DataFrame,
        benchmark: pd.DataFrame,
    ) -> dict[str, Any]:
        stock = daily.copy().sort_values("_date")
        stock["close"] = pd.to_numeric(stock.get("close"), errors="coerce")
        stock["high"] = pd.to_numeric(stock.get("high"), errors="coerce")
        stock["low"] = pd.to_numeric(stock.get("low"), errors="coerce")
        index = benchmark.copy().sort_values("_date")
        signal_stock = stock[stock["_date"] == signal_date]
        signal_index = index[index["_date"] == signal_date]
        if signal_stock.empty or signal_index.empty:
            return {
                "signal_close": None,
                "benchmark_signal_close": None,
                "horizons": {},
                "path": [],
                "limitations": ["信号日个股或沪深300收盘数据缺失。"],
            }
        stock_base = float(signal_stock.iloc[-1]["close"])
        index_base = float(signal_index.iloc[-1]["close"])
        future_index = index[index["_date"] >= signal_date].reset_index(drop=True)
        horizons: dict[str, dict[str, Any]] = {}
        for day in self.HORIZONS:
            if len(future_index) <= day:
                horizons[str(day)] = {
                    "status": "pending",
                    "target_date": None,
                    "stock_return_pct": None,
                    "benchmark_return_pct": None,
                    "excess_return_pct": None,
                    "max_upside_pct": None,
                    "max_drawdown_pct": None,
                    "max_upside_date": None,
                    "max_drawdown_date": None,
                }
                continue
            target = future_index.iloc[day]
            target_date = str(target["_date"])
            stock_window = stock[
                (stock["_date"] >= signal_date) & (stock["_date"] <= target_date)
            ]
            if stock_window.empty:
                horizons[str(day)] = {
                    "status": "unavailable",
                    "target_date": target_date,
                    "stock_return_pct": None,
                    "benchmark_return_pct": self._return_pct(
                        float(target["close"]), index_base
                    ),
                    "excess_return_pct": None,
                    "max_upside_pct": None,
                    "max_drawdown_pct": None,
                    "max_upside_date": None,
                    "max_drawdown_date": None,
                }
                continue
            stock_target = stock_window.iloc[-1]
            stock_return = self._return_pct(float(stock_target["close"]), stock_base)
            benchmark_return = self._return_pct(float(target["close"]), index_base)
            max_high_row = stock_window.loc[stock_window["high"].idxmax()]
            min_low_row = stock_window.loc[stock_window["low"].idxmin()]
            horizons[str(day)] = {
                "status": "available",
                "target_date": target_date,
                "stock_trade_date": str(stock_target["_date"]),
                "stock_return_pct": stock_return,
                "benchmark_return_pct": benchmark_return,
                "excess_return_pct": round(stock_return - benchmark_return, 4),
                "max_upside_pct": self._return_pct(
                    float(stock_window["high"].max()), stock_base
                ),
                "max_drawdown_pct": self._return_pct(
                    float(stock_window["low"].min()), stock_base
                ),
                "max_upside_date": str(max_high_row["_date"]),
                "max_drawdown_date": str(min_low_row["_date"]),
            }
        path: list[dict[str, Any]] = []
        for _, row in future_index.head(max(self.HORIZONS) + 1).iterrows():
            point_date = str(row["_date"])
            stock_as_of = stock[
                (stock["_date"] >= signal_date) & (stock["_date"] <= point_date)
            ]
            if stock_as_of.empty:
                continue
            stock_close = float(stock_as_of.iloc[-1]["close"])
            stock_return = self._return_pct(stock_close, stock_base)
            benchmark_return = self._return_pct(float(row["close"]), index_base)
            path.append(
                {
                    "trade_date": point_date,
                    "stock_return_pct": stock_return,
                    "benchmark_return_pct": benchmark_return,
                    "excess_return_pct": round(stock_return - benchmark_return, 4),
                }
            )
        return {
            "signal_close": stock_base,
            "benchmark_signal_close": index_base,
            "horizons": horizons,
            "path": path,
            "limitations": [],
        }

    def _market_cap_rows(
        self,
        symbol: str,
        *,
        start_date: str,
        end_date: str,
        sync_run_id: str,
    ) -> pd.DataFrame:
        cached = self.database.latest_tushare_dataset_snapshot(
            self.MARKET_CAP_DATASET, symbol, stable_only=True
        )
        if cached and self._covers(cached.get("payload") or {}, start_date, end_date):
            return pd.DataFrame((cached.get("payload") or {}).get("rows") or [])
        ts_code = TushareClient.to_tushare_symbol(symbol)
        frame = self.client.daily_basic(
            ts_code=ts_code,
            start_date=self._compact_date(start_date),
            end_date=self._compact_date(end_date),
            fields="ts_code,trade_date,total_mv,circ_mv",
        )
        rows = self._records(frame)
        for row in rows:
            total_mv = self._number(row.get("total_mv"))
            if total_mv is not None:
                row["total_mv_yi"] = total_mv / 10_000.0
            row["source"] = "Tushare Pro:daily_basic"
        payload = {
            "symbol": symbol,
            "start_date": start_date,
            "end_date": end_date,
            "rows": rows,
            "row_count": len(rows),
            "source": "Tushare Pro:daily_basic",
            "generated_at": utc_now(),
        }
        self.database.save_tushare_dataset_snapshot(
            dataset=self.MARKET_CAP_DATASET,
            scope_key=symbol,
            as_of_date=end_date,
            report_period=None,
            source_updated_at=payload["generated_at"],
            sync_run_id=sync_run_id,
            data_version=self._fingerprint(payload),
            data_status="stable" if rows else "incomplete",
            payload=payload,
        )
        if not rows:
            raise ValueError("historical daily_basic is empty")
        return pd.DataFrame(rows)

    def _benchmark_rows(
        self,
        *,
        start_date: str,
        end_date: str,
        sync_run_id: str,
    ) -> pd.DataFrame:
        cached = self.database.latest_tushare_dataset_snapshot(
            self.BENCHMARK_DATASET, self.BENCHMARK_SYMBOL, stable_only=True
        )
        if cached and self._covers(cached.get("payload") or {}, start_date, end_date):
            return self._dated_frame(
                (cached.get("payload") or {}).get("rows") or [], "trade_date"
            )
        frame = self.client.index_daily(
            ts_code=TushareClient.to_tushare_symbol(self.BENCHMARK_SYMBOL),
            start_date=self._compact_date(start_date),
            end_date=self._compact_date(end_date),
            fields="ts_code,trade_date,open,high,low,close,pre_close,pct_chg",
        )
        rows = self._records(frame)
        payload = {
            "symbol": self.BENCHMARK_SYMBOL,
            "name": self.BENCHMARK_NAME,
            "start_date": start_date,
            "end_date": end_date,
            "rows": rows,
            "row_count": len(rows),
            "source": "Tushare Pro:index_daily",
            "generated_at": utc_now(),
        }
        self.database.save_tushare_dataset_snapshot(
            dataset=self.BENCHMARK_DATASET,
            scope_key=self.BENCHMARK_SYMBOL,
            as_of_date=end_date,
            report_period=None,
            source_updated_at=payload["generated_at"],
            sync_run_id=sync_run_id,
            data_version=self._fingerprint(payload),
            data_status="stable" if rows else "incomplete",
            payload=payload,
        )
        if not rows:
            raise ValueError("benchmark history is empty")
        return self._dated_frame(rows, "trade_date")

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
        rows: list[dict[str, Any]] = []
        for item in (rule or {}).get("actual_value") or []:
            if not item.get("fallback_reason"):
                continue
            rows.append(
                {
                    "ts_code": symbol,
                    "end_date": item.get("report_period"),
                    "ann_date": item.get("announcement_date"),
                    "roe": item.get("roe_pct"),
                    "source": item.get("source"),
                    "source_url": item.get("source_url"),
                    "fallback_reason": item.get("fallback_reason"),
                }
            )
        return rows

    def _pending_symbols(self, base_meta: Mapping[str, Mapping[str, Any]]) -> list[str]:
        history = {
            str(item.get("scope_key")): item
            for item in self.database.list_latest_tushare_dataset_snapshots(
                self.HISTORY_DATASET,
                include_payload=True,
            )
        }
        states = self.database.latest_strategy_candidate_states(
            strategy_id=STRATEGY_ID,
            strategy_version=STRATEGY_VERSION,
            parameter_version=LiZongParameters().parameter_version,
        )
        pending = []
        for symbol, base in base_meta.items():
            existing = history.get(symbol)
            payload = (existing or {}).get("payload") or {}
            if (
                (existing or {}).get("data_status") == "stable"
                and payload.get("history_version") == self.HISTORY_VERSION
                and payload.get("base_data_version") == base.get("data_version")
            ):
                continue
            result = (states.get(symbol) or {}).get("result") or {}
            statuses = {
                str(item.get("rule_id")): str(item.get("status") or "")
                for item in result.get("rule_results") or []
            }
            passed = sum(statuses.get(rule_id) == "passed" for rule_id in CANDIDATE_RULE_IDS)
            pending.append((passed, symbol))
        pending.sort(key=lambda item: (-item[0], item[1]))
        return [symbol for _, symbol in pending]

    def _base_snapshot_meta(self) -> dict[str, dict[str, Any]]:
        items = self.database.list_latest_tushare_dataset_snapshots(
            "li_zong_inputs",
            data_status="stable",
            include_payload=False,
        )
        return {str(item["scope_key"]): item for item in items}

    def _save_incomplete_history(
        self,
        base_snapshot: Mapping[str, Any],
        *,
        sync_run_id: str,
        lookback_days: int,
        error_type: str,
    ) -> None:
        symbol = str(base_snapshot.get("scope_key") or "")
        payload = {
            "history_version": self.HISTORY_VERSION,
            "symbol": symbol,
            "as_of_date": base_snapshot.get("as_of_date"),
            "base_data_version": base_snapshot.get("data_version"),
            "lookback_days": lookback_days,
            "events": [],
            "error_type": error_type,
            "generated_at": utc_now(),
            "boundary": self.BOUNDARY,
        }
        self.database.save_tushare_dataset_snapshot(
            dataset=self.HISTORY_DATASET,
            scope_key=symbol,
            as_of_date=str(base_snapshot.get("as_of_date") or "") or None,
            report_period=None,
            source_updated_at=payload["generated_at"],
            sync_run_id=sync_run_id,
            data_version=self._fingerprint(payload),
            data_status="incomplete",
            payload=payload,
        )

    @staticmethod
    def _rule_summary(rules: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        by_id = {str(item.get("rule_id")): item for item in rules}
        return {
            "passed_candidate_rules": sum(
                (by_id.get(rule_id) or {}).get("status") == "passed"
                for rule_id in CANDIDATE_RULE_IDS
            ),
            "candidate_rule_count": len(CANDIDATE_RULE_IDS),
            "triggered_rules": [
                rule_id
                for rule_id in ("LZ-T-01", "LZ-T-02", "LZ-T-03")
                if (by_id.get(rule_id) or {}).get("status") == "passed"
            ],
        }

    def _batch_date_range(
        self, snapshots: Sequence[Mapping[str, Any]], lookback_days: int
    ) -> tuple[str, str]:
        starts: list[str] = []
        ends: list[str] = []
        for snapshot in snapshots:
            datasets = ((snapshot.get("payload") or {}).get("datasets") or {})
            rows = ((datasets.get("daily") or {}).get("rows") or [])
            frame = self._dated_frame(rows, "trade_date")
            if frame.empty:
                continue
            dates = list(frame["_date"].drop_duplicates().tail(lookback_days))
            if dates:
                starts.append(dates[0])
                ends.append(dates[-1])
        if not starts or not ends:
            raise ValueError("published history has no replay date range")
        return min(starts), max(ends)

    @staticmethod
    def _dated_frame(value: Any, column: str) -> pd.DataFrame:
        frame = value.copy() if isinstance(value, pd.DataFrame) else pd.DataFrame(value)
        if frame.empty or column not in frame:
            return pd.DataFrame()
        frame = frame.copy()
        frame["_date"] = frame[column].map(LiZongHistoryService._iso_date)
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
    def _covers(payload: Mapping[str, Any], start_date: str, end_date: str) -> bool:
        return bool(
            payload.get("rows")
            and str(payload.get("start_date") or "") <= start_date
            and str(payload.get("end_date") or "") >= end_date
        )

    @staticmethod
    def _return_pct(value: float, base: float) -> float:
        if base == 0:
            return 0.0
        return round((value / base - 1.0) * 100.0, 4)

    @staticmethod
    def _number(value: Any) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if pd.notna(number) else None

    @staticmethod
    def _iso_date(value: Any) -> str | None:
        if value is None or value == "":
            return None
        if isinstance(value, datetime):
            return value.date().isoformat()
        text = str(value).strip().replace("/", "-")
        if len(text) >= 10 and text[4] == "-" and text[7] == "-":
            return text[:10]
        digits = "".join(character for character in text if character.isdigit())
        if len(digits) >= 8:
            return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
        return None

    @staticmethod
    def _compact_date(value: str) -> str:
        return str(value).replace("-", "")

    @staticmethod
    def _fingerprint(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode(
                "utf-8"
            )
        ).hexdigest()

    @staticmethod
    def _canonical_symbols(symbols: Sequence[str]) -> list[str]:
        result: list[str] = []
        for value in symbols:
            symbol = normalize_symbol(str(value))
            if symbol.endswith((".SS", ".SZ", ".BJ")) and symbol not in result:
                result.append(symbol)
        return result


__all__ = ["LiZongHistoryService"]
