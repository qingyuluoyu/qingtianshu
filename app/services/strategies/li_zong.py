from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import date, datetime
import math
import re
from typing import Any, Mapping, Sequence

import pandas as pd

from app.services.strategies.base import StrategyEvaluation, StrategyRuleResult


STRATEGY_ID = "li_zong"
STRATEGY_VERSION = "li_zong_v1"
FORMULA_VERSION = "deterministic_li_zong_v1"

CANDIDATE_RULE_IDS = (
    "LZ-F-01",
    "LZ-F-02",
    "LZ-F-04",
    "LZ-C-01",
    "LZ-C-02",
    "LZ-C-03",
    "LZ-C-04",
    "LZ-VP-01",
    "LZ-VP-02",
)
TRIGGER_RULE_IDS = ("LZ-T-01", "LZ-T-02", "LZ-T-03")


@dataclass(frozen=True)
class LiZongParameters:
    parameter_version: str = "li_zong_v1_default"
    market_cap_min_yi: float = 150.0
    roe_min_pct: float = 10.0
    required_annual_roe_years: int = 5
    institution_holder_min_count: int = 5
    character_window_days: int = 240
    annual_limit_up_min_count: int = 6
    recent_window_days: int = 10
    adjusted_high_window_days: int = 360
    new_high_recent_days: int = 20
    volume_baseline_days: int = 20
    volume_sequence_days: int = 3
    volume_multiple: float = 2.0
    gap_open_min_pct: float = 3.5
    amplitude_min_pct: float = 9.8

    @classmethod
    def from_value(
        cls, value: Mapping[str, Any] | LiZongParameters | None
    ) -> LiZongParameters:
        if value is None:
            return cls()
        if isinstance(value, cls):
            return value
        valid = {item.name for item in fields(cls)}
        unknown = sorted(set(value) - valid)
        if unknown:
            raise ValueError(f"unsupported Li Zong parameters: {', '.join(unknown)}")
        return cls(**dict(value))


@dataclass(frozen=True)
class LiZongInput:
    symbol: str
    as_of_date: str | date | datetime
    daily: pd.DataFrame | Sequence[Mapping[str, Any]]
    roe_history: pd.DataFrame | Sequence[Mapping[str, Any]]
    shareholders: pd.DataFrame | Sequence[Mapping[str, Any]]
    daily_basic: pd.DataFrame | Sequence[Mapping[str, Any]] | Mapping[str, Any]

    @classmethod
    def from_value(cls, value: Mapping[str, Any] | LiZongInput) -> LiZongInput:
        if isinstance(value, cls):
            return value
        required = {"symbol", "as_of_date", "daily", "roe_history", "shareholders"}
        missing = sorted(required - set(value))
        if missing:
            raise ValueError(f"missing Li Zong input fields: {', '.join(missing)}")
        daily_basic = value.get("daily_basic", value.get("market_cap", {}))
        return cls(
            symbol=str(value["symbol"]),
            as_of_date=value["as_of_date"],
            daily=value["daily"],
            roe_history=value["roe_history"],
            shareholders=value["shareholders"],
            daily_basic=daily_basic,
        )


class LiZongStrategy:
    strategy_id = STRATEGY_ID
    strategy_version = STRATEGY_VERSION
    method = FORMULA_VERSION

    def evaluate(
        self,
        data: Mapping[str, Any] | LiZongInput,
        *,
        parameters: Mapping[str, Any] | LiZongParameters | None = None,
    ) -> dict[str, Any]:
        return deterministic_li_zong_v1(data, parameters=parameters)


