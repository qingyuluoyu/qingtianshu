from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, time as clock_time, timedelta
import hashlib
import math
import threading
import time
from typing import Any, Mapping
from zoneinfo import ZoneInfo

import pandas as pd

from app.providers.tushare import TushareProviderError
from app.utils import utc_now


class StockScreenerUnavailable(RuntimeError):
    """Raised when the deterministic screening dataset cannot be built."""


PROFILE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "quality": {
        "label": "经营改善候选",
        "description": "先约束市值和估值口径，再核验最新财报中的营收、净利润与 ROE 是否同时为正。",
        "sort_rule": "按最新财报营收同比从高到低排列；不计算综合分。",
        "defaults": {
            "min_market_cap_yi": 50.0,
            "min_pe_ttm": 0.01,
            "max_pe_ttm": 80.0,
            "min_pb": 0.01,
            "max_pb": 10.0,
            "min_revenue_yoy": 0.0,
            "min_net_profit_yoy": 0.0,
            "min_roe": 0.0,
        },
    },
    "trend": {
        "label": "相对行业增强候选",
        "description": "筛选近 5 日、20 日均为正，且近 20 日跑赢所属行业样本均值的股票。",
        "sort_rule": "按近 20 日相对行业超额收益从高到低排列；不计算综合分。",
        "defaults": {
            "min_market_cap_yi": 30.0,
            "min_return_5d": 0.0,
            "min_return_20d": 0.0,
            "min_industry_excess_20d": 0.0,
            "min_volume_ratio": 0.8,
            "max_turnover_rate": 25.0,
        },
    },
    "value": {
        "label": "估值约束观察候选",
        "description": "用正 PE、PB、市值和流动性做透明约束；命中不等于价值低估。",
        "sort_rule": "按 PE TTM 从低到高排列；不计算综合分。",
        "defaults": {
            "min_market_cap_yi": 50.0,
            "min_pe_ttm": 0.01,
            "max_pe_ttm": 25.0,
            "min_pb": 0.01,
            "max_pb": 3.0,
            "min_turnover_rate": 0.2,
        },
    },
    "pullback": {
        "label": "回撤后待复核候选",
        "description": "寻找近 20 日回撤、近 5 日暂时企稳且交易活跃度达到门槛的高风险观察样本。",
        "sort_rule": "按近 5 日收益从低到高排列，优先展示刚转正、较接近企稳的样本；不计算综合分。",
        "defaults": {
            "min_market_cap_yi": 30.0,
            "min_return_5d": 0.0,
            "min_return_20d": -20.0,
            "max_return_20d": -2.0,
            "min_volume_ratio": 0.8,
            "max_turnover_rate": 25.0,
        },
    },
}


FILTER_LABELS = {
    "min_market_cap_yi": "总市值下限",
    "max_market_cap_yi": "总市值上限",
    "min_pe_ttm": "PE TTM 下限",
    "max_pe_ttm": "PE TTM 上限",
    "min_pb": "PB 下限",
    "max_pb": "PB 上限",
    "min_turnover_rate": "换手率下限",
    "max_turnover_rate": "换手率上限",
    "min_volume_ratio": "量比下限",
    "min_return_5d": "近 5 日收益下限",
    "min_return_20d": "近 20 日收益下限",
    "max_return_20d": "近 20 日收益上限",
    "min_industry_excess_20d": "近 20 日行业超额下限",
    "min_revenue_yoy": "营收同比下限",
    "min_net_profit_yoy": "净利润同比下限",
    "min_roe": "ROE 下限",
}


NUMERIC_COLUMN_BY_FILTER = {
    "min_market_cap_yi": "total_mv_yi",
    "max_market_cap_yi": "total_mv_yi",
    "min_pe_ttm": "pe_ttm",
    "max_pe_ttm": "pe_ttm",
    "min_pb": "pb",
    "max_pb": "pb",
    "min_turnover_rate": "turnover_rate",
    "max_turnover_rate": "turnover_rate",
    "min_volume_ratio": "volume_ratio",
    "min_return_5d": "return_5d_pct",
    "min_return_20d": "return_20d_pct",
    "max_return_20d": "return_20d_pct",
    "min_industry_excess_20d": "industry_excess_20d_pct",
}


FINANCIAL_FILTERS = {
    "min_revenue_yoy": "revenue_yoy",
    "min_net_profit_yoy": "net_profit_yoy",
    "min_roe": "roe",
}


