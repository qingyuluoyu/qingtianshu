from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import date, datetime
import hashlib
import json
import math
import re
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

import pandas as pd

from app.catalog import normalize_symbol
from app.db import Database
from app.services.strategies.li_zong import (
    CANDIDATE_RULE_IDS,
    FORMULA_VERSION,
    STRATEGY_ID,
    STRATEGY_VERSION,
    LiZongParameters,
    deterministic_li_zong_v1,
)


RULE_DEFINITIONS = [
    {"rule_id": "LZ-F-01", "group": "fundamental", "label": "总市值严格大于150亿元"},
    {"rule_id": "LZ-F-02", "group": "fundamental", "label": "连续五个完整年度ROE达标"},
    {"rule_id": "LZ-F-04", "group": "fundamental", "label": "非自然人股东至少5名"},
    {"rule_id": "LZ-C-01", "group": "character", "label": "近一年至少6次收盘涨停"},
    {"rule_id": "LZ-C-02", "group": "character", "label": "近一年至少一次连续两日涨停"},
    {"rule_id": "LZ-C-03", "group": "character", "label": "近十日存在收盘涨停"},
    {"rule_id": "LZ-C-04", "group": "character", "label": "近十日无5%阴线"},
    {"rule_id": "LZ-VP-01", "group": "volume_price", "label": "近二十日出现360日复权新高"},
    {"rule_id": "LZ-VP-02", "group": "volume_price", "label": "连续三日成交量达到基准两倍"},
    {"rule_id": "LZ-T-01", "group": "trigger", "label": "当日收盘涨停"},
    {"rule_id": "LZ-T-02", "group": "trigger", "label": "高开至少3.5%且收阳"},
    {"rule_id": "LZ-T-03", "group": "trigger", "label": "振幅严格大于9.8%且收阳"},
]

FORMULAS = {
    "limit_up": "close == up_limit（逐股票逐交易日真实涨停价）",
    "bearish_drop": "close < open AND pct_chg <= -5.0",
    "adjusted_high": "adjusted_high，或 high * adj_factor",
    "volume_expansion": "连续3日 volume >= 2.0 * 前20日平均volume",
    "gap_open_pct": "(open / pre_close - 1) * 100",
    "amplitude_pct": "(high - low) / pre_close * 100",
}

INSTITUTION_MARKERS = (
    "公司",
    "基金",
    "资管",
    "资产管理",
    "保险",
    "社保",
    "信托",
    "证券",
    "银行",
    "国有资本",
    "国资",
    "中央结算",
    "投资合伙",
    "机构",
)


