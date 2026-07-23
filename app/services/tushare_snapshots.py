from __future__ import annotations

from datetime import date, datetime, timedelta
import hashlib
import json
import threading
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from app.catalog import normalize_symbol
from app.db import Database
from app.providers.tushare import TushareProviderError
from app.utils import utc_now


class TushareSnapshotUnavailable(RuntimeError):
    pass


class TushareSnapshotService:
    """Publish traceable per-symbol Tushare snapshots without replacing stable data."""

    METHOD = "tushare_symbol_snapshot_v1"
    SYMBOL_HISTORY_MARKET_DAYS = 700
    DATASETS = (
        "trade_cal",
        "stock_basic",
        "daily",
        "daily_basic",
        "fina_indicator",
        "adj_factor",
        "stk_limit",
        "top10_holders",
        "top10_floatholders",
        "income",
        "balancesheet",
        "cashflow",
        "forecast",
        "express",
        "disclosure_date",
    )
    REQUIRED_DATASETS = {
        "trade_cal",
        "stock_basic",
        "daily",
        "daily_basic",
        "fina_indicator",
        "adj_factor",
        "stk_limit",
        "top10_holders",
        "top10_floatholders",
    }
    UNIVERSE_MIN_MARKET_CAP_COVERAGE = 0.95

    def __init__(self, database: Database, client: Any | None):
        self.database = database
        self.client = client
        self._trade_calendar_cache: dict[tuple[str, str], pd.DataFrame] = {}
        self._trade_calendar_lock = threading.Lock()

    def sync_strategy_symbol(
        self,
        symbol: str,
        *,
        as_of_date: str | None = None,
        universe_item: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Sync only the datasets required by the deterministic strategy.

        The full-market snapshot already contains stock_basic and daily_basic.
        Reusing those rows avoids two identical per-symbol API calls, while
        optional statements remain available from an earlier full snapshot and
        can still be refreshed on demand through ``sync_symbol``.
        """

        return self.sync_symbol(
            symbol,
            as_of_date=as_of_date,
            include_optional=False,
            universe_item=universe_item,
        )

    def sync_symbol(
        self,
        symbol: str,
        *,
        as_of_date: str | None = None,
        include_optional: bool = True,
        universe_item: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self.client is None:
            raise TushareSnapshotUnavailable("Tushare 数据同步尚未配置")
        canonical = normalize_symbol(symbol)
        as_of = self._parse_as_of_date(as_of_date)
        requested_as_of = as_of.strftime("%Y%m%d")
        calendar_start = (as_of - timedelta(days=1100)).strftime("%Y%m%d")
        queried_datasets = tuple(
            dataset
            for dataset in self.DATASETS
            if include_optional or dataset in self.REQUIRED_DATASETS
        )
        previous_stable = self.database.latest_tushare_dataset_snapshot(
            "li_zong_inputs", canonical
        )
        sync_run = self.database.start_tushare_sync_run(
            job_scope=f"symbol:{canonical}",
            as_of_date=as_of.isoformat(),
            datasets=list(queried_datasets),
        )
        frames: dict[str, pd.DataFrame] = {}
        issues: list[dict[str, str]] = []
        reused_universe_datasets: set[str] = set()
        try:
            frames["trade_cal"] = self._trade_calendar(
                calendar_start=calendar_start,
                requested_as_of=requested_as_of,
            )
            trade_dates = self._open_trade_dates(frames["trade_cal"], requested_as_of)
            if not trade_dates:
                raise ValueError("没有可用的完整交易日")
            ts_code = self._to_tushare_symbol(canonical)
            hint_frames = self._universe_hint_frames(
                canonical=canonical,
                universe_item=universe_item,
                trade_dates=trade_dates,
                requested_as_of=requested_as_of,
            )
            frames.update(hint_frames)
            reused_universe_datasets.update(hint_frames)
            if "daily_basic" in frames:
                latest_trade_date = str(
                    frames["daily_basic"].iloc[0].get("trade_date")
                ).replace("-", "")
                daily_basic_error = None
            else:
                (
                    latest_trade_date,
                    frames["daily_basic"],
                    daily_basic_error,
                ) = self._latest_daily_basic(trade_dates, ts_code=ts_code)
            if daily_basic_error:
                issues.append(
                    {"dataset": "daily_basic", "error_type": daily_basic_error}
                )
            completed_trade_dates = [
                value for value in trade_dates if value <= latest_trade_date
            ]
            # The strategy needs up to 380 actual stock observations. Request a
            # substantially wider market-calendar buffer so a mature listing
            # with a long suspension can still contribute enough tradable rows
            # without adding another Tushare call.
            history_dates = completed_trade_dates[
                -self.SYMBOL_HISTORY_MARKET_DAYS :
            ]
            history_start = history_dates[0]
            query_specs = {
                "stock_basic": {
                    "ts_code": ts_code,
                    "fields": (
                        "ts_code,symbol,name,area,industry,market,list_date,"
                        "exchange,list_status"
                    ),
                },
                "daily": {
                    "ts_code": ts_code,
                    "start_date": history_start,
                    "end_date": latest_trade_date,
                    "fields": (
                        "ts_code,trade_date,open,high,low,close,pre_close,"
                        "change,pct_chg,vol,amount"
                    ),
                },
                "fina_indicator": {
                    "ts_code": ts_code,
                    "start_date": (as_of - timedelta(days=8 * 366)).strftime("%Y%m%d"),
                    "end_date": requested_as_of,
                    "fields": "ts_code,ann_date,end_date,roe,roe_waa,update_flag",
                },
                "adj_factor": {
                    "ts_code": ts_code,
                    "start_date": history_start,
                    "end_date": latest_trade_date,
                    "fields": "ts_code,trade_date,adj_factor",
                },
                "stk_limit": {
                    "ts_code": ts_code,
                    "start_date": history_start,
                    "end_date": latest_trade_date,
                    "fields": "ts_code,trade_date,pre_close,up_limit,down_limit",
                },
                "top10_holders": {
                    "ts_code": ts_code,
                    "start_date": (as_of - timedelta(days=3 * 366)).strftime("%Y%m%d"),
                    "end_date": requested_as_of,
                    "fields": (
                        "ts_code,ann_date,end_date,holder_name,hold_amount,hold_ratio"
                    ),
                },
                "top10_floatholders": {
                    "ts_code": ts_code,
                    "start_date": (as_of - timedelta(days=3 * 366)).strftime("%Y%m%d"),
                    "end_date": requested_as_of,
                    "fields": (
                        "ts_code,ann_date,end_date,holder_name,hold_amount,hold_ratio"
                    ),
                },
                "income": {
                    "ts_code": ts_code,
                    "start_date": (as_of - timedelta(days=8 * 366)).strftime("%Y%m%d"),
                    "end_date": requested_as_of,
                    "fields": (
                        "ts_code,ann_date,f_ann_date,end_date,report_type,"
                        "total_revenue,revenue,operate_profit,total_profit,"
                        "n_income,n_income_attr_p,basic_eps"
                    ),
                },
                "balancesheet": {
                    "ts_code": ts_code,
                    "start_date": (as_of - timedelta(days=8 * 366)).strftime("%Y%m%d"),
                    "end_date": requested_as_of,
                    "fields": (
                        "ts_code,ann_date,f_ann_date,end_date,total_assets,"
                        "total_liab,total_hldr_eqy_exc_min_int,accounts_receiv,"
                        "inventories"
                    ),
                },
                "cashflow": {
                    "ts_code": ts_code,
                    "start_date": (as_of - timedelta(days=8 * 366)).strftime("%Y%m%d"),
                    "end_date": requested_as_of,
                    "fields": (
                        "ts_code,ann_date,f_ann_date,end_date,n_cashflow_act,"
                        "n_cashflow_inv_act,n_cash_flows_fnc_act,"
                        "c_cash_equ_end_period"
                    ),
                },
                "forecast": {
                    "ts_code": ts_code,
                    "start_date": (as_of - timedelta(days=3 * 366)).strftime("%Y%m%d"),
                    "end_date": requested_as_of,
                    "fields": (
                        "ts_code,ann_date,end_date,type,p_change_min,p_change_max,"
                        "net_profit_min,net_profit_max,summary,change_reason"
                    ),
                },
                "express": {
                    "ts_code": ts_code,
                    "start_date": (as_of - timedelta(days=3 * 366)).strftime("%Y%m%d"),
                    "end_date": requested_as_of,
                    "fields": (
                        "ts_code,ann_date,end_date,revenue,operate_profit,"
                        "total_profit,n_income,total_assets,"
                        "total_hldr_eqy_exc_min_int,diluted_eps,diluted_roe"
                    ),
                },
                "disclosure_date": {
                    "ts_code": ts_code,
                    "start_date": (as_of - timedelta(days=366)).strftime("%Y%m%d"),
                    "end_date": (as_of + timedelta(days=366)).strftime("%Y%m%d"),
                    "fields": (
                        "ts_code,ann_date,end_date,pre_date,actual_date,modify_date"
                    ),
                },
            }
            for dataset, params in query_specs.items():
                if dataset not in queried_datasets or dataset in frames:
                    continue
                try:
                    frames[dataset] = self._query(dataset, **params)
                except Exception as exc:
                    frames[dataset] = pd.DataFrame()
                    issues.append(
                        {"dataset": dataset, "error_type": type(exc).__name__}
                    )

            generated_at = utc_now()
            dataset_packets: dict[str, dict[str, Any]] = {}
            missing_required: list[str] = []
            previous_datasets = (
                ((previous_stable or {}).get("payload") or {}).get("datasets") or {}
            )
            for dataset in self.DATASETS:
                previous_packet = previous_datasets.get(dataset) or {}
                if (
                    dataset not in queried_datasets
                    and previous_packet.get("rows")
                ):
                    payload = dict(previous_packet)
                    payload["reused_from_previous_snapshot"] = True
                else:
                    frame = frames.get(dataset, pd.DataFrame())
                    payload = self._dataset_payload(
                        dataset=dataset,
                        frame=frame,
                        canonical=canonical,
                        latest_trade_date=latest_trade_date,
                        generated_at=generated_at,
                    )
                    if dataset in reused_universe_datasets:
                        payload["source"] = "Tushare Pro:a_share_universe"
                        payload["reused_from_universe_snapshot"] = True
                dataset_packets[dataset] = payload
                if dataset in self.REQUIRED_DATASETS and not payload["rows"]:
                    missing_required.append(dataset)
                if dataset not in queried_datasets:
                    continue
                dataset_version = self._fingerprint(
                    {
                        "method": self.METHOD,
                        "dataset": dataset,
                        "scope": canonical,
                        "as_of": latest_trade_date,
                        "rows": payload["rows"],
                    }
                )
                self.database.save_tushare_dataset_snapshot(
                    dataset=dataset,
                    scope_key=canonical,
                    as_of_date=self._iso_date(latest_trade_date),
                    report_period=payload.get("report_period"),
                    source_updated_at=generated_at,
                    sync_run_id=str(sync_run["id"]),
                    data_version=dataset_version,
                    data_status="stable" if payload["rows"] else "incomplete",
                    payload=payload,
                )

            combined = {
                "method": self.METHOD,
                "sync_profile": (
                    "full_symbol_snapshot_v1"
                    if include_optional
                    else "strategy_required_only_v1"
                ),
                "symbol": canonical,
                "tushare_ts_code": self._to_tushare_symbol(canonical),
                "as_of_date": self._iso_date(latest_trade_date),
                "generated_at": generated_at,
                "datasets": dataset_packets,
                "coverage": {
                    "required": len(self.REQUIRED_DATASETS),
                    "available": len(self.REQUIRED_DATASETS) - len(missing_required),
                    "missing": missing_required,
                    "optional": len(self.DATASETS) - len(self.REQUIRED_DATASETS),
                    "optional_available": sum(
                        1
                        for dataset in self.DATASETS
                        if dataset not in self.REQUIRED_DATASETS
                        and dataset_packets[dataset]["rows"]
                    ),
                    "optional_missing": [
                        dataset
                        for dataset in queried_datasets
                        if dataset not in self.REQUIRED_DATASETS
                        and not dataset_packets[dataset]["rows"]
                    ],
                    "optional_skipped": [
                        dataset
                        for dataset in self.DATASETS
                        if dataset not in self.REQUIRED_DATASETS
                        and dataset not in queried_datasets
                    ],
                },
                "issues": issues,
                "data_status": "stable" if not missing_required else "incomplete",
                "boundary": (
                    "该快照只表示数据是否足以执行确定性选股规则；"
                    "不构成股票评分、推荐或交易指令。"
                ),
            }
            if include_optional:
                combined["coverage"].pop("optional_skipped", None)
            data_version = self._fingerprint(
                {
                    "method": self.METHOD,
                    "symbol": canonical,
                    "as_of_date": combined["as_of_date"],
                    "datasets": {
                        dataset: {
                            "report_period": packet.get("report_period"),
                            "rows": packet.get("rows") or [],
                        }
                        for dataset, packet in dataset_packets.items()
                    },
                    "issues": issues,
                }
            )
            if not missing_required:
                self.database.save_tushare_dataset_snapshot(
                    dataset="li_zong_inputs",
                    scope_key=canonical,
                    as_of_date=combined["as_of_date"],
                    report_period=self._latest_report_period(dataset_packets),
                    source_updated_at=generated_at,
                    sync_run_id=str(sync_run["id"]),
                    data_version=data_version,
                    data_status="stable",
                    payload=combined,
                )
                status = "stable"
            else:
                self.database.save_tushare_dataset_snapshot(
                    dataset="li_zong_inputs_incomplete",
                    scope_key=canonical,
                    as_of_date=combined["as_of_date"],
                    report_period=self._latest_report_period(dataset_packets),
                    source_updated_at=generated_at,
                    sync_run_id=str(sync_run["id"]),
                    data_version=data_version,
                    data_status="incomplete",
                    payload=combined,
                )
                status = "partial"
            finished = self.database.finish_tushare_sync_run(
                str(sync_run["id"]),
                status=status,
                data_version=data_version,
                summary={
                    "symbol": canonical,
                    "as_of_date": combined["as_of_date"],
                    "available_datasets": combined["coverage"]["available"],
                    "required_datasets": combined["coverage"]["required"],
                    "missing_datasets": missing_required,
                    "optional_available_datasets": combined["coverage"][
                        "optional_available"
                    ],
                    "optional_missing_datasets": combined["coverage"][
                        "optional_missing"
                    ],
                    "optional_skipped_datasets": combined["coverage"][
                        "optional_skipped"
                    ]
                    if "optional_skipped" in combined["coverage"]
                    else [],
                    "sync_profile": combined["sync_profile"],
                    "issues": issues,
                },
            )
            return {
                "run": self._public_run(finished),
                "snapshot": combined,
                "published": status == "stable",
                "previous_stable_retained": bool(
                    missing_required
                    and self.database.latest_tushare_dataset_snapshot(
                        "li_zong_inputs", canonical
                    )
                ),
            }
        except Exception as exc:
            previous = self.database.latest_tushare_dataset_snapshot(
                "li_zong_inputs", canonical
            )
            failed = self.database.finish_tushare_sync_run(
                str(sync_run["id"]),
                status="failed",
                data_version=None,
                summary={
                    "symbol": canonical,
                    "previous_stable_retained": previous is not None,
                },
                error=type(exc).__name__,
            )
            return {
                "run": self._public_run(failed),
                "snapshot": (previous or {}).get("payload"),
                "published": False,
                "previous_stable_retained": previous is not None,
            }

    def _trade_calendar(
        self, *, calendar_start: str, requested_as_of: str
    ) -> pd.DataFrame:
        key = (calendar_start, requested_as_of)
        with self._trade_calendar_lock:
            cached = self._trade_calendar_cache.get(key)
            if cached is not None:
                return cached.copy()
            frame = self._query(
                "trade_cal",
                exchange="SSE",
                start_date=calendar_start,
                end_date=requested_as_of,
                is_open="1",
                fields="exchange,cal_date,is_open,pretrade_date",
            )
            self._trade_calendar_cache = {key: frame.copy()}
            return frame.copy()

    @classmethod
    def _universe_hint_frames(
        cls,
        *,
        canonical: str,
        universe_item: dict[str, Any] | None,
        trade_dates: list[str],
        requested_as_of: str,
    ) -> dict[str, pd.DataFrame]:
        if not universe_item:
            return {}
        try:
            item_symbol = normalize_symbol(str(universe_item.get("symbol") or ""))
        except ValueError:
            return {}
        if item_symbol != canonical:
            return {}
        fallback_ts_code = (
            canonical[:-3] + ".SH" if canonical.endswith(".SS") else canonical
        )
        ts_code = str(
            universe_item.get("ts_code") or fallback_ts_code
        ).upper()
        stock_basic = pd.DataFrame(
            [
                {
                    "ts_code": ts_code,
                    "symbol": canonical.split(".", 1)[0],
                    "name": universe_item.get("name"),
                    "industry": universe_item.get("industry"),
                    "market": universe_item.get("market"),
                    "list_date": str(universe_item.get("list_date") or "").replace(
                        "-", ""
                    ),
                    "exchange": universe_item.get("exchange"),
                    "list_status": "L",
                }
            ]
        )
        frames = {"stock_basic": stock_basic}
        trade_date = str(universe_item.get("trade_date") or "").replace("-", "")
        if (
            trade_date
            and trade_date <= requested_as_of
            and trade_date in set(trade_dates)
            and universe_item.get("total_mv_yi") is not None
        ):
            frames["daily_basic"] = pd.DataFrame(
                [
                    {
                        "ts_code": ts_code,
                        "trade_date": trade_date,
                        "turnover_rate": universe_item.get("turnover_rate"),
                        "volume_ratio": universe_item.get("volume_ratio"),
                        "pe_ttm": universe_item.get("pe_ttm"),
                        "pb": universe_item.get("pb"),
                        "total_mv_yi": universe_item.get("total_mv_yi"),
                        "circ_mv_yi": universe_item.get("circ_mv_yi"),
                    }
                ]
            )
        return frames

    def get_symbol_snapshot(self, symbol: str) -> dict[str, Any]:
        canonical = normalize_symbol(symbol)
        stable = self.database.latest_tushare_dataset_snapshot(
            "li_zong_inputs", canonical
        )
        incomplete = self.database.latest_tushare_dataset_snapshot(
            "li_zong_inputs_incomplete", canonical, stable_only=False
        )
        if stable is None and incomplete is None:
            return {
                "symbol": canonical,
                "status": "not_ready",
                "snapshot": None,
                "boundary": "尚未发布可供选股使用的稳定 Tushare 快照。",
            }
        selected = stable or incomplete
        incomplete_payload = self._snapshot_payload_with_run_issues(incomplete)
        return {
            "symbol": canonical,
            "status": "stable" if stable is not None else "incomplete",
            "data_version": selected.get("data_version") if selected else None,
            "snapshot": selected.get("payload") if selected else None,
            "latest_incomplete": (
                incomplete_payload if incomplete_payload else None
            ),
            "boundary": (
                "稳定快照用于确定性研究和选股规则；缺失数据不会被自动判定为通过。"
            ),
        }

    def _snapshot_payload_with_run_issues(
        self, snapshot_record: dict[str, Any] | None
    ) -> dict[str, Any]:
        if not snapshot_record:
            return {}
        payload = dict(snapshot_record.get("payload") or {})
        if payload.get("issues"):
            return payload
        sync_run_id = str(snapshot_record.get("sync_run_id") or "")
        if not sync_run_id:
            return payload
        sync_run = self.database.get_tushare_sync_run(sync_run_id) or {}
        issues = list((sync_run.get("summary") or {}).get("issues") or [])
        if issues:
            payload["issues"] = issues
        return payload

    def sync_a_share_universe(
        self, *, as_of_date: str | None = None, force: bool = False
    ) -> dict[str, Any]:
        """Publish the listed A-share universe and latest market-cap prefilter."""

        as_of = self._parse_as_of_date(as_of_date)
        previous_stable = self.database.latest_tushare_dataset_snapshot(
            "a_share_universe", "all"
        )
        if (
            not force
            and previous_stable is not None
            and self._universe_snapshot_matches_request(
                previous_stable.get("payload") or {}, as_of
            )
        ):
            snapshot = previous_stable.get("payload") or {}
            return {
                "run": {
                    "id": previous_stable.get("sync_run_id"),
                    "job_scope": "universe:a_share",
                    "status": "stable",
                    "as_of_date": snapshot.get("as_of_date"),
                    "data_version": previous_stable.get("data_version"),
                    "summary": {
                        **(snapshot.get("coverage") or {}),
                        "as_of_date": snapshot.get("as_of_date"),
                        "published": True,
                        "reused": True,
                    },
                    "started_at": previous_stable.get("created_at"),
                    "finished_at": previous_stable.get("created_at"),
                },
                "snapshot": snapshot,
                "published": True,
                "previous_stable_retained": False,
                "reused": True,
            }
        if self.client is None:
            raise TushareSnapshotUnavailable("Tushare 数据同步尚未配置")
        requested_as_of = as_of.strftime("%Y%m%d")
        calendar_start = (as_of - timedelta(days=60)).strftime("%Y%m%d")
        sync_run = self.database.start_tushare_sync_run(
            job_scope="universe:a_share",
            as_of_date=as_of.isoformat(),
            datasets=["trade_cal", "stock_basic", "daily_basic"],
        )
        try:
            trade_cal = self._query(
                "trade_cal",
                exchange="SSE",
                start_date=calendar_start,
                end_date=requested_as_of,
                is_open="1",
                fields="exchange,cal_date,is_open,pretrade_date",
            )
            trade_dates = self._open_trade_dates(trade_cal, requested_as_of)
            if not trade_dates:
                raise ValueError("没有可用的完整交易日")
            stock_basic = self._query(
                "stock_basic",
                exchange="",
                list_status="L",
                fields=(
                    "ts_code,symbol,name,area,industry,market,list_date,"
                    "exchange,list_status"
                ),
            )
            latest_trade_date, daily_basic, daily_basic_error = (
                self._latest_daily_basic(trade_dates)
            )
            if stock_basic.empty:
                raise ValueError("股票基础名单为空")

            basics = stock_basic.copy().drop_duplicates("ts_code", keep="last")
            valuations = (
                daily_basic.copy().drop_duplicates("ts_code", keep="last")
                if not daily_basic.empty and "ts_code" in daily_basic
                else pd.DataFrame()
            )
            if not valuations.empty:
                merged = basics.merge(
                    valuations,
                    on="ts_code",
                    how="left",
                    suffixes=("", "_daily_basic"),
                )
            else:
                merged = basics

            items: list[dict[str, Any]] = []
            for _, row in merged.iterrows():
                ts_code = str(row.get("ts_code") or "").strip().upper()
                try:
                    symbol = self._from_tushare_symbol(ts_code)
                    normalize_symbol(symbol)
                except ValueError:
                    continue
                total_mv = pd.to_numeric(row.get("total_mv"), errors="coerce")
                total_mv_yi = (
                    round(float(total_mv) / 10_000.0, 4)
                    if pd.notna(total_mv)
                    else None
                )
                items.append(
                    {
                        "symbol": symbol,
                        "ts_code": ts_code,
                        "name": str(row.get("name") or symbol),
                        "industry": str(row.get("industry") or "") or None,
                        "market": str(row.get("market") or "") or None,
                        "exchange": str(row.get("exchange") or "") or None,
                        "list_date": self._iso_date(row.get("list_date")),
                        "trade_date": self._iso_date(
                            row.get("trade_date") or latest_trade_date
                        ),
                        "total_mv_yi": total_mv_yi,
                        "circ_mv_yi": self._wan_to_yi(row.get("circ_mv")),
                        "pe_ttm": self._optional_number(row.get("pe_ttm")),
                        "pb": self._optional_number(row.get("pb")),
                        "turnover_rate": self._optional_number(
                            row.get("turnover_rate")
                        ),
                        "volume_ratio": self._optional_number(
                            row.get("volume_ratio")
                        ),
                        "source": "Tushare Pro stock_basic + daily_basic",
                    }
                )
            items.sort(key=lambda item: item["symbol"])
            listed = len(items)
            with_market_cap = sum(
                item.get("total_mv_yi") is not None for item in items
            )
            coverage_ratio = with_market_cap / listed if listed else 0.0
            generated_at = utc_now()
            combined = {
                "method": "tushare_a_share_universe_v1",
                "requested_as_of_date": as_of.isoformat(),
                "as_of_date": self._iso_date(latest_trade_date),
                "generated_at": generated_at,
                "items": items,
                "coverage": {
                    "listed": listed,
                    "with_market_cap": with_market_cap,
                    "missing_market_cap": listed - with_market_cap,
                    "market_cap_coverage_ratio": round(coverage_ratio, 6),
                },
                "issues": (
                    [
                        {
                            "dataset": "daily_basic",
                            "error_type": daily_basic_error,
                        }
                    ]
                    if daily_basic_error
                    else []
                ),
                "boundary": (
                    "全市场名单和市值只用于李总策略第一层确定性预筛；"
                    "通过市值条件不代表进入候选池，仍需多年ROE、股东和量价证据。"
                ),
            }
            data_version = self._fingerprint(
                {
                    "method": combined["method"],
                    "as_of_date": combined["as_of_date"],
                    "items": items,
                }
            )
            stable = bool(listed) and (
                coverage_ratio >= self.UNIVERSE_MIN_MARKET_CAP_COVERAGE
            )
            dataset = "a_share_universe" if stable else "a_share_universe_incomplete"
            self.database.save_tushare_dataset_snapshot(
                dataset=dataset,
                scope_key="all",
                as_of_date=combined["as_of_date"],
                report_period=None,
                source_updated_at=generated_at,
                sync_run_id=str(sync_run["id"]),
                data_version=data_version,
                data_status="stable" if stable else "incomplete",
                payload=combined,
            )
            previous = self.database.latest_tushare_dataset_snapshot(
                "a_share_universe", "all"
            )
            finished = self.database.finish_tushare_sync_run(
                str(sync_run["id"]),
                status="stable" if stable else "partial",
                data_version=data_version,
                summary={
                    **combined["coverage"],
                    "as_of_date": combined["as_of_date"],
                    "published": stable,
                    "issues": combined["issues"],
                },
            )
            return {
                "run": self._public_run(finished),
                "snapshot": combined,
                "published": stable,
                "previous_stable_retained": bool(not stable and previous),
                "reused": False,
            }
        except Exception as exc:
            previous = self.database.latest_tushare_dataset_snapshot(
                "a_share_universe", "all"
            )
            failed = self.database.finish_tushare_sync_run(
                str(sync_run["id"]),
                status="failed",
                data_version=None,
                summary={"previous_stable_retained": previous is not None},
                error=type(exc).__name__,
            )
            return {
                "run": self._public_run(failed),
                "snapshot": (previous or {}).get("payload"),
                "published": False,
                "previous_stable_retained": previous is not None,
                "reused": False,
            }

    def get_a_share_universe(self) -> dict[str, Any]:
        stable = self.database.latest_tushare_dataset_snapshot(
            "a_share_universe", "all"
        )
        incomplete = self.database.latest_tushare_dataset_snapshot(
            "a_share_universe_incomplete", "all", stable_only=False
        )
        if stable is None and incomplete is None:
            return {
                "status": "not_ready",
                "snapshot": None,
                "boundary": "尚未发布A股全市场名单与市值快照。",
            }
        selected = stable or incomplete
        return {
            "status": "stable" if stable is not None else "incomplete",
            "data_version": selected.get("data_version") if selected else None,
            "snapshot": selected.get("payload") if selected else None,
            "latest_incomplete": (
                incomplete.get("payload") if incomplete is not None else None
            ),
            "boundary": (
                "全市场市值预筛是后台数据准备步骤；普通用户只读取已发布状态。"
            ),
        }

    def _query(self, api_name: str, **params: Any) -> pd.DataFrame:
        try:
            result = self.client.query(api_name, **params)
        except TushareProviderError:
            raise
        except Exception as exc:
            raise TushareProviderError(
                f"Tushare 接口 {api_name} 调用失败：{type(exc).__name__}"
            ) from exc
        if isinstance(result, pd.DataFrame):
            return result.copy()
        return pd.DataFrame(result or [])

    def _latest_daily_basic(
        self, trade_dates: list[str], *, ts_code: str | None = None
    ) -> tuple[str, pd.DataFrame, str | None]:
        latest_trade_date = trade_dates[-1]
        fields = (
            "ts_code,trade_date,turnover_rate,volume_ratio,pe_ttm,"
            "pb,total_mv,circ_mv"
        )
        for trade_date in reversed(trade_dates[-5:]):
            params: dict[str, Any] = {
                "trade_date": trade_date,
                "fields": fields,
            }
            if ts_code:
                params["ts_code"] = ts_code
            try:
                frame = self._query("daily_basic", **params)
            except Exception as exc:
                return latest_trade_date, pd.DataFrame(), type(exc).__name__
            if not frame.empty:
                return trade_date, frame, None
        return latest_trade_date, pd.DataFrame(), None

    @staticmethod
    def _open_trade_dates(frame: pd.DataFrame, as_of: str) -> list[str]:
        if frame.empty or "cal_date" not in frame:
            return []
        dates = []
        for _, row in frame.iterrows():
            value = str(row.get("cal_date") or "").replace("-", "")
            is_open = pd.to_numeric(row.get("is_open", 1), errors="coerce")
            if value and value <= as_of and is_open == 1:
                dates.append(value)
        return sorted(set(dates))

    @staticmethod
    def _dataset_payload(
        *,
        dataset: str,
        frame: pd.DataFrame,
        canonical: str,
        latest_trade_date: str,
        generated_at: str,
    ) -> dict[str, Any]:
        normalized = frame.copy()
        if not normalized.empty:
            normalized = normalized.replace({pd.NA: None})
            normalized = normalized.where(pd.notna(normalized), None)
        rows = normalized.to_dict(orient="records") if not normalized.empty else []
        report_periods = sorted(
            {
                str(row.get("end_date"))
                for row in rows
                if row.get("end_date") not in (None, "")
            },
            reverse=True,
        )
        return {
            "dataset": dataset,
            "symbol": canonical,
            "as_of_date": TushareSnapshotService._iso_date(latest_trade_date),
            "report_period": (
                TushareSnapshotService._iso_date(report_periods[0])
                if report_periods
                else None
            ),
            "source": "Tushare Pro",
            "source_updated_at": generated_at,
            "rows": rows,
            "row_count": len(rows),
        }

    @staticmethod
    def _latest_report_period(
        datasets: dict[str, dict[str, Any]]
    ) -> str | None:
        periods = sorted(
            {
                str(packet.get("report_period"))
                for packet in datasets.values()
                if packet.get("report_period")
            },
            reverse=True,
        )
        return periods[0] if periods else None

    @staticmethod
    def _fingerprint(payload: dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(
                payload, ensure_ascii=False, sort_keys=True, default=str
            ).encode("utf-8")
        ).hexdigest()

    def _to_tushare_symbol(self, symbol: str) -> str:
        converter = getattr(self.client, "to_tushare_symbol", None)
        if callable(converter):
            return str(converter(symbol))
        return symbol[:-3] + ".SH" if symbol.endswith(".SS") else symbol

    @staticmethod
    def _from_tushare_symbol(symbol: str) -> str:
        return symbol[:-3] + ".SS" if symbol.endswith(".SH") else symbol

    @staticmethod
    def _optional_number(value: Any) -> float | None:
        number = pd.to_numeric(value, errors="coerce")
        return round(float(number), 6) if pd.notna(number) else None

    @classmethod
    def _wan_to_yi(cls, value: Any) -> float | None:
        number = cls._optional_number(value)
        return round(number / 10_000.0, 4) if number is not None else None

    @staticmethod
    def _parse_as_of_date(value: str | None) -> date:
        if value:
            text = str(value).strip().replace("-", "")
            return datetime.strptime(text, "%Y%m%d").date()
        return datetime.now(ZoneInfo("Asia/Shanghai")).date()

    @staticmethod
    def _universe_snapshot_matches_request(
        snapshot: dict[str, Any], requested_as_of: date
    ) -> bool:
        requested = requested_as_of.isoformat()
        stored_request = str(snapshot.get("requested_as_of_date") or "").strip()
        if stored_request:
            return stored_request == requested
        return str(snapshot.get("as_of_date") or "").strip() == requested

    @staticmethod
    def _iso_date(value: Any) -> str | None:
        text = str(value or "").strip().replace("-", "")
        if len(text) != 8 or not text.isdigit():
            return None
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"

    @staticmethod
    def _public_run(run: dict[str, Any] | None) -> dict[str, Any] | None:
        if run is None:
            return None
        return {
            "id": run.get("id"),
            "job_scope": run.get("job_scope"),
            "status": run.get("status"),
            "as_of_date": run.get("as_of_date"),
            "data_version": run.get("data_version"),
            "summary": run.get("summary"),
            "started_at": run.get("started_at"),
            "finished_at": run.get("finished_at"),
        }
