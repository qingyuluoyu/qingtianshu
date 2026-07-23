from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
import math
from statistics import mean, pstdev, stdev
from typing import Any
from zoneinfo import ZoneInfo

from app.catalog import CORE_INDEX_SYMBOLS, INDEX_BY_SYMBOL, INDEX_CATALOG, RESEARCH_TARGETS
from app.db import Database
from app.providers.market import (
    CSIIndustryIndexProvider,
    EastmoneySectorProvider,
    ProviderError,
    YahooMarketProvider,
)
from app.services.live_market import (
    market_quote_semantics,
    previous_market_session_date,
)
from app.utils import utc_now


def analyze_history(history: dict[str, Any]) -> dict[str, Any]:
    points = history.get("points") or []
    closes = [float(point["close"]) for point in points if point.get("close") is not None]
    if not closes:
        raise ValueError("没有可分析的收盘价")

    metrics = {
        "latest_close": _round(closes[-1]),
        "return_1d_pct": period_return(closes, 1),
        "return_5d_pct": period_return(closes, 5),
        "return_20d_pct": period_return(closes, 20),
        "return_60d_pct": period_return(closes, 60),
        "ma20": moving_average(closes, 20),
        "ma60": moving_average(closes, 60),
        "volatility_20d_annualized_pct": annualized_volatility(closes, 20),
        "max_drawdown_60d_pct": maximum_drawdown(closes[-60:]),
    }
    metrics.update(build_technical_snapshot(points, closes))
    ma20 = metrics["ma20"]
    ma60 = metrics["ma60"]
    if ma20 is None or ma60 is None:
        trend = "数据不足"
    elif closes[-1] > ma20 > ma60:
        trend = "中期偏强"
    elif closes[-1] < ma20 < ma60:
        trend = "中期偏弱"
    else:
        trend = "趋势分化"
    metrics["trend_state"] = trend
    return metrics


def build_technical_snapshot(
    points: list[dict[str, Any]], closes: list[float]
) -> dict[str, Any]:
    rsi = relative_strength_index(closes, 14)
    macd = moving_average_convergence_divergence(closes)
    bands = bollinger_bands(closes, 20)
    atr_pct = average_true_range_pct(points, 14)
    volume_ratio = volume_ratio_5_20(points)
    latest = closes[-1] if closes else None
    ma20 = moving_average(closes, 20)

    if latest is None or ma20 is None:
        state = "数据不足"
    elif (
        rsi is not None
        and rsi >= 70
        and bands.get("upper") is not None
        and latest >= bands["upper"]
    ):
        state = "短期偏热"
    elif (
        rsi is not None
        and rsi <= 30
        and bands.get("lower") is not None
        and latest <= bands["lower"]
    ):
        state = "短期超跌观察"
    elif macd.get("histogram") is not None and macd["histogram"] > 0 and latest > ma20:
        state = "动量改善"
    elif macd.get("histogram") is not None and macd["histogram"] < 0 and latest < ma20:
        state = "动量转弱"
    else:
        state = "技术分化"

    return {
        "rsi_14": rsi,
        "macd_12_26": macd.get("macd"),
        "macd_signal_9": macd.get("signal"),
        "macd_histogram": macd.get("histogram"),
        "bollinger_upper_20": bands.get("upper"),
        "bollinger_middle_20": bands.get("middle"),
        "bollinger_lower_20": bands.get("lower"),
        "bollinger_position_20": bands.get("position"),
        "atr_14_pct": atr_pct,
        "volume_ratio_5_20": volume_ratio,
        "technical_state": state,
        "technical_method": (
            "RSI14、MACD(12,26,9)、20日布林带、ATR14占收盘价比例和5/20日量比；"
            "只描述已发生的技术结构，不生成买卖信号。"
        ),
    }


def period_return(closes: list[float], periods: int) -> float | None:
    if len(closes) <= periods or closes[-periods - 1] == 0:
        return None
    return _round((closes[-1] / closes[-periods - 1] - 1) * 100)


def moving_average(closes: list[float], window: int) -> float | None:
    if len(closes) < window:
        return None
    return _round(mean(closes[-window:]))


def annualized_volatility(closes: list[float], window: int) -> float | None:
    if len(closes) < window + 1:
        return None
    sample = closes[-(window + 1) :]
    returns = [sample[i] / sample[i - 1] - 1 for i in range(1, len(sample)) if sample[i - 1] != 0]
    if len(returns) < 2:
        return None
    return _round(stdev(returns) * math.sqrt(252) * 100)


def maximum_drawdown(closes: list[float]) -> float | None:
    if len(closes) < 2:
        return None
    peak = closes[0]
    worst = 0.0
    for close in closes:
        peak = max(peak, close)
        if peak:
            worst = min(worst, close / peak - 1)
    return _round(worst * 100)


def relative_strength_index(closes: list[float], window: int = 14) -> float | None:
    if len(closes) < window + 1:
        return None
    changes = [closes[index] - closes[index - 1] for index in range(1, len(closes))]
    sample = changes[-window:]
    average_gain = sum(max(change, 0.0) for change in sample) / window
    average_loss = sum(max(-change, 0.0) for change in sample) / window
    if average_loss == 0:
        return 100.0 if average_gain > 0 else 50.0
    relative_strength = average_gain / average_loss
    return _round(100 - 100 / (1 + relative_strength))


def exponential_moving_average(values: list[float], span: int) -> list[float]:
    if not values:
        return []
    alpha = 2 / (span + 1)
    output = [float(values[0])]
    for value in values[1:]:
        output.append(alpha * float(value) + (1 - alpha) * output[-1])
    return output


def moving_average_convergence_divergence(
    closes: list[float],
) -> dict[str, float | None]:
    if len(closes) < 35:
        return {"macd": None, "signal": None, "histogram": None}
    ema12 = exponential_moving_average(closes, 12)
    ema26 = exponential_moving_average(closes, 26)
    macd_series = [fast - slow for fast, slow in zip(ema12, ema26)]
    signal_series = exponential_moving_average(macd_series, 9)
    macd_value = macd_series[-1]
    signal_value = signal_series[-1]
    return {
        "macd": _round(macd_value),
        "signal": _round(signal_value),
        "histogram": _round(macd_value - signal_value),
    }


def bollinger_bands(
    closes: list[float], window: int = 20
) -> dict[str, float | None]:
    if len(closes) < window:
        return {"upper": None, "middle": None, "lower": None, "position": None}
    sample = closes[-window:]
    middle = mean(sample)
    deviation = pstdev(sample)
    upper = middle + 2 * deviation
    lower = middle - 2 * deviation
    width = upper - lower
    position = (closes[-1] - lower) / width if width else 0.5
    return {
        "upper": _round(upper),
        "middle": _round(middle),
        "lower": _round(lower),
        "position": _round(position),
    }


def average_true_range_pct(
    points: list[dict[str, Any]], window: int = 14
) -> float | None:
    valid = [point for point in points if point.get("close") is not None]
    if len(valid) < window + 1:
        return None
    true_ranges = []
    for previous, current in zip(valid[:-1], valid[1:]):
        previous_close = float(previous["close"])
        high = float(current.get("high") or current["close"])
        low = float(current.get("low") or current["close"])
        true_ranges.append(
            max(high - low, abs(high - previous_close), abs(low - previous_close))
        )
    latest_close = float(valid[-1]["close"])
    if latest_close == 0:
        return None
    return _round(mean(true_ranges[-window:]) / latest_close * 100)