class StockScreenerService:
    """Transparent A-share candidate screening backed by deterministic data."""

    MARKET_SNAPSHOT_DATASET = "stock_screen_market"
    MARKET_SNAPSHOT_INCOMPLETE_DATASET = "stock_screen_market_incomplete"

    def __init__(
        self,
        client: Any | None,
        *,
        database: Any | None = None,
        snapshot_ttl_seconds: int = 300,
        finance_ttl_seconds: int = 6 * 3600,
        finance_workers: int = 6,
        minimum_market_coverage_ratio: float = 0.95,
    ) -> None:
        self.client = client
        self.database = database
        self.snapshot_ttl_seconds = max(30, snapshot_ttl_seconds)
        self.finance_ttl_seconds = max(300, finance_ttl_seconds)
        self.finance_workers = max(1, min(int(finance_workers), 8))
        self.minimum_market_coverage_ratio = max(
            0.5, min(float(minimum_market_coverage_ratio), 1.0)
        )
        self._snapshot: tuple[float, pd.DataFrame, dict[str, Any]] | None = None
        self._finance_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._persisted_finance_packets: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    @staticmethod
    def profiles() -> list[dict[str, Any]]:
        return [
            {
                "key": key,
                "label": value["label"],
                "description": value["description"],
                "sort_rule": value["sort_rule"],
                "default_filters": dict(value["defaults"]),
            }
            for key, value in PROFILE_DEFINITIONS.items()
        ]

    def screen(
        self,
        *,
        profile: str = "trend",
        max_results: int = 12,
        market: str = "all",
        filters: Mapping[str, Any] | None = None,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        if self.client is None and self.database is None:
            raise StockScreenerUnavailable("选股数据尚未就绪，请稍后重试")
        if profile not in PROFILE_DEFINITIONS:
            raise ValueError("不支持的选股模板")
        if market not in {"all", "sh", "sz", "bj", "main", "gem", "star"}:
            raise ValueError("不支持的股票范围")
        max_results = max(1, min(int(max_results), 30))

        profile_definition = PROFILE_DEFINITIONS[profile]
        effective_filters = dict(profile_definition["defaults"])
        for key, value in (filters or {}).items():
            if value is None:
                continue
            if key not in FILTER_LABELS and key not in {
                "industry",
                "exclude_st",
                "min_listed_days",
            }:
                raise ValueError(f"不支持的筛选字段：{key}")
            effective_filters[key] = value
        effective_filters.setdefault("exclude_st", True)
        effective_filters.setdefault("min_listed_days", 180)

        frame, snapshot_meta = self._load_snapshot(force_refresh=force_refresh)
        working = frame.copy()
        input_count = len(working)
        market_cap_available = int(working["total_mv_yi"].notna().sum())
        valuation_available = int(working[["pe_ttm", "pb"]].notna().all(axis=1).sum())
        return_20d_available = int(working["return_20d_pct"].notna().sum())
        working = self._apply_universe_rules(
            working,
            market=market,
            filters=effective_filters,
            latest_trade_date=snapshot_meta["latest_completed_trade_date"],
        )
        common_count = len(working)
        working = self._apply_numeric_filters(working, effective_filters)
        market_rule_count = len(working)

        needs_financial_filter = profile == "quality" or any(
            key in effective_filters for key in FINANCIAL_FILTERS
        )
        financial_candidate_pool_count = len(working)
        finance_packets: dict[str, dict[str, Any]] = {}
        if needs_financial_filter:
            all_financial_symbols = [
                str(value)
                for value in working.get("ts_code", pd.Series(dtype=str)).tolist()
            ]
            finance_packets.update(
                self._persisted_financials_many(all_financial_symbols)
            )
            persisted_matches = self._apply_financial_filters(
                working, finance_packets, effective_filters
            )
            if self.client is not None and len(persisted_matches) < max_results:
                incomplete_symbols = {
                    code
                    for code in all_financial_symbols
                    if not self._financial_packet_complete_for_filters(
                        finance_packets.get(code), effective_filters
                    )
                }
                supplemental = working[
                    working["ts_code"].astype(str).isin(incomplete_symbols)
                ]
                pool_size = min(40, max(24, max_results * 2))
                supplemental = self._diverse_financial_pool(supplemental, pool_size)
                supplemental_symbols = [
                    str(value)
                    for value in supplemental.get(
                        "ts_code", pd.Series(dtype=str)
                    ).tolist()
                ]
                finance_packets.update(self._load_financials_many(supplemental_symbols))
            working = working[working["ts_code"].astype(str).isin(finance_packets)]
        else:
            working = self._sort_frame(working, profile).head(max_results * 2)
            financial_symbols = [
                str(value)
                for value in working.get("ts_code", pd.Series(dtype=str)).tolist()
            ]
            finance_packets = self._load_financials_many(
                financial_symbols,
                persisted_only=snapshot_meta.get("source_mode") == "persisted",
            )
            financial_candidate_pool_count = len(financial_symbols)
        financial_available = sum(
            bool(packet.get("report_period"))
            and str(packet.get("coverage_status") or "") != "unavailable"
            for packet in finance_packets.values()
        )

        if needs_financial_filter:
            working = self._apply_financial_filters(
                working, finance_packets, effective_filters
            )
        working = self._sort_frame(working, profile).head(max_results)

        items = [
            self._build_item(row, profile, finance_packets.get(str(row["ts_code"]), {}))
            for _, row in working.iterrows()
        ]
        report_periods = sorted(
            {
                str(item["financials"].get("report_period"))
                for item in items
                if item["financials"].get("report_period")
            },
            reverse=True,
        )
        data_meta = {
            **snapshot_meta,
            "generated_at": utc_now(),
            "financial_report_periods": report_periods,
            "financial_data_note": "财务指标按各公司最新已取得报告期展示，不与行情交易日混用。",
            "financial_candidate_pool_note": (
                "需要财务条件时，先使用生产数据库已有财务快照覆盖初筛池；"
                "不足部分再按行业分散补充实时逐股核验。"
                "财务覆盖未达到门槛时，结果不代表全市场财务排名。"
            ),
            "cache_hit": bool(snapshot_meta.get("cache_hit")),
        }
        expected_snapshot = int(snapshot_meta.get("listed_stock_count") or input_count)

        def coverage(available: int, expected: int) -> dict[str, Any]:
            return {
                "available": available,
                "expected": expected,
                "missing": max(0, expected - available),
                "ratio": round(available / expected, 6) if expected else 0.0,
            }

        market_snapshot_coverage = coverage(input_count, expected_snapshot)
        financial_pool_coverage = coverage(
            financial_available, financial_candidate_pool_count
        )
        required_coverage: list[tuple[str, dict[str, Any]]] = [
            ("行情截面", market_snapshot_coverage),
            ("20日比较日线", coverage(return_20d_available, input_count)),
        ]
        if any("market_cap" in key for key in effective_filters):
            required_coverage.append(
                ("市值字段", coverage(market_cap_available, input_count))
            )
        if any(
            key in effective_filters
            for key in ("min_pe_ttm", "max_pe_ttm", "min_pb", "max_pb")
        ):
            required_coverage.append(
                ("估值字段", coverage(valuation_available, input_count))
            )
        if needs_financial_filter:
            required_coverage.append(("财务核验", financial_pool_coverage))
        represents_requested_scope = all(
            float(item.get("ratio") or 0) >= self.minimum_market_coverage_ratio
            for _, item in required_coverage
        )
        represents_full_market = market == "all" and represents_requested_scope
        market_labels = {
            "sh": "上海A股",
            "sz": "深圳A股",
            "bj": "北京A股",
            "main": "沪深主板",
            "gem": "创业板",
            "star": "科创板",
        }
        if market == "all" and represents_full_market:
            actual_scope_label = "全部A股"
        elif (
            market == "all"
            and market_snapshot_coverage["ratio"] >= self.minimum_market_coverage_ratio
        ):
            actual_scope_label = "A股完整行情范围，财务或规则字段部分覆盖"
        elif market == "all":
            actual_scope_label = f"已同步A股 {input_count}/{expected_snapshot} 只"
        else:
            actual_scope_label = market_labels.get(market, "所选A股范围")
        representation_reasons: list[str] = []
        for label, item in required_coverage:
            if float(item.get("ratio") or 0) < self.minimum_market_coverage_ratio:
                representation_reasons.append(f"{label}覆盖不足")
        representation_note = (
            "本轮数据足以代表所选范围的确定性规则计算。"
            if represents_requested_scope
            else "；".join(representation_reasons)
            + "，结果只代表当前已覆盖范围，不能外推为全市场结论。"
        )
        data_meta.update(
            {
                "actual_scope_label": actual_scope_label,
                "coverage_status": (
                    "complete" if represents_requested_scope else "constrained"
                ),
                "represents_full_market": represents_full_market,
            }
        )

        data_contract = {
            "contract_version": "stock_screen_data_v1",
            "data_version": snapshot_meta.get("data_version"),
            "market_scope": market,
            "universe_definition": snapshot_meta.get("universe_definition"),
            "as_of": {
                "market_date": snapshot_meta.get("latest_completed_trade_date"),
                "return_5d_base_date": snapshot_meta.get("return_5d_base_date"),
                "return_20d_base_date": snapshot_meta.get("return_20d_base_date"),
                "financial_report_periods": report_periods,
                "generated_at": data_meta["generated_at"],
            },
            "coverage": {
                "market_snapshot": market_snapshot_coverage,
                "market_cap": coverage(market_cap_available, input_count),
                "valuation": coverage(valuation_available, input_count),
                "return_20d": coverage(return_20d_available, input_count),
                "financial_candidate_pool": financial_pool_coverage,
            },
            "representation": {
                "actual_scope_label": actual_scope_label,
                "coverage_status": (
                    "complete" if represents_requested_scope else "constrained"
                ),
                "represents_requested_scope": represents_requested_scope,
                "represents_full_market": represents_full_market,
                "minimum_coverage_ratio": self.minimum_market_coverage_ratio,
                "note": representation_note,
            },
            "sources": [
                {
                    "module": "股票基础",
                    "source": "Tushare Pro:stock_basic",
                    "as_of": snapshot_meta.get("latest_completed_trade_date"),
                },
                {
                    "module": "行情与收益",
                    "source": "Tushare Pro:daily",
                    "as_of": snapshot_meta.get("latest_completed_trade_date"),
                },
                {
                    "module": "估值与市值",
                    "source": "Tushare Pro:daily_basic",
                    "as_of": snapshot_meta.get("latest_completed_trade_date"),
                },
                {
                    "module": "财务质量",
                    "source": "Tushare Pro:fina_indicator",
                    "as_of": report_periods[0] if report_periods else None,
                },
            ],
            "license_boundary": (
                "当前兼容数据可用于MVP研究验证；商业展示、缓存和衍生使用仍需"
                "按数据供应商许可书面确认。"
            ),
        }
        warnings: list[str] = []
        if snapshot_meta.get("source_mode") == "persisted":
            warnings.append("本轮使用生产数据库中的最近稳定快照完成筛选。")
        if not represents_requested_scope:
            warnings.append(representation_note)
        if items and any(item["missing_fields"] for item in items):
            warnings.append("部分候选的财务或估值字段不完整，缺失项已逐只列出。")
        if not items:
            warnings.append(
                "按当前规则未命中候选；本轮不默认建议放宽规则。"
                if represents_requested_scope
                else "当前已覆盖范围内未命中候选；这不等于全市场没有候选。"
            )

        return {
            "type": "stock_screen",
            "status": "ready" if items else "empty",
            "profile": {
                "key": profile,
                "label": profile_definition["label"],
                "description": profile_definition["description"],
                "sort_rule": profile_definition["sort_rule"],
            },
            "market": market,
            "rules": self._rules(effective_filters),
            "effective_filters": effective_filters,
            "data_meta": data_meta,
            "data_contract": data_contract,
            "universe": {
                "listed_input": input_count,
                "after_common_rules": common_count,
                "after_market_rules": market_rule_count,
                "expected_listed": expected_snapshot,
                "market_coverage": input_count,
                "valuation_coverage": valuation_available,
                "financial_candidate_pool": financial_candidate_pool_count,
                "financials_checked": len(finance_packets),
                "represents_full_market": represents_full_market,
                "matched": len(items),
            },
            "items": items,
            "warnings": warnings,
            "boundary": "这是可解释的研究候选筛选，不构成推荐、评级、目标价或交易建议。",
        }

    def refresh_persisted_market_snapshot(self) -> dict[str, Any]:
        """Publish the market inputs consumed by the generic screener.

        This executes in a background worker.  The user-facing screening
        request only reads the resulting stable snapshot, so it never needs
        to initiate a full-market provider scan.
        """

        if self.client is None:
            raise StockScreenerUnavailable("选股快照同步尚未配置数据源")
        if self.database is None:
            raise StockScreenerUnavailable("选股快照同步缺少持久化数据库")

        run = self.database.start_tushare_sync_run(
            job_scope="stock_screen_market",
            as_of_date=None,
            datasets=["trade_cal", "stock_basic", "daily", "daily_basic"],
        )
        try:
            frame, metadata = self._build_snapshot()
            rows = self._json_rows(frame)
            coverage_ratio = float(metadata.get("market_coverage_ratio") or 0.0)
            stable = bool(rows) and coverage_ratio >= self.minimum_market_coverage_ratio
            dataset = (
                self.MARKET_SNAPSHOT_DATASET
                if stable
                else self.MARKET_SNAPSHOT_INCOMPLETE_DATASET
            )
            fingerprint = hashlib.sha256(b"stock-screen-market-v1")
            fingerprint.update(str(metadata.get("latest_completed_trade_date") or "").encode("utf-8"))
            fingerprint.update(
                pd.util.hash_pandas_object(
                    frame.sort_values("ts_code", kind="stable"), index=False
                ).values.tobytes()
            )
            data_version = f"stock-screen-market-v1-{fingerprint.hexdigest()[:16]}"
            payload = {
                "rows": rows,
                "metadata": metadata,
                "requested_as_of_date": metadata.get("latest_completed_trade_date"),
            }
            self.database.save_tushare_dataset_snapshot(
                dataset=dataset,
                scope_key="all",
                as_of_date=metadata.get("latest_completed_trade_date"),
                report_period=None,
                source_updated_at=metadata.get("snapshot_built_at"),
                sync_run_id=str(run["id"]),
                data_version=data_version,
                data_status="stable" if stable else "incomplete",
                payload=payload,
            )
            finished = self.database.finish_tushare_sync_run(
                str(run["id"]),
                status="stable" if stable else "partial",
                data_version=data_version,
                summary={
                    "snapshot_stock_count": len(rows),
                    "market_coverage_ratio": coverage_ratio,
                    "as_of_date": metadata.get("latest_completed_trade_date"),
                    "published": stable,
                },
            )
            return {
                "status": finished.get("status"),
                "published": stable,
                "data_version": data_version,
                "snapshot_stock_count": len(rows),
                "market_coverage_ratio": coverage_ratio,
                "previous_stable_retained": bool(
                    not stable
                    and self.database.latest_tushare_dataset_snapshot(
                        self.MARKET_SNAPSHOT_DATASET, "all"
                    )
                ),
            }
        except Exception as exc:
            previous = self.database.latest_tushare_dataset_snapshot(
                self.MARKET_SNAPSHOT_DATASET, "all"
            )
            finished = self.database.finish_tushare_sync_run(
                str(run["id"]),
                status="failed",
                data_version=None,
                summary={"previous_stable_retained": previous is not None},
                error=type(exc).__name__,
            )
            return {
                "status": finished.get("status"),
                "published": False,
                "data_version": None,
                "snapshot_stock_count": 0,
                "market_coverage_ratio": 0.0,
                "previous_stable_retained": previous is not None,
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

    def _load_snapshot(
        self, *, force_refresh: bool
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        now_monotonic = time.monotonic()
        with self._lock:
            if (
                not force_refresh
                and self._snapshot is not None
                and now_monotonic - self._snapshot[0] < self.snapshot_ttl_seconds
            ):
                cached_frame = self._snapshot[1].copy()
                cached_meta = dict(self._snapshot[2])
                cached_ratio = self._market_coverage_ratio(cached_frame, cached_meta)
                if not (
                    self.client is not None
                    and cached_meta.get("source_mode") == "persisted"
                    and cached_ratio < self.minimum_market_coverage_ratio
                ):
                    return cached_frame, {
                        **cached_meta,
                        "cache_hit": True,
                    }

        persisted_error: Exception | None = None
        persisted_snapshot: tuple[pd.DataFrame, dict[str, Any]] | None = None
        if self.database is not None and not force_refresh:
            try:
                frame, meta = self._build_persisted_snapshot()
            except (ValueError, KeyError, TypeError) as exc:
                persisted_error = exc
            else:
                if not frame.empty:
                    persisted_snapshot = (frame.copy(), dict(meta))
                    persisted_ratio = self._market_coverage_ratio(frame, meta)
                    if (
                        self.client is None
                        or persisted_ratio >= self.minimum_market_coverage_ratio
                    ):
                        if persisted_ratio < self.minimum_market_coverage_ratio:
                            meta = {
                                **meta,
                                "coverage_status": "constrained",
                                "market_snapshot_representative": False,
                            }
                        with self._lock:
                            self._snapshot = (
                                now_monotonic,
                                frame.copy(),
                                dict(meta),
                            )
                        return frame, {**meta, "cache_hit": False}

        live_error: Exception | None = None
        if self.client is not None:
            try:
                frame, meta = self._build_snapshot()
            except (TushareProviderError, ValueError, KeyError) as exc:
                live_error = exc
            else:
                if frame.empty:
                    live_error = ValueError("实时市场截面为空")
        if self.client is None or live_error is not None:
            if persisted_snapshot is not None:
                frame, meta = persisted_snapshot
                meta = {
                    **meta,
                    "coverage_status": "constrained",
                    "market_snapshot_representative": False,
                    "live_refresh_attempted": self.client is not None,
                    "live_refresh_succeeded": False,
                }
            else:
                try:
                    frame, meta = self._build_persisted_snapshot()
                except (ValueError, KeyError, TypeError) as exc:
                    raise StockScreenerUnavailable(
                        "选股数据正在准备中，请稍后重试"
                    ) from (live_error or persisted_error or exc)
        if frame.empty:
            raise StockScreenerUnavailable("当前没有可用于筛选的完整市场数据")
        with self._lock:
            self._snapshot = (now_monotonic, frame.copy(), dict(meta))
        return frame, {**meta, "cache_hit": False}

    @staticmethod
    def _market_coverage_ratio(frame: pd.DataFrame, meta: Mapping[str, Any]) -> float:
        expected = int(meta.get("listed_stock_count") or len(frame))
        return len(frame) / expected if expected else 0.0

    @staticmethod
    def _snapshot_rows(record: Mapping[str, Any] | None) -> list[dict[str, Any]]:
        payload = (record or {}).get("payload") or {}
        rows = payload.get("rows") or []
        return [dict(row) for row in rows if isinstance(row, Mapping)]

    def _build_persisted_snapshot(self) -> tuple[pd.DataFrame, dict[str, Any]]:
        if self.database is None:
            raise ValueError("没有持久化选股数据库")
        published = self.database.latest_tushare_dataset_snapshot(
            self.MARKET_SNAPSHOT_DATASET, "all"
        )
        if published is not None:
            return self._read_published_market_snapshot(published)
        datasets = {
            name: self.database.list_latest_tushare_dataset_snapshots(
                name,
                data_status="stable",
                limit=20_000,
            )
            for name in ("stock_basic", "daily", "daily_basic", "fina_indicator")
        }
        if not datasets["daily"] or not datasets["stock_basic"]:
            raise ValueError("持久化日线或股票基础数据为空")

        stock_by_code: dict[str, dict[str, Any]] = {}
        for record in datasets["stock_basic"]:
            for row in self._snapshot_rows(record)[:1]:
                code = str(row.get("ts_code") or "").strip().upper()
                if code:
                    stock_by_code[code] = row

        daily_basic_by_code: dict[str, dict[str, Any]] = {}
        for record in datasets["daily_basic"]:
            for row in self._snapshot_rows(record)[:1]:
                code = str(row.get("ts_code") or "").strip().upper()
                if code:
                    daily_basic_by_code[code] = row

        daily_by_code: dict[str, list[dict[str, Any]]] = {}
        recent_trade_dates: set[str] = set()
        for record in datasets["daily"]:
            rows = sorted(
                self._snapshot_rows(record),
                key=lambda row: self._date_string(row.get("trade_date")),
                reverse=True,
            )
            if not rows:
                continue
            code = str(rows[0].get("ts_code") or "").strip().upper()
            if not code:
                continue
            daily_by_code[code] = rows
            recent_trade_dates.update(
                self._date_string(row.get("trade_date"))
                for row in rows[:40]
                if self._date_string(row.get("trade_date"))
            )
        ordered_dates = sorted(recent_trade_dates)
        if len(ordered_dates) < 21:
            raise ValueError("持久化日线不足 21 个交易日")
        latest_date = ordered_dates[-1]
        date_5d = ordered_dates[-6]
        date_20d = ordered_dates[-21]
        target_dates = {latest_date, date_5d, date_20d}

        rows: list[dict[str, Any]] = []
        for code, history_rows in daily_by_code.items():
            basic = stock_by_code.get(code)
            if not basic:
                continue
            by_date = {
                self._date_string(row.get("trade_date")): row
                for row in history_rows
                if self._date_string(row.get("trade_date")) in target_dates
            }
            latest = by_date.get(latest_date)
            if latest is None:
                continue
            close = self._number(latest.get("close"))
            close_5d = self._number((by_date.get(date_5d) or {}).get("close"))
            close_20d = self._number((by_date.get(date_20d) or {}).get("close"))
            valuation = daily_basic_by_code.get(code, {})
            total_mv_yi = self._number(valuation.get("total_mv_yi"))
            circ_mv_yi = self._number(valuation.get("circ_mv_yi"))
            if total_mv_yi is None:
                total_mv = self._number(valuation.get("total_mv"))
                total_mv_yi = total_mv / 10_000.0 if total_mv is not None else None
            if circ_mv_yi is None:
                circ_mv = self._number(valuation.get("circ_mv"))
                circ_mv_yi = circ_mv / 10_000.0 if circ_mv is not None else None
            rows.append(
                {
                    **basic,
                    "ts_code": code,
                    "latest_close": close,
                    "pct_change": self._number(latest.get("pct_chg")),
                    "amount": self._number(latest.get("amount")),
                    "volume": self._number(latest.get("vol")),
                    "close_5d_base": close_5d,
                    "close_20d_base": close_20d,
                    "return_5d_pct": (
                        (close / close_5d - 1.0) * 100.0
                        if close is not None and close_5d not in {None, 0}
                        else math.nan
                    ),
                    "return_20d_pct": (
                        (close / close_20d - 1.0) * 100.0
                        if close is not None and close_20d not in {None, 0}
                        else math.nan
                    ),
                    "turnover_rate": self._number(valuation.get("turnover_rate")),
                    "volume_ratio": self._number(valuation.get("volume_ratio")),
                    "pe_ttm": self._number(valuation.get("pe_ttm")),
                    "pb": self._number(valuation.get("pb")),
                    "ps_ttm": self._number(valuation.get("ps_ttm")),
                    "total_mv_yi": total_mv_yi,
                    "circ_mv_yi": circ_mv_yi,
                    "trade_date": latest_date,
                    "internal_symbol": self._internal_symbol(code),
                }
            )
        frame = pd.DataFrame(rows)
        if frame.empty:
            raise ValueError("持久化选股截面为空")
        frame["industry"] = (
            frame.get("industry", "未分类").fillna("未分类").replace("", "未分类")
        )
        frame["industry_avg_return_20d_pct"] = frame.groupby("industry")[
            "return_20d_pct"
        ].transform("mean")
        frame["industry_excess_20d_pct"] = (
            frame["return_20d_pct"] - frame["industry_avg_return_20d_pct"]
        )

        persisted_finance: dict[str, dict[str, Any]] = {}
        for record in datasets["fina_indicator"]:
            packet = self._financial_packet(pd.DataFrame(self._snapshot_rows(record)))
            scope = str(record.get("scope_key") or "").strip().upper()
            if scope:
                persisted_finance[scope] = packet
        with self._lock:
            self._persisted_finance_packets = persisted_finance

        universe = self.database.latest_tushare_dataset_snapshot(
            "a_share_universe", "all"
        )
        universe_payload = (universe or {}).get("payload") or {}
        listed_stock_count = int(
            (universe_payload.get("coverage") or {}).get("listed") or len(stock_by_code)
        )
        fingerprint_columns = [
            "ts_code",
            "trade_date",
            "latest_close",
            "return_5d_pct",
            "return_20d_pct",
            "pe_ttm",
            "pb",
            "total_mv_yi",
            "volume_ratio",
        ]
        digest = hashlib.sha256(b"stock_screen_persisted_v1")
        digest.update(latest_date.encode("utf-8"))
        digest.update(
            pd.util.hash_pandas_object(
                frame[fingerprint_columns].sort_values("ts_code", kind="stable"),
                index=False,
            ).values.tobytes()
        )
        return frame, {
            "source": "PostgreSQL 持久化 Tushare 稳定快照",
            "source_mode": "persisted",
            "data_version": f"stock-screen-db-v1-{digest.hexdigest()[:16]}",
            "universe_definition": (
                "生产数据库中已发布稳定 stock_basic、daily 与 daily_basic 快照的A股；"
                "仅使用同一最近完整交易日及其5日、20日基准日。"
            ),
            "listed_stock_count": listed_stock_count,
            "latest_daily_count": len(daily_by_code),
            "daily_basic_count": len(daily_basic_by_code),
            "snapshot_stock_count": len(frame),
            "latest_completed_trade_date": self._iso_date(latest_date),
            "return_5d_base_date": self._iso_date(date_5d),
            "return_20d_base_date": self._iso_date(date_20d),
            "snapshot_built_at": utc_now(),
            "price_basis": "生产数据库最近稳定完整日线",
            "valuation_basis": "生产数据库同交易日 daily_basic 稳定截面",
            "market_coverage_ratio": round(len(frame) / listed_stock_count, 6)
            if listed_stock_count
            else 0.0,
            "market_snapshot_representative": (
                len(frame) / listed_stock_count >= self.minimum_market_coverage_ratio
                if listed_stock_count
                else False
            ),
            "coverage_status": (
                "complete"
                if listed_stock_count
                and len(frame) / listed_stock_count
                >= self.minimum_market_coverage_ratio
                else "constrained"
            ),
        }

    def _read_published_market_snapshot(
        self, snapshot: Mapping[str, Any]
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        payload = snapshot.get("payload") or {}
        rows = payload.get("rows") or []
        if not isinstance(rows, list) or not rows:
            raise ValueError("通用选股稳定快照为空")
        frame = pd.DataFrame(rows)
        required = {"ts_code", "latest_close", "return_5d_pct", "return_20d_pct"}
        if frame.empty or not required.issubset(frame.columns):
            raise ValueError("通用选股稳定快照字段不完整")
        for column in (
            "latest_close",
            "pct_change",
            "amount",
            "volume",
            "close_5d_base",
            "close_20d_base",
            "turnover_rate",
            "volume_ratio",
            "pe_ttm",
            "pb",
            "ps_ttm",
            "total_mv_yi",
            "circ_mv_yi",
            "return_5d_pct",
            "return_20d_pct",
        ):
            frame[column] = pd.to_numeric(frame.get(column), errors="coerce")
        frame["industry"] = frame.get("industry", "未分类").fillna("未分类").replace("", "未分类")
        frame["industry_avg_return_20d_pct"] = frame.groupby("industry")["return_20d_pct"].transform("mean")
        frame["industry_excess_20d_pct"] = frame["return_20d_pct"] - frame["industry_avg_return_20d_pct"]
        metadata = dict(payload.get("metadata") or {})
        metadata.update(
            {
                "source": "PostgreSQL 通用选股稳定快照",
                "source_mode": "persisted",
                "data_version": snapshot.get("data_version"),
                "snapshot_built_at": snapshot.get("created_at"),
                "cache_hit": False,
            }
        )
        if not metadata.get("latest_completed_trade_date"):
            raise ValueError("通用选股稳定快照缺少交易日")
        return frame, metadata

    @staticmethod
    def _json_rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
        def clean(value: Any) -> Any:
            if value is None or value is pd.NA:
                return None
            if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
                return None
            if isinstance(value, pd.Timestamp):
                return value.isoformat()
            if hasattr(value, "item"):
                return value.item()
            return value

        return [
            {str(key): clean(value) for key, value in row.items()}
            for row in frame.to_dict(orient="records")
        ]

    def _build_snapshot(self) -> tuple[pd.DataFrame, dict[str, Any]]:
        now_cn = datetime.now(ZoneInfo("Asia/Shanghai"))
        calendar_end = now_cn.date()
        calendar_start = calendar_end - timedelta(days=120)
        calendar = self._query(
            "trade_cal",
            exchange="SSE",
            start_date=calendar_start.strftime("%Y%m%d"),
            end_date=calendar_end.strftime("%Y%m%d"),
            is_open="1",
            fields="exchange,cal_date,is_open,pretrade_date",
        )
        if calendar.empty or "cal_date" not in calendar:
            raise ValueError("交易日历为空")
        open_mask = (
            pd.to_numeric(calendar["is_open"], errors="coerce").fillna(0) == 1
            if "is_open" in calendar
            else pd.Series(True, index=calendar.index)
        )
        open_dates = sorted(
            {
                self._date_string(value)
                for value in calendar.loc[open_mask, "cal_date"].tolist()
                if self._date_string(value)
            }
        )
        today = now_cn.strftime("%Y%m%d")
        if now_cn.time() < clock_time(15, 10):
            open_dates = [value for value in open_dates if value < today]
        else:
            open_dates = [value for value in open_dates if value <= today]
        if len(open_dates) < 21:
            raise ValueError("交易日历不足 21 个交易日")

        latest_date: str | None = None
        latest_daily = pd.DataFrame()
        latest_index = -1
        for candidate in reversed(open_dates[-6:]):
            candidate_daily = self._query(
                "daily",
                trade_date=candidate,
                fields="ts_code,trade_date,open,high,low,close,pre_close,pct_chg,vol,amount",
            )
            if not candidate_daily.empty:
                latest_date = candidate
                latest_daily = candidate_daily
                latest_index = open_dates.index(candidate)
                break
        if latest_date is None or latest_index < 20:
            raise ValueError("没有找到足够历史的完整日线")

        date_5d = open_dates[latest_index - 5]
        date_20d = open_dates[latest_index - 20]
        daily_5d = self._query(
            "daily", trade_date=date_5d, fields="ts_code,trade_date,close"
        )
        daily_20d = self._query(
            "daily", trade_date=date_20d, fields="ts_code,trade_date,close"
        )
        daily_basic = self._query(
            "daily_basic",
            trade_date=latest_date,
            fields=(
                "ts_code,trade_date,turnover_rate,volume_ratio,pe_ttm,pb,ps_ttm,"
                "total_mv,circ_mv"
            ),
        )
        stock_basic = self._query(
            "stock_basic",
            exchange="",
            list_status="L",
            fields="ts_code,symbol,name,area,industry,market,list_date,exchange",
        )
        required = {
            "latest daily": (latest_daily, {"ts_code", "close"}),
            "5-day daily": (daily_5d, {"ts_code", "close"}),
            "20-day daily": (daily_20d, {"ts_code", "close"}),
            "daily basic": (daily_basic, {"ts_code"}),
            "stock basic": (stock_basic, {"ts_code", "name"}),
        }
        for label, (data, columns) in required.items():
            if data.empty or not columns.issubset(data.columns):
                raise ValueError(f"{label} 字段不完整")

        latest = latest_daily.copy()
        latest = latest.rename(
            columns={
                "close": "latest_close",
                "pct_chg": "pct_change",
                "vol": "volume",
            }
        )
        base_5 = daily_5d[["ts_code", "close"]].rename(
            columns={"close": "close_5d_base"}
        )
        base_20 = daily_20d[["ts_code", "close"]].rename(
            columns={"close": "close_20d_base"}
        )
        frame = stock_basic.merge(latest, on="ts_code", how="inner")
        frame = frame.merge(base_5, on="ts_code", how="left")
        frame = frame.merge(base_20, on="ts_code", how="left")
        frame = frame.merge(
            daily_basic, on="ts_code", how="left", suffixes=("", "_basic")
        )
        numeric_columns = [
            "latest_close",
            "pct_change",
            "amount",
            "volume",
            "close_5d_base",
            "close_20d_base",
            "turnover_rate",
            "volume_ratio",
            "pe_ttm",
            "pb",
            "ps_ttm",
            "total_mv",
            "circ_mv",
        ]
        for column in numeric_columns:
            if column in frame:
                frame[column] = pd.to_numeric(frame[column], errors="coerce")
            else:
                frame[column] = math.nan
        frame["return_5d_pct"] = (
            frame["latest_close"] / frame["close_5d_base"] - 1.0
        ) * 100.0
        frame["return_20d_pct"] = (
            frame["latest_close"] / frame["close_20d_base"] - 1.0
        ) * 100.0
        frame["total_mv_yi"] = frame["total_mv"] / 10_000.0
        frame["circ_mv_yi"] = frame["circ_mv"] / 10_000.0
        if "industry" not in frame:
            frame["industry"] = "未分类"
        frame["industry"] = frame["industry"].fillna("未分类").replace("", "未分类")
        frame["industry_avg_return_20d_pct"] = frame.groupby("industry")[
            "return_20d_pct"
        ].transform("mean")
        frame["industry_excess_20d_pct"] = (
            frame["return_20d_pct"] - frame["industry_avg_return_20d_pct"]
        )
        frame["internal_symbol"] = frame["ts_code"].map(self._internal_symbol)
        frame["trade_date"] = latest_date
        fingerprint_columns = [
            column
            for column in (
                "ts_code",
                "trade_date",
                "latest_close",
                "return_5d_pct",
                "return_20d_pct",
                "pe_ttm",
                "pb",
                "total_mv_yi",
                "volume_ratio",
            )
            if column in frame
        ]
        fingerprint_frame = frame[fingerprint_columns].sort_values(
            "ts_code", kind="stable"
        )
        digest = hashlib.sha256(b"stock_screen_snapshot_v1")
        digest.update(latest_date.encode("utf-8"))
        digest.update(
            pd.util.hash_pandas_object(fingerprint_frame, index=False).values.tobytes()
        )
        data_version = f"stock-screen-v1-{digest.hexdigest()[:16]}"
        listed_stock_count = int(stock_basic["ts_code"].nunique())
        latest_daily_count = int(latest_daily["ts_code"].nunique())
        daily_basic_count = int(daily_basic["ts_code"].nunique())

        return frame, {
            "source": "Tushare Pro",
            "source_mode": "live",
            "data_version": data_version,
            "universe_definition": (
                "Tushare stock_basic 中 list_status=L 的A股，且最近完整交易日"
                "存在可用日线；ST、上市时长和市场范围随后按本轮规则过滤。"
            ),
            "listed_stock_count": listed_stock_count,
            "latest_daily_count": latest_daily_count,
            "daily_basic_count": daily_basic_count,
            "snapshot_stock_count": len(frame),
            "latest_completed_trade_date": self._iso_date(latest_date),
            "return_5d_base_date": self._iso_date(date_5d),
            "return_20d_base_date": self._iso_date(date_20d),
            "snapshot_built_at": utc_now(),
            "price_basis": "最近完整交易日日线",
            "valuation_basis": "与最近完整交易日对齐的 daily_basic 截面",
            "market_coverage_ratio": round(len(frame) / listed_stock_count, 6)
            if listed_stock_count
            else 0.0,
            "market_snapshot_representative": (
                len(frame) / listed_stock_count >= self.minimum_market_coverage_ratio
                if listed_stock_count
                else False
            ),
            "coverage_status": (
                "complete"
                if listed_stock_count
                and len(frame) / listed_stock_count
                >= self.minimum_market_coverage_ratio
                else "constrained"
            ),
        }

    def _apply_universe_rules(
        self,
        frame: pd.DataFrame,
        *,
        market: str,
        filters: Mapping[str, Any],
        latest_trade_date: str,
    ) -> pd.DataFrame:
        result = frame.copy()
        if bool(filters.get("exclude_st", True)):
            result = result[
                ~result["name"].fillna("").astype(str).str.upper().str.contains("ST")
            ]
        minimum_days = int(filters.get("min_listed_days", 180) or 0)
        if minimum_days > 0 and "list_date" in result:
            latest = pd.Timestamp(latest_trade_date)
            listed = pd.to_datetime(result["list_date"].astype(str), errors="coerce")
            result = result[(latest - listed).dt.days >= minimum_days]
        code = result["ts_code"].astype(str)
        if market == "sh":
            result = result[code.str.endswith(".SH")]
        elif market == "sz":
            result = result[code.str.endswith(".SZ")]
        elif market == "bj":
            result = result[code.str.endswith(".BJ")]
        elif market == "gem":
            result = result[code.str.match(r"^(?:300|301)")]
        elif market == "star":
            result = result[code.str.startswith("688")]
        elif market == "main":
            result = result[code.str.match(r"^(?:000|001|002|003|600|601|603|605)")]
        industry = str(filters.get("industry") or "").strip()
        if industry:
            result = result[
                result["industry"]
                .fillna("")
                .astype(str)
                .str.contains(industry, case=False, regex=False)
            ]
        return result[
            result["latest_close"].notna()
            & result["return_5d_pct"].notna()
            & result["return_20d_pct"].notna()
        ]

    @staticmethod
    def _apply_numeric_filters(
        frame: pd.DataFrame, filters: Mapping[str, Any]
    ) -> pd.DataFrame:
        result = frame.copy()
        for key, column in NUMERIC_COLUMN_BY_FILTER.items():
            if key not in filters or filters[key] is None:
                continue
            threshold = float(filters[key])
            if key.startswith("min_"):
                result = result[result[column].notna() & (result[column] >= threshold)]
            else:
                result = result[result[column].notna() & (result[column] <= threshold)]
        return result

    @staticmethod
    def _diverse_financial_pool(frame: pd.DataFrame, limit: int) -> pd.DataFrame:
        if frame.empty:
            return frame
        ordered = frame.sort_values(
            ["amount", "total_mv_yi", "ts_code"],
            ascending=[False, False, True],
            na_position="last",
        )
        diversified = ordered.groupby("industry", sort=False, group_keys=False).head(3)
        if len(diversified) < limit:
            selected = set(diversified["ts_code"].astype(str))
            remainder = ordered[~ordered["ts_code"].astype(str).isin(selected)]
            diversified = pd.concat(
                [diversified, remainder.head(limit - len(diversified))],
                ignore_index=True,
            )
        return diversified.head(limit).copy()

    def _load_persisted_financials(self, ts_code: str) -> dict[str, Any]:
        internal = self._internal_symbol(ts_code)
        with self._lock:
            cached = self._persisted_finance_packets.get(internal)
        if cached is not None:
            return dict(cached)
        if self.database is None:
            return {"status": "unavailable"}
        record = self.database.latest_tushare_dataset_snapshot(
            "fina_indicator", internal
        )
        packet = self._financial_packet(pd.DataFrame(self._snapshot_rows(record)))
        with self._lock:
            self._persisted_finance_packets[internal] = dict(packet)
        return packet

    def _persisted_financials_many(
        self, ts_codes: list[str]
    ) -> dict[str, dict[str, Any]]:
        with self._lock:
            persisted = dict(self._persisted_finance_packets)
        packets: dict[str, dict[str, Any]] = {}
        for code in dict.fromkeys(ts_codes):
            packet = persisted.get(self._internal_symbol(code))
            if packet and packet.get("status") == "available":
                packets[code] = dict(packet)
        return packets

    @staticmethod
    def _financial_packet_complete_for_filters(
        packet: Mapping[str, Any] | None,
        filters: Mapping[str, Any],
    ) -> bool:
        if not packet or packet.get("status") != "available":
            return False
        return all(
            StockScreenerService._number(packet.get(field)) is not None
            for filter_name, field in FINANCIAL_FILTERS.items()
            if filter_name in filters and filters[filter_name] is not None
        )

    def _load_financials(
        self, ts_code: str, *, persisted_only: bool = False
    ) -> dict[str, Any]:
        now_monotonic = time.monotonic()
        with self._lock:
            cached = self._finance_cache.get(ts_code)
            if cached:
                cached_ttl = (
                    self.finance_ttl_seconds
                    if cached[1].get("status") == "available"
                    else 30
                )
                if now_monotonic - cached[0] < cached_ttl:
                    return dict(cached[1])
        persisted = self._load_persisted_financials(ts_code)
        if persisted_only or self.client is None:
            return persisted
        try:
            frame = self._query(
                "fina_indicator",
                ts_code=ts_code,
                start_date=(datetime.now().date() - timedelta(days=800)).strftime(
                    "%Y%m%d"
                ),
                fields=(
                    "ts_code,ann_date,end_date,roe,grossprofit_margin,netprofit_margin,"
                    "debt_to_assets,tr_yoy,or_yoy,q_sales_yoy,netprofit_yoy,"
                    "q_netprofit_yoy,q_dtprofit_yoy"
                ),
            )
        except TushareProviderError:
            packet = {"status": "unavailable"}
        else:
            packet = self._financial_packet(frame)
        # Successful reports are durable for several hours. A transient
        # provider failure must never become a long-lived evidence gap.
        if packet.get("status") == "available":
            with self._lock:
                self._finance_cache[ts_code] = (now_monotonic, dict(packet))
        return packet

    def _load_financials_many(
        self, ts_codes: list[str], *, persisted_only: bool = False
    ) -> dict[str, dict[str, Any]]:
        unique_codes = list(dict.fromkeys(ts_codes))
        if not unique_codes:
            return {}
        if self.finance_workers == 1 or len(unique_codes) == 1:
            return {
                code: self._load_financials(code, persisted_only=persisted_only)
                for code in unique_codes
            }
        packets: dict[str, dict[str, Any]] = {}
        with ThreadPoolExecutor(
            max_workers=min(self.finance_workers, len(unique_codes)),
            thread_name_prefix="qingshu-finance",
        ) as executor:
            futures = {
                executor.submit(
                    self._load_financials, code, persisted_only=persisted_only
                ): code
                for code in unique_codes
            }
            for future in as_completed(futures):
                code = futures[future]
                try:
                    packets[code] = future.result()
                except Exception:
                    packets[code] = {"status": "unavailable"}
        # Concurrent calls keep the page responsive, but a provider may
        # throttle an isolated request. Retry only failed symbols once in a
        # calmer sequential pass so temporary transport errors are not shown
        # to users as missing company evidence.
        for code in unique_codes:
            if packets.get(code, {}).get("status") == "available":
                continue
            packets[code] = self._load_financials(code, persisted_only=persisted_only)
        return packets

    @classmethod
    def _financial_packet(cls, frame: pd.DataFrame) -> dict[str, Any]:
        if frame.empty:
            return {"status": "unavailable"}
        data = frame.copy()
        for column in ("end_date", "ann_date"):
            if column not in data:
                data[column] = ""
        data = data.sort_values(["end_date", "ann_date"], ascending=False)
        row = data.iloc[0]

        def first_number(*columns: str) -> float | None:
            for column in columns:
                if column not in row.index:
                    continue
                value = cls._number(row.get(column))
                if value is not None:
                    return value
            return None

        packet = {
            "status": "available",
            "report_period": cls._iso_date(row.get("end_date")),
            "announcement_date": cls._iso_date(row.get("ann_date")),
            "revenue_yoy": first_number(
                "tr_yoy", "or_yoy", "q_sales_yoy", "revenue_yoy"
            ),
            "net_profit_yoy": first_number(
                "netprofit_yoy", "q_netprofit_yoy", "q_dtprofit_yoy"
            ),
            "roe": first_number("roe"),
            "gross_margin": first_number("grossprofit_margin"),
            "net_margin": first_number("netprofit_margin"),
            "debt_to_assets": first_number("debt_to_assets"),
        }
        available = sum(
            packet.get(key) is not None
            for key in (
                "revenue_yoy",
                "net_profit_yoy",
                "roe",
                "gross_margin",
                "net_margin",
                "debt_to_assets",
            )
        )
        packet["coverage_status"] = (
            "sufficient"
            if available >= 5
            else "partial"
            if available
            else "unavailable"
        )
        return packet

    @staticmethod
    def _apply_financial_filters(
        frame: pd.DataFrame,
        packets: Mapping[str, Mapping[str, Any]],
        filters: Mapping[str, Any],
    ) -> pd.DataFrame:
        if frame.empty:
            return frame
        result = frame.copy()
        for field in FINANCIAL_FILTERS.values():
            result[field] = result["ts_code"].map(
                lambda code: StockScreenerService._number(
                    packets.get(str(code), {}).get(field)
                )
            )
        keep: list[bool] = []
        for _, row in result.iterrows():
            packet = packets.get(str(row["ts_code"]), {})
            matched = True
            for filter_name, field in FINANCIAL_FILTERS.items():
                if filter_name not in filters or filters[filter_name] is None:
                    continue
                value = StockScreenerService._number(packet.get(field))
                if value is None or value < float(filters[filter_name]):
                    matched = False
                    break
            keep.append(matched)
        return result.loc[keep].copy()

    @staticmethod
    def _sort_frame(frame: pd.DataFrame, profile: str) -> pd.DataFrame:
        if frame.empty:
            return frame
        if profile == "trend":
            columns, ascending = ["industry_excess_20d_pct", "ts_code"], [False, True]
        elif profile == "value":
            columns, ascending = ["pe_ttm", "pb", "ts_code"], [True, True, True]
        elif profile == "pullback":
            columns, ascending = ["return_5d_pct", "ts_code"], [True, True]
        else:
            if "revenue_yoy" in frame:
                columns, ascending = ["revenue_yoy", "ts_code"], [False, True]
            else:
                # The preliminary pool has no model-produced score and uses
                # liquidity only as a stable tiebreaker before finance is read.
                columns, ascending = ["amount", "ts_code"], [False, True]
        return frame.sort_values(columns, ascending=ascending, na_position="last")

    def _build_item(
        self, row: pd.Series, profile: str, financials: Mapping[str, Any]
    ) -> dict[str, Any]:
        industry = str(row.get("industry") or "未分类")
        metrics = {
            "latest_close": self._number(row.get("latest_close")),
            "pct_change": self._number(row.get("pct_change")),
            "return_5d_pct": self._number(row.get("return_5d_pct")),
            "return_20d_pct": self._number(row.get("return_20d_pct")),
            "industry_avg_return_20d_pct": self._number(
                row.get("industry_avg_return_20d_pct")
            ),
            "industry_excess_20d_pct": self._number(row.get("industry_excess_20d_pct")),
            "pe_ttm": self._number(row.get("pe_ttm")),
            "pb": self._number(row.get("pb")),
            "ps_ttm": self._number(row.get("ps_ttm")),
            "total_mv_yi": self._number(row.get("total_mv_yi")),
            "circ_mv_yi": self._number(row.get("circ_mv_yi")),
            "turnover_rate_pct": self._number(row.get("turnover_rate")),
            "volume_ratio": self._number(row.get("volume_ratio")),
        }
        clean_financials = {
            key: value
            for key, value in dict(financials).items()
            if key != "status" or value != "unavailable"
        }
        financial_fields = (
            "revenue_yoy",
            "net_profit_yoy",
            "roe",
            "gross_margin",
            "net_margin",
            "debt_to_assets",
        )
        not_applicable_fields: list[str] = []
        if any(term in industry for term in ("银行", "保险", "证券", "多元金融")):
            # Financial institutions do not use industrial-company gross
            # profit presentation. Treating a structurally absent gross margin
            # as a data failure would mislead users.
            not_applicable_fields.append("gross_margin")
        relevant_metric_fields = {
            "latest_close",
            "return_5d_pct",
            "return_20d_pct",
            "industry_excess_20d_pct",
            "pe_ttm",
            "pb",
            "total_mv_yi",
            "turnover_rate_pct",
            "volume_ratio",
        }
        relevant_financial_fields = (
            {"revenue_yoy", "net_profit_yoy", "roe"} if profile == "quality" else set()
        )
        relevant_fields = relevant_metric_fields | relevant_financial_fields
        missing_fields = [
            key
            for key, value in {**metrics, **clean_financials}.items()
            if key in relevant_fields
            and value is None
            and key not in not_applicable_fields
        ]
        if not financials or financials.get("status") == "unavailable":
            missing_fields.extend(
                key
                for key in relevant_financial_fields
                if key not in missing_fields and key not in not_applicable_fields
            )
            clean_financials = {
                "status": "unavailable",
                "coverage_status": "unavailable",
            }
        reasons = self._matched_reasons(profile, metrics, clean_financials)
        research_focus, attention_flags = self._research_guidance(
            profile, metrics, clean_financials
        )
        financial_coverage = str(
            clean_financials.get("coverage_status") or "unavailable"
        )
        missing_reasons = []
        for field in sorted(set(missing_fields)):
            if field in financial_fields:
                code = (
                    "financial_report_unavailable"
                    if not clean_financials.get("report_period")
                    else "financial_field_missing"
                )
                reason = (
                    "尚未取得可用财务报告期"
                    if code == "financial_report_unavailable"
                    else f"最新财务报告期未返回{FILTER_LABELS.get('min_' + field, field)}字段"
                )
            elif field in {"pe_ttm", "pb", "ps_ttm", "total_mv_yi", "circ_mv_yi"}:
                code = "daily_basic_field_missing"
                reason = "最近完整交易日的估值或市值截面未返回该字段"
            elif field in {"return_5d_pct", "return_20d_pct"}:
                code = "comparison_bar_missing"
                reason = "当前或比较基准交易日缺少完整日线"
            elif field in {"volume_ratio", "turnover_rate_pct"}:
                code = "liquidity_field_missing"
                reason = "最近完整交易日的流动性字段未返回"
            else:
                code = "market_field_missing"
                reason = "最近完整交易日未返回该字段"
            missing_reasons.append({"field": field, "code": code, "reason": reason})
        return {
            "ts_code": str(row.get("ts_code") or ""),
            "internal_symbol": str(row.get("internal_symbol") or ""),
            "name": str(row.get("name") or ""),
            "industry": industry,
            "market": str(row.get("market") or row.get("exchange") or "A股"),
            "list_date": self._iso_date(row.get("list_date")),
            "metrics": metrics,
            "financials": clean_financials,
            "evidence_times": {
                "market_date": self._iso_date(row.get("trade_date")),
                "financial_report_period": clean_financials.get("report_period"),
                "financial_announcement_date": clean_financials.get(
                    "announcement_date"
                ),
            },
            "source_contract": {
                "market_and_trend": "Tushare Pro:daily",
                "valuation": "Tushare Pro:daily_basic",
                "financial_quality": "Tushare Pro:fina_indicator",
            },
            "coverage_status": {
                "market_and_trend": "sufficient",
                "valuation": (
                    "sufficient"
                    if metrics["pe_ttm"] is not None and metrics["pb"] is not None
                    else "partial"
                ),
                "financial_quality": financial_coverage,
            },
            "matched_reasons": reasons,
            "research_focus": research_focus,
            "attention_flags": attention_flags,
            "missing_fields": sorted(set(missing_fields)),
            "missing_reasons": missing_reasons,
            "not_applicable_fields": not_applicable_fields,
            "limitations": [
                "阶段收益基于完整日线，不是盘中信号。",
                "行业相对表现使用同一 Tushare 行业标签下股票的简单均值，不代表官方行业指数。",
                "最新财务指标可能来自不同报告期，比较前需核对报告期和公告日。",
            ],
        }

    @staticmethod
    def _matched_reasons(
        profile: str,
        metrics: Mapping[str, Any],
        financials: Mapping[str, Any],
    ) -> list[str]:
        def fmt(value: Any) -> str:
            number = StockScreenerService._number(value)
            return "—" if number is None else f"{number:.2f}"

        if profile == "quality":
            return [
                f"最新财报营收同比 {fmt(financials.get('revenue_yoy'))}%",
                f"最新财报净利润同比 {fmt(financials.get('net_profit_yoy'))}%",
                f"最新财报 ROE {fmt(financials.get('roe'))}%",
            ]
        if profile == "trend":
            return [
                f"近 5 日收益 {fmt(metrics.get('return_5d_pct'))}%",
                f"近 20 日收益 {fmt(metrics.get('return_20d_pct'))}%",
                f"近 20 日相对所属行业样本均值 {fmt(metrics.get('industry_excess_20d_pct'))} 个百分点",
            ]
        if profile == "value":
            return [
                f"PE TTM {fmt(metrics.get('pe_ttm'))}",
                f"PB {fmt(metrics.get('pb'))}",
                f"总市值 {fmt(metrics.get('total_mv_yi'))} 亿元；命中估值约束不等于低估",
            ]
        return [
            f"近 20 日收益 {fmt(metrics.get('return_20d_pct'))}%",
            f"近 5 日收益 {fmt(metrics.get('return_5d_pct'))}%",
            f"量比 {fmt(metrics.get('volume_ratio'))}；仅表示活跃度，仍需复核回撤原因",
        ]

    @staticmethod
    def _research_guidance(
        profile: str,
        metrics: Mapping[str, Any],
        financials: Mapping[str, Any],
    ) -> tuple[str, list[str]]:
        """Build deterministic research priorities from displayed metrics."""

        def number(value: Any) -> float | None:
            return StockScreenerService._number(value)

        def fmt(value: Any) -> str:
            parsed = number(value)
            return "—" if parsed is None else f"{parsed:.2f}"

        if profile == "quality":
            research_focus = (
                f"营收同比 {fmt(financials.get('revenue_yoy'))}%、"
                f"净利润同比 {fmt(financials.get('net_profit_yoy'))}% 与 "
                f"ROE {fmt(financials.get('roe'))}% 是否来自主营并能转化为现金流，"
                "同时排除一次性损益。"
            )
        elif profile == "value":
            research_focus = (
                f"PE TTM {fmt(metrics.get('pe_ttm'))}、"
                f"PB {fmt(metrics.get('pb'))} 对应的是持续盈利能力，"
                "还是盈利恶化、周期高点或高负债造成的低估值。"
            )
        elif profile == "pullback":
            research_focus = (
                f"近 20 日 {fmt(metrics.get('return_20d_pct'))}% 的回撤原因是什么，"
                f"并确认近 5 日 {fmt(metrics.get('return_5d_pct'))}% "
                "是接近转正或刚转正的企稳迹象，还是快速反弹后的二次波动。"
            )
        else:
            research_focus = (
                f"近 20 日 {fmt(metrics.get('return_20d_pct'))}%、"
                f"相对行业 {fmt(metrics.get('industry_excess_20d_pct'))} 个百分点的强势"
                "是否有业绩或公告支撑，并明确趋势转弱条件。"
            )

        flags: list[str] = []
        pct_change = number(metrics.get("pct_change"))
        if pct_change is not None and pct_change <= -5:
            flags.append(
                f"当日下跌 {abs(pct_change):.2f}%，短期价格出现明显转弱，"
                "需优先核对公告、行业事件和资金兑现。"
            )
        return_5d = number(metrics.get("return_5d_pct"))
        if profile == "pullback" and return_5d is not None and return_5d >= 15:
            flags.append(
                f"近 5 日已反弹 {return_5d:.2f}%，不宜继续理解为“刚企稳”，"
                "需要检查追高和再次回落风险。"
            )
        net_profit_yoy = number(financials.get("net_profit_yoy"))
        if net_profit_yoy is not None and net_profit_yoy < 0:
            flags.append(
                f"最新财报净利润同比 {net_profit_yoy:.2f}%，"
                "盈利变化是当前候选逻辑的反方线索。"
            )
        roe = number(financials.get("roe"))
        if roe is not None and roe < 3:
            flags.append(f"最新财报 ROE {roe:.2f}%，资本回报仍偏低。")
        debt_to_assets = number(financials.get("debt_to_assets"))
        if debt_to_assets is not None and debt_to_assets >= 75:
            flags.append(f"资产负债率 {debt_to_assets:.2f}%，负债约束需要优先核验。")
        pe_ttm = number(metrics.get("pe_ttm"))
        pb = number(metrics.get("pb"))
        if (pe_ttm is not None and pe_ttm >= 80) or (pb is not None and pb >= 8):
            valuation_parts = []
            if pe_ttm is not None:
                valuation_parts.append(f"PE TTM {pe_ttm:.2f}")
            if pb is not None:
                valuation_parts.append(f"PB {pb:.2f}")
            flags.append(
                f"{'、'.join(valuation_parts)}，估值约束较高，"
                "对盈利兑现和预期变化更敏感。"
            )
        return research_focus, flags[:4]

    @staticmethod
    def _rules(filters: Mapping[str, Any]) -> list[dict[str, Any]]:
        rules: list[dict[str, Any]] = []
        if filters.get("exclude_st", True):
            rules.append(
                {
                    "field": "股票状态",
                    "operator": "排除",
                    "value": "ST / *ST",
                    "reason": "降低特殊处理和退市风险对首轮研究候选的干扰。",
                }
            )
        rules.append(
            {
                "field": "上市时长",
                "operator": ">=",
                "value": int(filters.get("min_listed_days", 180)),
                "unit": "自然日",
                "reason": "减少新股短历史和定价剧烈波动造成的阶段收益偏差。",
            }
        )
        for key, label in FILTER_LABELS.items():
            if key not in filters or filters[key] is None:
                continue
            unit = (
                "%"
                if any(
                    token in key
                    for token in ("return", "turnover", "revenue", "profit", "roe")
                )
                else "亿元"
                if "market_cap" in key
                else None
            )
            rules.append(
                {
                    "field": label,
                    "operator": ">=" if key.startswith("min_") else "<=",
                    "value": float(filters[key]),
                    **({"unit": unit} if unit else {}),
                    "reason": "用户可见、可修改的确定性筛选条件。",
                }
            )
        if filters.get("industry"):
            rules.append(
                {
                    "field": "行业",
                    "operator": "包含",
                    "value": str(filters["industry"]),
                    "reason": "按 Tushare 股票基础信息中的行业标签筛选。",
                }
            )
        return rules

    @staticmethod
    def _number(value: Any) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(number):
            return None
        return round(number, 4)

    @staticmethod
    def _date_string(value: Any) -> str:
        text = str(value or "").strip().replace("-", "")
        return text[:8] if len(text) >= 8 and text[:8].isdigit() else ""

    @classmethod
    def _iso_date(cls, value: Any) -> str | None:
        text = cls._date_string(value)
        if not text:
            return None
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"

    @staticmethod
    def _internal_symbol(ts_code: Any) -> str:
        value = str(ts_code or "").strip().upper()
        return value[:-3] + ".SS" if value.endswith(".SH") else value
