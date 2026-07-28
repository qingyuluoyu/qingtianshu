from __future__ import annotations

from datetime import datetime
from statistics import mean, pstdev
from typing import Any
from zoneinfo import ZoneInfo

from app.services.stock_price_move import (
    compact_stock_price_move_event_evidence,
    is_stock_price_move_question,
)


_PRIVATE_PROMPT_EVIDENCE_KEYS = {
    "id",
    "source",
    "source_key",
    "source_url",
    "url",
    "warnings",
    "degraded_from",
    "cache_hit",
    "refresh",
    "methodology",
    "method",
    "provider",
    "fetched_at",
    "error",
    "content_hash",
}


def prompt_local_time(value: Any, timezone_name: str) -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        timezone = ZoneInfo(timezone_name)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone)
        return parsed.astimezone(timezone).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return str(value).replace("T", " ")[:16]


def prompt_market_date(value: Any, timezone_name: str) -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        timezone_value = ZoneInfo(timezone_name)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone_value)
        return parsed.astimezone(timezone_value).date().isoformat()
    except (TypeError, ValueError):
        return str(value)[:10]


def evidence_for_prompt(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: evidence_for_prompt(item)
            for key, item in value.items()
            if key not in _PRIVATE_PROMPT_EVIDENCE_KEYS
        }
    if isinstance(value, list):
        return [evidence_for_prompt(item) for item in value]
    return value