def volume_ratio_5_20(points: list[dict[str, Any]]) -> float | None:
    volumes = [
        float(point["volume"])
        for point in points
        if isinstance(point.get("volume"), (int, float)) and point["volume"] > 0
    ]
    if len(volumes) < 20:
        return None
    baseline = mean(volumes[-20:])
    if baseline == 0:
        return None
    return _round(mean(volumes[-5:]) / baseline)


def classify_market(index_items: list[dict[str, Any]]) -> dict[str, Any]:
    returns = [
        item["metrics"]["return_1d_pct"]
        for item in index_items
        if item.get("status") == "available" and item.get("metrics", {}).get("return_1d_pct") is not None
    ]
    total = len(index_items)
    coverage = len(returns) / total if total else 0
    if not returns or coverage < 0.5:
        return {
            "label": "数据不足",
            "coverage_ratio": _round(coverage),
            "average_return_1d_pct": None,
            "advance_ratio": None,
            "dispersion_pct": None,
            "breadth_scope": "representative_indices",
            "whole_market_breadth_available": False,
            "method": "代表性指数一日收益的均值、上涨比例与离散度",
        }

    average_return = mean(returns)
    advance_ratio = sum(value > 0 for value in returns) / len(returns)
    dispersion = pstdev(returns) if len(returns) > 1 else 0.0
    if average_return >= 0.6 and advance_ratio >= 0.6:
        label = "偏强"
    elif average_return <= -0.6 and advance_ratio <= 0.4:
        label = "承压"
    elif dispersion >= 1.5 or 0.4 <= advance_ratio <= 0.6:
        label = "分化"
    else:
        label = "中性"
    return {
        "label": label,
        "coverage_ratio": _round(coverage),
        "average_return_1d_pct": _round(average_return),
        "advance_ratio": _round(advance_ratio),
        "dispersion_pct": _round(dispersion),
        "breadth_scope": "representative_indices",
        "whole_market_breadth_available": False,
        "method": "代表性指数一日收益的均值、上涨比例与离散度；不是涨跌预测",
    }


_MARKET_TIMEZONES = {
    "china": "Asia/Shanghai",
    "hong_kong": "Asia/Hong_Kong",
    "us": "America/New_York",
    "europe": "Europe/London",
    "japan": "Asia/Tokyo",
    "korea": "Asia/Seoul",
}


def _timestamp_market_date(value: Any, timezone_name: str) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(ZoneInfo(timezone_name)).date().isoformat()
    except (TypeError, ValueError, KeyError):
        return text[:10] if len(text) >= 10 else None


def _current_quote_snapshot(
    history: dict[str, Any], metrics: dict[str, Any]
) -> dict[str, Any] | None:
    price = history.get("regular_market_price")
    quote_timestamp = history.get("regular_market_timestamp")
    points = list(history.get("points") or [])
    if (
        history.get("is_stale")
        or not isinstance(price, (int, float))
        or not quote_timestamp
        or not points
    ):
        return None
    latest_bar = points[-1]
    latest_close = latest_bar.get("close")
    if not isinstance(latest_close, (int, float)) or latest_close == 0:
        return None
    timezone_name = str(history.get("timezone") or "UTC")
    quote_date = _timestamp_market_date(quote_timestamp, timezone_name)
    daily_date = _timestamp_market_date(latest_bar.get("timestamp"), timezone_name)
    if quote_date is None or daily_date is None or quote_date < daily_date:
        return None
    quote_is_newer = quote_date > daily_date
    quote_semantics = (
        market_quote_semantics("china", quote_timestamp)
        if timezone_name == "Asia/Shanghai"
        else {}
    )
    is_intraday = bool(
        quote_is_newer
        and quote_semantics.get("quote_basis", "intraday_snapshot")
        == "intraday_snapshot"
    )
    pct_change = (
        _round((float(price) / float(latest_close) - 1) * 100)
        if quote_is_newer
        else metrics.get("return_1d_pct")
    )
    basis = (
        str(quote_semantics.get("quote_basis") or "intraday_snapshot")
        if quote_is_newer
        else "latest_complete_close"
    )
    label = (
        str(quote_semantics.get("quote_label") or "最新报价")
        if quote_is_newer
        else "最近收盘"
    )
    return {
        "price": _round(float(price)),
        "pct_change": pct_change,
        "currency": history.get("currency"),
        "market_timestamp": quote_timestamp,
        "market_date": quote_date,
        "basis": basis,
        "label": label,
        "is_intraday": is_intraday,
        "quote_session_status": quote_semantics.get("quote_session_status"),
        "current_session_status": quote_semantics.get("current_session_status"),
        "complete_daily_bar_confirmed": not quote_is_newer,
    }


def _index_market_key(item: dict[str, Any]) -> str:
    symbol = str(item.get("symbol") or "")
    group = str(item.get("group") or "")
    if symbol == "^N225":
        return "japan"
    if symbol == "^KS11":
        return "korea"
    return group or "china"


def _validated_index_metrics(
    history: dict[str, Any], symbol: str
) -> dict[str, Any]:
    metrics = analyze_history(history)
    points = list(history.get("points") or [])
    catalog_item = INDEX_BY_SYMBOL.get(symbol) or {"symbol": symbol, "group": ""}
    market_key = _index_market_key(catalog_item)
    if len(points) < 2:
        return metrics
    timezone_name = str(history.get("timezone") or "UTC")
    latest_date = _timestamp_market_date(points[-1].get("timestamp"), timezone_name)
    previous_date = _timestamp_market_date(points[-2].get("timestamp"), timezone_name)
    expected_previous = previous_market_session_date(market_key, latest_date)
    if expected_previous and previous_date != expected_previous:
        metrics["return_1d_pct"] = None
        metrics["return_1d_status"] = "missing_previous_session"
        metrics["return_1d_previous_market_date"] = previous_date
        metrics["return_1d_expected_previous_market_date"] = expected_previous
    else:
        metrics["return_1d_status"] = "verified_adjacent_sessions"
    return metrics


def _index_market_date(item: dict[str, Any]) -> str | None:
    market_key = _index_market_key(item)
    timezone_name = _MARKET_TIMEZONES.get(market_key, "UTC")
    latest_bar = item.get("latest_bar") or {}
    return _timestamp_market_date(
        latest_bar.get("timestamp") or item.get("market_timestamp"),
        timezone_name,
    )


def _market_brief_target_date(
    market_key: str | None,
    index_items: list[dict[str, Any]],
    breadth_data: dict[str, Any],
) -> tuple[str | None, str]:
    if market_key is None:
        return None, "multi_market_sessions"
    dates = [
        date
        for item in index_items
        if item.get("status") == "available"
        and (date := _index_market_date(item))
    ]
    if dates:
        counts = Counter(dates)
        target = max(counts, key=lambda date: (counts[date], date))
        return target, "representative_index_session"
    if market_key == "china" and breadth_data.get("status") == "available":
        breadth_market_date = str(breadth_data.get("market_date") or "").strip()
        if breadth_market_date:
            return breadth_market_date, (
                "a_share_previous_completed_session"
                if breadth_data.get("served_as_previous_close")
                else "a_share_whole_market_breadth"
            )
    return None, "unavailable"


