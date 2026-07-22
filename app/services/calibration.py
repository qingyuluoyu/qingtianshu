from __future__ import annotations

from datetime import datetime, timedelta, timezone
from statistics import mean, median
from typing import Any

from app.catalog import normalize_symbol
from app.db import Database
from app.services.analysis import analyze_history, build_conditional_outlook
from app.utils import utc_now


OUTLOOK_LABELS = ("偏强观察", "震荡观察", "偏弱观察")


def _round(value: float | None, digits: int = 4) -> float | None:
    return round(value, digits) if value is not None else None


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return _round(ordered[lower] * (1 - weight) + ordered[upper] * weight)


def _adjusted_points(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    adjusted = []
    for item in points:
        raw_close = item.get("close")
        adjusted_close = item.get("adjusted_close")
        if raw_close is None:
            continue
        ratio = 1.0
        if isinstance(adjusted_close, (int, float)) and float(raw_close) != 0:
            ratio = float(adjusted_close) / float(raw_close)
        normalized = dict(item)
        normalized["close"] = float(adjusted_close) if isinstance(
            adjusted_close, (int, float)
        ) else float(raw_close)
        for key in ("open", "high", "low"):
            if isinstance(item.get(key), (int, float)):
                normalized[key] = float(item[key]) * ratio
        adjusted.append(normalized)
    return adjusted


def _price_levels(points: list[dict[str, Any]], metrics: dict[str, Any]) -> dict[str, Any]:
    recent = points[-20:]
    highs = [float(item.get("high") or item["close"]) for item in recent]
    lows = [float(item.get("low") or item["close"]) for item in recent]
    return {
        "recent_20d_high": _round(max(highs)),
        "recent_20d_low": _round(min(lows)),
        "ma20": metrics.get("ma20"),
        "ma60": metrics.get("ma60"),
    }


def generate_walk_forward_records(
    points: list[dict[str, Any]],
    horizon: int,
    min_history: int = 80,
) -> list[dict[str, Any]]:
    """Generate non-overlapping forward records without using future data in signals."""

    clean = [
        item
        for item in points
        if item.get("timestamp") and item.get("close") is not None
    ]
    if len(clean) < min_history + horizon:
        return []
    records = []
    for signal_index in range(min_history - 1, len(clean) - horizon, horizon):
        prefix = clean[: signal_index + 1]
        metrics = analyze_history({"points": prefix})
        outlook = build_conditional_outlook(
            metrics, _price_levels(prefix, metrics), sentiment=None
        )
        start_close = float(clean[signal_index]["close"])
        future = clean[signal_index + 1 : signal_index + horizon + 1]
        future_closes = [float(item["close"]) for item in future]
        if not future_closes or start_close == 0:
            continue
        forward_return = (future_closes[-1] / start_close - 1) * 100
        maximum_favorable = (max(future_closes) / start_close - 1) * 100
        maximum_adverse = (min(future_closes) / start_close - 1) * 100
        records.append(
            {
                "signal_index": signal_index,
                "signal_at": clean[signal_index]["timestamp"],
                "evaluated_at": future[-1]["timestamp"],
                "label": outlook["label"],
                "score": outlook["evidence_score"],
                "forward_return_pct": _round(forward_return),
                "maximum_favorable_excursion_pct": _round(maximum_favorable),
                "maximum_adverse_excursion_pct": _round(maximum_adverse),
            }
        )
    return records


def _group_summary(records: list[dict[str, Any]], label: str) -> dict[str, Any]:
    selected = [item for item in records if item["label"] == label]
    returns = [float(item["forward_return_pct"]) for item in selected]
    favorable = [
        float(item["maximum_favorable_excursion_pct"]) for item in selected
    ]
    adverse = [float(item["maximum_adverse_excursion_pct"]) for item in selected]
    if not selected:
        return {
            "sample_size": 0,
            "median_forward_return_pct": None,
            "p25_forward_return_pct": None,
            "p75_forward_return_pct": None,
            "historical_positive_share": None,
            "direction_consistency": None,
            "reliability": "insufficient",
        }
    positive_share = sum(value > 0 for value in returns) / len(returns)
    if label == "偏强观察":
        direction_consistency = positive_share
        sign_aligned = median(returns) > 0
    elif label == "偏弱观察":
        direction_consistency = 1 - positive_share
        sign_aligned = median(returns) < 0
    else:
        direction_consistency = None
        sign_aligned = False
    if len(selected) < 8:
        reliability = "insufficient"
    elif label == "震荡观察":
        reliability = "descriptive_only"
    elif direction_consistency is not None and direction_consistency >= 0.55 and sign_aligned:
        reliability = "directionally_consistent"
    else:
        reliability = "not_directionally_consistent"
    return {
        "sample_size": len(selected),
        "mean_forward_return_pct": _round(mean(returns)),
        "median_forward_return_pct": _round(median(returns)),
        "p25_forward_return_pct": _percentile(returns, 0.25),
        "p75_forward_return_pct": _percentile(returns, 0.75),
        "historical_positive_share": _round(positive_share),
        "direction_consistency": _round(direction_consistency),
        "median_maximum_favorable_excursion_pct": _round(median(favorable)),
        "median_maximum_adverse_excursion_pct": _round(median(adverse)),
        "reliability": reliability,
    }


def _period(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "first_signal_at": records[0]["signal_at"] if records else None,
        "last_evaluated_at": records[-1]["evaluated_at"] if records else None,
    }


def summarize_walk_forward_records(
    records: list[dict[str, Any]], horizon: int, train_fraction: float = 0.7
) -> dict[str, Any]:
    split = int(len(records) * train_fraction)
    if records:
        split = min(max(split, 1), len(records))
    in_sample = records[:split]
    out_of_sample = records[split:]
    return {
        "horizon_trading_days": horizon,
        "sample_spacing_trading_days": horizon,
        "total_samples": len(records),
        "in_sample": {
            "sample_size": len(in_sample),
            "period": _period(in_sample),
        },
        "out_of_sample": {
            "sample_size": len(out_of_sample),
            "period": _period(out_of_sample),
            "by_label": {
                label: _group_summary(out_of_sample, label) for label in OUTLOOK_LABELS
            },
        },
    }


def build_walk_forward_calibration(points: list[dict[str, Any]]) -> dict[str, Any]:
    clean = _adjusted_points([
        item
        for item in points
        if item.get("timestamp") and item.get("close") is not None
    ])
    horizons = {}
    for horizon in (5, 10, 20):
        records = generate_walk_forward_records(clean, horizon=horizon)
        horizons[f"{horizon}d"] = summarize_walk_forward_records(records, horizon)
    return {
        "method": "fixed_rule_prequential_oos_v2",
        "generated_at": utc_now(),
        "history": {
            "points": len(clean),
            "first_timestamp": clean[0]["timestamp"] if clean else None,
            "last_timestamp": clean[-1]["timestamp"] if clean else None,
            "price_basis": "adjusted_close_when_available",
        },
        "protocol": {
            "signal_information": "每个信号只使用该交易日及以前的价格数据。",
            "evaluation_information": "未来价格只用于信号产生后的评分，不回写到历史信号。",
            "sample_spacing": "信号间隔等于评估周期，减少未来窗口重叠。",
            "holdout": "时间上最后 30% 的信号作为保留样本外区间，规则不在该区间重新调参。",
        },
        "horizons": horizons,
        "limitations": [
            "仅校准固定价格规则，不包含历史时点的公告、财务、新闻或社区情绪。",
            "历史频率不等于未来概率，市场制度和波动结构可能发生漂移。",
            "当前未计入交易成本、停牌和涨跌停可成交性；复权结果依赖上游口径。",
        ],
    }


def attach_outlook_calibration(
    outlook: dict[str, Any],
    calibration: dict[str, Any],
    price_signal_label: str,
    primary_horizon: str = "10d",
) -> dict[str, Any]:
    result = dict(outlook)
    horizon = (calibration.get("horizons") or {}).get(primary_horizon) or {}
    out_of_sample = horizon.get("out_of_sample") or {}
    analog = (out_of_sample.get("by_label") or {}).get(price_signal_label) or {}
    reliability = analog.get("reliability", "insufficient")
    if reliability in {"insufficient", "not_directionally_consistent"}:
        result["confidence"] = "low"
    result["calibration"] = {
        "method": calibration.get("method"),
        "calibrated_signal": "price_rule_only",
        "price_signal_label": price_signal_label,
        "horizon": primary_horizon,
        "total_samples": horizon.get("total_samples", 0),
        "out_of_sample_samples": out_of_sample.get("sample_size", 0),
        "out_of_sample_period": out_of_sample.get("period"),
        "historical_analog": analog,
        "reliability": reliability,
        "excludes": ["公告", "财务", "新闻", "社区情绪"],
    }
    result["method"] = "transparent_rule_based_outlook_v2"
    result["probability"] = None
    result["warning"] = (
        "已完成固定价格规则的历史走查与最近30%样本外检验；"
        "历史频率不等于未来概率，仍不提供胜率、目标价或确定性涨跌概率。"
    )
    return result


def _is_older_than(value: str | None, seconds: int) -> bool:
    if not value:
        return True
    try:
        timestamp = datetime.fromisoformat(value).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return True
    return datetime.now(timezone.utc) - timestamp > timedelta(seconds=seconds)


class OutlookCalibrationService:
    def __init__(self, database: Database, market_provider: Any):
        self.database = database
        self.market_provider = market_provider

    def refresh_symbol(self, symbol: str) -> dict[str, Any]:
        canonical = normalize_symbol(symbol)
        history = self.market_provider.fetch_history(canonical, range_name="5y")
        calibration = build_walk_forward_calibration(history.get("points") or [])
        if calibration["history"]["points"] < 100 or not calibration["history"][
            "last_timestamp"
        ]:
            raise ValueError("至少需要 100 个有效日线点才能生成历史走查")
        snapshot = {
            "symbol": canonical,
            "method": calibration["method"],
            "history_first": calibration["history"]["first_timestamp"],
            "history_last": calibration["history"]["last_timestamp"],
            "history_points": calibration["history"]["points"],
            "source": history.get("source") or "unknown",
            "fetched_at": history.get("fetched_at") or utc_now(),
            "calibration": calibration,
        }
        return self.database.save_outlook_calibration(snapshot)

    def get_packet(
        self, symbol: str, refresh_max_age_seconds: int = 21_600
    ) -> dict[str, Any]:
        canonical = normalize_symbol(symbol)
        packet = self.database.latest_outlook_calibration(canonical)
        should_refresh = packet is None or _is_older_than(
            packet.get("created_at") if packet else None, refresh_max_age_seconds
        )
        warnings = []
        if should_refresh:
            try:
                packet = self.refresh_symbol(canonical)
            except Exception as exc:
                if packet is None:
                    raise
                warnings.append(f"校准刷新未完成：{type(exc).__name__}")
        result = dict(packet or {})
        result["warnings"] = warnings
        return result

    def refresh_symbols(self, symbols: list[str]) -> dict[str, Any]:
        results = []
        for symbol in sorted(set(symbols)):
            try:
                packet = self.refresh_symbol(symbol)
                results.append(
                    {
                        "symbol": packet["symbol"],
                        "status": "ok",
                        "history_points": packet["history_points"],
                    }
                )
            except Exception as exc:
                results.append(
                    {
                        "symbol": symbol,
                        "status": "failed",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
        return {
            "requested": len(set(symbols)),
            "completed": sum(item["status"] == "ok" for item in results),
            "results": results,
        }