def deterministic_li_zong_v1(
    data: Mapping[str, Any] | LiZongInput,
    *,
    parameters: Mapping[str, Any] | LiZongParameters | None = None,
) -> dict[str, Any]:
    """Evaluate Li Zong v1 using only supplied, as-of structured data."""

    packet = LiZongInput.from_value(data)
    params = LiZongParameters.from_value(parameters)
    as_of = _normalize_date(packet.as_of_date)
    daily = _prepare_daily(packet.daily, as_of)

    rules = [
        _market_cap_rule(packet.daily_basic, as_of, params),
        _roe_rule(packet.roe_history, as_of, params),
        _shareholder_rule(packet.shareholders, as_of, params),
        _annual_limit_count_rule(daily, as_of, params),
        _consecutive_limit_rule(daily, as_of, params),
        _recent_limit_rule(daily, as_of, params),
        _recent_bearish_drop_rule(daily, as_of, params),
        _adjusted_new_high_rule(daily, as_of, params),
        _volume_expansion_rule(daily, as_of, params),
        _today_limit_trigger(daily, as_of),
        _gap_open_trigger(daily, as_of, params),
        _amplitude_trigger(daily, as_of, params),
    ]

    by_id = {rule.rule_id: rule for rule in rules}
    candidate_rules = [by_id[rule_id] for rule_id in CANDIDATE_RULE_IDS]
    has_failed = any(rule.status == "failed" for rule in candidate_rules)
    has_incomplete = any(rule.status == "data_incomplete" for rule in candidate_rules)
    candidate_qualified = not has_failed and not has_incomplete
    trigger_rules = [by_id[rule_id] for rule_id in TRIGGER_RULE_IDS]
    triggered_rule_ids = tuple(
        rule_id
        for rule_id in TRIGGER_RULE_IDS
        if by_id[rule_id].status == "passed"
    )
    trigger_data_incomplete = (
        candidate_qualified
        and not triggered_rule_ids
        and any(rule.status == "data_incomplete" for rule in trigger_rules)
    )

    if has_failed:
        status = "not_qualified"
    elif has_incomplete:
        status = "data_incomplete"
    elif triggered_rule_ids:
        status = "triggered"
    elif trigger_data_incomplete:
        status = "data_incomplete"
    else:
        status = "qualified"

    limitations: list[str] = []
    if has_failed and has_incomplete:
        limitations.append("已存在明确不通过规则，同时仍有数据缺口；当前状态按 not_qualified 处理。")
    if not candidate_qualified and triggered_rule_ids:
        limitations.append("当日触发形态仅作证据展示；候选池未通过，因此不会进入触发池。")
    if trigger_data_incomplete:
        limitations.append("候选池规则已通过，但当日触发条件数据不完整，不能判定为 qualified。")

    return StrategyEvaluation(
        strategy_id=STRATEGY_ID,
        strategy_version=STRATEGY_VERSION,
        parameter_version=params.parameter_version,
        method=FORMULA_VERSION,
        symbol=packet.symbol,
        as_of_date=as_of,
        status=status,
        candidate_qualified=candidate_qualified,
        triggered_rule_ids=triggered_rule_ids if candidate_qualified else (),
        rule_results=tuple(rules),
        limitations=tuple(limitations),
    ).to_dict()


def _market_cap_rule(
    value: Any, as_of: str, params: LiZongParameters
) -> StrategyRuleResult:
    frame = _as_frame(value)
    if frame.empty and isinstance(value, Mapping):
        frame = pd.DataFrame([dict(value)])
    row = _latest_row_as_of(frame, as_of, ("trade_date", "evidence_date"))
    source = _source(row, "input.daily_basic")
    evidence_date = _row_date(row, ("trade_date", "evidence_date")) or as_of
    market_cap_yi: float | None = None
    if row is not None:
        market_cap_yi = _number(row.get("total_mv_yi"))
        if market_cap_yi is None:
            total_mv_wan = _number(row.get("total_mv"))
            if total_mv_wan is not None:
                market_cap_yi = total_mv_wan / 10_000.0
    if market_cap_yi is None:
        return _rule(
            "LZ-F-01",
            "data_incomplete",
            None,
            {"operator": ">", "market_cap_yi": params.market_cap_min_yi},
            source,
            evidence_date=evidence_date,
            limitations=("缺少最近完整交易日总市值。",),
        )
    return _rule(
        "LZ-F-01",
        "passed" if market_cap_yi > params.market_cap_min_yi else "failed",
        {"market_cap_yi": market_cap_yi},
        {"operator": ">", "market_cap_yi": params.market_cap_min_yi},
        source,
        evidence_date=evidence_date,
    )