class LiZongStrategyService:
    """Run Li Zong v1 on published snapshots with traceable data fallbacks."""

    ROE_FALLBACK_VERSION = "eastmoney_reported_roe_v1"
    PRICE_HISTORY_WINDOW_VERSION = "market_days_700_v1"
    INCOMPLETE_BOUNDARY_VERSION = "data_incomplete_v2"
    MAX_DEEP_SYNC_WORKERS = 2
    MAX_TRANSIENT_SYNC_RETRIES = 3
    PRICE_HISTORY_RULE_IDS = {
        "LZ-C-01",
        "LZ-C-02",
        "LZ-C-03",
        "LZ-C-04",
        "LZ-VP-01",
        "LZ-VP-02",
    }

    SUBSCRIPTION_BOUNDARY = (
        "用户策略订阅、通知偏好和提醒渠道暂未在本服务持久化；"
        "当前只发布公共候选与触发事实，后续由独立用户订阅层关联。"
    )

    def __init__(
        self,
        database: Database,
        snapshot_service: Any,
        fundamentals_provider: Any | None = None,
    ):
        self.database = database
        self.snapshot_service = snapshot_service
        self.fundamentals_provider = fundamentals_provider
        self._ensure_definition()
        self.database.repair_unstable_strategy_prefilter_runs(STRATEGY_ID)

    def list_strategies(self) -> list[dict[str, Any]]:
        return [
            {
                **item,
                "subscription_boundary": self.SUBSCRIPTION_BOUNDARY,
            }
            for item in self.database.list_strategy_definitions()
        ]

    def get_definition(self, strategy_id: str = STRATEGY_ID) -> dict[str, Any]:
        if strategy_id != STRATEGY_ID:
            raise KeyError(f"unknown strategy: {strategy_id}")
        definition = self.database.get_strategy_definition(strategy_id)
        if definition is None:
            raise KeyError(f"unknown strategy: {strategy_id}")
        version = self.database.get_strategy_version(strategy_id, STRATEGY_VERSION)
        parameter = self.database.get_strategy_parameter_version(
            strategy_id,
            STRATEGY_VERSION,
            LiZongParameters().parameter_version,
        )
        return {
            **definition,
            "version": version,
            "default_parameter_version": parameter,
            "subscription_boundary": self.SUBSCRIPTION_BOUNDARY,
        }

    def run_symbols(
        self,
        symbols: Sequence[str],
        *,
        parameters: Mapping[str, Any] | LiZongParameters | None = None,
        run_scope: str = "symbol_batch",
        universe_count: int = 0,
        prefiltered_count: int = 0,
        coverage_ratio: float = 0.0,
        warnings: list[str] | None = None,
    ) -> dict[str, Any]:
        canonical_symbols = self._canonical_symbols(symbols)
        params = LiZongParameters.from_value(parameters)
        self._save_parameter_version(params)

        packets: dict[str, dict[str, Any]] = {}
        packet_errors: dict[str, str] = {}
        for symbol in canonical_symbols:
            try:
                packets[symbol] = self.snapshot_service.get_symbol_snapshot(symbol)
            except Exception as exc:
                packets[symbol] = {
                    "symbol": symbol,
                    "status": "not_ready",
                    "snapshot": None,
                }
                packet_errors[symbol] = type(exc).__name__

        supplemental_roe: dict[str, list[dict[str, Any]]] = {}
        roe_fallback_attempted: dict[str, bool] = {}
        for symbol, packet in packets.items():
            rows, attempted = self._supplemental_roe_rows(symbol, packet, params)
            supplemental_roe[symbol] = rows
            roe_fallback_attempted[symbol] = attempted

        retry_metadata: dict[str, dict[str, Any]] = {}
        for symbol, packet in packets.items():
            current_state = self.database.latest_strategy_candidate_snapshot(
                strategy_id=STRATEGY_ID,
                strategy_version=STRATEGY_VERSION,
                parameter_version=params.parameter_version,
                symbol=symbol,
            )
            retryable_sync_issue = self._packet_has_retryable_sync_issue(packet)
            packet_as_of = self._packet_as_of(packet)
            same_market_date = bool(
                current_state
                and packet_as_of
                and str(current_state.get("as_of_date") or "") == packet_as_of
            )
            previous_retry_count = (
                int(
                    ((current_state or {}).get("result") or {}).get(
                        "sync_retry_count"
                    )
                    or 0
                )
                if same_market_date
                else 0
            )
            sync_retry_count = (
                previous_retry_count + 1 if retryable_sync_issue else 0
            )
            retry_metadata[symbol] = {
                "current_state": current_state,
                "retryable": retryable_sync_issue,
                "retry_count": sync_retry_count,
                "retry_exhausted": bool(
                    retryable_sync_issue
                    and sync_retry_count >= self.MAX_TRANSIENT_SYNC_RETRIES
                ),
                "as_of_date": packet_as_of,
            }

        data_versions: dict[str, str] = {}
        for symbol, packet in packets.items():
            packet_version = self._packet_data_version(symbol, packet)
            retry = retry_metadata[symbol]
            version_payload: dict[str, Any] = {
                "packet_data_version": packet_version,
                "price_history_window_version": self.PRICE_HISTORY_WINDOW_VERSION,
                "incomplete_boundary_version": self.INCOMPLETE_BOUNDARY_VERSION,
            }
            if retry["retryable"]:
                version_payload.update(
                    {
                        "sync_retry_attempt": retry["retry_count"],
                        "sync_retry_as_of_date": retry["as_of_date"],
                    }
                )
            if roe_fallback_attempted[symbol]:
                version_payload.update(
                    {
                        "roe_fallback_version": self.ROE_FALLBACK_VERSION,
                        "supplemental_roe": supplemental_roe[symbol],
                    }
                )
            data_versions[symbol] = self._fingerprint(version_payload)
        as_of_dates = [
            value
            for value in (self._packet_as_of(packet) for packet in packets.values())
            if value
        ]
        batch_version = (
            next(iter(data_versions.values()))
            if len(data_versions) == 1
            else self._fingerprint(data_versions)
        )
        run = self.database.start_strategy_screen_run(
            strategy_id=STRATEGY_ID,
            strategy_version=STRATEGY_VERSION,
            parameter_version=params.parameter_version,
            data_version=batch_version,
            data_versions=data_versions,
            as_of_date=max(as_of_dates) if as_of_dates else self._today(),
            requested_count=len(canonical_symbols),
            run_scope=run_scope,
            universe_count=universe_count,
            prefiltered_count=prefiltered_count,
            coverage_ratio=coverage_ratio,
            warnings=warnings,
        )

        items: list[dict[str, Any]] = []
        counts = {
            "processed": 0,
            "qualified": 0,
            "triggered": 0,
            "data_incomplete": 0,
            "invalidated": 0,
        }
        errors = dict(packet_errors)
        for symbol in canonical_symbols:
            packet = packets[symbol]
            data_version = data_versions[symbol]
            stock_basic = self._packet_stock_basic(packet)
            retry = retry_metadata[symbol]
            current_state = retry["current_state"]
            try:
                evaluation = deterministic_li_zong_v1(
                    self._build_input(
                        symbol,
                        packet,
                        supplemental_roe_rows=supplemental_roe[symbol],
                    ),
                    parameters=params,
                )
                evaluation = self._enforce_incomplete_boundary(evaluation, packet)
            except Exception as exc:
                errors[symbol] = type(exc).__name__
                evaluation = deterministic_li_zong_v1(
                    self._empty_input(symbol, self._packet_as_of(packet)),
                    parameters=params,
                )
                evaluation = self._force_incomplete(
                    evaluation,
                    "策略输入转换失败，已按 data_incomplete 保存，未进入候选或触发池。",
                )
            if roe_fallback_attempted[symbol]:
                evaluation["roe_fallback_version"] = self.ROE_FALLBACK_VERSION
                evaluation["roe_fallback_rows"] = len(supplemental_roe[symbol])
            evaluation["price_history_window_version"] = (
                self.PRICE_HISTORY_WINDOW_VERSION
            )
            evaluation["incomplete_boundary_version"] = (
                self.INCOMPLETE_BOUNDARY_VERSION
            )
            retryable_sync_issue = bool(retry["retryable"])
            if retryable_sync_issue:
                evaluation = self._force_incomplete(
                    evaluation,
                    "本轮必要数据接口未完整返回；既有稳定快照仅作历史参考，"
                    "本轮不会进入候选或触发池。",
                )
                if retry["as_of_date"]:
                    evaluation["as_of_date"] = retry["as_of_date"]
            evaluation["evaluation_depth"] = (
                "sync_incomplete" if retryable_sync_issue else "full_rules"
            )
            evaluation["sync_retry_count"] = int(retry["retry_count"])
            evaluation["sync_retry_exhausted"] = bool(
                retry["retry_exhausted"]
            )
            if retry["retry_exhausted"]:
                limitation = (
                    "必要数据接口连续多次未完成，本交易日停止自动重试；"
                    "下一个交易日将重新核验。"
                )
                evaluation["limitations"] = list(
                    dict.fromkeys(
                        [*(evaluation.get("limitations") or []), limitation]
                    )
                )
            evaluation["stock_basic"] = stock_basic

            previous = self.database.latest_strategy_candidate_snapshot(
                strategy_id=STRATEGY_ID,
                strategy_version=STRATEGY_VERSION,
                parameter_version=params.parameter_version,
                symbol=symbol,
                exclude_data_version=data_version,
            )
            stored_status = self._stored_status(evaluation["status"], previous)
            candidate, created = self.database.save_strategy_candidate_snapshot(
                run_id=str(run["id"]),
                strategy_id=STRATEGY_ID,
                strategy_version=STRATEGY_VERSION,
                parameter_version=params.parameter_version,
                data_version=data_version,
                symbol=symbol,
                as_of_date=evaluation["as_of_date"],
                status=stored_status,
                evaluation=evaluation,
                previous_status=previous.get("status") if previous else None,
            )
            created_trigger_ids = self._save_trigger_events(candidate, evaluation)
            candidate["idempotent_reused"] = not created
            candidate["new_trigger_event_ids"] = created_trigger_ids
            items.append(candidate)
            counts["processed"] += 1
            if candidate["status"] in counts:
                counts[candidate["status"]] += 1

        run_status = "partial" if errors else "completed"
        finished = self.database.finish_strategy_screen_run(
            str(run["id"]),
            status=run_status,
            counts=counts,
            error=json.dumps(errors, ensure_ascii=False, sort_keys=True) if errors else None,
            coverage_ratio=coverage_ratio,
            warnings=warnings,
        )
        return {
            "run": finished,
            "items": items,
            "counts": counts,
            "errors": errors,
            "boundary": (
                "介入仅表示进入重点关注和人工复核；"
                "本服务不创建持仓、交易、订单或收益承诺。"
            ),
        }

    def run_universe_batch(
        self,
        *,
        batch_size: int = 5,
        as_of_date: str | None = None,
        parameters: Mapping[str, Any] | LiZongParameters | None = None,
    ) -> dict[str, Any]:
        """Incrementally cover the full A-share universe in background batches."""

        params = LiZongParameters.from_value(parameters)
        self._save_parameter_version(params)
        size = max(1, min(int(batch_size), 200))
        universe_sync = self.snapshot_service.sync_a_share_universe(
            as_of_date=as_of_date
        )
        universe_packet = self.snapshot_service.get_a_share_universe()
        snapshot = universe_packet.get("snapshot")
        universe_items = list((snapshot or {}).get("items") or [])
        universe_as_of = str((snapshot or {}).get("as_of_date") or self._today())
        if universe_packet.get("status") != "stable" or not universe_items:
            return {
                "status": "not_ready",
                "universe_sync": universe_sync,
                "coverage": self.coverage_packet(universe_packet),
                "boundary": (
                    "全市场名单与最近完整交易日市值尚未达到稳定发布门槛；"
                    "本轮不会生成预筛结果，也不会逐股拉取多年数据。"
                ),
            }

        universe_count = len(universe_items)
        eligible_items: list[dict[str, Any]] = []
        prefilter_items: list[dict[str, Any]] = []
        for item in universe_items:
            market_cap = item.get("total_mv_yi")
            target = (
                eligible_items
                if market_cap is not None
                and float(market_cap) > params.market_cap_min_yi
                else prefilter_items
            )
            target.append(item)
        previous_states = self.database.latest_strategy_candidate_states(
            strategy_id=STRATEGY_ID,
            strategy_version=STRATEGY_VERSION,
            parameter_version=params.parameter_version,
        )
        deep_eligible_items: list[dict[str, Any]] = []
        history_insufficient_items: list[dict[str, Any]] = []
        for item in eligible_items:
            enriched = dict(item)
            enriched["history_precheck"] = self._history_precheck(
                item, as_of_date=universe_as_of, parameters=params
            )
            if enriched["history_precheck"]["status"] == "insufficient":
                history_insufficient_items.append(enriched)
            else:
                deep_eligible_items.append(enriched)
        current_dates = self.database.latest_strategy_candidate_dates(
            strategy_id=STRATEGY_ID,
            strategy_version=STRATEGY_VERSION,
            parameter_version=params.parameter_version,
        )
        prefilter_pending = [
            item
            for item in prefilter_items
            if current_dates.get(str(item.get("symbol"))) != universe_as_of
        ]
        prefilter_result = self._publish_universe_prefilter(
            prefilter_pending,
            universe_data_version=str(universe_packet.get("data_version") or "unknown"),
            as_of_date=universe_as_of,
            parameters=params,
            universe_count=universe_count,
            prefiltered_count=len(eligible_items),
        )

        current_dates = self.database.latest_strategy_candidate_dates(
            strategy_id=STRATEGY_ID,
            strategy_version=STRATEGY_VERSION,
            parameter_version=params.parameter_version,
        )
        history_pending = [
            item
            for item in history_insufficient_items
            if current_dates.get(str(item.get("symbol"))) != universe_as_of
            or self._evaluation_depth(
                (
                    previous_states.get(str(item.get("symbol"))) or {}
                ).get("result")
                or {}
            )
            != "history_precheck"
            or (
                (
                    (
                        previous_states.get(str(item.get("symbol"))) or {}
                    ).get("result")
                    or {}
                ).get("history_precheck")
                or {}
            )
            != (item.get("history_precheck") or {})
        ]
        history_result = self._publish_universe_history_incomplete(
            history_pending,
            universe_data_version=str(
                universe_packet.get("data_version") or "unknown"
            ),
            as_of_date=universe_as_of,
            parameters=params,
            universe_count=universe_count,
            prefiltered_count=len(eligible_items),
        )

        current_dates = self.database.latest_strategy_candidate_dates(
            strategy_id=STRATEGY_ID,
            strategy_version=STRATEGY_VERSION,
            parameter_version=params.parameter_version,
        )
        def needs_deep_processing(item: Mapping[str, Any]) -> bool:
            symbol = str(item.get("symbol") or "")
            if current_dates.get(symbol) != universe_as_of:
                return True
            state = previous_states.get(symbol) or {}
            result = state.get("result") or {}
            depth = self._evaluation_depth(result)
            retry_exhausted = bool(result.get("sync_retry_exhausted"))
            if depth == "sync_incomplete":
                return bool(
                    not retry_exhausted
                    and self._latest_snapshot_has_retryable_sync_issue(symbol)
                )
            if depth != "full_rules":
                return True
            if (
                self.fundamentals_provider is not None
                and self._roe_rule_incomplete(result)
                and str(result.get("roe_fallback_version") or "")
                != self.ROE_FALLBACK_VERSION
            ):
                return True
            if (
                self._price_history_rule_incomplete(result)
                and str(result.get("price_history_window_version") or "")
                != self.PRICE_HISTORY_WINDOW_VERSION
            ):
                return True
            if (
                str(state.get("status") or "") == "data_incomplete"
                and str(result.get("incomplete_boundary_version") or "")
                != self.INCOMPLETE_BOUNDARY_VERSION
            ):
                return True
            return bool(
                not retry_exhausted
                and self._latest_snapshot_has_retryable_sync_issue(symbol)
            )

        pending_eligible = [
            item for item in deep_eligible_items if needs_deep_processing(item)
        ]
        pending_eligible.sort(
            key=lambda item: (
                0
                if (item.get("history_precheck") or {}).get("status")
                == "eligible"
                else 1,
                self._deep_data_availability_score(
                    previous_states.get(str(item.get("symbol")))
                ),
                -float(item.get("total_mv_yi") or 0),
                str(item.get("symbol") or ""),
            )
        )
        selected = pending_eligible[:size]
        def sync_selected_item(item: dict[str, Any]) -> dict[str, Any]:
            symbol = str(item["symbol"])
            try:
                strategy_sync = getattr(
                    self.snapshot_service, "sync_strategy_symbol", None
                )
                if callable(strategy_sync):
                    result = strategy_sync(
                        symbol,
                        as_of_date=universe_as_of,
                        universe_item=item,
                    )
                else:
                    result = self.snapshot_service.sync_symbol(
                        symbol, as_of_date=universe_as_of
                    )
                return {
                    "symbol": symbol,
                    "status": (result.get("run") or {}).get("status"),
                    "published": bool(result.get("published")),
                    "previous_stable_retained": bool(
                        result.get("previous_stable_retained")
                    ),
                }
            except Exception as exc:
                return {
                    "symbol": symbol,
                    "status": "unavailable",
                    "error_type": type(exc).__name__,
                }

        sync_workers = min(self.MAX_DEEP_SYNC_WORKERS, len(selected))
        if sync_workers > 1:
            with ThreadPoolExecutor(max_workers=sync_workers) as executor:
                sync_results = list(executor.map(sync_selected_item, selected))
        else:
            sync_results = [sync_selected_item(item) for item in selected]

        batch_result: dict[str, Any] | None = None
        if selected:
            coverage_before = self.coverage_packet(universe_packet)
            warnings = self._universe_warnings(
                universe_packet, pending_eligible=len(pending_eligible)
            )
            batch_result = self.run_symbols(
                [str(item["symbol"]) for item in selected],
                parameters=params,
                run_scope="universe_batch",
                universe_count=universe_count,
                prefiltered_count=len(eligible_items),
                coverage_ratio=float(coverage_before.get("coverage_ratio") or 0),
                warnings=warnings,
            )

        coverage = self.coverage_packet(universe_packet)
        active_run = (
            batch_result or history_result or prefilter_result or {}
        ).get("run")
        if active_run:
            counts = (
                batch_result or history_result or prefilter_result or {}
            ).get("counts") or {}
            active_run = self.database.finish_strategy_screen_run(
                str(active_run["id"]),
                status=(
                    "completed"
                    if coverage.get("full_market_coverage")
                    and coverage.get("deep_check_complete")
                    else "partial"
                ),
                counts=counts,
                coverage_ratio=float(coverage.get("coverage_ratio") or 0),
                warnings=self._universe_warnings(
                    universe_packet,
                    pending_eligible=int(
                        coverage.get("deep_remaining_symbols") or 0
                    ),
                ),
            )
        return {
            "status": (
                "completed"
                if coverage.get("full_market_coverage")
                and coverage.get("deep_check_complete")
                else "partial"
            ),
            "run": active_run,
            "universe_sync": universe_sync,
            "prefilter": prefilter_result,
            "history_precheck": history_result,
            "batch": batch_result,
            "sync_results": sync_results,
            "selected_symbols": [str(item["symbol"]) for item in selected],
            "coverage": coverage,
            "boundary": (
                "全市场名单与市值先批量发布；上市后量价历史明确不足的股票直接保存"
                " data_incomplete，不请求逐股深度数据。其余市值规则通过的股票"
                "按历史完整性、既有数据可得性和市值顺序分批补齐多年ROE、股东"
                "与量价证据。页面始终读取已发布快照。"
            ),
        }

    def coverage_packet(
        self, universe_packet: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        getter = getattr(self.snapshot_service, "get_a_share_universe", None)
        packet = (
            universe_packet
            if universe_packet is not None
            else getter()
            if callable(getter)
            else {"status": "not_ready", "snapshot": None}
        )
        snapshot = packet.get("snapshot") or {}
        items = list(snapshot.get("items") or [])
        as_of_date = snapshot.get("as_of_date")
        params = LiZongParameters()
        universe_symbols = {str(item.get("symbol")) for item in items}
        eligible_items = [
            item
            for item in items
            if item.get("total_mv_yi") is not None
            and float(item["total_mv_yi"]) > params.market_cap_min_yi
        ]
        eligible_count = len(eligible_items)
        missing_market_cap = sum(
            item.get("total_mv_yi") is None for item in items
        )
        history_checks = {
            str(item.get("symbol")): self._history_precheck(
                item, as_of_date=str(as_of_date or self._today()), parameters=params
            )
            for item in eligible_items
        }
        history_insufficient_symbols = {
            symbol
            for symbol, check in history_checks.items()
            if check.get("status") == "insufficient"
        }
        history_unknown_symbols = {
            symbol
            for symbol, check in history_checks.items()
            if check.get("status") == "unknown"
        }
        deep_check_symbols = {
            str(item.get("symbol"))
            for item in eligible_items
            if str(item.get("symbol")) not in history_insufficient_symbols
        }
        candidate_states = self.database.latest_strategy_candidate_states(
            strategy_id=STRATEGY_ID,
            strategy_version=STRATEGY_VERSION,
            parameter_version=params.parameter_version,
        )
        evaluated_states = (
            {
                symbol: state
                for symbol, state in candidate_states.items()
                if symbol in universe_symbols
                and (
                    not as_of_date
                    or state.get("as_of_date") == str(as_of_date)
                )
            }
            if packet.get("status") == "stable"
            else {}
        )
        universe_count = len(items)
        evaluated_count = len(evaluated_states)
        coverage_ratio = evaluated_count / universe_count if universe_count else 0.0
        counts = {
            "total": evaluated_count,
            "qualified": 0,
            "triggered": 0,
            "not_qualified": 0,
            "data_incomplete": 0,
            "invalidated": 0,
        }
        for state in evaluated_states.values():
            status = str(state.get("status") or "")
            if status in counts and status != "total":
                counts[status] += 1
        evaluation_depths = {
            symbol: self._evaluation_depth(state.get("result") or {})
            for symbol, state in evaluated_states.items()
        }
        deep_processed_symbols = {
            symbol
            for symbol, depth in evaluation_depths.items()
            if symbol in deep_check_symbols and depth == "full_rules"
        }
        deep_decisive_symbols = {
            symbol
            for symbol in deep_processed_symbols
            if self._candidate_rules_complete(
                (evaluated_states[symbol].get("result") or {}).get(
                    "rule_results"
                )
                or []
            )
        }
        deep_check_count = len(deep_check_symbols)
        deep_processed_count = len(deep_processed_symbols)
        deep_decisive_count = len(deep_decisive_symbols)
        deep_processing_ratio = (
            deep_processed_count / deep_check_count if deep_check_count else 1.0
        )
        market_cap_rejected_count = max(
            0, universe_count - eligible_count - missing_market_cap
        )
        decisive_status_count = market_cap_rejected_count + deep_decisive_count
        latest_run = self.database.latest_strategy_screen_run(
            strategy_id=STRATEGY_ID,
            parameter_version=params.parameter_version,
        )
        return {
            "status": packet.get("status") or "not_ready",
            "as_of_date": as_of_date,
            "data_version": packet.get("data_version"),
            "universe_count": universe_count,
            "market_cap_eligible_count": eligible_count,
            "market_cap_rejected_count": market_cap_rejected_count,
            "missing_market_cap_count": missing_market_cap,
            "deep_check_eligible_count": deep_check_count,
            "history_insufficient_count": len(history_insufficient_symbols),
            "history_unknown_count": len(history_unknown_symbols),
            "deep_processed_symbols": deep_processed_count,
            "deep_remaining_symbols": max(
                0, deep_check_count - deep_processed_count
            ),
            "deep_processing_ratio": round(deep_processing_ratio, 6),
            "deep_decisive_symbols": deep_decisive_count,
            "deep_data_incomplete_symbols": max(
                0, deep_processed_count - deep_decisive_count
            ),
            "decisive_status_count": decisive_status_count,
            "decisive_coverage_ratio": round(
                decisive_status_count / universe_count if universe_count else 0.0,
                6,
            ),
            "evaluated_symbols": evaluated_count,
            "remaining_symbols": max(0, universe_count - evaluated_count),
            "coverage_ratio": round(coverage_ratio, 6),
            "full_market_coverage": bool(
                packet.get("status") == "stable"
                and universe_count
                and evaluated_count == universe_count
            ),
            "deep_check_complete": bool(
                packet.get("status") == "stable"
                and deep_processed_count == deep_check_count
            ),
            "counts": counts,
            "latest_run": latest_run,
            "scope": "full_market_incremental",
            "boundary": (
                "名单覆盖率表示当期股票已得到预筛或规则状态，不等于深度规则"
                "已经完整运行。深度处理进度只统计具备历史核验条件并实际执行"
                "多年ROE、股东和量价规则的股票；data_incomplete 不会进入候选"
                "或触发池。"
            ),
        }

    def resolve_universe_mentions(
        self, message: str, *, limit: int = 5
    ) -> list[str]:
        """Resolve multiple A-share codes or company names from the stable universe."""

        text = str(message or "").strip()
        if not text:
            return []
        getter = getattr(self.snapshot_service, "get_a_share_universe", None)
        if not callable(getter):
            return []
        packet = getter()
        items = list(((packet.get("snapshot") or {}).get("items") or []))
        known_symbols = {
            str(item.get("symbol") or ""): item
            for item in items
            if item.get("symbol")
        }
        matches: list[tuple[int, int, str]] = []
        for match in re.finditer(
            r"(?<!\d)(\d{6})(?:\.(SH|SS|SZ|BJ))?(?!\d)",
            text,
            flags=re.IGNORECASE,
        ):
            raw = match.group(1)
            suffix = str(match.group(2) or "").upper()
            if suffix:
                raw = f"{raw}.{suffix}"
            try:
                symbol = normalize_symbol(raw)
            except ValueError:
                continue
            if symbol in known_symbols:
                matches.append((match.start(), -len(match.group(0)), symbol))

        folded = text.casefold()
        for symbol, item in known_symbols.items():
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            position = folded.find(name.casefold())
            if position >= 0:
                matches.append((position, -len(name), symbol))

        resolved: list[str] = []
        for _, _, symbol in sorted(matches):
            if symbol not in resolved:
                resolved.append(symbol)
            if len(resolved) >= max(1, min(int(limit), 10)):
                break
        return resolved

    def _publish_universe_prefilter(
        self,
        items: list[dict[str, Any]],
        *,
        universe_data_version: str,
        as_of_date: str,
        parameters: LiZongParameters,
        universe_count: int,
        prefiltered_count: int,
    ) -> dict[str, Any] | None:
        if not items:
            return None
        data_versions = {
            str(item["symbol"]): self._fingerprint(
                {
                    "universe_data_version": universe_data_version,
                    "symbol": item["symbol"],
                    "total_mv_yi": item.get("total_mv_yi"),
                }
            )
            for item in items
        }
        run = self.database.start_strategy_screen_run(
            strategy_id=STRATEGY_ID,
            strategy_version=STRATEGY_VERSION,
            parameter_version=parameters.parameter_version,
            data_version=self._fingerprint(data_versions),
            data_versions=data_versions,
            as_of_date=as_of_date,
            requested_count=len(items),
            run_scope="universe_prefilter",
            universe_count=universe_count,
            prefiltered_count=prefiltered_count,
        )
        counts = {
            "processed": 0,
            "qualified": 0,
            "triggered": 0,
            "data_incomplete": 0,
            "invalidated": 0,
        }
        stored_items: list[dict[str, Any]] = []
        for item in items:
            symbol = str(item["symbol"])
            market_cap = item.get("total_mv_yi")
            evaluation = deterministic_li_zong_v1(
                {
                    "symbol": symbol,
                    "as_of_date": as_of_date,
                    "daily": [],
                    "roe_history": [],
                    "shareholders": [],
                    "daily_basic": {
                        "trade_date": as_of_date,
                        "total_mv_yi": market_cap,
                        "source": "Tushare Pro:a_share_universe",
                    },
                },
                parameters=parameters,
            )
            evaluation["evaluation_depth"] = "market_cap_prefilter"
            evaluation["stock_basic"] = {
                "name": item.get("name"),
                "industry": item.get("industry"),
                "market": item.get("market"),
                "list_date": item.get("list_date"),
            }
            previous = self.database.latest_strategy_candidate_snapshot(
                strategy_id=STRATEGY_ID,
                strategy_version=STRATEGY_VERSION,
                parameter_version=parameters.parameter_version,
                symbol=symbol,
                exclude_data_version=data_versions[symbol],
            )
            stored_status = self._stored_status(evaluation["status"], previous)
            candidate, _ = self.database.save_strategy_candidate_snapshot(
                run_id=str(run["id"]),
                strategy_id=STRATEGY_ID,
                strategy_version=STRATEGY_VERSION,
                parameter_version=parameters.parameter_version,
                data_version=data_versions[symbol],
                symbol=symbol,
                as_of_date=as_of_date,
                status=stored_status,
                evaluation=evaluation,
                previous_status=previous.get("status") if previous else None,
            )
            stored_items.append(candidate)
            counts["processed"] += 1
            if candidate["status"] in counts:
                counts[candidate["status"]] += 1
        finished = self.database.finish_strategy_screen_run(
            str(run["id"]), status="partial", counts=counts
        )
        return {"run": finished, "items": stored_items, "counts": counts}

    def _publish_universe_history_incomplete(
        self,
        items: list[dict[str, Any]],
        *,
        universe_data_version: str,
        as_of_date: str,
        parameters: LiZongParameters,
        universe_count: int,
        prefiltered_count: int,
    ) -> dict[str, Any] | None:
        """Persist obvious post-listing price-history gaps without symbol syncs."""

        if not items:
            return None
        data_versions = {
            str(item["symbol"]): self._fingerprint(
                {
                    "universe_data_version": universe_data_version,
                    "symbol": item["symbol"],
                    "total_mv_yi": item.get("total_mv_yi"),
                    "list_date": item.get("list_date"),
                    "history_precheck": item.get("history_precheck") or {},
                }
            )
            for item in items
        }
        run = self.database.start_strategy_screen_run(
            strategy_id=STRATEGY_ID,
            strategy_version=STRATEGY_VERSION,
            parameter_version=parameters.parameter_version,
            data_version=self._fingerprint(data_versions),
            data_versions=data_versions,
            as_of_date=as_of_date,
            requested_count=len(items),
            run_scope="universe_history_precheck",
            universe_count=universe_count,
            prefiltered_count=prefiltered_count,
            warnings=[
                f"{len(items)} 只股票上市后量价历史明确不足，未发起逐股深度数据请求。"
            ],
        )
        counts = {
            "processed": 0,
            "qualified": 0,
            "triggered": 0,
            "data_incomplete": 0,
            "invalidated": 0,
        }
        stored_items: list[dict[str, Any]] = []
        for item in items:
            symbol = str(item["symbol"])
            history_precheck = dict(item.get("history_precheck") or {})
            reasons = [str(value) for value in history_precheck.get("reasons") or []]
            limitation = (
                "上市后量价历史预判未达到策略最小窗口："
                + "；".join(reasons)
                + "。本轮未请求逐股ROE、股东、复权行情和涨跌停价；"
                "达到历史门槛后会自动进入深度批次。"
            )
            evaluation = deterministic_li_zong_v1(
                {
                    "symbol": symbol,
                    "as_of_date": as_of_date,
                    "daily": [],
                    "roe_history": [],
                    "shareholders": [],
                    "daily_basic": {
                        "trade_date": as_of_date,
                        "total_mv_yi": item.get("total_mv_yi"),
                        "source": "Tushare Pro:a_share_universe",
                    },
                },
                parameters=parameters,
            )
            evaluation = self._force_incomplete(evaluation, limitation)
            evaluation["evaluation_depth"] = "history_precheck"
            evaluation["history_precheck"] = history_precheck
            evaluation["stock_basic"] = {
                "name": item.get("name"),
                "industry": item.get("industry"),
                "market": item.get("market"),
                "list_date": item.get("list_date"),
            }
            previous = self.database.latest_strategy_candidate_snapshot(
                strategy_id=STRATEGY_ID,
                strategy_version=STRATEGY_VERSION,
                parameter_version=parameters.parameter_version,
                symbol=symbol,
                exclude_data_version=data_versions[symbol],
            )
            candidate, _ = self.database.save_strategy_candidate_snapshot(
                run_id=str(run["id"]),
                strategy_id=STRATEGY_ID,
                strategy_version=STRATEGY_VERSION,
                parameter_version=parameters.parameter_version,
                data_version=data_versions[symbol],
                symbol=symbol,
                as_of_date=as_of_date,
                status="data_incomplete",
                evaluation=evaluation,
                previous_status=previous.get("status") if previous else None,
            )
            stored_items.append(candidate)
            counts["processed"] += 1
            counts["data_incomplete"] += 1
        finished = self.database.finish_strategy_screen_run(
            str(run["id"]), status="partial", counts=counts
        )
        return {"run": finished, "items": stored_items, "counts": counts}

    @classmethod
    def _history_precheck(
        cls,
        item: Mapping[str, Any],
        *,
        as_of_date: str,
        parameters: LiZongParameters,
    ) -> dict[str, Any]:
        required_trading_days = max(
            parameters.character_window_days,
            parameters.adjusted_high_window_days
            + parameters.new_high_recent_days
            - 1,
            parameters.adjusted_high_window_days
            + parameters.volume_baseline_days,
        )
        # A-share trading calendars average roughly 242 open days per year.
        # Use that market-specific ratio plus a small holiday buffer instead
        # of a weekday-only estimate, which let 377-row recent listings slip
        # into an expensive deep sync that could never satisfy 380 rows.
        required_trading_calendar_days = (
            math.ceil(required_trading_days * 365.2425 / 242) + 7
        )
        required_roe_calendar_days = parameters.required_annual_roe_years * 365
        listed = cls._parse_date(item.get("list_date"))
        as_of = cls._parse_date(as_of_date)
        base = {
            "list_date": listed.isoformat() if listed else None,
            "as_of_date": as_of.isoformat() if as_of else as_of_date,
            "required_annual_roe_years": parameters.required_annual_roe_years,
            "required_trading_days": required_trading_days,
            "required_trading_calendar_days": required_trading_calendar_days,
        }
        if listed is None or as_of is None:
            return {
                **base,
                "status": "unknown",
                "listing_age_days": None,
                "reasons": ["上市日期缺失或格式异常，不能提前判定历史不足"],
            }
        age_days = (as_of - listed).days
        reasons: list[str] = []
        if age_days < required_trading_calendar_days:
            reasons.append(
                f"{required_trading_days}个交易日量价窗口按日历缓冲至少需要约"
                f"{required_trading_calendar_days}天，当前上市{max(age_days, 0)}天"
            )
        if reasons:
            status = "insufficient"
        elif age_days < required_roe_calendar_days:
            status = "unknown"
            reasons.append(
                "上市日期不能证明上市前年度ROE不可得，"
                "需实际查询连续五个完整年度的财务指标"
            )
        else:
            status = "eligible"
        return {
            **base,
            "status": status,
            "listing_age_days": age_days,
            "reasons": reasons,
        }

    @classmethod
    def _deep_data_availability_score(
        cls, state: Mapping[str, Any] | None
    ) -> int:
        if not state:
            return 2
        result = state.get("result") or {}
        if cls._evaluation_depth(result) == "sync_incomplete":
            return 3
        if cls._evaluation_depth(result) != "full_rules":
            return 2
        return 0 if cls._candidate_rules_complete(
            result.get("rule_results") or []
        ) else 1

    @staticmethod
    def _evaluation_depth(result: Mapping[str, Any]) -> str:
        explicit = str(result.get("evaluation_depth") or "").strip()
        if explicit:
            return explicit
        if result.get("history_precheck"):
            return "history_precheck"
        rules = {
            str(rule.get("rule_id")): str(rule.get("status") or "")
            for rule in result.get("rule_results") or []
        }
        if not rules:
            return "unknown"
        market_status = rules.get("LZ-F-01")
        other_statuses = [
            rules.get(rule_id) for rule_id in CANDIDATE_RULE_IDS if rule_id != "LZ-F-01"
        ]
        if market_status in {"failed", "data_incomplete"} and all(
            status in {None, "data_incomplete"} for status in other_statuses
        ):
            return "market_cap_prefilter"
        return "full_rules"

    @staticmethod
    def _candidate_rules_complete(rule_results: Sequence[Mapping[str, Any]]) -> bool:
        statuses = {
            str(rule.get("rule_id")): str(rule.get("status") or "")
            for rule in rule_results
            if rule.get("rule_id") in CANDIDATE_RULE_IDS
        }
        return set(statuses) == set(CANDIDATE_RULE_IDS) and all(
            status in {"passed", "failed"} for status in statuses.values()
        )

    @classmethod
    def _price_history_rule_incomplete(cls, result: Mapping[str, Any]) -> bool:
        return any(
            str(rule.get("rule_id") or "") in cls.PRICE_HISTORY_RULE_IDS
            and str(rule.get("status") or "") == "data_incomplete"
            for rule in result.get("rule_results") or []
        )

    @staticmethod
    def _snapshot_has_retryable_sync_issue(snapshot: Mapping[str, Any]) -> bool:
        missing = set((snapshot.get("coverage") or {}).get("missing") or [])
        return any(
            str(issue.get("dataset") or "") in missing
            and bool(issue.get("error_type"))
            for issue in snapshot.get("issues") or []
        )

    @staticmethod
    def _snapshot_is_newer(
        candidate: Mapping[str, Any], baseline: Mapping[str, Any]
    ) -> bool:
        candidate_time = str(candidate.get("generated_at") or "")
        baseline_time = str(baseline.get("generated_at") or "")
        return bool(candidate_time and baseline_time and candidate_time > baseline_time)

    @classmethod
    def _retryable_sync_snapshot(
        cls, packet: Mapping[str, Any]
    ) -> Mapping[str, Any] | None:
        snapshot = packet.get("snapshot") or {}
        latest_incomplete = packet.get("latest_incomplete") or {}
        if str(packet.get("status") or "") != "stable":
            for candidate in (latest_incomplete, snapshot):
                if cls._snapshot_has_retryable_sync_issue(candidate):
                    return candidate
            return None
        if (
            cls._snapshot_has_retryable_sync_issue(latest_incomplete)
            and cls._snapshot_is_newer(latest_incomplete, snapshot)
        ):
            return latest_incomplete
        return None

    @classmethod
    def _packet_has_retryable_sync_issue(cls, packet: Mapping[str, Any]) -> bool:
        return cls._retryable_sync_snapshot(packet) is not None

    def _latest_snapshot_has_retryable_sync_issue(self, symbol: str) -> bool:
        try:
            packet = self.snapshot_service.get_symbol_snapshot(symbol)
        except Exception:
            return False
        return self._packet_has_retryable_sync_issue(packet)

    @staticmethod
    def _parse_date(value: Any) -> date | None:
        text = str(value or "").strip().replace("-", "")
        if len(text) != 8 or not text.isdigit():
            return None
        try:
            return datetime.strptime(text, "%Y%m%d").date()
        except ValueError:
            return None

    @staticmethod
    def _universe_warnings(
        universe_packet: dict[str, Any], *, pending_eligible: int
    ) -> list[str]:
        snapshot = universe_packet.get("snapshot") or {}
        coverage = snapshot.get("coverage") or {}
        warnings: list[str] = []
        if universe_packet.get("status") != "stable":
            warnings.append("全市场名单或市值覆盖尚未达到稳定发布门槛。")
        if coverage.get("missing_market_cap"):
            warnings.append(
                f"{coverage['missing_market_cap']} 只股票缺少当日总市值，按 data_incomplete 保存。"
            )
        as_of_date = str(snapshot.get("as_of_date") or "")
        history_insufficient = sum(
            LiZongStrategyService._history_precheck(
                item,
                as_of_date=as_of_date,
                parameters=LiZongParameters(),
            ).get("status")
            == "insufficient"
            for item in snapshot.get("items") or []
            if item.get("total_mv_yi") is not None
            and float(item.get("total_mv_yi") or 0)
            > LiZongParameters().market_cap_min_yi
        )
        if history_insufficient:
            warnings.append(
                f"{history_insufficient} 只市值达标股票上市后量价历史不足，"
                "已直接标记 data_incomplete，未发起逐股深度请求。"
            )
        if pending_eligible:
            warnings.append(
                f"仍有 {pending_eligible} 只可深度核验股票等待补齐多年ROE、股东与量价数据。"
            )
        return warnings

    def list_candidates(
        self,
        *,
        status: str | None = None,
        parameter_version: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        allowed = {
            "qualified",
            "triggered",
            "not_qualified",
            "data_incomplete",
            "invalidated",
        }
        if status is not None and status not in allowed:
            raise ValueError("unsupported candidate status")
        items = self.database.list_strategy_candidate_snapshots(
            strategy_id=STRATEGY_ID,
            strategy_version=STRATEGY_VERSION,
            parameter_version=parameter_version
            or LiZongParameters().parameter_version,
            status=status,
            limit=limit,
        )
        return [self._with_stock_basic(item) for item in items]

    def list_actionable_candidates(self, *, limit: int = 50) -> list[dict[str, Any]]:
        """Return only actual candidate-pool members, with triggers first."""

        size = max(1, min(int(limit), 200))
        triggered = self.list_candidates(status="triggered", limit=size)
        remaining = max(0, size - len(triggered))
        qualified = (
            self.list_candidates(status="qualified", limit=remaining)
            if remaining
            else []
        )
        return [*triggered, *qualified]

    def get_candidate(
        self,
        symbol: str,
        *,
        parameter_version: str | None = None,
    ) -> dict[str, Any] | None:
        canonical = self._canonical_symbols([symbol])[0]
        item = self.database.latest_strategy_candidate_snapshot(
            strategy_id=STRATEGY_ID,
            strategy_version=STRATEGY_VERSION,
            parameter_version=parameter_version
            or LiZongParameters().parameter_version,
            symbol=canonical,
        )
        if item is not None:
            item = self._with_stock_basic(item)
            item["trigger_events"] = self.get_triggers(
                symbol=canonical,
                parameter_version=parameter_version,
                limit=100,
            )
        return item

    def _with_stock_basic(self, item: dict[str, Any]) -> dict[str, Any]:
        enriched = dict(item)
        result = dict(enriched.get("result") or {})
        stock_basic = dict(result.get("stock_basic") or {})
        missing = [
            key for key in ("name", "industry", "market") if not stock_basic.get(key)
        ]
        if missing:
            try:
                packet = self.snapshot_service.get_symbol_snapshot(
                    str(enriched.get("symbol") or result.get("symbol") or "")
                )
                fallback = self._packet_stock_basic(packet)
            except Exception:
                fallback = {}
            for key in missing:
                if fallback.get(key):
                    stock_basic[key] = fallback[key]
        result["stock_basic"] = stock_basic
        enriched["result"] = result
        return enriched

    def get_triggers(
        self,
        *,
        symbol: str | None = None,
        parameter_version: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        canonical = self._canonical_symbols([symbol])[0] if symbol else None
        return self.database.list_strategy_trigger_events(
            strategy_id=STRATEGY_ID,
            strategy_version=STRATEGY_VERSION,
            parameter_version=parameter_version
            or LiZongParameters().parameter_version,
            symbol=canonical,
            limit=limit,
        )

    def _ensure_definition(self) -> None:
        self.database.upsert_strategy_definition(
            {
                "strategy_id": STRATEGY_ID,
                "name": "李总策略",
                "description": "A股确定性研究候选筛选与盘后进入关注条件监控。",
                "status": "active",
                "owner_type": "system",
                "current_version": STRATEGY_VERSION,
                "boundary": "不自动交易，不生成平台买卖指令。",
                "subscriptions_enabled": False,
            }
        )
        self.database.save_strategy_version(
            {
                "strategy_id": STRATEGY_ID,
                "version": STRATEGY_VERSION,
                "method": FORMULA_VERSION,
                "rules": RULE_DEFINITIONS,
                "formulas": FORMULAS,
                "change_notes": "冻结首版基本面、股性、量价和三类盘后触发口径。",
            }
        )
        self._save_parameter_version(LiZongParameters())

    def _save_parameter_version(self, params: LiZongParameters) -> None:
        expected = asdict(params)
        stored = self.database.save_strategy_parameter_version(
            {
                "strategy_id": STRATEGY_ID,
                "strategy_version": STRATEGY_VERSION,
                "parameter_version": params.parameter_version,
                "parameters": expected,
            }
        )
        if stored["parameters"] != expected:
            raise ValueError(
                "parameter_version 已存在且参数不同；请创建新的参数版本，不能覆盖历史口径"
            )

    def _build_input(
        self,
        symbol: str,
        packet: dict[str, Any],
        *,
        supplemental_roe_rows: Sequence[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        snapshot = packet.get("snapshot") or {}
        datasets = snapshot.get("datasets") or {}
        daily = self._dataset_frame(datasets, "daily")
        adj_factor = self._dataset_frame(datasets, "adj_factor")
        stk_limit = self._dataset_frame(datasets, "stk_limit")

        if not daily.empty and "trade_date" in daily:
            if not adj_factor.empty and {"trade_date", "adj_factor"} <= set(
                adj_factor.columns
            ):
                daily = daily.merge(
                    adj_factor[["trade_date", "adj_factor"]].drop_duplicates(
                        "trade_date", keep="last"
                    ),
                    on="trade_date",
                    how="left",
                )
            if not stk_limit.empty and "trade_date" in stk_limit:
                limit_columns = [
                    column
                    for column in ("trade_date", "up_limit", "down_limit")
                    if column in stk_limit
                ]
                daily = daily.merge(
                    stk_limit[limit_columns].drop_duplicates(
                        "trade_date", keep="last"
                    ),
                    on="trade_date",
                    how="left",
                )
            daily["source"] = self._combined_source(
                datasets, ("daily", "adj_factor", "stk_limit")
            )

        shareholders = pd.concat(
            [
                self._dataset_frame(datasets, "top10_holders"),
                self._dataset_frame(datasets, "top10_floatholders"),
            ],
            ignore_index=True,
        )
        if not shareholders.empty:
            shareholders["report_period"] = shareholders.get("end_date")
            classifications = shareholders.apply(
                self._classify_holder, axis=1, result_type="expand"
            )
            shareholders["holder_type"] = classifications[0]
            shareholders["classification_reason"] = classifications[1]
            shareholders["source"] = self._combined_source(
                datasets, ("top10_holders", "top10_floatholders")
            )

        roe = self._dataset_frame(datasets, "fina_indicator")
        if not roe.empty:
            roe["source"] = self._dataset_source(datasets, "fina_indicator")
        if supplemental_roe_rows:
            roe = pd.concat(
                [roe, pd.DataFrame(list(supplemental_roe_rows))],
                ignore_index=True,
            )
        daily_basic = self._dataset_frame(datasets, "daily_basic")
        if not daily_basic.empty:
            daily_basic["source"] = self._dataset_source(datasets, "daily_basic")

        return {
            "symbol": symbol,
            "as_of_date": snapshot.get("as_of_date") or self._today(),
            "daily": daily,
            "roe_history": roe,
            "shareholders": shareholders,
            "daily_basic": daily_basic,
        }

    def _supplemental_roe_rows(
        self,
        symbol: str,
        packet: dict[str, Any],
        parameters: LiZongParameters,
    ) -> tuple[list[dict[str, Any]], bool]:
        if self.fundamentals_provider is None:
            return [], False
        snapshot = packet.get("snapshot") or {}
        datasets = snapshot.get("datasets") or {}
        direct = self._dataset_frame(datasets, "fina_indicator")
        missing_periods = self._missing_roe_periods(
            direct,
            as_of_date=str(snapshot.get("as_of_date") or self._today()),
            required_years=parameters.required_annual_roe_years,
        )
        if not missing_periods:
            return [], False
        try:
            payload = self.fundamentals_provider.fetch_financial_periods(
                symbol, limit=20
            )
        except Exception:
            return [], True
        rows: list[dict[str, Any]] = []
        as_of = self._parse_date(snapshot.get("as_of_date"))
        for period in payload.get("periods") or []:
            report_date = self._parse_date(period.get("report_date"))
            notice_date = self._parse_date(period.get("notice_date"))
            roe = pd.to_numeric(period.get("roe_weighted_pct"), errors="coerce")
            if (
                report_date is None
                or report_date.isoformat() not in missing_periods
                or notice_date is None
                or (as_of is not None and notice_date > as_of)
                or pd.isna(roe)
            ):
                continue
            rows.append(
                {
                    "ts_code": symbol,
                    "ann_date": notice_date.isoformat(),
                    "end_date": report_date.isoformat(),
                    "roe": float(roe),
                    "roe_waa": float(roe),
                    "source": period.get("source")
                    or payload.get("source")
                    or "Eastmoney F10 Main Financial Data",
                    "source_url": period.get("source_url"),
                    "fallback_reason": "Tushare fina_indicator 缺少该年度ROE",
                }
            )
        rows.sort(key=lambda item: str(item.get("end_date") or ""), reverse=True)
        return rows, True

    @classmethod
    def _missing_roe_periods(
        cls,
        frame: pd.DataFrame,
        *,
        as_of_date: str,
        required_years: int,
    ) -> set[str]:
        if frame.empty or required_years <= 0:
            return set()
        period_column = next(
            (column for column in ("end_date", "report_period") if column in frame),
            None,
        )
        announcement_column = next(
            (column for column in ("ann_date", "announcement_date") if column in frame),
            None,
        )
        roe_column = next(
            (column for column in ("roe", "roe_pct") if column in frame), None
        )
        if not period_column or not announcement_column or not roe_column:
            return set()
        as_of = cls._parse_date(as_of_date)
        annual: dict[str, float] = {}
        annual_years: set[int] = set()
        for _, row in frame.iterrows():
            period = cls._parse_date(row.get(period_column))
            announced = cls._parse_date(row.get(announcement_column))
            if (
                period is None
                or (period.month, period.day) != (12, 31)
                or announced is None
                or (as_of is not None and announced > as_of)
            ):
                continue
            annual_years.add(period.year)
            number = pd.to_numeric(row.get(roe_column), errors="coerce")
            if pd.notna(number):
                annual[period.isoformat()] = float(number)
        if not annual_years:
            return set()
        latest_year = max(annual_years)
        required = {
            f"{year}-12-31"
            for year in range(latest_year, latest_year - required_years, -1)
        }
        return required - set(annual)

    @staticmethod
    def _roe_rule_incomplete(result: Mapping[str, Any]) -> bool:
        return any(
            rule.get("rule_id") == "LZ-F-02"
            and rule.get("status") == "data_incomplete"
            for rule in result.get("rule_results") or []
        )

    def _enforce_incomplete_boundary(
        self, evaluation: dict[str, Any], packet: dict[str, Any]
    ) -> dict[str, Any]:
        candidate_rules = [
            rule
            for rule in evaluation.get("rule_results") or []
            if rule.get("rule_id") in CANDIDATE_RULE_IDS
        ]
        missing_rule_data = any(
            rule.get("status") == "data_incomplete" for rule in candidate_rules
        )
        snapshot = packet.get("snapshot") or {}
        snapshot_incomplete = (
            packet.get("status") != "stable"
            or snapshot.get("data_status") != "stable"
            or bool((snapshot.get("coverage") or {}).get("missing"))
        )
        if missing_rule_data or snapshot_incomplete:
            return self._force_incomplete(
                evaluation,
                "关键数据集或规则窗口不完整，当前暂不能形成完整判断。",
            )
        return evaluation

    @staticmethod
    def _force_incomplete(
        evaluation: dict[str, Any], limitation: str
    ) -> dict[str, Any]:
        result = dict(evaluation)
        result["status"] = "data_incomplete"
        result["candidate_qualified"] = False
        result["triggered_rule_ids"] = []
        limitations = []
        rewrote_conflicting_status = False
        for value in result.get("limitations") or []:
            text = str(value)
            if "当前状态按 not_qualified 处理" in text:
                text = (
                    "已存在明确不通过规则，同时仍有数据缺口；"
                    "在关键缺口补齐前按数据不完整处理。"
                )
                rewrote_conflicting_status = True
            limitations.append(text)
        if not (
            rewrote_conflicting_status
            and limitation.startswith("关键数据集或规则窗口不完整")
        ):
            limitations.append(limitation)
        result["limitations"] = list(dict.fromkeys(limitations))
        return result

    @staticmethod
    def _stored_status(
        evaluation_status: str, previous: dict[str, Any] | None
    ) -> str:
        previous_status = previous.get("status") if previous else None
        if evaluation_status == "not_qualified" and previous_status in {
            "qualified",
            "triggered",
            "invalidated",
        }:
            return "invalidated"
        return evaluation_status

    def _save_trigger_events(
        self, candidate: dict[str, Any], evaluation: dict[str, Any]
    ) -> list[str]:
        if candidate["status"] != "triggered":
            return []
        rules = {
            rule["rule_id"]: rule for rule in evaluation.get("rule_results") or []
        }
        created_ids: list[str] = []
        for rule_id in evaluation.get("triggered_rule_ids") or []:
            rule = rules.get(rule_id)
            if not rule or not rule.get("evidence_date"):
                continue
            event, created = self.database.save_strategy_trigger_event(
                {
                    "candidate_snapshot_id": candidate["id"],
                    "strategy_id": STRATEGY_ID,
                    "strategy_version": STRATEGY_VERSION,
                    "parameter_version": candidate["parameter_version"],
                    "data_version": candidate["data_version"],
                    "symbol": candidate["symbol"],
                    "rule_id": rule_id,
                    "evidence_date": rule["evidence_date"],
                    "evidence": {
                        "actual_value": rule.get("actual_value"),
                        "threshold": rule.get("threshold"),
                        "source": rule.get("source"),
                        "formula_version": rule.get("formula_version"),
                    },
                }
            )
            if created:
                created_ids.append(str(event["id"]))
        return created_ids

    @staticmethod
    def _dataset_frame(
        datasets: Mapping[str, Any], dataset: str
    ) -> pd.DataFrame:
        packet = datasets.get(dataset) or {}
        return pd.DataFrame(packet.get("rows") or [])

    @staticmethod
    def _dataset_source(datasets: Mapping[str, Any], dataset: str) -> str:
        packet = datasets.get(dataset) or {}
        source = str(packet.get("source") or "published snapshot")
        return f"{source}:{dataset}"

    @classmethod
    def _combined_source(
        cls, datasets: Mapping[str, Any], names: Sequence[str]
    ) -> str:
        return "+".join(cls._dataset_source(datasets, name) for name in names)

    @staticmethod
    def _classify_holder(row: pd.Series) -> tuple[str, str]:
        explicit = str(row.get("holder_type") or row.get("classification") or "").lower()
        if explicit in {"institution", "company", "fund", "bank", "insurance"}:
            return "institution", f"快照显式类型：{explicit}"
        if explicit in {"natural_person", "individual", "person"}:
            return "natural_person", f"快照显式类型：{explicit}"
        name = str(row.get("holder_name") or "").strip()
        marker = next((value for value in INSTITUTION_MARKERS if value in name), None)
        if marker:
            return "institution", f"名称包含明确机构标识“{marker}”"
        return "unknown", "快照未提供可靠类型，名称也无明确机构标识"

    @staticmethod
    def _packet_data_version(symbol: str, packet: dict[str, Any]) -> str:
        value = packet.get("data_version")
        if value:
            return str(value)
        return "unavailable-" + LiZongStrategyService._fingerprint(
            {"symbol": symbol, "status": packet.get("status")}
        )[:24]

    @classmethod
    def _packet_as_of(cls, packet: dict[str, Any]) -> str | None:
        snapshot = cls._retryable_sync_snapshot(packet) or packet.get("snapshot") or {}
        value = snapshot.get("as_of_date")
        return str(value) if value else None

    @classmethod
    def _packet_stock_basic(cls, packet: dict[str, Any]) -> dict[str, str | None]:
        snapshot = packet.get("snapshot") or {}
        datasets = snapshot.get("datasets") or {}
        frame = cls._dataset_frame(datasets, "stock_basic")
        if frame.empty:
            return {
                "name": None,
                "industry": None,
                "market": None,
                "list_date": None,
            }
        row = frame.iloc[0]

        def clean(column: str) -> str | None:
            value = row.get(column)
            if value is None or pd.isna(value):
                return None
            text = str(value).strip()
            return text or None

        list_date = cls._parse_date(row.get("list_date"))
        return {
            "name": clean("name"),
            "industry": clean("industry"),
            "market": clean("market"),
            "list_date": list_date.isoformat() if list_date else None,
        }

    @staticmethod
    def _fingerprint(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode(
                "utf-8"
            )
        ).hexdigest()

    @staticmethod
    def _today() -> str:
        return datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()

    @classmethod
    def _empty_input(cls, symbol: str, as_of_date: str | None) -> dict[str, Any]:
        return {
            "symbol": symbol,
            "as_of_date": as_of_date or cls._today(),
            "daily": pd.DataFrame(),
            "roe_history": pd.DataFrame(),
            "shareholders": pd.DataFrame(),
            "daily_basic": pd.DataFrame(),
        }

    @staticmethod
    def _canonical_symbols(symbols: Sequence[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for raw in symbols:
            canonical = normalize_symbol(str(raw))
            if not re.fullmatch(r"\d{6}\.(?:SZ|SS|BJ)", canonical):
                raise ValueError("李总策略首版仅支持A股股票")
            if canonical not in seen:
                seen.add(canonical)
                result.append(canonical)
        if not result:
            raise ValueError("至少提供一只A股股票")
        return result


__all__ = ["LiZongStrategyService"]
