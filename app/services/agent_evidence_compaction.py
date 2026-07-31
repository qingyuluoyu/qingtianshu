from __future__ import annotations

from datetime import datetime
from statistics import mean, pstdev
from typing import Any
from zoneinfo import ZoneInfo

from app.services.live_market import previous_market_session_date
from app.services.stock_price_move import (
    compact_stock_price_move_event_evidence,
    is_deep_stock_price_move_question,
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
    prior_questions = [
        str(item)
        for item in (evidence.get("_conversation_user_questions") or [])
        if str(item).strip()
    ]
    question_context = "\n".join((question, *prior_questions))
    cause_query = focus_key == "market_cause" or any(
        term in question_context for term in ("为什么", "为何", "原因", "反差")
    )
    observation_followup = bool(prior_questions) and any(
        term in question for term in ("接下来", "最值得看", "观察", "不要重复")
    )
    concise_market_observation = observation_followup or (
        cause_query and focus_key == "market_risk"
    )
    cross_date_comparison = any(
        term in question_context
        for term in ("今天", "今日", "当前", "盘中", "午间")
    ) and any(
        term in question_context
        for term in ("昨天", "昨日", "上一交易日", "前一交易日", "前日")
    )
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
        "market_cause": ("return_1d_pct",),
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
    if observation_followup:
        metric_keys = ("latest_close", "ma20", "ma60", "trend_state")
    elif cause_query and focus_key == "market_risk":
        metric_keys = (
            "latest_close",
            "return_1d_pct",
            "ma20",
            "ma60",
            "trend_state",
        )
    if not observation_followup and "60日" in question and any(
        term in question for term in ("收益", "涨幅", "跌幅", "涨跌")
    ):
        metric_keys = tuple(dict.fromkeys((*metric_keys, "return_60d_pct")))
    latest_bar_keys = (
        ("timestamp", "open", "high", "low", "close", "volume")
        if focus_key in {"volume_flows", "market_risk"}
        and not cause_query
        and not observation_followup
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
            key: item.get(key) for key in identity_keys if item.get(key) is not None
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
        if cross_date_comparison and target_market_date and interval == "1d":
            recent_bars = list(item.get("recent_bars") or [])
            item_market_key = str(item.get("group") or market_key)
            timezone_name = {
                "china": "Asia/Shanghai",
                "hong_kong": "Asia/Hong_Kong",
                "us": "America/New_York",
                "europe": "Europe/London",
                "japan": "Asia/Tokyo",
                "korea": "Asia/Seoul",
            }.get(item_market_key, "UTC")
            target_index = next(
                (
                    index
                    for index, bar in enumerate(recent_bars)
                    if prompt_market_date(bar.get("timestamp"), timezone_name)
                    == target_market_date
                ),
                None,
            )
            if target_index is not None and target_index >= 2:
                previous_bar = recent_bars[target_index - 1]
                previous_previous_bar = recent_bars[target_index - 2]
                previous_date = prompt_market_date(
                    previous_bar.get("timestamp"), timezone_name
                )
                previous_previous_date = prompt_market_date(
                    previous_previous_bar.get("timestamp"), timezone_name
                )
                expected_previous_date = previous_market_session_date(
                    item_market_key, target_market_date
                )
                expected_previous_previous_date = previous_market_session_date(
                    item_market_key, previous_date
                )
                previous_close = previous_bar.get("close")
                previous_previous_close = previous_previous_bar.get("close")
                if (
                    previous_date == expected_previous_date
                    and previous_previous_date == expected_previous_previous_date
                    and isinstance(previous_close, (int, float))
                    and isinstance(previous_previous_close, (int, float))
                    and previous_previous_close
                ):
                    compact_item["previous_market_date"] = previous_date
                    compact_item["previous_return_1d_pct"] = round(
                        (
                            float(previous_close) / float(previous_previous_close)
                            - 1
                        )
                        * 100,
                        4,
                    )
        latest_close = metrics.get("latest_close")
        moving_average_keys = (
            ()
            if focus_key == "market_cause"
            or cause_query
            or observation_followup
            else ("ma20", "ma60")
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
        if observation_followup
        else 0
        if cause_query and causal_evidence
        else 4
        if cause_query
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
    if cross_date_comparison:
        compact["cross_date_comparison"] = True
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
        visible_available_indices = sum(
            item.get("status") != "unavailable" for item in compact_indices
        )
        if "available_indices" in compact["date_alignment"]:
            compact["date_alignment"]["available_indices"] = visible_available_indices
        if "aligned_indices" in compact["date_alignment"]:
            compact["date_alignment"]["aligned_indices"] = visible_available_indices
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
        if focus_key == "market_cause" or concise_market_observation:
            compact["market_state"] = {
                key: compact["market_state"].get(key)
                for key in (
                    "label",
                    "whole_market_breadth_available",
                    "whole_market_breadth_state",
                    "whole_market_advancers",
                    "whole_market_decliners",
                    "whole_market_unchanged",
                )
                if compact["market_state"].get(key) is not None
            }
    compact["indices"] = compact_indices
    compact["market_drivers"] = compact_drivers
    if cause_query and causal_evidence and not observation_followup:
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
        compact_candidates: list[dict[str, Any]] = []
        seen_candidate_titles: list[str] = []

        def causal_candidate_rank(item: dict[str, Any]) -> int:
            title = str(item.get("title") or "")
            if any(
                term in title
                for term in ("跌停", "大跌", "重挫", "下挫", "下跌", "跳水")
            ):
                return 0
            if any(
                term in title
                for term in ("逆市", "收红", "走强", "上涨", "大涨", "扩大")
            ):
                return 1
            return 2

        for item in sorted(
            causal_evidence.get("candidates") or [], key=causal_candidate_rank
        ):
            title = str(item.get("title") or "").strip()
            normalized_title = "".join(character for character in title if character.isalnum())
            if not title or any(
                normalized_title in existing or existing in normalized_title
                for existing in seen_candidate_titles
            ):
                continue
            seen_candidate_titles.append(normalized_title)
            compact_candidates.append(
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
            )
            if len(compact_candidates) >= 3:
                break
        compact["causal_evidence"]["candidates"] = compact_candidates
        for item in compact["causal_evidence"]["candidates"]:
            if item.get("title") is not None:
                item["title"] = str(item["title"])[:220]
            if item.get("summary") is not None:
                item["summary"] = str(item["summary"])[:240]
    industry_focus = evidence.get("industry_focus") or {}
    industry_snapshot = evidence.get("industry_snapshot") or {}
    generic_industry_names = {
        "行业",
        "板块",
        "热门",
        "热点",
        "热门板块",
        "热点板块",
    }
    if industry_focus.get("name") and str(
        industry_focus.get("name")
    ) not in generic_industry_names:
        compact["industry_focus"] = {
            key: industry_focus.get(key)
            for key in ("name", "market_scope", "requested_by_user")
            if industry_focus.get(key) is not None
        }
    if (
        industry_snapshot
        and str(industry_focus.get("name") or "") not in generic_industry_names
    ):
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
    if focus_key == "trend_reversal" or (
        focus_key == "market_risk" and not concise_market_observation
    ):
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
    if (
        focus_key == "market_risk"
        and not concise_market_observation
        and len(compact_indices) >= 2
    ):
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

    if not observation_followup and (market_key == "china" or global_query) and (
        focus_key
        in {
        "market_overview",
        "market_cause",
        "sector_rotation",
        "volume_flows",
        }
        or cause_query
    ):
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
        "market_risk",
        "sector_rotation",
        "volume_flows",
    }:
        market_breadth = evidence.get("market_breadth") or {}
        if (
            market_breadth.get("status") == "available"
            and (
                market_breadth.get("same_date_as_analysis_target") is not False
                or cross_date_comparison
            )
        ):
            breadth_keys = (
                ("total", "advancers", "decliners", "unchanged", "state")
                if concise_market_observation
                else (
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
            )
            raw_turnover = market_breadth.get("turnover") or {}
            if concise_market_observation:
                history_comparison = raw_turnover.get("history_comparison") or {}
                compact_turnover = {
                    key: raw_turnover.get(key)
                    for key in ("status", "currency", "total_amount_100m_cny")
                    if raw_turnover.get(key) is not None
                }
                compact_history_comparison = {
                    key: history_comparison.get(key)
                    for key in (
                        "status",
                        "previous_market_date",
                        "change_vs_previous_pct",
                        "previous_5d_average_amount_cny",
                        "change_vs_previous_5d_average_pct",
                        "previous_20d_average_amount_cny",
                        "change_vs_previous_20d_average_pct",
                        "available_prior_sessions",
                        "method",
                    )
                    if history_comparison.get(key) is not None
                }
                if compact_history_comparison:
                    compact_turnover["history_comparison"] = (
                        compact_history_comparison
                    )
                compact_distribution: dict[str, Any] = {}
            else:
                compact_turnover = {
                    "status": raw_turnover.get("status"),
                    "currency": raw_turnover.get("currency"),
                    "total_amount_cny": raw_turnover.get("total_amount_cny"),
                    "total_amount_100m_cny": raw_turnover.get(
                        "total_amount_100m_cny"
                    ),
                    "coverage": raw_turnover.get("coverage"),
                    "exchanges": raw_turnover.get("exchanges"),
                    "history_comparison": raw_turnover.get("history_comparison"),
                    "interpretation": raw_turnover.get("interpretation"),
                }
                compact_distribution = {
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
                }
            compact["market_breadth"] = {
                "status": "available",
                "scope": market_breadth.get("scope"),
                "market_date": market_breadth.get("market_date"),
                "same_date_as_analysis_target": market_breadth.get(
                    "same_date_as_analysis_target"
                ),
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
                    for key in breadth_keys
                    if (market_breadth.get("breadth") or {}).get(key) is not None
                },
                "turnover": compact_turnover,
                "distribution": compact_distribution,
            }
            if not compact_turnover:
                compact["market_breadth"].pop("turnover", None)
            if not compact_distribution:
                compact["market_breadth"].pop("distribution", None)
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
            phrase in str(item.get("title") or "") for phrase in specific_market_titles
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


def compact_stock_conversation_history(
    history: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    # Each stock turn rebuilds current quotes, financial statements and event
    # evidence. Re-sending prior assistant prose both wastes context and lets a
    # deterministic fallback or an older weak interpretation influence the new
    # DeepSeek answer. User questions preserve the research thread; current
    # evidence and the bound stock workspace restore the actual facts.
    questions: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in reversed(history):
        if item.get("role") != "user":
            continue
        content = str(item.get("content") or "")[:600]
        normalized = " ".join(content.split()).casefold()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        questions.append({"role": "user", "content": content})
        if len(questions) >= 6:
            break
    return list(reversed(questions))


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
        compacted = []
        for item in (items or [])[:4]:
            compact_item = select(
                item,
                (
                    "category",
                    "title",
                    "publisher",
                    "published_at",
                    "notice_date",
                    "form",
                    "filing_date",
                    "summary",
                ),
            )
            if compact_item.get("summary"):
                compact_item["summary"] = str(compact_item["summary"])[:500]
            alignment = event_price_window_alignment(item)
            if alignment:
                compact_item["price_window_alignment"] = alignment
            compacted.append(compact_item)
        return compacted

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
    if focus == "relative_industry":
        market_context = evidence.get("stock_market_context") or {}
        industry = market_context.get("exact_industry_index") or {}
        component_breadth = industry.get("component_breadth") or {}
        coverage = component_breadth.get("coverage") or {}
        prompt_industry = select(
            industry,
            (
                "status",
                "index_code",
                "name",
                "market_date",
                "return_1d_pct",
                "stock_return_1d_pct",
                "stock_minus_industry_pct",
                "constituent_count",
                "subject_is_constituent",
                "subject_weight_pct",
            ),
        )
        for key in (
            "return_1d_pct",
            "stock_return_1d_pct",
            "stock_minus_industry_pct",
            "subject_weight_pct",
        ):
            value = prompt_industry.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                prompt_industry[key] = round(float(value), 2)
        relative_compact = select(
            evidence,
            (
                "type",
                "generated_at",
                "symbol",
                "display_name",
                "user_question",
                "evidence_status",
            ),
        )
        relative_compact["metrics"] = select(
            evidence.get("metrics") or {},
            (
                "latest_close",
                "return_1d_pct",
                "return_1d_base_date",
                "return_1d_end_date",
                "return_60d_pct",
                "ma60",
                "volatility_20d_annualized_pct",
                "max_drawdown_60d_pct",
            ),
        )
        relative_compact["provenance"] = select(
            evidence.get("provenance") or {},
            ("market_timestamp", "is_stale"),
        )
        relative_compact["research_plan"] = compact["research_plan"]
        relative_compact["research_evidence_contract"] = select(
            evidence.get("research_evidence_contract") or {},
            (
                "contract_version",
                "path",
                "answer_source",
                "boundary",
                "data_times",
            ),
        )
        relative_compact["stock_market_context"] = {
            **select(
                market_context,
                (
                    "generated_at",
                    "company_industry",
                    "exact_industry_match_available",
                    "analysis_target",
                ),
            ),
            "exact_industry_index": {
                **prompt_industry,
                "industry_mapping": select(
                    industry.get("industry_mapping") or {},
                    (
                        "company_industry",
                        "index_industry",
                        "match_type",
                        "boundary",
                    ),
                ),
                "component_breadth": {
                    **select(
                        component_breadth,
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
                            "boundary",
                        ),
                    ),
                    "coverage": select(
                        coverage,
                        (
                            "constituents",
                            "available_returns",
                            "missing_returns",
                            "coverage_ratio",
                            "primary_adjusted_returns",
                            "fallback_unadjusted_returns",
                        ),
                    ),
                    "source_fallbacks": [
                        select(
                            item,
                            (
                                "symbol",
                                "name",
                                "public_source_label",
                                "adjustment",
                            ),
                        )
                        for item in (component_breadth.get("source_fallbacks") or [])[
                            :2
                        ]
                    ],
                },
            },
        }
        return relative_compact
    question = str(evidence.get("user_question") or "")
    metrics = evidence.get("metrics") or {}
    research_entry = (evidence.get("stock_workspace_context") or {}).get(
        "research_entry"
    ) or {}
    price_window_context = " ".join(
        [
            question,
            str(research_entry.get("research_focus") or ""),
            *[str(item) for item in (research_entry.get("matched_reasons") or [])],
        ]
    )
    compact_price_window_context = "".join(price_window_context.split())
    requested_price_windows: dict[str, dict[str, str]] = {}
    for days in (5, 20, 60):
        if not any(
            token in compact_price_window_context
            for token in (f"{days}日", f"{days}天", f"{days}个交易日")
        ):
            continue
        start = prompt_market_date(
            metrics.get(f"return_{days}d_base_date"), "Asia/Shanghai"
        )
        end = prompt_market_date(
            metrics.get(f"return_{days}d_end_date"), "Asia/Shanghai"
        )
        if start and end:
            requested_price_windows[f"return_{days}d"] = {
                "start_date": start,
                "end_date": end,
                "definition": f"最近{days}个交易日累计收益对应的价格窗口",
            }

    def event_price_window_alignment(item: dict[str, Any]) -> dict[str, Any]:
        raw_event_date = (
            item.get("event_date")
            or item.get("published_at")
            or item.get("notice_date")
            or item.get("filing_date")
        )
        event_date = prompt_market_date(raw_event_date, "Asia/Shanghai")
        if not event_date or not requested_price_windows:
            return {}
        alignment: dict[str, Any] = {"event_date": event_date}
        for key, window in requested_price_windows.items():
            if event_date < window["start_date"]:
                relation = "before_window"
            elif event_date > window["end_date"]:
                relation = "after_window"
            else:
                relation = "inside_window"
            alignment[key] = {
                "relation": relation,
                "window_start": window["start_date"],
                "window_end": window["end_date"],
            }
        return alignment

    if requested_price_windows:
        compact["requested_price_windows"] = requested_price_windows
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
            "重新判断",
            "什么情况会推翻",
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
        target_market_date = str(
            (market_context.get("analysis_target") or {}).get("market_date") or ""
        )[:10]
        breadth_market_date = str(breadth.get("market_date") or "")[:10]
        breadth_matches_target = breadth.get("same_date_as_target") is True or bool(
            target_market_date
            and breadth_market_date
            and target_market_date == breadth_market_date
        )
        if price_move_question and not breadth_matches_target:
            breadth = {}
        component_breadth = industry.get("component_breadth") or {}
        source_scope_question = any(
            term in question
            for term in ("数据源", "行情源", "口径", "未复权", "复权", "除权除息")
        )
        prompt_component_breadth = select(
            component_breadth,
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
                "failures",
                "boundary",
            ),
        )
        coverage_keys = [
            "constituents",
            "available_returns",
            "missing_returns",
            "coverage_ratio",
        ]
        if source_scope_question:
            coverage_keys.extend(
                ("primary_adjusted_returns", "fallback_unadjusted_returns")
            )
        prompt_component_breadth["coverage"] = select(
            component_breadth.get("coverage") or {}, tuple(coverage_keys)
        )
        if not prompt_component_breadth["coverage"]:
            prompt_component_breadth.pop("coverage", None)
        if source_scope_question:
            prompt_component_breadth["source_fallbacks"] = [
                select(
                    item,
                    (
                        "symbol",
                        "name",
                        "public_source_label",
                        "adjustment",
                    ),
                )
                for item in (component_breadth.get("source_fallbacks") or [])[:3]
            ]
        industry_keys = [
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
        ]
        if any(term in question for term in ("贡献", "权重", "归因")):
            industry_keys.append("subject_weight_pct")
        raw_indices = list(market_context.get("indices") or [])
        if price_move_question:
            raw_indices = [
                item
                for item in raw_indices
                if item.get("comparison_status") in {None, "same_market_date"}
            ]
            preferred_symbols = (
                ("399001.SZ", "000001.SS")
                if str(evidence.get("symbol") or "").endswith(".SZ")
                else ("000001.SS", "399001.SZ")
            )
            ordered_indices = [
                item
                for symbol in preferred_symbols
                for item in raw_indices
                if item.get("symbol") == symbol
            ]
            ordered_indices.extend(
                item for item in raw_indices if item not in ordered_indices
            )
            raw_indices = ordered_indices[:2]
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
                for item in raw_indices[:4]
            ],
            "exact_industry_index": {
                **select(
                    industry,
                    tuple(industry_keys),
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
                "component_breadth": prompt_component_breadth,
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
        if not breadth:
            compact["stock_market_context"].pop("market_breadth", None)
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
                    "segments": [
                        select(
                            segment,
                            (
                                "item_name",
                                "revenue",
                                "revenue_share_pct",
                                "gross_profit_share_pct",
                                "gross_margin_pct",
                                "comparison_status",
                                "comparable_revenue_share_pct",
                                "comparable_gross_margin_pct",
                                "revenue_growth_pct",
                                "revenue_share_change_pp",
                                "gross_margin_change_pp",
                            ),
                        )
                        for segment in (dimension.get("segments") or [])[:6]
                    ],
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
                    "coverage_limits",
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
        event_items = list(event_timeline.get("events") or [])
        if focus == "events":
            recent_events = event_items[:4]
            direct_events = [
                item
                for item in event_items
                if item.get("direct_excerpt") and item not in recent_events
            ][:2]
            event_items = sorted(
                [*recent_events, *direct_events],
                key=lambda item: str(
                    item.get("published_at") or item.get("event_date") or ""
                ),
                reverse=True,
            )
        if focus == "quality_review":
            event_items = [
                item
                for item in event_items
                if item.get("evidence_level") == "official_disclosure"
            ]
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
                        "source",
                        "url",
                    ),
                )
                | (
                    {"direct_excerpt": str(item.get("direct_excerpt") or "")[:1200]}
                    if item.get("direct_excerpt")
                    else {}
                )
                | (
                    {"price_window_alignment": alignment}
                    if (alignment := event_price_window_alignment(item))
                    else {}
                )
                for item in event_items[:event_limit]
            ],
        }

    if focus in {"mixed", "quality_review", "valuation_review"}:
        folded_question = question.casefold().replace(" ", "")
        needs_market_comparison = any(
            term in folded_question
            for term in (
                "大盘",
                "市场",
                "指数",
                "行业",
                "板块",
                "系统性",
                "同步",
                "分化",
                "拖累",
                "跑赢",
                "跑输",
                "相对",
            )
        )
        if not needs_market_comparison:
            compact.pop("stock_market_context", None)

        # research_claims already keeps the most relevant supporting,
        # weakening and unresolved claims.  Sending the full debate board as a
        # second copy makes mixed questions slower and encourages report-like
        # repetition without adding source facts.
        if compact.get("research_claims"):
            compact.pop("evidence_debate", None)

        report_keys = (
            "report_date",
            "report_type",
            "report_date_name",
            "notice_date",
            "currency",
            "period_basis",
            "period_basis_label",
            "revenue",
            "revenue_yoy_pct",
            "revenue_growth_pct",
            "parent_net_profit",
            "net_profit_yoy_pct",
            "net_profit_growth_pct",
            "gross_margin_pct",
            "net_margin_pct",
            "debt_asset_ratio_pct",
            "operating_cashflow",
            "operating_cashflow_to_net_profit",
        )

        compact_fundamentals = compact.get("fundamentals") or {}
        if compact_fundamentals:
            full_summary = compact_fundamentals.get("summary") or {}
            compact_summary = select(
                full_summary,
                ("operating_cashflow_to_net_profit", "missing_context"),
            )
            latest_report = select(full_summary.get("latest_report") or {}, report_keys)
            if latest_report:
                compact_summary["latest_report"] = latest_report
            compact_fundamentals["summary"] = compact_summary
            if not any(
                term in folded_question
                for term in (
                    "估值",
                    "市盈率",
                    "市净率",
                    "pe",
                    "pb",
                    "便宜",
                    "贵不贵",
                    "低估",
                )
            ):
                compact_fundamentals.pop("valuation", None)
            if not compact_fundamentals.get("regulatory_filings"):
                compact_fundamentals.pop("regulatory_filings", None)

        compact_quality = compact.get("earnings_quality") or {}
        if compact_quality:
            compact_quality["latest_report"] = select(
                compact_quality.get("latest_report") or {}, report_keys
            )
            compact_quality["comparable_report"] = select(
                compact_quality.get("comparable_report") or {}, report_keys
            )
            compact_quality["factors"] = [
                select(
                    item,
                    ("key", "label", "status", "interpretation"),
                )
                for item in (compact_quality.get("factors") or [])[:6]
            ]
            compact_quality["review_points"] = (
                compact_quality.get("review_points") or []
            )[:2]

        compact_drivers = compact.get("financial_drivers") or {}
        if compact_drivers:
            compact_drivers["latest_period"] = select(
                compact_drivers.get("latest_period") or {}, report_keys
            )
            compact_drivers["comparable_period"] = select(
                compact_drivers.get("comparable_period") or {}, report_keys
            )
            drivers = sorted(
                compact_drivers.get("confirmed_mechanical_drivers") or [],
                key=lambda item: abs(float(item.get("amount") or 0)),
                reverse=True,
            )[:5]
            compact_drivers["confirmed_mechanical_drivers"] = [
                select(
                    item,
                    (
                        "key",
                        "label",
                        "direction",
                        "statement",
                        "calculation_nature",
                        "interpretation_boundary",
                    ),
                )
                for item in drivers
            ]
            compact_drivers["cashflow_analysis"] = select(
                compact_drivers.get("cashflow_analysis") or {},
                (
                    "operating_cashflow",
                    "comparable_operating_cashflow",
                    "operating_cashflow_change",
                    "operating_cashflow_change_pct",
                    "operating_cashflow_to_net_profit",
                    "comparable_operating_cashflow_to_net_profit",
                    "cash_received_from_sales_to_revenue_pct",
                    "comparable_cash_received_from_sales_to_revenue_pct",
                    "investing_cashflow",
                    "financing_cashflow",
                ),
            )
            compact_drivers["plausible_clues"] = [
                select(item, ("key", "label", "evidence"))
                for item in (compact_drivers.get("plausible_clues") or [])[:2]
            ]
            filing = compact_drivers.get("filing_evidence") or {}
            if filing:
                compact_drivers["filing_evidence"] = {
                    **select(filing, ("status", "summary", "boundary")),
                    "document": select(
                        filing.get("document") or {},
                        (
                            "title",
                            "document_type",
                            "report_period",
                            "notice_date",
                            "published_at",
                            "source_url",
                        ),
                    ),
                    "explicit_company_explanations": (
                        filing.get("explicit_company_explanations") or []
                    )[:2],
                    "unresolved_themes": (filing.get("unresolved_themes") or [])[:4],
                }
            for duplicate_key in (
                "profit_bridge",
                "expense_analysis",
                "working_capital_analysis",
                "company_explanations",
                "coverage",
            ):
                compact_drivers.pop(duplicate_key, None)
            compact_drivers["unresolved_causes"] = (
                compact_drivers.get("unresolved_causes") or []
            )[:2]
            compact_drivers["review_points"] = (
                compact_drivers.get("review_points") or []
            )[:2]

    if focus == "valuation_review":
        # 估值约束专项只保留估值截面、同日同行、同报告期财务质量、
        # 现金流、主营结构、预期 EPS 和直接披露。技术指标、历史研究板、
        # 泛新闻和完整对话检索会显著放大 Prompt，并诱导模型用价格故事
        # 或旧报告替代本轮估值核验。
        for key in (
            "facts",
            "metrics",
            "current_quote",
            "price_levels",
            "provenance",
            "research_frame",
            "evidence_debate",
            "research_claims",
            "stock_market_context",
            "conditional_outlook",
            "price_move_event_evidence",
            "outlook_calibration",
            "knowledge_context",
            "global_information",
            "module_statuses",
            "evidence_status",
            "li_zong_strategy",
        ):
            compact.pop(key, None)

        valuation_question = "".join(question.casefold().split())
        asks_live_valuation = any(
            term in valuation_question
            for term in ("今天", "今日", "当前", "最新", "现在", "盘中")
        )
        compact_fundamentals = compact.get("fundamentals") or {}
        if asks_live_valuation and compact_fundamentals.get("valuation"):
            compact["fundamentals"] = {
                "valuation": select(
                    compact_fundamentals.get("valuation") or {},
                    (
                        "price",
                        "pe_ttm",
                        "pe_dynamic",
                        "pe_static",
                        "pb",
                        "market_timestamp",
                    ),
                )
            }
        else:
            # 同行比较必须使用 peer_comparison 的同日标的值；未询问盘中
            # 变化时，不再发送另一日期的估值快照诱导模型混算。
            compact.pop("fundamentals", None)

        contract = compact.get("research_evidence_contract") or {}
        if contract:
            compact["research_evidence_contract"] = select(
                contract,
                ("contract_version", "answer_source", "boundary", "data_times"),
            )

        compact_quality = compact.get("earnings_quality") or {}
        if compact_quality:
            compact["earnings_quality"] = {
                **select(
                    compact_quality,
                    ("overall_label", "summary", "boundary"),
                ),
                "latest_report": compact_quality.get("latest_report") or {},
                "comparable_report": compact_quality.get("comparable_report") or {},
                "contradictions": (compact_quality.get("contradictions") or [])[:2],
            }

        compact_drivers = compact.get("financial_drivers") or {}
        if compact_drivers:
            filing = compact_drivers.get("filing_evidence") or {}
            if filing:
                filing = {
                    **select(filing, ("status", "summary", "boundary")),
                    "document": filing.get("document") or {},
                    "explicit_company_explanations": (
                        filing.get("explicit_company_explanations") or []
                    )[:1],
                    "unresolved_themes": (filing.get("unresolved_themes") or [])[:2],
                }
            compact["financial_drivers"] = {
                **select(
                    compact_drivers,
                    (
                        "overall_label",
                        "summary",
                        "latest_period",
                        "comparable_period",
                        "cashflow_analysis",
                        "unresolved_causes",
                        "boundary",
                    ),
                ),
                **({"filing_evidence": filing} if filing else {}),
            }

        information = compact.get("a_share_information") or {}
        if information:
            compact["a_share_information"] = {
                "announcements": (information.get("announcements") or [])[:1],
            }

        timeline = compact.get("event_timeline") or {}
        if timeline:
            official_events = [
                item
                for item in (timeline.get("events") or [])
                if item.get("evidence_level") == "official_disclosure"
                or item.get("direct_excerpt")
            ][:2]
            official_events = [
                {
                    **item,
                    **(
                        {"direct_excerpt": str(item["direct_excerpt"])[:700]}
                        if item.get("direct_excerpt")
                        else {}
                    ),
                }
                for item in official_events
            ]
            compact["event_timeline"] = {
                **select(
                    timeline,
                    (
                        "type",
                        "symbol",
                        "name",
                        "status",
                        "generated_at",
                        "as_of_date",
                        "coverage",
                        "boundary",
                    ),
                ),
                "events": official_events,
            }

        if compact.get("event_timeline"):
            # 正式披露已经在事件时间线保留；公告摘要不再重复发送。
            compact.pop("a_share_information", None)

        expectations = compact.get("analyst_expectations") or {}
        asks_expectations = any(
            term in valuation_question
            for term in ("分析师", "券商", "研报", "预期", "预测", "eps")
        )
        if expectations and asks_expectations:
            compact["analyst_expectations"] = select(
                expectations,
                (
                    "type",
                    "symbol",
                    "name",
                    "industry",
                    "status",
                    "generated_at",
                    "as_of_date",
                    "forecast_eps",
                    "forecast_statement",
                    "revision",
                    "boundary",
                ),
            )
        else:
            compact.pop("analyst_expectations", None)

        structure = compact.get("business_structure") or {}
        if structure:
            compact_dimensions = []
            for dimension in (structure.get("dimensions") or [])[:1]:
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
                        "segments": (dimension.get("segments") or [])[:2],
                    }
                )
            compact["business_structure"] = {
                **select(
                    structure,
                    (
                        "type",
                        "symbol",
                        "name",
                        "status",
                        "generated_at",
                        "anchor_report_date",
                        "summary",
                        "boundary",
                    ),
                ),
                "dimensions": compact_dimensions,
                "key_changes": (structure.get("key_changes") or [])[:2],
            }

        workspace_context = compact.get("stock_workspace_context") or {}
        if workspace_context:
            compact["stock_workspace_context"] = select(
                workspace_context,
                (
                    "contract_version",
                    "symbol",
                    "name",
                    "research_entry",
                    "boundary",
                ),
            )

    if focus == "quality_review":
        # 经营改善质量只需要披露、财务、现金流驱动和主营结构。
        # 当前报价、技术指标、同行估值和分析师预期既会显著放大 Prompt，
        # 也容易诱导模型把股价表现或市场定价当作经营改善的证据。
        for key in (
            "facts",
            "metrics",
            "current_quote",
            "price_levels",
            "provenance",
            "research_frame",
            "evidence_debate",
            "research_claims",
            "stock_market_context",
            "conditional_outlook",
            "price_move_event_evidence",
            "analyst_expectations",
            "peer_comparison",
            "outlook_calibration",
            "knowledge_context",
            "global_information",
            "module_statuses",
            "evidence_status",
        ):
            compact.pop(key, None)

        compact_fundamentals = compact.get("fundamentals") or {}
        compact_fundamentals.pop("valuation", None)
        # 财务报告原文已经由 earnings_quality / financial_drivers 的
        # filing_evidence 保留；这里再发送同一批监管文件只会重复。
        compact_fundamentals.pop("regulatory_filings", None)
        # 最新期财务数字已经同时存在于 earnings_quality 和
        # financial_drivers。质量专项不再把 fundamentals 的第三份副本
        # 发送给模型，原始证据仍完整保存在 Run 中供展示与守卫使用。
        compact.pop("fundamentals", None)

        compact_quality = compact.get("earnings_quality") or {}
        if compact_quality:
            report_keys = (
                "report_date",
                "report_type",
                "report_date_name",
                "notice_date",
                "currency",
                "period_basis",
                "revenue",
                "revenue_yoy_pct",
                "parent_net_profit",
                "net_profit_yoy_pct",
                "gross_margin_pct",
                "net_margin_pct",
                "debt_asset_ratio_pct",
                "operating_cashflow",
                "operating_cashflow_to_net_profit",
            )
            compact["earnings_quality"] = {
                **select(
                    compact_quality,
                    ("overall_label", "summary", "boundary"),
                ),
                "latest_report": select(
                    compact_quality.get("latest_report") or {}, report_keys
                ),
                "comparable_report": select(
                    compact_quality.get("comparable_report") or {}, report_keys
                ),
                "contradictions": (compact_quality.get("contradictions") or [])[:2],
            }

        compact_information = compact.get("a_share_information") or {}
        if compact_information:
            relevant_announcement_terms = (
                "报告",
                "业绩",
                "经营",
                "产销",
                "订单",
                "投资者关系",
                "库存",
            )
            announcements = []
            source_information = evidence.get("a_share_information") or {}
            ranked_announcements = sorted(
                source_information.get("announcements") or [],
                key=lambda item: (
                    0
                    if "投资者关系" in str(item.get("title") or "")
                    else 1
                    if any(
                        term in str(item.get("title") or "")
                        for term in ("年度报告", "半年度报告", "季度报告")
                    )
                    else 2,
                    0
                    if str(item.get("summary") or "").startswith("公司公告原文摘录")
                    else 1,
                ),
            )
            for item in ranked_announcements:
                if not any(
                    term
                    in (str(item.get("title") or "") + str(item.get("summary") or ""))
                    for term in relevant_announcement_terms
                ):
                    continue
                compact_item = select(
                    item,
                    (
                        "category",
                        "title",
                        "publisher",
                        "published_at",
                        "notice_date",
                        "summary",
                        "source",
                        "url",
                    ),
                )
                summary = str(compact_item.get("summary") or "")
                if summary:
                    summary_limit = (
                        2600 if summary.startswith("公司公告原文摘录") else 350
                    )
                    compact_item["summary"] = summary[:summary_limit]
                announcements.append(compact_item)
                if len(announcements) >= 2:
                    break
            if announcements:
                compact["a_share_information"] = {"announcements": announcements}
            else:
                compact.pop("a_share_information", None)

        compact_timeline = compact.get("event_timeline") or {}
        if compact_timeline:
            has_direct_announcement_excerpt = any(
                str(item.get("summary") or "").startswith("公司公告原文摘录")
                for item in (
                    (compact.get("a_share_information") or {}).get("announcements")
                    or []
                )
            )
            official_events = [
                item
                for item in (compact_timeline.get("events") or [])
                if item.get("evidence_level") == "official_disclosure"
            ][:1]
            if has_direct_announcement_excerpt:
                # 公告正文已经在 a_share_information 中保留。事件脉络的
                # 同一正文、主题统计和复核说明属于重复 Prompt 负载。
                compact.pop("event_timeline", None)
            elif official_events:
                compact["event_timeline"] = {
                    "events": [
                        select(
                            official_events[0],
                            (
                                "event_type",
                                "event_label",
                                "title",
                                "published_at",
                                "event_date",
                                "evidence_level",
                                "direct_excerpt",
                            ),
                        )
                    ],
                    "boundary": compact_timeline.get("boundary"),
                }
            else:
                compact.pop("event_timeline", None)

        compact_business = compact.get("business_structure") or {}
        if compact_business:
            dimensions = []
            for dimension in compact_business.get("dimensions") or []:
                if dimension.get("classification") not in {"product", "region"}:
                    continue
                dimensions.append(
                    {
                        **select(
                            dimension,
                            (
                                "classification",
                                "label",
                                "current_report_date",
                                "comparable_report_date",
                                "report_basis",
                            ),
                        ),
                        "segments": [
                            select(
                                item,
                                (
                                    "item_name",
                                    "revenue_share_pct",
                                    "gross_margin_pct",
                                    "comparison_status",
                                    "comparable_revenue_share_pct",
                                    "comparable_gross_margin_pct",
                                    "revenue_share_change_pp",
                                    "gross_margin_change_pp",
                                ),
                            )
                            for item in (dimension.get("segments") or [])[:4]
                        ],
                    }
                )
            compact["business_structure"] = {
                **select(
                    compact_business,
                    (
                        "anchor_report_date",
                        "summary",
                        "coverage_limits",
                        "boundary",
                    ),
                ),
                "dimensions": dimensions,
                "quality_review_boundary": (
                    "产品或地区收入占比变化只说明披露结构发生变化，不等于结构优化、"
                    "业务升级或利润质量改善；分部毛利率变化也不能代表行业整体毛利率。"
                ),
            }

        compact_drivers = compact.get("financial_drivers") or {}
        if compact_drivers:
            compact_drivers["confirmed_mechanical_drivers"] = [
                item
                for item in (compact_drivers.get("confirmed_mechanical_drivers") or [])
                if item.get("key") != "gross_profit_revenue_scale_effect"
            ]
            filing = compact_drivers.get("filing_evidence") or {}
            if filing:
                explicit_explanations = list(
                    filing.get("explicit_company_explanations") or []
                )
                question = str(evidence.get("user_question") or "")
                if not any(
                    term in question for term in ("其他收益", "投资收益", "公允价值")
                ):
                    explicit_explanations = [
                        item
                        for item in explicit_explanations
                        if item.get("theme") == "financial_expense_fx_interest"
                        or any(
                            term
                            in " ".join(
                                str(item.get(key) or "")
                                for key in ("theme", "label", "statement", "excerpt")
                            )
                            for term in ("财务费用", "汇兑", "外币", "利息")
                        )
                    ]
                filing["explicit_company_explanations"] = explicit_explanations[:2]
            compact["financial_drivers"] = select(
                compact_drivers,
                (
                    "overall_label",
                    "summary",
                    "latest_period",
                    "comparable_period",
                    "cashflow_analysis",
                    "confirmed_mechanical_drivers",
                    "plausible_clues",
                    "filing_evidence",
                    "unresolved_causes",
                    "boundary",
                ),
            )

        workspace_context = compact.get("stock_workspace_context") or {}
        if workspace_context:
            compact["stock_workspace_context"] = select(
                workspace_context,
                (
                    "contract_version",
                    "symbol",
                    "name",
                    "research_entry",
                    "data_meta",
                    "boundary",
                ),
            )

    peers = evidence.get("peer_comparison") or {}
    if peers and focus != "quality_review":
        compact_peers = select(
            peers,
            (
                "group_label",
                "selection_basis",
                "method",
                "coverage",
                "subject",
                "metrics",
                "peers",
                "operating_comparison",
                "as_of",
                "warnings",
            ),
        )
        if focus == "valuation_review":
            operating = compact_peers.get("operating_comparison") or {}
            if str(operating.get("status") or "") in {"partial", "unavailable"}:
                compact_peers["operating_comparison"] = select(
                    operating,
                    (
                        "status",
                        "anchor_report_date",
                        "anchor_report_type",
                        "anchor_report_date_name",
                        "anchor_period_basis",
                        "coverage",
                        "missing_items",
                        "warnings",
                    ),
                )
        compact["peer_comparison"] = compact_peers
    if price_move_question:
        compact_market_context = compact.get("stock_market_context") or {}
        if compact_market_context:
            target_keys = ["status", "market_date", "close", "return_1d_pct"]
            if any(
                term in question
                for term in ("昨天", "前日", "前一日", "前一天", "两日", "连续")
            ):
                target_keys.extend(
                    (
                        "previous_market_date",
                        "previous_close",
                        "previous_return_1d_pct",
                    )
                )
            compact_market_context["stock_target"] = select(
                compact_market_context.get("stock_target") or {}, tuple(target_keys)
            )
            if not compact_market_context["stock_target"]:
                compact_market_context.pop("stock_target", None)
            compact_market_context.pop("market_state", None)
            if not any(term in question for term in ("贡献", "权重", "归因")):
                (compact_market_context.get("exact_industry_index") or {}).pop(
                    "subject_weight_pct", None
                )
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
        allowed = [
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
        ]

        financial_in_scope = is_deep_stock_price_move_question(question) or any(
            term in question
            for term in (
                "财务",
                "财报",
                "营收",
                "利润",
                "毛利",
                "现金流",
                "基本面",
            )
        )
        if financial_in_scope:
            def compact_company_explanation(item: dict[str, Any]) -> dict[str, Any]:
                excerpt = " ".join(str(item.get("excerpt") or "").split())
                cause_at = excerpt.find("主要因")
                raw_statement = (
                    excerpt[cause_at:] if cause_at >= 0 else excerpt[:240]
                )
                company_statement = "".join(raw_statement.split())
                return {
                    **select(
                        item,
                        ("theme", "label", "report_title", "report_period", "notice_date"),
                    ),
                    "company_statement": company_statement,
                }

            explanation_priority = {
                "operating_cashflow": 0,
                "financial_expense_fx_interest": 1,
                "inventory": 2,
                "receivables_collection": 3,
            }

            def explanation_rank(item: dict[str, Any]) -> int:
                return explanation_priority.get(str(item.get("theme") or ""), 99)

            fundamentals = compact.get("fundamentals") or {}
            summary = fundamentals.get("summary") or {}
            latest_report = summary.get("latest_report") or {}
            compact["fundamentals"] = {
                "summary": {
                    "latest_report": select(
                        latest_report,
                        (
                            "report_date",
                            "report_type",
                            "notice_date",
                            "period_basis",
                            "revenue",
                            "revenue_yoy_pct",
                            "parent_net_profit",
                            "net_profit_yoy_pct",
                            "gross_margin_pct",
                            "net_margin_pct",
                            "operating_cashflow",
                            "operating_cashflow_to_net_profit",
                        ),
                    ),
                    "operating_cashflow_to_net_profit": summary.get(
                        "operating_cashflow_to_net_profit"
                    ),
                }
            }

            quality = compact.get("earnings_quality") or {}
            quality_report_keys = (
                "report_date",
                "report_type",
                "report_date_name",
                "notice_date",
                "currency",
                "revenue",
                "revenue_yoy_pct",
                "parent_net_profit",
                "net_profit_yoy_pct",
                "gross_margin_pct",
                "net_margin_pct",
                "operating_cashflow",
                "operating_cashflow_to_net_profit",
                "period_basis",
            )
            compact["earnings_quality"] = {
                **select(
                    quality,
                    ("boundary",),
                ),
                "latest_report": select(
                    quality.get("latest_report") or {}, quality_report_keys
                ),
                "comparable_report": select(
                    quality.get("comparable_report") or {}, quality_report_keys
                ),
                "factors": [
                    select(
                        item,
                        (
                            "key",
                            "label",
                            "value_pct",
                            "comparable_pct",
                            "change_pp",
                            "value_ratio",
                            "comparable_ratio",
                            "interpretation",
                            "interpretation_boundary",
                        ),
                    )
                    for item in (quality.get("factors") or [])[:5]
                ],
            }

            drivers = compact.get("financial_drivers") or {}
            filing = drivers.get("filing_evidence") or {}
            cashflow_analysis = select(
                drivers.get("cashflow_analysis") or {},
                (
                    "operating_cashflow",
                    "comparable_operating_cashflow",
                    "operating_cashflow_to_net_profit",
                    "comparable_operating_cashflow_to_net_profit",
                    "cash_received_from_sales_to_revenue_pct",
                    "comparable_cash_received_from_sales_to_revenue_pct",
                ),
            )
            mechanical_drivers = [
                item
                for item in (drivers.get("confirmed_mechanical_drivers") or [])
                if item.get("calculation_nature") != "static_counterfactual"
            ]
            company_explanations = sorted(
                filing.get("explicit_company_explanations") or [],
                key=explanation_rank,
            )
            compact["financial_drivers"] = {
                **select(
                    drivers,
                    ("boundary",),
                ),
                "cashflow_analysis": cashflow_analysis,
                "confirmed_mechanical_drivers": [
                    select(
                        item,
                        (
                            "key",
                            "label",
                            "direction",
                            "statement",
                            "calculation_nature",
                            "interpretation_boundary",
                        ),
                    )
                    for item in mechanical_drivers[:4]
                ],
                "filing_evidence": {
                    **select(filing, ("status", "boundary")),
                    "document": select(
                        filing.get("document") or {},
                        (
                            "title",
                            "document_type",
                            "report_period",
                            "notice_date",
                            "published_at",
                            "source_url",
                        ),
                    ),
                    "explicit_company_explanations": (
                        [
                            compact_company_explanation(item)
                            for item in company_explanations[:4]
                        ]
                    ),
                },
            }
            allowed.extend(
                ("fundamentals", "earnings_quality", "financial_drivers")
            )

        if any(term in question for term in ("情绪", "社区", "股吧", "讨论")):
            information = compact.get("a_share_information") or {}
            compact["a_share_information"] = {
                "sentiment": information.get("sentiment") or {},
                "sentiment_caveat": information.get("sentiment_caveat"),
            }
            allowed.append("a_share_information")

        return {
            key: compact[key]
            for key in allowed
            if compact.get(key) not in (None, "", [], {})
        }
    return compact