def _roe_rule(
    value: Any, as_of: str, params: LiZongParameters
) -> StrategyRuleResult:
    frame = _as_frame(value)
    source = _frame_source(frame, "input.fina_indicator")
    threshold = {
        "operator": ">= every_year",
        "roe_pct": params.roe_min_pct,
        "required_full_years": params.required_annual_roe_years,
    }
    if frame.empty:
        return _rule(
            "LZ-F-02",
            "data_incomplete",
            [],
            threshold,
            source,
            report_period=None,
            limitations=("缺少年度 ROE 数据。",),
        )
    period_col = _first_column(frame, ("report_period", "end_date"))
    ann_col = _first_column(frame, ("ann_date", "announcement_date"))
    roe_col = _first_column(frame, ("roe", "roe_pct"))
    if period_col is None or ann_col is None or roe_col is None:
        return _rule(
            "LZ-F-02",
            "data_incomplete",
            [],
            threshold,
            source,
            report_period=None,
            limitations=("年度 ROE 必须同时包含报告期、公告日和 ROE。",),
        )

    working = frame.copy()
    working["_period"] = working[period_col].map(_normalize_date_or_none)
    working["_ann"] = working[ann_col].map(_normalize_date_or_none)
    working["_roe"] = working[roe_col].map(_number)
    working = working[
        working["_period"].str.endswith("-12-31", na=False)
        & working["_ann"].notna()
        & (working["_ann"] <= as_of)
    ]
    if working.empty:
        return _rule(
            "LZ-F-02",
            "data_incomplete",
            [],
            threshold,
            source,
            report_period=None,
            limitations=("as_of_date 当时没有已公告的完整年度 ROE。",),
        )
    working = working.sort_values(["_period", "_ann"]).drop_duplicates(
        "_period", keep="last"
    )
    latest_year = int(str(working["_period"].max())[:4])
    required_periods = [
        f"{year}-12-31"
        for year in range(
            latest_year,
            latest_year - params.required_annual_roe_years,
            -1,
        )
    ]
    selected = working.set_index("_period").reindex(required_periods)
    actual = [
        {
            "report_period": report_period,
            "roe_pct": _json_number(row.get("_roe")),
            "announcement_date": row.get("_ann") if pd.notna(row.get("_ann")) else None,
        }
        for report_period, row in selected.iterrows()
    ]
    missing_periods = [
        item["report_period"] for item in actual if item["roe_pct"] is None
    ]
    latest_period = required_periods[0] if required_periods else None
    if missing_periods:
        return _rule(
            "LZ-F-02",
            "data_incomplete",
            actual,
            threshold,
            source,
            report_period=latest_period,
            limitations=(f"缺少连续年度 ROE：{', '.join(missing_periods)}。",),
        )
    passed = all(float(item["roe_pct"]) >= params.roe_min_pct for item in actual)
    return _rule(
        "LZ-F-02",
        "passed" if passed else "failed",
        actual,
        threshold,
        source,
        report_period=latest_period,
    )


def _shareholder_rule(
    value: Any, as_of: str, params: LiZongParameters
) -> StrategyRuleResult:
    frame = _as_frame(value)
    source = _frame_source(frame, "input.top10_holders+top10_floatholders")
    threshold = {
        "operator": ">=",
        "non_natural_holder_count": params.institution_holder_min_count,
    }
    if frame.empty:
        return _rule(
            "LZ-F-04",
            "data_incomplete",
            None,
            threshold,
            source,
            report_period=None,
            limitations=("缺少最新十大股东和十大流通股东结构。",),
        )
    period_col = _first_column(frame, ("report_period", "end_date"))
    name_col = _first_column(frame, ("holder_name", "holder", "name"))
    if period_col is None or name_col is None:
        return _rule(
            "LZ-F-04",
            "data_incomplete",
            None,
            threshold,
            source,
            report_period=None,
            limitations=("股东数据缺少报告期或股东名称。",),
        )
    working = frame.copy()
    working["_period"] = working[period_col].map(_normalize_date_or_none)
    ann_col = _first_column(working, ("ann_date", "announcement_date"))
    if ann_col is not None:
        working["_ann"] = working[ann_col].map(_normalize_date_or_none)
        working = working[working["_ann"].notna() & (working["_ann"] <= as_of)]
    working = working[working["_period"].notna()]
    if working.empty:
        return _rule(
            "LZ-F-04",
            "data_incomplete",
            None,
            threshold,
            source,
            report_period=None,
            limitations=("as_of_date 当时没有已披露的股东结构。",),
        )
    latest_period = str(working["_period"].max())
    working = working[working["_period"] == latest_period]

    classified: dict[str, dict[str, Any]] = {}
    for _, row in working.iterrows():
        raw_name = str(row.get(name_col) or "").strip()
        if not raw_name:
            continue
        normalized = _normalize_holder_name(raw_name)
        classification, reason = _holder_classification(row)
        existing = classified.get(normalized)
        rank = {"unknown": 0, "natural_person": 1, "institution": 2}
        if existing is None or rank[classification] > rank[existing["classification"]]:
            classified[normalized] = {
                "normalized_name": normalized,
                "raw_names": [raw_name],
                "classification": classification,
                "classification_reason": reason,
            }
        elif raw_name not in existing["raw_names"]:
            existing["raw_names"].append(raw_name)

    institutions = [
        item for item in classified.values() if item["classification"] == "institution"
    ]
    unknown = [
        item for item in classified.values() if item["classification"] == "unknown"
    ]
    actual = {
        "non_natural_holder_count": len(institutions),
        "unknown_holder_count": len(unknown),
        "holders": sorted(classified.values(), key=lambda item: item["normalized_name"]),
    }
    limitations = (
        (f"{len(unknown)} 名股东无法可靠分类，未计入非自然人数量。",)
        if unknown
        else ()
    )
    return _rule(
        "LZ-F-04",
        "passed"
        if len(institutions) >= params.institution_holder_min_count
        else "failed",
        actual,
        threshold,
        source,
        report_period=latest_period,
        limitations=limitations,
    )