def build_conditional_outlook(
    metrics: dict[str, Any],
    price_levels: dict[str, Any],
    sentiment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    score = 0.0
    reasons = []
    latest = metrics.get("latest_close")
    ma20 = metrics.get("ma20")
    ma60 = metrics.get("ma60")
    return_20d = metrics.get("return_20d_pct")
    if latest is not None and ma20 is not None:
        if latest > ma20:
            score += 1
            reasons.append("最新收盘位于 MA20 上方")
        else:
            score -= 1
            reasons.append("最新收盘位于 MA20 下方")
    if ma20 is not None and ma60 is not None:
        if ma20 > ma60:
            score += 1
            reasons.append("MA20 高于 MA60")
        else:
            score -= 1
            reasons.append("MA20 不高于 MA60")
    if return_20d is not None:
        score += 1 if return_20d > 0 else -1
        reasons.append(f"20 日收益为 {return_20d}%")
    price_score = score
    if price_score >= 1.5:
        price_label = "偏强观察"
    elif price_score <= -1.5:
        price_label = "偏弱观察"
    else:
        price_label = "震荡观察"
    sentiment_adjustment = 0.0
    sentiment_score = (sentiment or {}).get("score")
    if isinstance(sentiment_score, (int, float)):
        if sentiment_score >= 0.2:
            sentiment_adjustment = 0.5
            score += sentiment_adjustment
            reasons.append("社区情绪样本轻微偏多，但只作为弱证据")
        elif sentiment_score <= -0.2:
            sentiment_adjustment = -0.5
            score += sentiment_adjustment
            reasons.append("社区情绪样本轻微偏空，但只作为弱证据")

    if score >= 1.5:
        label = "偏强观察"
    elif score <= -1.5:
        label = "偏弱观察"
    else:
        label = "震荡观察"
    volatility = metrics.get("volatility_20d_annualized_pct")
    sample_size = (sentiment or {}).get("sample_size", 0)
    confidence = "medium" if ma20 is not None and ma60 is not None else "low"
    if volatility is None or volatility > 45 or (
        sentiment is not None and sample_size < 10
    ):
        confidence = "low"

    recent_high = price_levels.get("recent_20d_high")
    recent_low = price_levels.get("recent_20d_low")
    upside_candidates = [
        value for value in (recent_high, ma20, ma60) if isinstance(value, (int, float))
    ]
    upside_level = max(upside_candidates) if upside_candidates else recent_high
    downside_candidates = [
        value
        for value in (ma20, ma60, recent_low)
        if isinstance(value, (int, float)) and latest is not None and value < latest
    ]
    downside_level = max(downside_candidates) if downside_candidates else recent_low
    return {
        "horizon": "未来 5—20 个交易日",
        "label": label,
        "confidence": confidence,
        "evidence_score": round(score, 2),
        "price_evidence_score": round(price_score, 2),
        "price_signal_label": price_label,
        "sentiment_adjustment": sentiment_adjustment,
        "reasons": reasons,
        "scenarios": [
            {
                "name": "向上延续",
                "condition": f"收盘有效站上上方关键位 {upside_level}，且随后不跌回 MA20 {ma20}",
                "meaning": "动量延续的条件得到更多价格证据，但仍需公告或基本面催化交叉验证。",
            },
            {
                "name": "区间震荡",
                "condition": f"价格继续运行在近20日低点 {recent_low} 与高点 {recent_high} 之间",
                "meaning": "当前信息没有形成方向性突破，不宜把单日波动解释成趋势。",
            },
            {
                "name": "下行风险",
                "condition": f"收盘跌破关键参考位 {downside_level}，同时20日收益继续恶化",
                "meaning": "原有偏强或震荡假设需要失效处理，优先复核风险证据与当前研究判断。",
            },
        ],
        "invalidation": (
            f"当前“{label}”判断在价格跨越关键参考位后必须重算；"
            "公告、财务或行业证据若与价格方向冲突，应降低价格信号权重。"
        ),
        "method": "transparent_rule_based_outlook_v1",
        "probability": None,
        "warning": "尚未完成样本外回测，因此不提供胜率、目标价或确定性涨跌概率。",
    }


def build_evidence_debate(evidence: dict[str, Any]) -> dict[str, Any]:
    metrics = evidence.get("metrics") or {}
    information = evidence.get("a_share_information") or {}
    sentiment = information.get("sentiment") or {}
    fundamentals = evidence.get("fundamentals") or {}
    fundamental_summary = fundamentals.get("summary") or {}
    latest_report = fundamental_summary.get("latest_report") or {}
    earnings_quality = evidence.get("earnings_quality") or {}
    financial_drivers = evidence.get("financial_drivers") or {}
    business_structure = evidence.get("business_structure") or {}
    event_timeline = evidence.get("event_timeline") or {}
    outlook_calibration = (
        (evidence.get("conditional_outlook") or {}).get("calibration") or {}
    )
    calibration_analog = outlook_calibration.get("historical_analog") or {}
    bull: list[dict[str, str]] = []
    bear: list[dict[str, str]] = []
    risks: list[dict[str, str]] = []

    if (metrics.get("return_20d_pct") or 0) > 0:
        bull.append(
            {
                "claim": "近20日价格动量为正",
                "evidence": f"20日收益 {metrics.get('return_20d_pct')}%",
                "source": "deterministic_price_metrics",
            }
        )
    if metrics.get("ma20") is not None and metrics.get("latest_close") is not None:
        if metrics["latest_close"] > metrics["ma20"]:
            bull.append(
                {
                    "claim": "最新收盘位于短期均线上方",
                    "evidence": f"收盘 {metrics['latest_close']} > MA20 {metrics['ma20']}",
                    "source": "deterministic_price_metrics",
                }
            )
        else:
            bear.append(
                {
                    "claim": "最新收盘位于短期均线下方",
                    "evidence": f"收盘 {metrics['latest_close']} < MA20 {metrics['ma20']}",
                    "source": "deterministic_price_metrics",
                }
            )
    if (metrics.get("return_60d_pct") or 0) < 0:
        bear.append(
            {
                "claim": "中期价格表现仍为负",
                "evidence": f"60日收益 {metrics.get('return_60d_pct')}%",
                "source": "deterministic_price_metrics",
            }
        )
    sentiment_score = sentiment.get("score")
    if isinstance(sentiment_score, (int, float)) and sentiment.get("sample_size", 0) >= 10:
        target = bull if sentiment_score >= 0.2 else bear if sentiment_score <= -0.2 else None
        if target is not None:
            target.append(
                {
                    "claim": f"零售社区情绪{sentiment.get('band')}",
                    "evidence": f"score={sentiment_score}, sample={sentiment.get('sample_size')}, confidence={sentiment.get('confidence')}",
                    "source": "eastmoney_guba_heuristic_weak",
                }
            )
    for event in (event_timeline.get("supportive_events") or [])[:2]:
        if event.get("evidence_level") not in {
            "official_disclosure",
            "regulatory_filing",
        }:
            continue
        bull.append(
            {
                "claim": "出现需继续核验的支持性官方事件",
                "evidence": (
                    f"{event.get('event_date') or '日期待确认'}｜"
                    f"{event.get('event_label')}｜{event.get('title')}"
                ),
                "source": "deterministic_event_timeline",
            }
        )
    for event in (event_timeline.get("risk_events") or [])[:3]:
        if event.get("evidence_level") not in {
            "official_disclosure",
            "regulatory_filing",
        }:
            continue
        evidence_text = (
            f"{event.get('event_date') or '日期待确认'}｜"
            f"{event.get('event_label')}｜{event.get('title')}"
        )
        bear.append(
            {
                "claim": "出现需优先复核的官方风险事件",
                "evidence": evidence_text,
                "source": "deterministic_event_timeline",
            }
        )
        risks.append(
            {
                "risk": "官方事件可能影响原研究假设",
                "evidence": evidence_text,
                "action": "阅读公告或监管文件原文，再与财务、业务和价格证据交叉验证。",
            }
        )
    revenue_growth = latest_report.get("revenue_yoy_pct")
    if isinstance(revenue_growth, (int, float)):
        target = bull if revenue_growth > 0 else bear if revenue_growth < 0 else None
        if target is not None:
            target.append(
                {
                    "claim": "最新报告期营收同比增长"
                    if revenue_growth > 0
                    else "最新报告期营收同比下降",
                    "evidence": (
                        f"{latest_report.get('report_date_name')}营收同比 "
                        f"{revenue_growth}%"
                    ),
                    "source": "structured_fundamentals",
                }
            )
    profit_growth = latest_report.get("net_profit_yoy_pct")
    if isinstance(profit_growth, (int, float)):
        target = bull if profit_growth > 0 else bear if profit_growth < 0 else None
        if target is not None:
            target.append(
                {
                    "claim": "最新报告期净利润同比增长"
                    if profit_growth > 0
                    else "最新报告期净利润同比下降",
                    "evidence": (
                        f"{latest_report.get('report_date_name')}净利润同比 "
                        f"{profit_growth}%"
                    ),
                    "source": "structured_fundamentals",
                }
            )
    existing_bull_claims = {item["claim"] for item in bull}
    existing_bear_claims = {item["claim"] for item in bear}
    for claim in (earnings_quality.get("supports") or [])[:3]:
        if claim not in existing_bull_claims:
            bull.append(
                {
                    "claim": claim,
                    "evidence": earnings_quality.get("overall_label")
                    or "财报质量支持项",
                    "source": "deterministic_earnings_quality",
                }
            )
            existing_bull_claims.add(claim)
    for claim in (earnings_quality.get("contradictions") or [])[:3]:
        if claim not in existing_bear_claims:
            bear.append(
                {
                    "claim": claim,
                    "evidence": earnings_quality.get("overall_label")
                    or "财报质量矛盾项",
                    "source": "deterministic_earnings_quality",
                }
            )
            existing_bear_claims.add(claim)
    for driver in (financial_drivers.get("confirmed_mechanical_drivers") or [])[:6]:
        direction = driver.get("direction")
        target = bull if direction == "positive" else bear if direction == "negative" else None
        if target is None:
            continue
        claim = str(driver.get("label") or "财务科目机械影响")
        existing = existing_bull_claims if target is bull else existing_bear_claims
        if claim in existing:
            continue
        target.append(
            {
                "claim": claim,
                "evidence": str(driver.get("statement") or "已完成确定性科目拆解"),
                "source": "deterministic_financial_driver",
            }
        )
        existing.add(claim)
    drawdown = metrics.get("max_drawdown_60d_pct")
    if isinstance(drawdown, (int, float)) and drawdown <= -15:
        risks.append(
            {
                "risk": "尾部回撤较大",
                "evidence": f"60日最大回撤 {drawdown}%",
                "action": "任何偏强情景都应同时设置可观察的失效位。",
            }
        )
    volatility = metrics.get("volatility_20d_annualized_pct")
    if isinstance(volatility, (int, float)) and volatility >= 35:
        risks.append(
            {
                "risk": "短期波动较高",
                "evidence": f"20日年化波动率 {volatility}%",
                "action": "降低方向判断置信度，避免由单日涨跌外推趋势。",
            }
        )
    cashflow_ratio = fundamental_summary.get("operating_cashflow_to_net_profit")
    if isinstance(cashflow_ratio, (int, float)) and cashflow_ratio < 0.5:
        risks.append(
            {
                "risk": "经营现金流对利润覆盖偏弱",
                "evidence": f"经营现金流/归母净利润={cashflow_ratio}",
                "action": "核对现金流变化原因及其是否具有季节性，不能只看利润同比。",
            }
        )
    debt_ratio = latest_report.get("debt_asset_ratio_pct")
    if isinstance(debt_ratio, (int, float)) and debt_ratio >= 70:
        risks.append(
            {
                "risk": "资产负债率较高",
                "evidence": f"最新报告期资产负债率 {debt_ratio}%",
                "action": "继续核对有息负债、偿债期限和现金流覆盖。",
            }
        )
    quality_contradictions = earnings_quality.get("contradictions") or []
    if quality_contradictions:
        risks.append(
            {
                "risk": "财报质量存在需要解释的矛盾",
                "evidence": "；".join(quality_contradictions[:2]),
                "action": (earnings_quality.get("review_points") or [
                    "核对公告原文、现金流和会计口径。"
                ])[0],
            }
        )
    driver_clues = financial_drivers.get("plausible_clues") or []
    if driver_clues:
        risks.append(
            {
                "risk": "利润或现金流科目出现需要复核的线索",
                "evidence": "；".join(
                    str(item.get("evidence") or item.get("label"))
                    for item in driver_clues[:2]
                ),
                "action": (financial_drivers.get("review_points") or [
                    "核对详细三表、公告附注和分业务披露。"
                ])[0],
            }
        )
    structure_dimensions = {
        item.get("classification"): item
        for item in business_structure.get("dimensions") or []
    }
    concentration_candidates = []
    for classification in ("product", "region"):
        dimension = structure_dimensions.get(classification) or {}
        concentration = dimension.get("concentration") or {}
        share = concentration.get("top1_revenue_share_pct")
        if isinstance(share, (int, float)) and share >= 50:
            concentration_candidates.append(
                {
                    "classification": classification,
                    "label": dimension.get("label") or classification,
                    "item": concentration.get("top1_item"),
                    "share": share,
                    "report_date": dimension.get("current_report_date"),
                }
            )
    if concentration_candidates:
        concentration_candidates.sort(key=lambda item: item["share"], reverse=True)
        item = concentration_candidates[0]
        risks.append(
            {
                "risk": "主营结构集中度需要复核",
                "evidence": (
                    f"{item['report_date']} {item['label']}第一大项目"
                    f"{item['item']}收入占比 {item['share']}%"
                ),
                "action": (
                    "这只表示需要进一步核对产品、客户或地区依赖，"
                    "不能据此认定经营风险已经发生。"
                ),
            }
        )
    calibration_reliability = outlook_calibration.get("reliability")
    calibrated_label = outlook_calibration.get("price_signal_label")
    if calibration_reliability == "not_directionally_consistent":
        risks.append(
            {
                "risk": "历史走查未支持当前价格方向",
                "evidence": (
                    f"{outlook_calibration.get('horizon')} 保留样本中，"
                    f"{calibrated_label}方向一致率 "
                    f"{calibration_analog.get('direction_consistency')}"
                ),
                "action": "降低价格规则权重，等待新的公告、财务或价格条件确认。",
            }
        )
    elif calibration_reliability == "insufficient" and calibrated_label != "震荡观察":
        risks.append(
            {
                "risk": "当前方向的历史同类样本不足",
                "evidence": (
                    f"{outlook_calibration.get('horizon')} 保留样本仅 "
                    f"{calibration_analog.get('sample_size', 0)} 次"
                ),
                "action": "不提高方向置信度，继续按条件触发和失效位观察。",
            }
        )
    missing = evidence.get("research_frame", {}).get("missing_information", [])
    critical_missing = [
        item
        for item in missing
        if not str(item).startswith("行业供需与一致预期")
    ]
    if critical_missing:
        risks.append(
            {
                "risk": "证据覆盖不完整",
                "evidence": "；".join(critical_missing),
                "action": "补齐数据前不形成完整投资建议。",
            }
        )

    if len(bull) >= 2 and len(bear) == 0 and len(risks) <= 1:
        decision = "支持继续研究，但等待条件确认"
    elif len(bear) >= 2 or len(risks) >= 2:
        decision = "风险优先，原假设需要更强证据"
    else:
        decision = "证据分化，维持观察"
    return {
        "bull_case": bull,
        "bear_case": bear,
        "risk_committee": risks,
        "manager_view": decision,
        "confidence": "medium" if len(bull) + len(bear) >= 3 else "low",
        "method": "deterministic_evidence_debate_v3",
        "warning": "该结构用于暴露分歧和风险，不等于 BUY/HOLD/SELL 指令。",
    }


def build_research_analysis_board(evidence: dict[str, Any]) -> dict[str, Any]:
    """Assemble deterministic analyst modules and a non-predictive review plan.

    The module split follows the useful part of TradingAgents (specialized
    evidence roles plus bull/bear/risk review) and Rongxian (3/5/10-session
    tracking), while keeping every conclusion tied to persisted evidence.
    """

    metrics = evidence.get("metrics") or {}
    information = evidence.get("a_share_information") or {}
    global_information = evidence.get("global_information") or {}
    fundamentals = evidence.get("fundamentals") or {}
    earnings_quality = evidence.get("earnings_quality") or {}
    financial_drivers = evidence.get("financial_drivers") or {}
    business_structure = evidence.get("business_structure") or {}
    shareholder_structure = evidence.get("shareholder_structure") or {}
    analyst_expectations = evidence.get("analyst_expectations") or {}
    event_timeline = evidence.get("event_timeline") or {}
    peers = evidence.get("peer_comparison") or {}
    peer_operating = peers.get("operating_comparison") or {}
    debate = evidence.get("evidence_debate") or {}
    outlook = evidence.get("conditional_outlook") or {}
    price_levels = evidence.get("price_levels") or {}

    modules = [
        {
            "key": "market",
            "label": "行情结构",
            "status": "ready" if metrics.get("latest_close") is not None else "missing",
            "evidence_count": sum(
                metrics.get(key) is not None
                for key in (
                    "latest_close",
                    "return_20d_pct",
                    "ma20",
                    "rsi_14",
                    "macd_histogram",
                    "atr_14_pct",
                    "volume_ratio_5_20",
                    "volatility_20d_annualized_pct",
                    "max_drawdown_60d_pct",
                )
            ),
        },
        {
            "key": "news",
            "label": "公告、新闻与事件脉络",
            "status": "ready"
            if (
                information.get("announcements")
                or information.get("news")
                or global_information.get("news")
                or event_timeline.get("status") == "available"
            )
            else "missing",
            "evidence_count": max(
                len(event_timeline.get("events") or []),
                len(information.get("announcements") or [])
                + len(information.get("news") or [])
                + len(global_information.get("news") or []),
            ),
        },
        {
            "key": "sentiment",
            "label": "情绪与分歧",
            "status": "ready" if information.get("sentiment") else "not_applicable",
            "evidence_count": (information.get("sentiment") or {}).get("sample_size", 0),
        },
        {
            "key": "fundamentals",
            "label": "基本面与现金流",
            "status": "ready"
            if (
                fundamentals.get("summary")
                or fundamentals.get("valuation")
                or earnings_quality.get("status") == "available"
                or financial_drivers.get("status") == "available"
                or business_structure.get("status") == "available"
                or shareholder_structure.get("status") == "available"
            )
            else "missing",
            "evidence_count": len((fundamentals.get("financial_periods") or []))
            + int(bool(fundamentals.get("valuation")))
            + len(earnings_quality.get("factors") or [])
            + len(earnings_quality.get("supports") or [])
            + len(earnings_quality.get("contradictions") or [])
            + len(financial_drivers.get("confirmed_mechanical_drivers") or [])
            + len(financial_drivers.get("plausible_clues") or [])
            + len(financial_drivers.get("company_explanations") or [])
            + len(financial_drivers.get("unresolved_causes") or [])
            + len(business_structure.get("dimensions") or [])
            + len(business_structure.get("key_changes") or [])
            + len(shareholder_structure.get("holder_history") or [])
            + len(shareholder_structure.get("top_holders") or []),
        },
        {
            "key": "peers",
            "label": "同行估值与经营",
            "status": "ready"
            if peers.get("metrics") or peer_operating.get("metrics")
            else "missing",
            "evidence_count": len(peers.get("peers") or [])
            + int(
                (peer_operating.get("coverage") or {}).get(
                    "same_period_financial_peers", 0
                )
            ),
        },
        {
            "key": "analyst_expectations",
            "label": "分析师预期与研报",
            "status": "ready"
            if analyst_expectations.get("status") == "available"
            else "not_applicable"
            if not str(evidence.get("symbol") or "").endswith((".SS", ".SZ"))
            else "missing",
            "evidence_count": len(
                analyst_expectations.get("forecast_eps") or []
            )
            + len(analyst_expectations.get("latest_reports") or [])
            + int(
                isinstance(
                    analyst_expectations.get("rating_organization_count"), int
                )
            ),
        },
        {
            "key": "debate",
            "label": "多空与风险委员会",
            "status": "ready" if debate else "missing",
            "evidence_count": len(debate.get("bull_case") or [])
            + len(debate.get("bear_case") or [])
            + len(debate.get("risk_committee") or []),
        },
    ]

    thesis = evidence.get("user_thesis") or "尚未记录关注理由"
    tracking_plan = [
        {
            "horizon_sessions": 3,
            "focus": "确认短期价格结构与信息增量",
            "checks": [
                f"收盘与 MA20 {price_levels.get('ma20')} 的相对位置是否变化",
                "RSI、MACD、ATR 与5/20日量比是否出现一致或背离",
                "是否出现新公告、监管文件或与主营直接相关的新闻",
                "事件脉络中的官方披露与媒体线索是否出现矛盾",
                "单日涨跌是否伴随波动与回撤结构变化",
            ],
        },
        {
            "horizon_sessions": 5,
            "focus": "复核动量延续与原假设是否受到反证",
            "checks": [
                f"价格是否仍在近20日区间 {price_levels.get('recent_20d_low')} 至 {price_levels.get('recent_20d_high')} 内",
                f"原关注理由“{thesis}”是否出现可核验的支持或反方证据",
                "新闻叙事、社区情绪与确定性数据是否出现背离",
                "最新支持性或风险事件是否真正改变原关注理由",
            ],
        },
        {
            "horizon_sessions": 10,
            "focus": "重新综合基本面、同行、历史校准与风险",
            "checks": [
                "最新财务、现金流或估值证据是否发生实质变化",
                "利润桥、费用率、营运资金与现金流线索是否得到公告附注确认",
                "主营收入、毛利来源和产品/地区集中度是否发生同口径变化",
                "股东户数集中或分散线索是否持续，以及下一份十大股东报告是否出现可比变化",
                "同财年EPS一致预期是否发生修订，覆盖机构数变化是否影响可比性",
                "与固定同行样本的相对估值和基本面差异是否收敛或扩大",
                f"条件展望“{outlook.get('label') or outlook.get('price_signal_label') or '待确认'}”的触发与失效条件是否需要重算",
            ],
        },
    ]
    applicable_modules = [
        item for item in modules if item["status"] != "not_applicable"
    ]
    ready_modules = sum(item["status"] == "ready" for item in modules)
    missing_core_modules = [
        item["label"]
        for item in modules
        if item["key"] in {"market", "fundamentals"}
        and item["status"] != "ready"
    ]
    optional_gaps = list(
        (evidence.get("research_frame") or {}).get("missing_information") or []
    )
    coverage_ratio = (
        ready_modules / len(applicable_modules) if applicable_modules else 0.0
    )
    if not missing_core_modules and coverage_ratio >= 0.8:
        readiness_status = "ready"
        readiness_label = "核心证据完整"
        response_policy = "直接回答当前问题；可在结尾列出仍待补充的研究维度。"
    elif not missing_core_modules and coverage_ratio >= 0.6:
        readiness_status = "usable"
        readiness_label = "核心证据可用"
        response_policy = "先用已有证据回答，再明确尚待补充的模块。"
    else:
        readiness_status = "insufficient"
        readiness_label = "关键证据待补"
        response_policy = "只回答已验证部分，并明确关键缺口与补证动作。"

    return {
        "framework": "deterministic_multi_analyst_board_v2_readiness_gate",
        "modules": modules,
        "ready_modules": ready_modules,
        "total_modules": len(modules),
        "readiness": {
            "status": readiness_status,
            "label": readiness_label,
            "coverage_ratio": round(coverage_ratio, 4),
            "missing_core_modules": missing_core_modules,
            "optional_gaps": optional_gaps,
            "response_policy": response_policy,
        },
        "tracking_plan": tracking_plan,
        "boundary": (
            "3/5/10 个交易日是研究复核周期，不是涨跌预测、"
            "目标价或持仓指令。"
        ),
    }


class MarketAnalysisService:
    def __init__(
        self,
        database: Database,
        market_provider: YahooMarketProvider,
        sector_provider: EastmoneySectorProvider,
        breadth_provider: Any | None = None,
        industry_index_provider: CSIIndustryIndexProvider | None = None,
        china_index_provider: Any | None = None,
    ):
        self.database = database
        self.market_provider = market_provider
        self.sector_provider = sector_provider
        self.breadth_provider = breadth_provider
        self.industry_index_provider = industry_index_provider
        self.china_index_provider = china_index_provider

    def get_index_history(self, symbol: str, range_name: str = "1y") -> dict[str, Any]:
        history = self._fetch_index_history(symbol, range_name=range_name)
        return {**history, "metrics": _validated_index_metrics(history, symbol)}

    def get_indices(self, scope: str = "core", group: str | None = None) -> dict[str, Any]:
        catalog = INDEX_CATALOG
        if scope == "core":
            catalog = [INDEX_BY_SYMBOL[symbol] for symbol in CORE_INDEX_SYMBOLS]
        if group:
            catalog = [item for item in catalog if item["group"] == group]

        items = self._fetch_index_items(catalog, range_name="3mo")
        warnings = [warning for item in items for warning in item.get("warnings", [])]
        return {
            "generated_at": utc_now(),
            "scope": scope,
            "group": group,
            "coverage": {
                "requested": len(catalog),
                "available": sum(item["status"] == "available" for item in items),
            },
            "warnings": warnings,
            "indices": items,
        }

    def hot_sectors(self, limit: int = 20) -> dict[str, Any]:
        try:
            return self.sector_provider.fetch_hot_sectors(limit=limit)
        except ProviderError as exc:
            return {
                "source": "Eastmoney A-share sector ranking",
                "market_timestamp": None,
                "fetched_at": utc_now(),
                "is_stale": False,
                "coverage": {"returned": 0, "total_available": None},
                "warnings": [str(exc)],
                "sectors": [],
                "status": "unavailable",
            }

    def industry_snapshot(
        self, industry_name: str, market_date: str | None = None
    ) -> dict[str, Any]:
        if self.industry_index_provider is None:
            return {
                "type": "industry_index",
                "status": "unavailable",
                "industry_name": industry_name,
                "warnings": ["当前运行环境没有配置精确行业指数提供器。"],
                "points": [],
                "constituents": [],
            }
        try:
            result = self.industry_index_provider.fetch(
                industry_name, market_date=market_date
            )
            if result.get("status") == "available" and result.get("points"):
                result = dict(result)
                result["metrics"] = analyze_history(
                    {"points": list(result.get("points") or [])}
                )
            return result
        except ProviderError as exc:
            return {
                "type": "industry_index",
                "status": "unavailable",
                "industry_name": industry_name,
                "warnings": [str(exc)],
                "points": [],
                "constituents": [],
            }

    def market_breadth(self) -> dict[str, Any]:
        if self.breadth_provider is None:
            return {
                "source": "A-share breadth provider not configured",
                "market_timestamp": None,
                "fetched_at": utc_now(),
                "is_stale": False,
                "coverage": {
                    "expected": None,
                    "returned": 0,
                    "valid_change": 0,
                    "coverage_ratio": 0.0,
                },
                "warnings": ["当前运行环境没有配置A股全市场广度提供器。"],
                "breadth": {},
                "exchange_breakdown": {},
                "status": "unavailable",
                "scope": "all_a_shares_including_beijing",
            }
        try:
            return self.breadth_provider.fetch_breadth()
        except ProviderError as exc:
            return {
                "source": "Sina Finance all A-share snapshot",
                "market_timestamp": None,
                "fetched_at": utc_now(),
                "is_stale": False,
                "coverage": {
                    "expected": None,
                    "returned": 0,
                    "valid_change": 0,
                    "coverage_ratio": 0.0,
                },
                "warnings": [str(exc)],
                "breadth": {},
                "exchange_breakdown": {},
                "status": "unavailable",
                "scope": "all_a_shares_including_beijing",
            }

    def market_brief(self, market_key: str | None = None) -> dict[str, Any]:
        catalog = [INDEX_BY_SYMBOL[symbol] for symbol in CORE_INDEX_SYMBOLS]
        if market_key:
            catalog = [
                item
                for item in INDEX_CATALOG
                if (
                    (market_key == "china" and item.get("group") == "china")
                    or (
                        market_key == "hong_kong"
                        and item.get("group") == "hong_kong"
                    )
                    or (
                        market_key == "us"
                        and item.get("group") == "us"
                        and item.get("symbol") != "^VIX"
                    )
                    or (
                        market_key == "europe"
                        and item.get("group") == "europe"
                    )
                    or (
                        market_key == "japan"
                        and item.get("symbol") == "^N225"
                    )
                    or (
                        market_key == "korea"
                        and item.get("symbol") == "^KS11"
                    )
                )
            ]
        index_items = self._fetch_index_items(catalog, range_name="3mo")
        sector_data = self.hot_sectors(limit=10)
        breadth_data = (
            self.market_breadth()
            if market_key in {None, "china"}
            else {
                "status": "not_applicable",
                "scope": "all_a_shares_including_beijing",
                "breadth": {},
                "coverage": {},
                "warnings": [],
            }
        )
        analysis_market_date, analysis_date_basis = _market_brief_target_date(
            market_key,
            index_items,
            breadth_data,
        )
        annotated_indices = []
        for item in index_items:
            item_market_date = _index_market_date(item)
            same_date = (
                item_market_date == analysis_market_date
                if analysis_market_date and item_market_date
                else None
            )
            annotated_indices.append(
                {
                    **item,
                    "market_date": item_market_date,
                    "same_date_as_analysis_target": same_date,
                    "analysis_eligibility": (
                        "same_market_date"
                        if same_date is True
                        else "cross_date_excluded"
                        if same_date is False
                        else "date_not_constrained"
                    ),
                }
            )
        index_items = annotated_indices

        sector_data = dict(sector_data)
        sector_market_date = _timestamp_market_date(
            sector_data.get("market_timestamp"), "Asia/Shanghai"
        )
        sector_same_date = (
            sector_market_date == analysis_market_date
            if analysis_market_date and sector_market_date
            else None
        )
        sector_data.update(
            {
                "market_date": sector_market_date,
                "same_date_as_analysis_target": sector_same_date,
                "analysis_eligibility": (
                    "same_market_date"
                    if sector_same_date is True
                    else "cross_date_excluded"
                    if sector_same_date is False
                    else "date_not_constrained"
                ),
            }
        )

        breadth_data = dict(breadth_data)
        breadth_market_date = str(breadth_data.get("market_date") or "").strip() or None
        breadth_same_date = (
            breadth_market_date == analysis_market_date
            if analysis_market_date and breadth_market_date
            else None
        )
        breadth_data["same_date_as_analysis_target"] = breadth_same_date

        warnings = [warning for item in index_items for warning in item.get("warnings", [])]
        warnings.extend(sector_data.get("warnings", []))
        warnings.extend(breadth_data.get("warnings", []))
        aligned_indices = [
            item
            for item in index_items
            if item.get("status") == "available"
            and (
                analysis_market_date is None
                or item.get("same_date_as_analysis_target") is True
            )
        ]
        if market_key is None:
            market_state = {
                "label": "跨市场分时",
                "coverage_ratio": None,
                "average_return_1d_pct": None,
                "advance_ratio": None,
                "dispersion_pct": None,
                "breadth_scope": "multiple_market_sessions",
                "whole_market_breadth_available": False,
                "method": "不同市场处于不同交易时段，不合成单一市场强弱标签。",
            }
        else:
            market_state = classify_market(aligned_indices)
        market_state.update(
            {
                "market_date": analysis_market_date,
                "date_basis": analysis_date_basis,
                "aligned_index_count": len(aligned_indices),
                "available_index_count": sum(
                    item.get("status") == "available" for item in index_items
                ),
            }
        )
        breadth = breadth_data.get("breadth") or {}
        turnover = breadth_data.get("turnover") or {}
        distribution = breadth_data.get("distribution") or {}
        if (
            market_key == "china"
            and breadth_data.get("status") == "available"
            and breadth.get("total")
            and breadth_same_date is not False
        ):
            market_state.update(
                {
                    "whole_market_breadth_available": True,
                    "whole_market_breadth_scope": breadth_data.get("scope"),
                    "whole_market_total": breadth.get("total"),
                    "whole_market_advancers": breadth.get("advancers"),
                    "whole_market_decliners": breadth.get("decliners"),
                    "whole_market_unchanged": breadth.get("unchanged"),
                    "whole_market_net_advancers": breadth.get("net_advancers"),
                    "whole_market_advance_ratio": breadth.get("advance_ratio"),
                    "whole_market_unchanged_ratio": breadth.get("unchanged_ratio"),
                    "whole_market_breadth_state": breadth.get("state"),
                    "whole_market_turnover_available": turnover.get("status")
                    == "available",
                    "whole_market_total_amount_cny": turnover.get(
                        "total_amount_cny"
                    ),
                    "whole_market_distribution_available": distribution.get(
                        "status"
                    )
                    == "available",
                    "whole_market_median_pct_change": distribution.get(
                        "median_pct_change"
                    ),
                }
            )
        if analysis_market_date and sector_same_date is False:
            warnings.append(
                f"热门板块快照日期 {sector_market_date} 与分析日期 "
                f"{analysis_market_date} 不一致，未用于综合市场判断。"
            )
        mismatched_index_dates = sorted(
            {
                str(item.get("market_date"))
                for item in index_items
                if item.get("same_date_as_analysis_target") is False
                and item.get("market_date")
            }
        )
        if analysis_market_date and mismatched_index_dates:
            warnings.append(
                "部分代表性指数日期与分析日期不一致，已从综合市场状态中排除："
                + "、".join(mismatched_index_dates)
            )
        available_index_count = sum(
            item.get("status") == "available" for item in index_items
        )
        if analysis_market_date is None:
            alignment_status = "multi_market_sessions"
        elif not aligned_indices:
            alignment_status = "no_aligned_indices"
        elif len(aligned_indices) < available_index_count:
            alignment_status = "partial_alignment"
        else:
            alignment_status = "same_market_date"
        return {
            "type": "market_brief",
            "generated_at": utc_now(),
            "market_key": market_key,
            "analysis_target": {
                "market_date": analysis_market_date,
                "date_basis": analysis_date_basis,
                "market_key": market_key,
            },
            "date_alignment": {
                "status": alignment_status,
                "target_market_date": analysis_market_date,
                "aligned_indices": len(aligned_indices),
                "available_indices": available_index_count,
                "sector_status": (
                    "same_market_date"
                    if sector_same_date is True
                    else "cross_date_excluded"
                    if sector_same_date is False
                    else "not_date_constrained"
                ),
                "sector_market_date": sector_market_date,
                "breadth_status": (
                    "same_market_date"
                    if breadth_same_date is True
                    else "cross_date_excluded"
                    if breadth_same_date is False
                    else "not_date_constrained"
                ),
                "breadth_market_date": breadth_market_date,
                "rule": (
                    "综合市场状态只使用目标交易日一致的代表性指数；"
                    "板块与全市场广度跨日期时只保留为独立快照，不参与合成判断。"
                ),
            },
            "market_state": market_state,
            "indices": index_items,
            "hot_sectors": sector_data,
            "market_breadth": breadth_data,
            "warnings": warnings,
            "methodology": [
                "市场状态只使用同一目标交易日的代表性指数一日收益、上涨比例和离散度。",
                "用户明确市场时，代表性指数范围会切换到该市场；VIX不进入股票指数广度计算。",
                "热门板块按东方财富板块涨跌幅字段排序；日期不同于目标交易日时不参与综合判断。",
                "A股全市场广度按沪深京A股列表逐页汇总涨跌幅字段；覆盖不完整时不确认普涨。",
                "跨市场或跨日期快照不合成单一偏强、分化或承压标签。",
                "该结果描述已发生的数据，不预测下一交易日。",
            ],
        }

    def watchlist_brief(self, user_id: str) -> dict[str, Any]:
        watchlist = self.database.list_watchlist(user_id)
        if not watchlist:
            return {
                "type": "watchlist_brief",
                "generated_at": utc_now(),
                "items": [],
                "coverage": {"requested": 0, "available": 0},
                "warnings": ["自选股为空。可先通过 POST /users/{id}/watchlist 添加。"],
            }

        def fetch(item: dict[str, Any]) -> dict[str, Any]:
            change_event = self.database.latest_research_change_event(item["symbol"])
            display_name = (
                RESEARCH_TARGETS.get(item["symbol"], {}).get("name")
                or item.get("name")
                or item["symbol"]
            )
            latest_change = None
            if change_event is not None:
                payload = change_event.get("payload") or {}
                latest_change = {
                    "severity": change_event.get("severity"),
                    "summary": change_event.get("summary"),
                    "created_at": change_event.get("created_at"),
                    "data_as_of": payload.get("data_as_of"),
                }
            try:
                history = self.market_provider.fetch_history(item["symbol"], range_name="1y")
                metrics = analyze_history(history)
                return {
                    **item,
                    "name": display_name,
                    "status": "available",
                    "latest_change": latest_change,
                    "metrics": metrics,
                    "current_quote": _current_quote_snapshot(history, metrics),
                    "latest_bar": history["points"][-1],
                    "recent_bars": history["points"][-5:],
                    "source": history["source"],
                    "market_timestamp": history["market_timestamp"],
                    "fetched_at": history["fetched_at"],
                    "is_stale": history.get("is_stale", False),
                    "coverage": history["coverage"],
                    "warnings": history.get("warnings", []),
                }
            except (ProviderError, ValueError) as exc:
                return {
                    **item,
                    "name": display_name,
                    "status": "unavailable",
                    "latest_change": latest_change,
                    "warnings": [str(exc)],
                }

        items = self._parallel_map(watchlist, fetch)
        items.sort(
            key=lambda item: abs(
                (item.get("current_quote") or {}).get("pct_change")
                if (item.get("current_quote") or {}).get("pct_change") is not None
                else item.get("metrics", {}).get("return_1d_pct") or 0
            ),
            reverse=True,
        )
        return {
            "type": "watchlist_brief",
            "generated_at": utc_now(),
            "items": items,
            "coverage": {
                "requested": len(watchlist),
                "available": sum(item["status"] == "available" for item in items),
            },
            "warnings": [warning for item in items for warning in item.get("warnings", [])],
            "sorting": "按一日涨跌幅绝对值排序，不代表投资优先级",
        }

    def stock_research(self, user_id: str, symbol: str) -> dict[str, Any]:
        history = self.market_provider.fetch_history(symbol, range_name="1y")
        metrics = analyze_history(history)
        recent_points = history["points"][-20:]
        recent_highs = [
            float(point.get("high") or point["close"]) for point in recent_points
        ]
        recent_lows = [
            float(point.get("low") or point["close"]) for point in recent_points
        ]
        price_levels = {
            "recent_20d_high": _round(max(recent_highs)),
            "recent_20d_low": _round(min(recent_lows)),
            "ma20": metrics.get("ma20"),
            "ma60": metrics.get("ma60"),
        }
        watchlist_item = self.database.get_watchlist_item(user_id, symbol)
        confirmed_memories = self.database.list_memories(user_id, status="confirmed")
        facts = [
            f"最新收盘价为 {metrics['latest_close']} {history.get('currency') or ''}".strip(),
            f"1/5/20/60日收益分别为 {metrics['return_1d_pct']}%、{metrics['return_5d_pct']}%、{metrics['return_20d_pct']}%、{metrics['return_60d_pct']}%",
            f"MA20={metrics['ma20']}，MA60={metrics['ma60']}，趋势状态={metrics['trend_state']}",
            f"20日年化波动率={metrics['volatility_20d_annualized_pct']}%，60日最大回撤={metrics['max_drawdown_60d_pct']}%",
        ]
        return {
            "type": "stock_research",
            "generated_at": utc_now(),
            "symbol": symbol,
            "display_name": watchlist_item.get("name") if watchlist_item else history["display_name"],
            "user_thesis": watchlist_item.get("thesis") if watchlist_item else None,
            "confirmed_user_memories": [
                {"kind": item["kind"], "content": item["content"]} for item in confirmed_memories
            ],
            "facts": facts,
            "metrics": metrics,
            "price_levels": price_levels,
            "conditional_outlook": build_conditional_outlook(
                metrics, price_levels, sentiment=None
            ),
            "recent_bars": history["points"][-5:],
            "research_frame": {
                "supporting_evidence": [],
                "contrary_evidence": [],
                "invalidation_conditions": [],
                "missing_information": [
                    "公司最新公告尚未接入",
                    "结构化财务与估值数据尚未接入",
                    "行业供需与一致预期尚未接入",
                    "新闻与事件影响尚未接入",
                ],
            },
            "provenance": {
                "source": history["source"],
                "market_timestamp": history["market_timestamp"],
                "fetched_at": history["fetched_at"],
                "coverage": history["coverage"],
                "is_stale": history.get("is_stale", False),
            },
            "warnings": history.get("warnings", [])
            + ["价格证据不能单独形成完整投资建议。"],
        }

    def _fetch_index_items(
        self, catalog: list[dict[str, str]], range_name: str
    ) -> list[dict[str, Any]]:
        def fetch(item: dict[str, str]) -> dict[str, Any]:
            try:
                history = self._fetch_index_history(
                    item["symbol"], range_name=range_name
                )
                metrics = _validated_index_metrics(history, item["symbol"])
                warnings = list(history.get("warnings", []))
                if metrics.get("return_1d_status") == "missing_previous_session":
                    warnings.append(
                        "最近两个日线点不是相邻交易日，未计算一日涨跌幅。"
                    )
                return {
                    **item,
                    "status": "available",
                    "metrics": metrics,
                    "latest_bar": history["points"][-1],
                    "recent_bars": history["points"][-5:],
                    "source": history["source"],
                    "market_timestamp": history["market_timestamp"],
                    "fetched_at": history["fetched_at"],
                    "is_stale": history.get("is_stale", False),
                    "coverage": history["coverage"],
                    "warnings": warnings,
                }
            except (ProviderError, ValueError) as exc:
                return {**item, "status": "unavailable", "warnings": [str(exc)]}

        items = self._parallel_map(catalog, fetch)
        order = {item["symbol"]: index for index, item in enumerate(catalog)}
        items.sort(key=lambda item: order[item["symbol"]])
        return items

    def _fetch_index_history(
        self, symbol: str, *, range_name: str
    ) -> dict[str, Any]:
        histories: list[dict[str, Any]] = []
        failures: list[Exception] = []
        try:
            histories.append(
                self.market_provider.fetch_history(symbol, range_name=range_name)
            )
        except (ProviderError, ValueError) as exc:
            failures.append(exc)

        fallback = self.china_index_provider
        if fallback is not None and fallback.supports(symbol):
            try:
                histories.append(
                    fallback.fetch_history(symbol, range_name=range_name)
                )
            except (ProviderError, ValueError) as exc:
                failures.append(exc)

        if not histories:
            detail = str(failures[-1]) if failures else "没有可用日线"
            raise ProviderError(f"指数日线不可用：{detail}")

        def freshness(
            history: dict[str, Any],
        ) -> tuple[date, bool, bool, int, datetime]:
            raw = str(history.get("market_timestamp") or "")
            try:
                timestamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)
            except ValueError:
                timestamp = datetime.min.replace(tzinfo=timezone.utc)
            point_count = len(history.get("points") or [])
            return (
                timestamp.date(),
                not bool(history.get("is_stale")),
                point_count >= 2,
                point_count,
                timestamp,
            )

        return max(histories, key=freshness)

    @staticmethod
    def _parallel_map(items: list[dict[str, Any]], function: Any) -> list[dict[str, Any]]:
        workers = min(6, max(1, len(items)))
        output = []
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(function, item) for item in items]
            for future in as_completed(futures):
                output.append(future.result())
        return output


def _round(value: float, digits: int = 4) -> float:
    return round(float(value), digits)