def aligned_market_indices(
    evidence: dict[str, Any],
    indices: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    items = list(indices if indices is not None else evidence.get("indices") or [])
    target_market_date = str(
        (evidence.get("analysis_target") or {}).get("market_date") or ""
    ).strip()
    if not target_market_date:
        return items
    aligned = []
    for item in items:
        explicit = item.get("same_date_as_analysis_target")
        if explicit is False:
            continue
        item_market_date = str(
            item.get("market_date")
            or (item.get("latest_bar") or {}).get("timestamp")
            or item.get("market_timestamp")
            or ""
        )[:10]
        if explicit is True or item_market_date == target_market_date:
            aligned.append(item)
    return aligned


def compact_market_brief_evidence(
    evidence: dict[str, Any],
) -> dict[str, Any]:
    market_drivers = evidence.get("market_drivers") or {}
    market_key = str(market_drivers.get("market_key") or "china")
    question_focus = evidence.get("question_focus") or {}
    focus_key = str(
        question_focus.get("key")
        or market_drivers.get("question_focus")
        or "market_overview"
    )
    question = str(evidence.get("user_question") or "")
    global_query = any(
        term in question
        for term in (
            "全球",
            "海外市场",
            "各国市场",
            "各市场",
            "中日韩美",
            "跨市场",
        )
    )

    def matches_market(item: dict[str, Any]) -> bool:
        group = str(item.get("group") or "")
        region = str(item.get("region") or "")
        name = str(item.get("name") or "")
        if market_key == "china":
            return group == "china"
        if market_key == "hong_kong":
            return group == "hong_kong" or "香港" in region
        if market_key == "us":
            return group == "us" or "美国" in region
        if market_key == "japan":
            return "日本" in region or "日经" in name
        if market_key == "korea":
            return "韩国" in region or "KOSPI" in name.upper()
        if market_key == "europe":
            return group == "europe" or "欧洲" in region
        if market_key == "gold":
            return False
        return True

    indices = list(evidence.get("indices") or [])
    if not global_query:
        focused = [item for item in indices if matches_market(item)]
        if focused:
            indices = focused
    analysis_target = evidence.get("analysis_target") or {}
    target_market_date = str(analysis_target.get("market_date") or "").strip()
    if target_market_date and not global_query:
        indices = aligned_market_indices(evidence, indices)

    metric_keys_by_focus = {
        "trend_reversal": (
            "latest_close",
            "return_1d_pct",
            "return_5d_pct",
            "return_20d_pct",
            "return_60d_pct",
            "ma20",
            "ma60",
            "max_drawdown_60d_pct",
            "technical_state",
            "trend_state",
        ),
        "volume_flows": (
            "return_1d_pct",
            "return_5d_pct",
            "volume_ratio_5_20",
            "atr_14_pct",
            "technical_state",
            "trend_state",
        ),
        "sector_rotation": (
            "return_1d_pct",
            "return_5d_pct",
            "return_20d_pct",
            "volume_ratio_5_20",
            "trend_state",
        ),
        "market_cause": (
            "return_1d_pct",
        ),
        "market_risk": (
            "latest_close",
            "return_1d_pct",
            "return_5d_pct",
            "return_20d_pct",
            "return_60d_pct",
            "ma20",
            "ma60",
            "volatility_20d_annualized_pct",
            "max_drawdown_60d_pct",
            "atr_14_pct",
            "technical_state",
            "trend_state",
        ),
        "market_overview": (
            "return_1d_pct",
            "return_5d_pct",
            "return_20d_pct",
            "ma20",
            "ma60",
            "volatility_20d_annualized_pct",
            "max_drawdown_60d_pct",
            "trend_state",
        ),
    }
    metric_keys = metric_keys_by_focus.get(
        focus_key, metric_keys_by_focus["market_overview"]
    )
    if "60日" in question and any(
        term in question for term in ("收益", "涨幅", "跌幅", "涨跌")
    ):
        metric_keys = tuple(dict.fromkeys((*metric_keys, "return_60d_pct")))
    latest_bar_keys = (
        ("timestamp", "open", "high", "low", "close", "volume")
        if focus_key in {"volume_flows", "market_risk"}
        else ()
    )

    compact_indices = []
    for item in indices[: 8 if global_query else 5]:
        coverage = item.get("coverage") or {}
        interval = str(coverage.get("interval") or "")
        identity_keys = (
            (
                "symbol",
                "name",
                "status",
                "is_stale",
                "same_date_as_analysis_target",
            )
            if focus_key == "market_cause"
            else (
                "symbol",
                "name",
                "region",
                "group",
                "status",
                "is_stale",
                "same_date_as_analysis_target",
            )
        )
        compact_item = {
            key: item.get(key)
            for key in identity_keys
            if item.get(key) is not None
        }
        compact_coverage = {
            key: coverage.get(key)
            for key in ("requested_range", "interval")
            if coverage.get(key) is not None
        }
        first_timestamp = str(coverage.get("first_timestamp") or "")
        last_timestamp = str(coverage.get("last_timestamp") or "")
        if interval == "1d":
            if first_timestamp and focus_key != "market_cause":
                compact_coverage["first_date"] = first_timestamp[:10]
            if last_timestamp and focus_key != "market_cause":
                compact_coverage["last_date"] = last_timestamp[:10]
            item_market_date = str(
                item.get("market_date") or item.get("market_timestamp") or ""
            )
            if item_market_date:
                compact_item["market_date"] = item_market_date[:10]
            if focus_key != "market_cause":
                compact_item["time_basis"] = (
                    "daily_bar_session_date_not_intraday_cutoff"
                )
        elif item.get("market_timestamp") is not None:
            compact_item["market_timestamp"] = item.get("market_timestamp")
            if first_timestamp:
                compact_coverage["first_timestamp"] = first_timestamp
            if last_timestamp:
                compact_coverage["last_timestamp"] = last_timestamp
        if compact_coverage and focus_key != "market_cause":
            compact_item["coverage"] = compact_coverage
        metrics = item.get("metrics") or {}
        compact_item["metrics"] = {
            key: metrics.get(key) for key in metric_keys if metrics.get(key) is not None
        }
        latest_close = metrics.get("latest_close")
        moving_average_keys = (
            () if focus_key == "market_cause" else ("ma20", "ma60")
        )
        for moving_average_key in moving_average_keys:
            moving_average = metrics.get(moving_average_key)
            if not isinstance(latest_close, (int, float)) or not isinstance(
                moving_average, (int, float)
            ):
                continue
            compact_item["metrics"][f"{moving_average_key}_gap_points"] = round(
                float(moving_average) - float(latest_close)
            )
            compact_item["metrics"][f"distance_to_{moving_average_key}_pct"] = round(
                (float(latest_close) / float(moving_average) - 1) * 100,
                1,
            )
        if latest_bar_keys and item.get("latest_bar"):
            latest_bar = item.get("latest_bar") or {}
            compact_item["latest_bar"] = {
                key: latest_bar.get(key)
                for key in latest_bar_keys
                if key != "timestamp"
                if latest_bar.get(key) is not None
            }
            if latest_bar.get("timestamp"):
                compact_item["latest_bar"][
                    "date" if interval == "1d" else "timestamp"
                ] = str(latest_bar.get("timestamp"))[: 10 if interval == "1d" else None]
        compact_indices.append(compact_item)

    compact_drivers = {
        key: market_drivers.get(key)
        for key in (
            "market_key",
            "market_label",
            "question_focus",
            "generated_at",
            "coverage",
            "interpretation",
        )
        if market_drivers.get(key) is not None
    }
    causal_evidence = market_drivers.get("causal_evidence") or {}
    driver_limit = (
        0
        if focus_key == "market_cause" and causal_evidence
        else 4
        if focus_key == "market_cause"
        else 3
        if focus_key == "market_risk"
        else 0
        if focus_key == "trend_reversal"
        else 4
    )
    compact_drivers["items"] = [
        {
            key: (
                str(item.get(key))[:220]
                if key == "title"
                else str(item.get(key))[:320]
                if key == "summary"
                else item.get(key)
            )
            for key in (
                "category",
                "title",
                "summary",
                "source",
                "published_at",
            )
            if item.get(key) is not None
        }
        for item in (market_drivers.get("items") or [])[:driver_limit]
    ]

    compact = {
        key: evidence.get(key)
        for key in (
            "type",
            "generated_at",
            "analysis_target",
            "market_state",
            "user_question",
        )
        if evidence.get(key) is not None
    }
    focused_live_market = evidence.get("focused_live_market") or {}
    if focused_live_market:
        compact["focused_live_market"] = {
            key: focused_live_market.get(key)
            for key in (
                "key",
                "name",
                "instrument",
                "symbol",
                "timezone",
                "status",
                "session_label",
                "session_status",
                "latest_price",
                "previous_close",
                "pct_change",
                "market_timestamp",
                "freshness",
                "interval",
            )
            if focused_live_market.get(key) is not None
        }
    live_alignment = evidence.get("live_alignment") or {}
    if live_alignment:
        compact["live_alignment"] = {
            key: live_alignment.get(key)
            for key in (
                "status",
                "target_market_date",
                "live_market_date",
                "rule",
            )
            if live_alignment.get(key) is not None
        }
    date_alignment = evidence.get("date_alignment") or {}
    if date_alignment:
        compact["date_alignment"] = {
            key: date_alignment.get(key)
            for key in (
                "status",
                "target_market_date",
                "aligned_indices",
                "available_indices",
                "sector_status",
                "sector_market_date",
                "breadth_status",
                "breadth_market_date",
            )
            if date_alignment.get(key) is not None
        }
    if question_focus:
        compact["question_focus"] = {
            key: question_focus.get(key)
            for key in ("key", "label")
            if question_focus.get(key) is not None
        }
    if not global_query:
        compact["market_state"] = focused_market_state(
            indices,
            market_key=market_key,
            original=evidence.get("market_state") or {},
        )
        if focus_key == "market_cause":
            compact["market_state"] = {
                key: compact["market_state"].get(key)
                for key in (
                    "label",
                    "coverage_ratio",
                    "average_return_1d_pct",
                    "advance_ratio",
                    "dispersion_pct",
                    "breadth_scope",
                    "whole_market_breadth_available",
                )
                if compact["market_state"].get(key) is not None
            }
    compact["indices"] = compact_indices
    compact["market_drivers"] = compact_drivers
    if focus_key == "market_cause" and causal_evidence:
        compact["causal_evidence"] = {
            key: causal_evidence.get(key)
            for key in (
                "target_market_date",
                "coverage_status",
                "candidate_count",
                "same_date_candidate_count",
                "source_count",
                "corroborated_categories",
                "boundary",
            )
            if causal_evidence.get(key) is not None
        }
        compact["causal_evidence"]["candidates"] = [
            {
                key: item.get(key)
                for key in (
                    "category_label",
                    "source",
                    "title",
                    "summary",
                    "published_at",
                    "published_market_date",
                    "date_relation",
                    "independent_sources",
                    "same_date_sources",
                    "support_level",
                )
                if item.get(key) is not None
            }
            for item in (causal_evidence.get("candidates") or [])[:4]
        ]
        for item in compact["causal_evidence"]["candidates"]:
            if item.get("title") is not None:
                item["title"] = str(item["title"])[:220]
            if item.get("summary") is not None:
                item["summary"] = str(item["summary"])[:240]
    industry_focus = evidence.get("industry_focus") or {}
    industry_snapshot = evidence.get("industry_snapshot") or {}
    if industry_focus.get("name"):
        compact["industry_focus"] = {
            key: industry_focus.get(key)
            for key in ("name", "market_scope", "requested_by_user")
            if industry_focus.get(key) is not None
        }
    if industry_snapshot:
        points = list(industry_snapshot.get("points") or [])
        target_point = next(
            (
                point
                for point in reversed(points)
                if str(point.get("market_date") or "") == target_market_date
            ),
            points[-1] if points else None,
        )
        component_analysis = industry_snapshot.get("component_analysis") or {}
        compact["industry_snapshot"] = {
            key: industry_snapshot.get(key)
            for key in (
                "status",
                "industry_name",
                "index_code",
                "index_name",
                "index_full_name",
                "index_description",
                "market_timestamp",
                "coverage",
                "constituents_as_of",
                "weights_as_of",
                "industry_mapping",
            )
            if industry_snapshot.get(key) is not None
        }
        compact_industry_metrics = {
            key: (industry_snapshot.get("metrics") or {}).get(key)
            for key in (
                "latest_close",
                "return_1d_pct",
                "return_5d_pct",
                "return_20d_pct",
                "return_60d_pct",
                "ma20",
                "ma60",
                "volatility_20d_annualized_pct",
                "max_drawdown_60d_pct",
                "trend_state",
            )
            if (industry_snapshot.get("metrics") or {}).get(key) is not None
        }
        latest_close = compact_industry_metrics.get("latest_close")
        for moving_average_key in ("ma20", "ma60"):
            moving_average = compact_industry_metrics.get(moving_average_key)
            if not isinstance(latest_close, (int, float)) or not isinstance(
                moving_average, (int, float)
            ):
                continue
            compact_industry_metrics[f"distance_to_{moving_average_key}_pct"] = round(
                (float(latest_close) / float(moving_average) - 1) * 100,
                1,
            )
        compact["industry_snapshot"]["metrics"] = compact_industry_metrics
        if target_point:
            compact["industry_snapshot"]["target_point"] = {
                key: target_point.get(key)
                for key in (
                    "market_date",
                    "close",
                    "change",
                    "pct_change",
                    "volume",
                    "turnover",
                    "constituent_count",
                )
                if target_point.get(key) is not None
            }
        if component_analysis:
            compact["industry_snapshot"]["component_analysis"] = {
                key: component_analysis.get(key)
                for key in (
                    "status",
                    "market_date",
                    "coverage",
                    "breadth",
                    "top_positive_contributors",
                    "top_negative_contributors",
                    "source_fallbacks",
                )
                if component_analysis.get(key) is not None
            }
    if "volume_ratio_5_20" in metric_keys:
        compact["metric_definitions"] = {
            "volume_ratio_5_20": (
                "最近5个交易日日均成交量 / 最近20个交易日日均成交量；"
                "不是当日成交量相对20日均量"
            )
        }
    if focus_key in {"trend_reversal", "market_risk"}:
        compact.setdefault("metric_definitions", {}).update(
            {
                "return_5d_pct": "最近5个交易日累计收益，不表示连续5日每天同向涨跌",
                "return_20d_pct": "最近20个交易日累计收益",
                "return_60d_pct": "最近60个交易日累计收益",
                "max_drawdown_60d_pct": (
                    "最近60日路径中的最大回撤；不是当前低位、累计损失或正常波动范围"
                ),
                "volatility_20d_annualized_pct": (
                    "由最近20日日收益估算的年化波动率；不能与路径最大回撤直接比较"
                ),
                "atr_14_pct": (
                    "14日平均真实波幅占收盘价比例；不能乘以天数累积后与最大回撤比较"
                ),
                "trend_state": (
                    "中期偏弱只表示当前证据下趋势确认不足，不等同已确认下行趋势"
                ),
            }
        )
    if "return_60d_pct" in metric_keys:
        compact.setdefault("metric_definitions", {}).setdefault(
            "return_60d_pct", "最近60个交易日累计收益"
        )
    if focus_key == "market_risk" and len(compact_indices) >= 2:
        first_volatility = (
            compact_indices[0].get("metrics", {}).get("volatility_20d_annualized_pct")
        )
        second_volatility = (
            compact_indices[1].get("metrics", {}).get("volatility_20d_annualized_pct")
        )
        if (
            isinstance(first_volatility, (int, float))
            and isinstance(second_volatility, (int, float))
            and float(first_volatility) != 0
        ):
            compact["relative_comparisons"] = {
                "volatility_20d_annualized": {
                    "numerator_name": compact_indices[1].get("name"),
                    "denominator_name": compact_indices[0].get("name"),
                    "ratio": round(
                        float(second_volatility) / float(first_volatility), 1
                    ),
                    "interpretation": (
                        "只表示分子指数年化波动率除以分母指数年化波动率；"
                        "不代表高低等级、正常区间或风险阈值"
                    ),
                }
            }

    if (market_key == "china" or global_query) and focus_key in {
        "market_overview",
        "market_cause",
        "sector_rotation",
        "volume_flows",
    }:
        hot_sectors = evidence.get("hot_sectors") or {}
        if hot_sectors.get("same_date_as_analysis_target") is not False:
            compact["hot_sectors"] = {
                key: hot_sectors.get(key)
                for key in (
                    "market_date",
                    "same_date_as_analysis_target",
                    "is_stale",
                    "coverage",
                )
                if hot_sectors.get(key) is not None
            }
            market_local_time = prompt_local_time(
                hot_sectors.get("market_timestamp"), "Asia/Shanghai"
            )
            if market_local_time:
                compact["hot_sectors"]["market_local_time"] = market_local_time
            sector_limit = 6 if focus_key == "sector_rotation" else 4
            sector_keys = ["code", "name", "pct_change"]
            if focus_key in {"sector_rotation", "volume_flows"}:
                sector_keys.extend(
                    ["main_net_inflow", "advancers", "decliners", "unchanged"]
                )
            compact["hot_sectors"]["sectors"] = [
                {key: item.get(key) for key in sector_keys if item.get(key) is not None}
                for item in (hot_sectors.get("sectors") or [])[:sector_limit]
            ]

    if (market_key == "china" or global_query) and focus_key in {
        "market_overview",
        "market_cause",
        "sector_rotation",
        "volume_flows",
    }:
        market_breadth = evidence.get("market_breadth") or {}
        if (
            market_breadth.get("status") == "available"
            and market_breadth.get("same_date_as_analysis_target") is not False
        ):
            compact["market_breadth"] = {
                "status": "available",
                "scope": market_breadth.get("scope"),
                "market_date": market_breadth.get("market_date"),
                "coverage": {
                    key: (market_breadth.get("coverage") or {}).get(key)
                    for key in (
                        "expected",
                        "returned",
                        "valid_change",
                        "coverage_ratio",
                        "latest_tick_time",
                    )
                    if (market_breadth.get("coverage") or {}).get(key) is not None
                },
                "breadth": {
                    key: (market_breadth.get("breadth") or {}).get(key)
                    for key in (
                        "total",
                        "advancers",
                        "decliners",
                        "unchanged",
                        "net_advancers",
                        "advance_ratio",
                        "decline_ratio",
                        "unchanged_ratio",
                        "state",
                        "classification_method",
                    )
                    if (market_breadth.get("breadth") or {}).get(key) is not None
                },
                "turnover": {
                    "status": (market_breadth.get("turnover") or {}).get("status"),
                    "currency": (market_breadth.get("turnover") or {}).get("currency"),
                    "total_amount_cny": (market_breadth.get("turnover") or {}).get(
                        "total_amount_cny"
                    ),
                    "total_amount_100m_cny": (market_breadth.get("turnover") or {}).get(
                        "total_amount_100m_cny"
                    ),
                    "coverage": (market_breadth.get("turnover") or {}).get("coverage"),
                    "exchanges": (market_breadth.get("turnover") or {}).get(
                        "exchanges"
                    ),
                    "history_comparison": (market_breadth.get("turnover") or {}).get(
                        "history_comparison"
                    ),
                    "interpretation": (market_breadth.get("turnover") or {}).get(
                        "interpretation"
                    ),
                },
                "distribution": {
                    key: (market_breadth.get("distribution") or {}).get(key)
                    for key in (
                        "status",
                        "coverage",
                        "median_pct_change",
                        "p25_pct_change",
                        "p75_pct_change",
                        "bins",
                        "bin_ratios",
                        "method",
                    )
                    if (market_breadth.get("distribution") or {}).get(key) is not None
                },
            }
            snapshot_local_time = prompt_local_time(
                market_breadth.get("fetched_at"), "Asia/Shanghai"
            )
            if snapshot_local_time:
                compact["market_breadth"]["snapshot_local_time"] = snapshot_local_time

    return compact


def focused_market_state(
    indices: list[dict[str, Any]],
    *,
    market_key: str,
    original: dict[str, Any],
) -> dict[str, Any]:
    returns = [
        float(item.get("metrics", {}).get("return_1d_pct"))
        for item in indices
        if item.get("status") != "unavailable"
        and isinstance(item.get("metrics", {}).get("return_1d_pct"), (int, float))
    ]
    total = len(indices)
    coverage = len(returns) / total if total else 0.0
    whole_market_state = {
        key: value for key, value in original.items() if key.startswith("whole_market_")
    }
    whole_market_state.setdefault("whole_market_breadth_available", False)
    if not returns:
        return {
            **original,
            "breadth_scope": f"{market_key}_representative_indices",
            **whole_market_state,
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
        "coverage_ratio": round(coverage, 4),
        "average_return_1d_pct": round(average_return, 4),
        "advance_ratio": round(advance_ratio, 4),
        "dispersion_pct": round(dispersion, 4),
        "breadth_scope": f"{market_key}_representative_indices",
        "method": "当前市场代表性指数一日收益的均值、上涨比例与离散度；不是全市场股票广度",
        **whole_market_state,
    }


def compact_market_knowledge_context(
    context: dict[str, Any],
) -> dict[str, Any]:
    items = list(context.get("items") or [])

    specific_market_titles = (
        "市场涨跌原因",
        "市场趋势与风险",
        "大盘分析规则",
    )

    preferred_items = sorted(
        (
            item
            for item in items
            if item.get("scope") == "user"
            or not any(
                phrase in str(item.get("title") or "")
                for phrase in (*specific_market_titles, "证据层级")
            )
        ),
        key=lambda item: 0 if item.get("scope") == "user" else 1,
    )
    specific_items = [
        item
        for item in items
        if any(
            phrase in str(item.get("title") or "")
            for phrase in specific_market_titles
        )
    ]
    if preferred_items:
        selected_items = preferred_items[:2]
    elif specific_items:
        selected_items = specific_items[:2]
    else:
        selected_items = []
    return {
        "query": context.get("query"),
        "coverage": context.get("coverage") or {},
        "items": [
            {
                key: item.get(key)
                for key in (
                    "title",
                    "scope",
                    "excerpt",
                    "relevance_score",
                    "updated_at",
                )
                if item.get(key) is not None
            }
            | (
                {"excerpt": str(item.get("excerpt") or "")[:500]}
                if item.get("excerpt")
                else {}
            )
            for item in selected_items
        ],
    }


def compact_market_conversation_history(
    history: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    # Market answers are regenerated from a fresh evidence packet. Feeding
    # the previous assistant prose back to the model encourages it to copy
    # the prior structure and can perpetuate an earlier weak inference.
    # User questions are enough to preserve conversational intent because
    # the market region is inherited separately from message metadata.
    return [
        {
            "role": "user",
            "content": str(item.get("content") or "")[:500],
        }
        for item in history
        if item.get("role") == "user"
    ][-4:]


def compact_stock_knowledge_context(
    context: dict[str, Any],
) -> dict[str, Any]:
    items = list(context.get("items") or [])
    selected = sorted(
        enumerate(items),
        key=lambda pair: (
            0 if pair[1].get("scope") == "user" else 1,
            pair[0],
        ),
    )[:3]
    return {
        "query": context.get("query"),
        "coverage": context.get("coverage") or {},
        "items": [
            {
                key: item.get(key)
                for key in (
                    "title",
                    "scope",
                    "relevance_score",
                    "updated_at",
                )
                if item.get(key) is not None
            }
            | (
                {"excerpt": str(item.get("excerpt") or "")[:500]}
                if item.get("excerpt")
                else {}
            )
            for _, item in selected
        ],
    }


def compact_stock_research_evidence(
    evidence: dict[str, Any],
) -> dict[str, Any]:
    def select(value: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
        return {key: value.get(key) for key in keys if value.get(key) is not None}

    def compact_events(items: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        return [
            select(
                item,
                (
                    "category",
                    "title",
                    "publisher",
                    "published_at",
                    "notice_date",
                    "form",
                    "filing_date",
                ),
            )
            for item in (items or [])[:4]
        ]

    compact = select(
        evidence,
        (
            "type",
            "generated_at",
            "symbol",
            "display_name",
            "user_question",
            "user_thesis",
            "facts",
            "metrics",
            "current_quote",
            "price_levels",
            "research_frame",
            "provenance",
            "evidence_debate",
            "module_statuses",
            "evidence_status",
            "research_evidence_contract",
        ),
    )
    plan = evidence.get("research_plan") or {}
    focus = str(plan.get("focus") or "comprehensive")
    compact["research_plan"] = select(
        plan,
        (
            "contract_version",
            "focus",
            "focus_label",
            "selected_modules",
            "selected_skills",
            "answer_requirements",
            "evidence_contract_version",
            "evidence_path",
        ),
    )
    question = str(evidence.get("user_question") or "")
    price_move_question = is_stock_price_move_question(question)
    needs_outlook = any(
        term in question
        for term in (
            "走势",
            "后续",
            "未来",
            "展望",
            "情景",
            "失效条件",
            "支撑",
            "阻力",
            "怎么看",
        )
    )
    outlook = evidence.get("conditional_outlook") or {}
    if outlook and needs_outlook:
        compact["conditional_outlook"] = {
            **select(
                outlook,
                (
                    "horizon",
                    "label",
                    "confidence",
                    "reasons",
                    "invalidation",
                    "warning",
                ),
            ),
            "scenarios": (outlook.get("scenarios") or [])[:3],
            "current_quote_alignment": select(
                outlook.get("current_quote_alignment") or {},
                (
                    "status",
                    "price",
                    "market_timestamp",
                    "quote_label",
                    "complete_daily_bar_confirmed",
                    "crossed_conditions",
                    "boundary",
                ),
            ),
        }

    claims = evidence.get("research_claims") or {}
    if claims.get("claims"):
        relation_priority = {"weakens": 0, "unresolved": 1, "supports": 2}
        selected_claims = sorted(
            list(claims.get("claims") or []),
            key=lambda item: relation_priority.get(str(item.get("relation")), 3),
        )[:7]
        compact["research_claims"] = {
            "status": claims.get("status"),
            "summary": claims.get("summary") or {},
            "claims": [
                select(
                    item,
                    (
                        "relation",
                        "claim",
                        "evidence_summary",
                        "evidence_type",
                        "published_at",
                        "data_time",
                        "report_period",
                        "trade_date",
                        "limitations",
                        "next_step",
                    ),
                )
                for item in selected_claims
            ],
            "information_gaps": (claims.get("information_gaps") or [])[:2],
            "invalidation_conditions": (
                (claims.get("invalidation_conditions") or [])[:2]
                if "失效" in question
                else []
            ),
            "boundary": claims.get("boundary"),
        }

    market_context = evidence.get("stock_market_context") or {}
    if market_context:
        industry = market_context.get("exact_industry_index") or {}
        breadth = market_context.get("market_breadth") or {}
        compact["stock_market_context"] = {
            **select(
                market_context,
                (
                    "generated_at",
                    "market_key",
                    "analysis_target",
                    "stock_target",
                    "company_industry",
                    "exact_industry_match_available",
                    "market_state",
                ),
            ),
            "indices": [
                select(
                    item,
                    (
                        "symbol",
                        "name",
                        "status",
                        "comparison_status",
                        "market_date",
                        "close",
                        "return_1d_pct",
                        "stock_minus_index_pct",
                    ),
                )
                for item in (market_context.get("indices") or [])[:4]
            ],
            "exact_industry_index": {
                **select(
                    industry,
                    (
                        "status",
                        "index_code",
                        "name",
                        "market_date",
                        "close",
                        "return_1d_pct",
                        "stock_return_1d_pct",
                        "stock_minus_industry_pct",
                        "constituent_count",
                        "subject_is_constituent",
                        "subject_weight_pct",
                    ),
                ),
                "industry_mapping": select(
                    industry.get("industry_mapping") or {},
                    (
                        "company_industry",
                        "index_industry",
                        "match_type",
                        "boundary",
                    ),
                ),
                "component_breadth": select(
                    industry.get("component_breadth") or {},
                    (
                        "status",
                        "market_date",
                        "total_constituents",
                        "available_returns",
                        "advancers",
                        "decliners",
                        "unchanged",
                        "median_pct_change",
                        "state",
                        "coverage",
                        "failures",
                        "source_fallbacks",
                        "boundary",
                    ),
                ),
            },
            "market_breadth": {
                **select(
                    breadth,
                    (
                        "status",
                        "market_date",
                        "same_date_as_target",
                        "latest_tick_time",
                        "coverage",
                        "breadth",
                    ),
                ),
                "turnover": select(
                    breadth.get("turnover") or {},
                    (
                        "status",
                        "currency",
                        "total_amount_100m_cny",
                        "history_comparison",
                        "interpretation",
                    ),
                ),
                "distribution": select(
                    breadth.get("distribution") or {},
                    (
                        "status",
                        "coverage",
                        "median_pct_change",
                        "p25_pct_change",
                        "p75_pct_change",
                    ),
                ),
            },
        }
        if any(term in question for term in ("贡献", "权重", "归因")):
            compact["stock_market_context"]["exact_industry_index"][
                "component_contribution"
            ] = industry.get("component_contribution") or {}

    if price_move_question:
        compact["price_move_event_evidence"] = compact_stock_price_move_event_evidence(
            evidence
        )

    knowledge = evidence.get("knowledge_context") or {}
    if knowledge.get("items"):
        compact["knowledge_context"] = {
            "query": knowledge.get("query"),
            "coverage": knowledge.get("coverage") or {},
            "items": [
                select(
                    item,
                    (
                        "title",
                        "scope",
                        "relevance_score",
                        "updated_at",
                    ),
                )
                | {"excerpt": str(item.get("excerpt") or "")[:600]}
                for item in (knowledge.get("items") or [])[:2]
            ],
        }

    workspace = evidence.get("stock_workspace_context") or {}
    if workspace:
        compact["stock_workspace_context"] = {
            **select(
                workspace,
                (
                    "contract_version",
                    "symbol",
                    "name",
                    "research_focus",
                    "relation",
                    "formal_thesis",
                    "research_entry",
                    "position",
                    "completeness",
                    "data_meta",
                    "boundary",
                ),
            ),
            "active_action_plans": (workspace.get("active_action_plans") or [])[:2],
            "active_observation_tasks": (
                workspace.get("active_observation_tasks") or []
            )[:2],
            "recent_trade_reviews": (workspace.get("recent_trade_reviews") or [])[:1],
            "important_changes": (workspace.get("important_changes") or [])[:1],
            "pending_actions": (workspace.get("pending_actions") or [])[:2],
        }

    if focus == "comprehensive":
        for key in ("analysis_board", "deep_stock_coverage", "research_change"):
            if evidence.get(key):
                compact[key] = evidence[key]

    information = evidence.get("a_share_information") or {}
    sentiment = information.get("sentiment") or {}
    if information:
        compact["a_share_information"] = {
            "announcements": compact_events(information.get("announcements")),
            "news": compact_events(information.get("news")),
            "sentiment": select(
                sentiment,
                (
                    "band",
                    "score",
                    "confidence",
                    "sample_size",
                    "positive_count",
                    "negative_count",
                    "neutral_count",
                    "method",
                ),
            ),
            "sentiment_caveat": (sentiment.get("evidence") or {}).get("caveat"),
        }

    global_information = evidence.get("global_information") or {}
    if global_information:
        compact["global_information"] = {
            "news": compact_events(global_information.get("news")),
        }

    fundamentals = evidence.get("fundamentals") or {}
    summary = fundamentals.get("summary") or {}
    if fundamentals:
        compact["fundamentals"] = {
            "valuation": select(
                fundamentals.get("valuation") or {},
                (
                    "symbol",
                    "name",
                    "currency",
                    "price",
                    "pct_change",
                    "turnover_rate_pct",
                    "pe_ttm",
                    "pe_dynamic",
                    "pe_static",
                    "pb",
                    "float_market_cap",
                    "total_market_cap",
                    "market_timestamp",
                    "fetched_at",
                ),
            ),
            "summary": select(
                summary,
                (
                    "latest_report",
                    "latest_annual_report",
                    "operating_cashflow_to_net_profit",
                    "facts",
                    "missing_context",
                ),
            ),
            "regulatory_filings": compact_events(
                fundamentals.get("regulatory_filings")
            ),
        }

    earnings_quality = evidence.get("earnings_quality") or {}
    if earnings_quality:
        compact["earnings_quality"] = select(
            earnings_quality,
            (
                "type",
                "symbol",
                "name",
                "status",
                "generated_at",
                "overall_label",
                "confidence",
                "summary",
                "latest_report",
                "comparable_report",
                "factors",
                "supports",
                "contradictions",
                "review_points",
                "coverage",
                "company_explanations",
                "filing_evidence",
                "boundary",
            ),
        )

    financial_drivers = evidence.get("financial_drivers") or {}
    if financial_drivers:
        compact["financial_drivers"] = select(
            financial_drivers,
            (
                "type",
                "symbol",
                "name",
                "status",
                "generated_at",
                "overall_label",
                "confidence",
                "summary",
                "latest_period",
                "comparable_period",
                "profit_bridge",
                "expense_analysis",
                "working_capital_analysis",
                "cashflow_analysis",
                "confirmed_mechanical_drivers",
                "plausible_clues",
                "company_explanations",
                "filing_evidence",
                "unresolved_causes",
                "review_points",
                "coverage",
                "boundary",
            ),
        )

    business_structure = evidence.get("business_structure") or {}
    if business_structure:
        compact_dimensions = []
        for dimension in business_structure.get("dimensions") or []:
            compact_dimensions.append(
                {
                    **select(
                        dimension,
                        (
                            "classification",
                            "label",
                            "current_report_date",
                            "comparable_report_date",
                            "report_basis",
                            "concentration",
                            "margin_coverage",
                        ),
                    ),
                    "segments": (dimension.get("segments") or [])[:6],
                    "margin_reference": dimension.get("margin_reference"),
                }
            )
        compact["business_structure"] = {
            **select(
                business_structure,
                (
                    "type",
                    "symbol",
                    "name",
                    "status",
                    "generated_at",
                    "anchor_report_date",
                    "latest_fetched_at",
                    "sources",
                    "summary",
                    "review_points",
                    "coverage",
                    "boundary",
                ),
            ),
            "dimensions": compact_dimensions,
            "key_changes": (business_structure.get("key_changes") or [])[:10],
        }

    shareholder_structure = evidence.get("shareholder_structure") or {}
    if shareholder_structure:
        compact["shareholder_structure"] = select(
            shareholder_structure,
            (
                "type",
                "symbol",
                "name",
                "status",
                "generated_at",
                "holder_count_as_of",
                "announced_at",
                "holder_count",
                "previous_holder_count",
                "holder_count_change",
                "holder_count_change_pct",
                "average_holding",
                "average_market_cap",
                "interval_price_change_pct",
                "previous_holder_count_as_of",
                "holder_count_signal",
                "holder_count_signal_label",
                "holder_count_statement",
                "recent_pattern",
                "holder_count_streak_direction",
                "holder_count_streak_count",
                "holder_history",
                "top10_report_date",
                "top10_ratio_pct",
                "top3_ratio_pct",
                "top10_historical_comparison_available",
                "top_holders",
                "top_holders_statement",
                "special_name_notes",
                "summary",
                "review_points",
                "coverage",
                "boundary",
            ),
        )

    analyst_expectations = evidence.get("analyst_expectations") or {}
    if analyst_expectations:
        compact["analyst_expectations"] = {
            **select(
                analyst_expectations,
                (
                    "type",
                    "symbol",
                    "name",
                    "industry",
                    "status",
                    "generated_at",
                    "as_of_date",
                    "latest_report_date",
                    "rating_window",
                    "rating_organization_count",
                    "rating_counts",
                    "rating_statement",
                    "forecast_eps",
                    "forecast_statement",
                    "revision",
                    "review_points",
                    "coverage",
                    "boundary",
                ),
            ),
            "latest_reports": (analyst_expectations.get("latest_reports") or [])[:6],
        }

    event_timeline = evidence.get("event_timeline") or {}
    if event_timeline:
        event_limit = 6 if focus == "events" else 4
        compact["event_timeline"] = {
            **select(
                event_timeline,
                (
                    "type",
                    "symbol",
                    "name",
                    "status",
                    "generated_at",
                    "as_of_date",
                    "themes",
                    "coverage",
                    "review_points",
                    "boundary",
                ),
            ),
            "events": [
                select(
                    item,
                    (
                        "event_type",
                        "event_label",
                        "title",
                        "published_at",
                        "event_date",
                        "category",
                        "evidence_level",
                        "evidence_label",
                        "event_status",
                        "research_relevance",
                        "research_relevance_label",
                    ),
                )
                for item in (event_timeline.get("events") or [])[:event_limit]
            ],
        }

    peers = evidence.get("peer_comparison") or {}
    if peers:
        compact["peer_comparison"] = select(
            peers,
            (
                "group_label",
                "selection_basis",
                "coverage",
                "metrics",
                "peers",
                "operating_comparison",
                "as_of",
            ),
        )
    if price_move_question:
        compact_market_context = compact.get("stock_market_context") or {}
        compact_breadth = compact_market_context.get("market_breadth") or {}
        if not any(term in question for term in ("成交额", "量能", "放量", "缩量")):
            compact_breadth.pop("turnover", None)
        if not any(term in question for term in ("涨跌分布", "中位数", "四分位")):
            compact_breadth.pop("distribution", None)
        compact["metrics"] = select(
            evidence.get("metrics") or {},
            ("latest_close", "return_1d_pct"),
        )
        compact["provenance"] = select(
            evidence.get("provenance") or {},
            ("market_timestamp", "is_stale"),
        )
        allowed = (
            "type",
            "generated_at",
            "symbol",
            "display_name",
            "user_question",
            "current_quote",
            "metrics",
            "provenance",
            "research_plan",
            "stock_market_context",
            "price_move_event_evidence",
            "research_evidence_contract",
        )
        return {
            key: compact[key]
            for key in allowed
            if compact.get(key) not in (None, "", [], {})
        }
    return compact


def compact_stock_comparison_evidence(
    evidence: dict[str, Any],
) -> dict[str, Any]:
    items = []
    for item in (evidence.get("items") or [])[:5]:
        compact_item = {
            key: item.get(key)
            for key in (
                "symbol",
                "name",
                "market",
                "status",
                "snapshot",
                "limitations",
            )
            if item.get(key) not in (None, [], {}, "")
        }
        item_evidence = item.get("evidence") or {}
        compact_item["evidence"] = {
            key: item_evidence.get(key)
            for key in (
                "symbol",
                "display_name",
                "current_quote",
                "metrics",
                "provenance",
                "user_thesis",
                "fundamentals",
                "earnings_quality",
                "financial_drivers",
                "business_structure",
                "analyst_expectations",
                "event_timeline",
                "company_information",
                "evidence_debate",
                "conditional_outlook",
            )
            if item_evidence.get(key) not in (None, [], {}, "")
        }
        items.append(compact_item)
    return {
        key: evidence.get(key)
        for key in (
            "contract_version",
            "type",
            "status",
            "generated_at",
            "user_question",
            "symbols",
            "targets",
            "available_symbols",
            "unavailable_symbols",
            "comparison_focus",
            "comparison_basis",
            "warnings",
            "boundary",
        )
        if evidence.get(key) not in (None, [], {}, "")
    } | {"items": items}


def compact_research_actions_evidence(
    evidence: dict[str, Any],
) -> dict[str, Any]:
    compact_items = []
    for item in evidence.get("items") or []:
        actions = list(item.get("actions") or [])
        selected = [
            *[action for action in actions if action.get("status") == "triggered"][:3],
            *[action for action in actions if action.get("status") == "pending_data"][
                :2
            ],
            *[action for action in actions if action.get("status") == "watching"][:1],
        ]
        compact_items.append(
            {
                key: item.get(key)
                for key in (
                    "symbol",
                    "name",
                    "thesis",
                    "research_status",
                    "research_status_label",
                    "priority_score",
                    "priority_label",
                    "data_as_of",
                    "headline",
                )
                if item.get(key) is not None
            }
            | {
                "actions": [
                    {
                        key: action.get(key)
                        for key in (
                            "key",
                            "category",
                            "title",
                            "status",
                            "severity",
                            "condition",
                            "current_evidence",
                            "next_step",
                        )
                        if action.get(key) is not None
                    }
                    | (
                        {"checks": list(action.get("checks") or [])[:2]}
                        if action.get("checks")
                        else {}
                    )
                    for action in selected
                ]
            }
        )
    return {
        key: evidence.get(key)
        for key in (
            "type",
            "generated_at",
            "method",
            "summary",
            "status_legend",
            "boundary",
        )
        if evidence.get(key) is not None
    } | {"items": compact_items}


def compact_stock_screen_evidence(
    evidence: dict[str, Any],
) -> dict[str, Any]:
    if (evidence.get("profile") or {}).get("key") == "li_zong":
        return evidence

    source_items = list(evidence.get("items") or [])
    items: list[dict[str, Any]] = []
    for item in source_items[:12]:
        missing_reasons = [
            {
                key: reason.get(key)
                for key in ("field", "reason")
                if reason.get(key) not in (None, "")
            }
            for reason in (item.get("missing_reasons") or [])[:8]
            if isinstance(reason, dict)
        ]
        compact_item = {
            key: item.get(key)
            for key in (
                "name",
                "internal_symbol",
                "industry",
                "market",
                "list_date",
                "metrics",
                "financials",
                "evidence_times",
                "coverage_status",
                "matched_reasons",
                "missing_fields",
                "not_applicable_fields",
                "limitations",
            )
            if item.get(key) not in (None, [], {}, "")
        }
        if missing_reasons:
            compact_item["missing_reasons"] = missing_reasons
        items.append(compact_item)

    contract = evidence.get("data_contract") or {}
    compact_contract = {
        key: contract.get(key)
        for key in (
            "contract_version",
            "data_version",
            "market_scope",
            "universe_definition",
            "as_of",
            "coverage",
            "representation",
            "sources",
            "license_boundary",
        )
        if contract.get(key) not in (None, [], {}, "")
    }
    compact = {
        key: evidence.get(key)
        for key in (
            "type",
            "status",
            "profile",
            "rules",
            "effective_filters",
            "data_meta",
            "universe",
            "warnings",
            "boundary",
            "user_question",
        )
        if evidence.get(key) not in (None, [], {}, "")
    }
    if compact_contract:
        compact["data_contract"] = compact_contract
    compact["candidate_count_total"] = len(source_items)
    compact["items_in_prompt"] = len(items)
    compact["items"] = items
    return compact