def _annual_limit_count_rule(
    daily: pd.DataFrame, as_of: str, params: LiZongParameters
) -> StrategyRuleResult:
    tradable = daily[~daily["_suspended"]].tail(params.character_window_days)
    threshold = {
        "operator": ">=",
        "limit_up_count": params.annual_limit_up_min_count,
        "window_trading_days": params.character_window_days,
    }
    if len(tradable) < params.character_window_days:
        return _daily_incomplete(
            "LZ-C-01", threshold, daily, as_of, "最近一年完整交易日不足。"
        )
    if tradable["_limit_known"].eq(False).any():
        return _daily_incomplete(
            "LZ-C-01", threshold, tradable, as_of, "涨跌停价覆盖不完整。"
        )
    dates = tradable.loc[tradable["_limit_up"], "_date"].tolist()
    return _rule(
        "LZ-C-01",
        "passed" if len(dates) >= params.annual_limit_up_min_count else "failed",
        {
            "limit_up_count": len(dates),
            "limit_up_dates": dates,
            "window_start": str(tradable.iloc[0]["_date"]),
            "window_end": str(tradable.iloc[-1]["_date"]),
        },
        threshold,
        _frame_source(tradable, "input.daily+stk_limit"),
        evidence_date=str(tradable.iloc[-1]["_date"]),
    )


def _consecutive_limit_rule(
    daily: pd.DataFrame, as_of: str, params: LiZongParameters
) -> StrategyRuleResult:
    tradable = daily[~daily["_suspended"]].tail(params.character_window_days)
    threshold = {
        "operator": ">=",
        "consecutive_limit_up_trading_days": 2,
        "window_days": params.character_window_days,
    }
    if len(tradable) < params.character_window_days:
        return _daily_incomplete(
            "LZ-C-02", threshold, daily, as_of, "最近一年完整交易日不足。"
        )
    calendar_window = daily[daily["_date"] >= str(tradable.iloc[0]["_date"])]
    if calendar_window.loc[~calendar_window["_suspended"], "_limit_known"].eq(False).any():
        return _daily_incomplete(
            "LZ-C-02", threshold, calendar_window, as_of, "涨跌停价覆盖不完整。"
        )
    sequences: list[list[str]] = []
    current: list[str] = []
    for _, row in calendar_window.iterrows():
        if not row["_suspended"] and row["_limit_up"]:
            current.append(str(row["_date"]))
        else:
            if len(current) >= 2:
                sequences.append(current)
            current = []
    if len(current) >= 2:
        sequences.append(current)
    return _rule(
        "LZ-C-02",
        "passed" if sequences else "failed",
        {"sequences": sequences},
        threshold,
        _frame_source(calendar_window, "input.daily+stk_limit"),
        evidence_date=str(calendar_window.iloc[-1]["_date"]),
    )


def _recent_limit_rule(
    daily: pd.DataFrame, as_of: str, params: LiZongParameters
) -> StrategyRuleResult:
    recent = daily[~daily["_suspended"]].tail(params.recent_window_days)
    threshold = {
        "operator": ">=",
        "limit_up_count": 1,
        "window_trading_days": params.recent_window_days,
    }
    if len(recent) < params.recent_window_days:
        return _daily_incomplete(
            "LZ-C-03", threshold, daily, as_of, "最近十个完整交易日不足。"
        )
    if recent["_limit_known"].eq(False).any():
        return _daily_incomplete(
            "LZ-C-03", threshold, recent, as_of, "涨跌停价覆盖不完整。"
        )
    dates = recent.loc[recent["_limit_up"], "_date"].tolist()
    return _rule(
        "LZ-C-03",
        "passed" if dates else "failed",
        {"limit_up_count": len(dates), "limit_up_dates": dates},
        threshold,
        _frame_source(recent, "input.daily+stk_limit"),
        evidence_date=str(recent.iloc[-1]["_date"]),
    )


