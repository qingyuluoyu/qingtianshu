from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import hashlib
import json
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
    """Run and persist Li Zong v1 against published Tushare snapshots only."""

    SUBSCRIPTION_BOUNDARY = (
        "用户策略订阅、通知偏好和提醒渠道暂未在本服务持久化；"
        "当前只发布公共候选与触发事实，后续由独立用户订阅层关联。"
    )

    def __init__(self, database: Database, snapshot_service: Any):
        self.database = database
        self.snapshot_service = snapshot_service
        self._ensure_definition()

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

        data_versions = {
            symbol: self._packet_data_version(symbol, packet)
            for symbol, packet in packets.items()
        }
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
            try:
                evaluation = deterministic_li_zong_v1(
                    self._build_input(symbol, packet), parameters=params
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

    def _build_input(self, symbol: str, packet: dict[str, Any]) -> dict[str, Any]:
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
                "关键数据集或规则窗口不完整，服务层强制保持 data_incomplete。",
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
        result["limitations"] = [*(result.get("limitations") or []), limitation]
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

    @staticmethod
    def _packet_as_of(packet: dict[str, Any]) -> str | None:
        snapshot = packet.get("snapshot") or {}
        value = snapshot.get("as_of_date")
        return str(value) if value else None

    @classmethod
    def _packet_stock_basic(cls, packet: dict[str, Any]) -> dict[str, str | None]:
        snapshot = packet.get("snapshot") or {}
        datasets = snapshot.get("datasets") or {}
        frame = cls._dataset_frame(datasets, "stock_basic")
        if frame.empty:
            return {"name": None, "industry": None, "market": None}
        row = frame.iloc[0]

        def clean(column: str) -> str | None:
            value = row.get(column)
            if value is None or pd.isna(value):
                return None
            text = str(value).strip()
            return text or None

        return {
            "name": clean("name"),
            "industry": clean("industry"),
            "market": clean("market"),
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
            if not re.fullmatch(r"\d{6}\.(?:SZ|SS)", canonical):
                raise ValueError("李总策略首版仅支持A股股票")
            if canonical not in seen:
                seen.add(canonical)
                result.append(canonical)
        if not result:
            raise ValueError("至少提供一只A股股票")
        return result


__all__ = ["LiZongStrategyService"]