_STOCK_SPECIALIST_EVIDENCE_KEYS = {
    "earnings_quality": "earnings_quality",
    "financial_drivers": "financial_drivers",
    "business_structure": "business_structure",
    "shareholder_structure": "shareholder_structure",
    "analyst_expectations": "analyst_expectations",
    "event_timeline": "event_timeline",
}


def compact_stock_specialist_evidence(
    evidence: dict[str, Any],
) -> dict[str, Any]:
    """Compact a specialist stock packet without discarding its root payload.

    Specialist services return their module as the root object, while the
    comprehensive stock packet nests the same object under a module key.  Wrap
    the root temporarily so the proven stock compactor can keep the relevant
    module, current research plan and stock workspace while dropping duplicate
    reports, historical changes and unrelated knowledge excerpts.
    """

    evidence_type = str(evidence.get("type") or "")
    module_key = _STOCK_SPECIALIST_EVIDENCE_KEYS.get(evidence_type)
    if module_key is None:
        return compact_stock_research_evidence(evidence)

    workspace = evidence.get("stock_workspace_context") or {}
    display_name = str(
        evidence.get("display_name")
        or workspace.get("name")
        or evidence.get("name")
        or evidence.get("symbol")
        or ""
    ).strip()
    wrapped = {
        **evidence,
        module_key: evidence,
    }
    if display_name:
        wrapped["display_name"] = display_name
    compact = compact_stock_research_evidence(wrapped)
    compact_workspace = compact.get("stock_workspace_context") or {}
    if compact_workspace:
        # A specialist answer needs the bound stock identity and any formally
        # confirmed thesis, but not the screening-entry card, position panel or
        # unrelated workspace change feed.  Those fields can contain older
        # price/financial candidate wording and previously caused a business
        # composition follow-up to discuss quarterly net profit instead of the
        # current annual segment packet.
        compact["stock_workspace_context"] = {
            key: compact_workspace.get(key)
            for key in (
                "contract_version",
                "symbol",
                "name",
                "research_focus",
                "relation",
                "formal_thesis",
                "boundary",
            )
            if compact_workspace.get(key) not in (None, "", [], {})
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
                "research_focus",
                "attention_flags",
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