def _recent_bearish_drop_rule(
    daily: pd.DataFrame, as_of: str, params: LiZongParameters
) -> StrategyRuleResult:
    recent = daily[~daily["_suspended"]].tail(params.recent_window_days)
    threshold = {
        "operator": "no_match",
        "definition": "close < open AND pct_chg <= -5.0",
        "window_trading_days": params.recent_window_days,
    }
    if len(recent) < params.recent_window_days:
        return _daily_incomplete(
            "LZ-C-04", threshold, daily, as_of, "最近十个完整交易日不足。"
        )
    if _missing_numeric(recent, ("open", "close", "pct_chg")):
        return _daily_incomplete(
            "LZ-C-04", threshold, recent, as_of, "开收盘价或涨跌幅缺失。"
        )
    mask = (recent["close"] < recent["open"]) & (recent["pct_chg"] <= -5.0)
    rows = [
        {
            "trade_date": str(row["_date"]),
            "open": float(row["open"]),
            "close": float(row["close"]),
            "pct_chg": float(row["pct_chg"]),
        }
        for _, row in recent[mask].iterrows()
    ]
    return _rule(
        "LZ-C-04",
        "failed" if rows else "passed",
        {"bearish_drop_count": len(rows), "bearish_drop_days": rows},
        threshold,
        _frame_source(recent, "input.daily"),
        evidence_date=str(recent.iloc[-1]["_date"]),
    )


def _adjusted_new_high_rule(
    daily: pd.DataFrame, as_of: str, params: LiZongParameters
) -> StrategyRuleResult:
    required = params.adjusted_high_window_days + params.new_high_recent_days - 1
    threshold = {
        "operator": ">= prior rolling maximum",
        "adjusted_high_window_days": params.adjusted_high_window_days,
        "recent_candidate_days": params.new_high_recent_days,
    }
    tradable = daily[~daily["_suspended"]]
    if len(tradable) < required:
        return _daily_incomplete(
            "LZ-VP-01",
            threshold,
            tradable,
            as_of,
            f"复权新高需要至少 {required} 个完整交易日。",
        )
    window = tradable.tail(required).copy()
    if window["_adjusted_high"].isna().any():
        return _daily_incomplete(
            "LZ-VP-01", threshold, window, as_of, "缺少统一复权口径的最高价。"
        )
    rolling = window["_adjusted_high"].rolling(
        params.adjusted_high_window_days,
        min_periods=params.adjusted_high_window_days,
    ).max()
    candidate = window.tail(params.new_high_recent_days).copy()
    candidate["_rolling_high"] = rolling.tail(params.new_high_recent_days).values
    hit = candidate[
        candidate["_adjusted_high"] >= candidate["_rolling_high"] - 1e-12
    ]
    actual = {
        "new_high_dates": hit["_date"].astype(str).tolist(),
        "window_start": str(window.iloc[0]["_date"]),
        "window_end": str(window.iloc[-1]["_date"]),
        "calculation": "adjusted_high if supplied, otherwise high * adj_factor",
    }
    return _rule(
        "LZ-VP-01",
        "passed" if not hit.empty else "failed",
        actual,
        threshold,
        _frame_source(window, "input.daily+adj_factor"),
        evidence_date=str(window.iloc[-1]["_date"]),
    )


def _volume_expansion_rule(
    daily: pd.DataFrame, as_of: str, params: LiZongParameters
) -> StrategyRuleResult:
    search_days = params.adjusted_high_window_days
    required = search_days + params.volume_baseline_days
    threshold = {
        "operator": ">= each_day",
        "volume_multiple": params.volume_multiple,
        "sequence_days": params.volume_sequence_days,
        "baseline_days": params.volume_baseline_days,
        "search_days": search_days,
    }
    tradable = daily[~daily["_suspended"]]
    if len(tradable) < required:
        return _daily_incomplete(
            "LZ-VP-02",
            threshold,
            tradable,
            as_of,
            f"三日放量判断需要至少 {required} 个完整交易日。",
        )
    window = tradable.tail(required).copy()
    calendar_window = daily[daily["_date"] >= str(window.iloc[0]["_date"])]
    if calendar_window["_suspended"].any():
        return _daily_incomplete(
            "LZ-VP-02",
            threshold,
            calendar_window,
            as_of,
            "放量回看窗口包含停牌日，不能可靠判定连续三日放量。",
        )
    if _missing_numeric(window, ("volume",)) or (window["volume"] <= 0).any():
        return _daily_incomplete(
            "LZ-VP-02", threshold, window, as_of, "成交量缺失、为零或包含停牌。"
        )
    hits: list[dict[str, Any]] = []
    first_start = params.volume_baseline_days
    last_start = len(window) - params.volume_sequence_days
    for start in range(first_start, last_start + 1):
        baseline = window.iloc[start - params.volume_baseline_days : start]["volume"]
        sequence = window.iloc[start : start + params.volume_sequence_days]
        baseline_volume = float(baseline.mean())
        if baseline_volume <= 0:
            continue
        multiples = [float(value) / baseline_volume for value in sequence["volume"]]
        if all(value + 1e-12 >= params.volume_multiple for value in multiples):
            hits.append(
                {
                    "start_date": str(sequence.iloc[0]["_date"]),
                    "end_date": str(sequence.iloc[-1]["_date"]),
                    "baseline_volume": baseline_volume,
                    "volumes": [float(value) for value in sequence["volume"]],
                    "multiples": multiples,
                }
            )
    return _rule(
        "LZ-VP-02",
        "passed" if hits else "failed",
        {"sequences": hits},
        threshold,
        _frame_source(window, "input.daily"),
        evidence_date=str(window.iloc[-1]["_date"]),
    )


def _today_limit_trigger(daily: pd.DataFrame, as_of: str) -> StrategyRuleResult:
    row = _latest_daily_row(daily)
    threshold = {"operator": "close == up_limit", "requires_real_up_limit": True}
    if row is None:
        return _daily_incomplete("LZ-T-01", threshold, daily, as_of, "缺少当日行情。")
    if not bool(row["_limit_known"]):
        return _daily_incomplete(
            "LZ-T-01", threshold, daily.tail(1), as_of, "当日真实涨停价缺失。"
        )
    actual = {
        "close": _json_number(row.get("close")),
        "up_limit": _json_number(row.get("up_limit")),
        "has_price_limit": bool(row["_has_price_limit"]),
    }
    return _rule(
        "LZ-T-01",
        "passed" if bool(row["_limit_up"]) else "failed",
        actual,
        threshold,
        _source(row, "input.daily+stk_limit"),
        evidence_date=str(row["_date"]),
    )


def _gap_open_trigger(
    daily: pd.DataFrame, as_of: str, params: LiZongParameters
) -> StrategyRuleResult:
    row = _latest_daily_row(daily)
    threshold = {
        "gap_open_pct": {"operator": ">=", "value": params.gap_open_min_pct},
        "candle": "close > open",
    }
    if row is None or any(_number(row.get(key)) is None for key in ("open", "close", "pre_close")):
        return _daily_incomplete(
            "LZ-T-02", threshold, daily.tail(1), as_of, "当日开盘、收盘或前收盘缺失。"
        )
    pre_close = float(row["pre_close"])
    if pre_close <= 0:
        return _daily_incomplete(
            "LZ-T-02", threshold, daily.tail(1), as_of, "前收盘必须大于零。"
        )
    gap = (float(row["open"]) / pre_close - 1.0) * 100.0
    bullish = float(row["close"]) > float(row["open"])
    return _rule(
        "LZ-T-02",
        "passed" if gap + 1e-12 >= params.gap_open_min_pct and bullish else "failed",
        {
            "open": float(row["open"]),
            "close": float(row["close"]),
            "pre_close": pre_close,
            "gap_open_pct": gap,
            "bullish_candle": bullish,
        },
        threshold,
        _source(row, "input.daily"),
        evidence_date=str(row["_date"]),
    )


def _amplitude_trigger(
    daily: pd.DataFrame, as_of: str, params: LiZongParameters
) -> StrategyRuleResult:
    row = _latest_daily_row(daily)
    threshold = {
        "amplitude_pct": {"operator": ">", "value": params.amplitude_min_pct},
        "candle": "close > open",
    }
    keys = ("open", "close", "high", "low", "pre_close")
    if row is None or any(_number(row.get(key)) is None for key in keys):
        return _daily_incomplete(
            "LZ-T-03", threshold, daily.tail(1), as_of, "当日 OHLC 或前收盘缺失。"
        )
    pre_close = float(row["pre_close"])
    if pre_close <= 0:
        return _daily_incomplete(
            "LZ-T-03", threshold, daily.tail(1), as_of, "前收盘必须大于零。"
        )
    amplitude = (float(row["high"]) - float(row["low"])) / pre_close * 100.0
    bullish = float(row["close"]) > float(row["open"])
    return _rule(
        "LZ-T-03",
        "passed" if amplitude > params.amplitude_min_pct and bullish else "failed",
        {
            "open": float(row["open"]),
            "close": float(row["close"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "pre_close": pre_close,
            "amplitude_pct": amplitude,
            "bullish_candle": bullish,
        },
        threshold,
        _source(row, "input.daily"),
        evidence_date=str(row["_date"]),
    )


def _prepare_daily(value: Any, as_of: str) -> pd.DataFrame:
    frame = _as_frame(value)
    if frame.empty:
        return pd.DataFrame(
            columns=[
                "_date",
                "_suspended",
                "_has_price_limit",
                "_limit_known",
                "_limit_up",
                "_adjusted_high",
            ]
        )
    date_col = _first_column(frame, ("trade_date", "evidence_date", "date"))
    if date_col is None:
        return pd.DataFrame(
            columns=[
                "_date",
                "_suspended",
                "_has_price_limit",
                "_limit_known",
                "_limit_up",
                "_adjusted_high",
            ]
        )
    working = frame.copy()
    working["_date"] = working[date_col].map(_normalize_date_or_none)
    working = working[working["_date"].notna() & (working["_date"] <= as_of)]
    if "data_status" in working:
        bad = working["data_status"].astype(str).str.lower().isin(
            {"missing", "error", "incomplete", "unstable"}
        )
        working = working[~bad]
    if "is_complete" in working:
        working = working[working["is_complete"].fillna(False).astype(bool)]
    working = working.sort_values("_date").drop_duplicates("_date", keep="last")
    suspended = pd.Series(False, index=working.index)
    if "is_suspended" in working:
        suspended = working["is_suspended"].fillna(False).astype(bool)
    elif "suspended" in working:
        suspended = working["suspended"].fillna(False).astype(bool)
    working["_suspended"] = suspended

    if "has_price_limit" in working:
        has_limit = working["has_price_limit"].fillna(True).astype(bool)
        explicit_no_limit = ~has_limit
    else:
        has_limit = pd.Series(True, index=working.index)
        explicit_no_limit = pd.Series(False, index=working.index)
    working["_has_price_limit"] = has_limit
    up_limit = (
        pd.to_numeric(working["up_limit"], errors="coerce")
        if "up_limit" in working
        else pd.Series(float("nan"), index=working.index)
    )
    close = (
        pd.to_numeric(working["close"], errors="coerce")
        if "close" in working
        else pd.Series(float("nan"), index=working.index)
    )
    working["_limit_known"] = explicit_no_limit | (has_limit & up_limit.notna())
    working["_limit_up"] = has_limit & up_limit.notna() & close.notna() & (
        (close - up_limit).abs() <= 1e-4
    )

    if "adjusted_high" in working:
        adjusted_high = pd.to_numeric(working["adjusted_high"], errors="coerce")
    elif "high" in working and "adj_factor" in working:
        adjusted_high = pd.to_numeric(working["high"], errors="coerce") * pd.to_numeric(
            working["adj_factor"], errors="coerce"
        )
    else:
        adjusted_high = pd.Series(float("nan"), index=working.index)
    working["_adjusted_high"] = adjusted_high
    for column in ("open", "high", "low", "close", "pre_close", "pct_chg", "volume"):
        if column in working:
            working[column] = pd.to_numeric(working[column], errors="coerce")
    if "volume" not in working and "vol" in working:
        working["volume"] = pd.to_numeric(working["vol"], errors="coerce")
    return working.reset_index(drop=True)


def _holder_classification(row: pd.Series) -> tuple[str, str]:
    explicit = str(
        row.get("classification")
        or row.get("holder_type")
        or row.get("category")
        or ""
    ).strip().lower()
    institution_values = {
        "institution",
        "institutional",
        "non_natural",
        "non-natural",
        "legal_person",
        "company",
        "fund",
        "asset_management",
        "insurance",
        "social_security",
        "trust",
        "securities",
        "bank",
        "state_owned",
        "机构",
        "法人",
        "非自然人",
    }
    natural_values = {"natural_person", "natural", "individual", "person", "自然人", "个人"}
    if explicit in institution_values:
        return "institution", str(row.get("classification_reason") or f"显式类型：{explicit}")
    if explicit in natural_values:
        return "natural_person", str(
            row.get("classification_reason") or f"显式类型：{explicit}"
        )
    if _truthy_or_none(row.get("is_institution")) is True:
        return "institution", str(row.get("classification_reason") or "is_institution=true")
    if _truthy_or_none(row.get("is_natural_person")) is True:
        return "natural_person", str(
            row.get("classification_reason") or "is_natural_person=true"
        )
    return "unknown", str(row.get("classification_reason") or "缺少可靠的显式股东类型")


def _normalize_holder_name(value: str) -> str:
    return re.sub(r"[\s\-—_·,，.。()（）]+", "", value).upper()


def _latest_daily_row(frame: pd.DataFrame) -> pd.Series | None:
    if frame.empty:
        return None
    complete = frame[~frame["_suspended"]]
    if complete.empty:
        return None
    return complete.iloc[-1]


def _daily_incomplete(
    rule_id: str,
    threshold: Any,
    frame: pd.DataFrame,
    as_of: str,
    limitation: str,
) -> StrategyRuleResult:
    evidence_date = as_of
    if not frame.empty and "_date" in frame:
        evidence_date = str(frame.iloc[-1]["_date"])
    return _rule(
        rule_id,
        "data_incomplete",
        None,
        threshold,
        _frame_source(frame, "input.daily"),
        evidence_date=evidence_date,
        limitations=(limitation,),
    )


def _rule(
    rule_id: str,
    status: str,
    actual_value: Any,
    threshold: Any,
    source: str,
    *,
    evidence_date: str | None = None,
    report_period: str | None = None,
    limitations: tuple[str, ...] = (),
) -> StrategyRuleResult:
    return StrategyRuleResult(
        rule_id=rule_id,
        status=status,  # type: ignore[arg-type]
        actual_value=actual_value,
        threshold=threshold,
        evidence_date=evidence_date,
        report_period=report_period,
        source=source,
        formula_version=FORMULA_VERSION,
        limitations=limitations,
    )


def _as_frame(value: Any) -> pd.DataFrame:
    if isinstance(value, pd.DataFrame):
        return value.copy()
    if value is None:
        return pd.DataFrame()
    if isinstance(value, Mapping):
        return pd.DataFrame([dict(value)])
    return pd.DataFrame(list(value))


def _latest_row_as_of(
    frame: pd.DataFrame, as_of: str, date_candidates: tuple[str, ...]
) -> pd.Series | None:
    if frame.empty:
        return None
    date_col = _first_column(frame, date_candidates)
    if date_col is None:
        return frame.iloc[-1]
    working = frame.copy()
    working["_date"] = working[date_col].map(_normalize_date_or_none)
    working = working[working["_date"].notna() & (working["_date"] <= as_of)]
    if working.empty:
        return None
    return working.sort_values("_date").iloc[-1]


def _first_column(frame: pd.DataFrame, candidates: tuple[str, ...]) -> str | None:
    return next((column for column in candidates if column in frame.columns), None)


def _normalize_date(value: Any) -> str:
    normalized = _normalize_date_or_none(value)
    if normalized is None:
        raise ValueError(f"invalid date: {value!r}")
    return normalized


def _normalize_date_or_none(value: Any) -> str | None:
    if value is None or (not isinstance(value, (str, date, datetime)) and pd.isna(value)):
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    if not text:
        return None
    digits = re.sub(r"\D", "", text)
    if len(digits) >= 8:
        try:
            return date(int(digits[:4]), int(digits[4:6]), int(digits[6:8])).isoformat()
        except ValueError:
            return None
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        return None


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _json_number(value: Any) -> float | None:
    return _number(value)


def _missing_numeric(frame: pd.DataFrame, columns: tuple[str, ...]) -> bool:
    if any(column not in frame for column in columns):
        return True
    return any(pd.to_numeric(frame[column], errors="coerce").isna().any() for column in columns)


def _source(row: pd.Series | None, default: str) -> str:
    if row is None:
        return default
    value = row.get("source")
    return str(value).strip() if value is not None and str(value).strip() else default


def _frame_source(frame: pd.DataFrame, default: str) -> str:
    if frame.empty or "source" not in frame:
        return default
    values = sorted({str(value).strip() for value in frame["source"] if str(value).strip()})
    return "+".join(values) if values else default


def _row_date(row: pd.Series | None, candidates: tuple[str, ...]) -> str | None:
    if row is None:
        return None
    for key in candidates:
        value = _normalize_date_or_none(row.get(key))
        if value is not None:
            return value
    return None


def _truthy_or_none(value: Any) -> bool | None:
    if value is None or (not isinstance(value, (str, bool, int, float)) and pd.isna(value)):
        return None
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y"}:
            return True
        if normalized in {"false", "0", "no", "n"}:
            return False
        return None
    return bool(value)
