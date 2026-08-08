from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.db import Database
from app.providers.market import ProviderError
from app.providers.market_news import GoogleNewsMarketProvider, MARKET_NEWS_QUERIES
from app.utils import utc_now


_FOCUS_TERMS = {
    "trend_reversal": ("反弹", "反转", "企稳", "回升", "震荡", "趋势", "rebound"),
    "volume_flows": ("成交", "放量", "缩量", "资金", "etf", "北向", "流入", "流出"),
    "sector_rotation": (
        "板块",
        "行业",
        "题材",
        "领涨",
        "领跌",
        "轮动",
        "普涨",
        "结构性",
        "市场广度",
        "sector",
    ),
    "market_cause": ("原因", "驱动", "利好", "利空", "为何", "why", "amid"),
    "market_risk": ("风险", "回撤", "下跌", "承压", "波动", "risk", "fall"),
}

_MARKET_TIMEZONES = {
    "us": "America/New_York",
    "china": "Asia/Shanghai",
    "hong_kong": "Asia/Hong_Kong",
    "japan": "Asia/Tokyo",
    "korea": "Asia/Seoul",
    "europe": "Europe/London",
    "gold": "Europe/London",
}

_DRIVER_CATEGORIES = {
    "monetary_policy": {
        "label": "货币政策与央行表态",
        "terms": (
            "fed",
            "federal reserve",
            "powell",
            "rate cut",
            "rate hike",
            "央行",
            "降息",
            "加息",
            "利率决议",
            "货币政策",
        ),
    },
    "rates_fx": {
        "label": "利率、债券与汇率",
        "terms": (
            "treasury",
            "yield",
            "bond",
            "dollar",
            "yen",
            "yuan",
            "国债",
            "收益率",
            "债券",
            "美元",
            "日元",
            "人民币",
            "汇率",
        ),
    },
    "macro_data": {
        "label": "宏观数据",
        "terms": (
            "inflation",
            "cpi",
            "ppi",
            "payroll",
            "jobs report",
            "gdp",
            "pmi",
            "retail sales",
            "通胀",
            "就业",
            "非农",
            "经济数据",
            "社零",
            "工业增加值",
        ),
    },
    "earnings_corporate": {
        "label": "财报与公司事件",
        "terms": (
            "earnings",
            "profit warning",
            "guidance",
            "results",
            "财报",
            "业绩",
            "盈利预警",
            "业绩指引",
            "回购",
        ),
    },
    "policy_geopolitics": {
        "label": "政策与地缘事件",
        "terms": (
            "tariff",
            "sanction",
            "trade war",
            "geopolitical",
            "war",
            "关税",
            "制裁",
            "贸易摩擦",
            "地缘",
            "监管",
            "政策",
        ),
    },
    "technology_sector": {
        "label": "科技与行业事件",
        "terms": (
            "ai",
            "chip",
            "semiconductor",
            "tech stocks",
            "科技股",
            "芯片",
            "半导体",
            "人工智能",
            "板块",
            "行业",
        ),
    },
    "flows_positioning": {
        "label": "资金、仓位与交易结构",
        "terms": (
            "etf",
            "flows",
            "positioning",
            "profit taking",
            "selloff",
            "资金流",
            "净流入",
            "净流出",
            "获利了结",
            "成交",
            "放量",
            "缩量",
        ),
    },
}


class MarketNewsService:
    def __init__(self, database: Database, provider: GoogleNewsMarketProvider):
        self.database = database
        self.provider = provider

    def get_packet(
        self,
        message: str,
        limit: int = 10,
        market_key: str | None = None,
        focus_key: str | None = None,
        target_market_date: str | None = None,
        refresh_max_age_seconds: int = 600,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        market_key = market_key or self.infer_market(message)
        if market_key not in MARKET_NEWS_QUERIES:
            market_key = self.infer_market(message)
        marker = f"__MARKET_{market_key.upper()}__"
        fetch_limit = max(limit, 20) if focus_key in _FOCUS_TERMS else limit
        if target_market_date:
            # The latest complete trading session can be older than a dense stream of
            # newer headlines. Keep enough history to retrieve the target session
            # instead of accidentally limiting the packet to the newest 30 rows.
            stored_limit = max(limit * 24, 240)
        else:
            stored_limit = max(limit * 3, 30) if focus_key in _FOCUS_TERMS else limit
        stored = self.database.list_news(
            symbol=marker,
            limit=stored_limit,
            categories=("market_news",),
        )
        cache_age_seconds = _cache_age_seconds(stored)
        refresh_attempted = bool(
            force_refresh
            or not stored
            or cache_age_seconds is None
            or cache_age_seconds > max(0, refresh_max_age_seconds)
        )
        refreshed = False
        packet = {
            "market_key": market_key,
            "market_label": MARKET_NEWS_QUERIES[market_key]["label"],
        }
        if refresh_attempted:
            try:
                packet = self.provider.fetch(market_key, limit=fetch_limit)
                self.database.upsert_news_items(packet["items"])
                refreshed = True
                stored = self.database.list_news(
                    symbol=marker,
                    limit=stored_limit,
                    categories=("market_news",),
                )
                cache_age_seconds = _cache_age_seconds(stored)
            except ProviderError:
                pass
        ranked_pool = _rank_for_target_context(
            stored,
            market_key=market_key,
            focus_key=focus_key,
            target_market_date=target_market_date,
        )
        ranked = ranked_pool[:limit]
        causal_evidence = _build_causal_evidence(
            ranked_pool[: max(limit * 3, 30)],
            market_key=market_key,
            target_market_date=target_market_date,
            limit=min(limit, 6),
        )
        return {
            "market_key": market_key,
            "market_label": packet["market_label"],
            "question_focus": focus_key or "market_overview",
            "generated_at": utc_now(),
            "refreshed": refreshed,
            "refresh_attempted": refresh_attempted,
            "cache": {
                "status": "fresh"
                if cache_age_seconds is not None
                and cache_age_seconds <= max(0, refresh_max_age_seconds)
                else "stale"
                if stored
                else "empty",
                "age_seconds": round(cache_age_seconds, 1)
                if cache_age_seconds is not None
                else None,
                "max_age_seconds": max(0, refresh_max_age_seconds),
            },
            "items": ranked,
            "coverage": {"available": len(ranked), "requested": limit},
            "selection": {
                "stored_considered": len(stored),
                "target_market_date": target_market_date,
                "same_date_available": sum(
                    _market_date(item.get("published_at"), market_key)
                    == target_market_date
                    for item in stored
                )
                if target_market_date
                else None,
                "strategy": (
                    "target_market_date_then_question_focus"
                    if target_market_date
                    else "question_focus_then_recency"
                ),
            },
            "causal_evidence": causal_evidence,
            "interpretation": (
                "资讯按目标交易日、事件类型与独立来源数整理为候选驱动；"
                "同日多来源只能提高线索可信度，仍不能单独证明唯一因果。"
            ),
        }

    @staticmethod
    def infer_market(message: str) -> str:
        folded = message.casefold()
        if any(term in folded for term in ("伦敦金", "黄金", "xau")):
            return "gold"
        if any(
            term in folded for term in ("美股", "标普", "纳指", "道指", "nasdaq", "s&p")
        ):
            return "us"
        if any(term in folded for term in ("港股", "恒生")):
            return "hong_kong"
        if any(term in folded for term in ("日股", "日经", "日本股市")):
            return "japan"
        if any(term in folded for term in ("韩股", "kospi", "韩国股市")):
            return "korea"
        if any(term in folded for term in ("欧股", "欧洲股市", "dax", "stoxx")):
            return "europe"
        return "china"


def _rank_for_focus(
    items: list[dict[str, Any]], focus_key: str | None
) -> list[dict[str, Any]]:
    terms = _FOCUS_TERMS.get(str(focus_key or ""), ())
    if not terms:
        return items
    scored = []
    for position, item in enumerate(items):
        text = f"{item.get('title') or ''} {item.get('summary') or ''}".casefold()
        score = sum(term in text for term in terms)
        scored.append((score, position, item))
    if not any(score for score, _, _ in scored):
        return items
    scored.sort(key=lambda row: (-row[0], row[1]))
    return [item for _, _, item in scored]


def _rank_for_target_context(
    items: list[dict[str, Any]],
    *,
    market_key: str,
    focus_key: str | None,
    target_market_date: str | None,
) -> list[dict[str, Any]]:
    if not target_market_date:
        return _rank_for_focus(items, focus_key)
    terms = _FOCUS_TERMS.get(str(focus_key or ""), ())
    scored = []
    for position, item in enumerate(items):
        published_market_date = _market_date(item.get("published_at"), market_key)
        if published_market_date == target_market_date:
            date_score = 4
        elif published_market_date:
            try:
                date_gap = abs(
                    (
                        datetime.fromisoformat(published_market_date).date()
                        - datetime.fromisoformat(target_market_date).date()
                    ).days
                )
            except ValueError:
                date_gap = 99
            date_score = 2 if date_gap <= 1 else 0
        else:
            date_score = 1
        text = f"{item.get('title') or ''} {item.get('summary') or ''}".casefold()
        focus_score = sum(term in text for term in terms)
        category_score = 1 if _driver_category(item)[0] != "other" else 0
        scored.append((date_score, focus_score, category_score, position, item))
    scored.sort(key=lambda row: (-row[0], -row[1], -row[2], row[3]))
    return [item for _, _, _, _, item in scored]


def _parse_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _cache_age_seconds(items: list[dict[str, Any]]) -> float | None:
    fetched = [
        parsed
        for item in items
        if (parsed := _parse_datetime(item.get("fetched_at"))) is not None
    ]
    if not fetched:
        return None
    return max(0.0, (datetime.now(timezone.utc) - max(fetched)).total_seconds())


def _market_date(value: Any, market_key: str) -> str | None:
    parsed = _parse_datetime(value)
    if parsed is None:
        return None
    timezone_name = _MARKET_TIMEZONES.get(market_key, "UTC")
    return parsed.astimezone(ZoneInfo(timezone_name)).date().isoformat()


def _driver_category(item: dict[str, Any]) -> tuple[str, str]:
    text = f"{item.get('title') or ''} {item.get('summary') or ''}".casefold()
    matches = []
    for key, config in _DRIVER_CATEGORIES.items():
        score = sum(term in text for term in config["terms"])
        if score:
            matches.append((score, key, str(config["label"])))
    if not matches:
        return "other", "其他市场事件"
    matches.sort(key=lambda row: (-row[0], row[1]))
    _, key, label = matches[0]
    return key, label


def _build_causal_evidence(
    items: list[dict[str, Any]],
    *,
    market_key: str,
    target_market_date: str | None,
    limit: int,
) -> dict[str, Any]:
    prepared = []
    category_sources: dict[str, set[str]] = defaultdict(set)
    category_same_date_sources: dict[str, set[str]] = defaultdict(set)
    for position, item in enumerate(items):
        category, category_label = _driver_category(item)
        source = str(item.get("source") or "未标明来源").strip()
        published_market_date = _market_date(item.get("published_at"), market_key)
        if target_market_date and published_market_date == target_market_date:
            date_relation = "same_market_date"
            date_score = 4
        elif target_market_date and published_market_date:
            try:
                date_gap = abs(
                    (
                        datetime.fromisoformat(published_market_date).date()
                        - datetime.fromisoformat(target_market_date).date()
                    ).days
                )
            except ValueError:
                date_gap = 99
            date_relation = (
                "adjacent_date" if date_gap <= 1 else "outside_target_window"
            )
            date_score = 2 if date_gap <= 1 else 0
        else:
            date_relation = "date_unanchored"
            date_score = 1
        category_sources[category].add(source)
        if date_relation == "same_market_date":
            category_same_date_sources[category].add(source)
        prepared.append(
            {
                "position": position,
                "score": date_score + (1 if category != "other" else 0),
                "category": category,
                "category_label": category_label,
                "source": source,
                "title": str(item.get("title") or "")[:500],
                "summary": str(item.get("summary") or "")[:500] or None,
                "published_at": item.get("published_at"),
                "published_market_date": published_market_date,
                "date_relation": date_relation,
            }
        )
    for candidate in prepared:
        category = candidate["category"]
        same_date_sources = len(category_same_date_sources[category])
        all_sources = len(category_sources[category])
        candidate["independent_sources"] = all_sources
        candidate["same_date_sources"] = same_date_sources
        if candidate["date_relation"] == "same_market_date" and same_date_sources >= 2:
            candidate["support_level"] = "same_date_multi_source"
            candidate["score"] += 3
        elif candidate["date_relation"] == "same_market_date":
            candidate["support_level"] = "same_date_single_source"
            candidate["score"] += 1
        elif all_sources >= 2:
            candidate["support_level"] = "near_date_multi_source"
            candidate["score"] += 1
        else:
            candidate["support_level"] = "single_source_lead"
    prepared.sort(key=lambda item: (-int(item["score"]), int(item["position"])))

    selected = []
    seen_sources: set[str] = set()
    for candidate in prepared:
        if len(selected) >= limit:
            break
        if candidate["source"] in seen_sources and len(seen_sources) < min(limit, 3):
            continue
        selected.append(
            {
                key: value
                for key, value in candidate.items()
                if key not in {"position", "score"}
            }
        )
        seen_sources.add(candidate["source"])
    if len(selected) < limit:
        selected_keys = {(item["source"], item["title"]) for item in selected}
        for candidate in prepared:
            if len(selected) >= limit:
                break
            key = (candidate["source"], candidate["title"])
            if key in selected_keys:
                continue
            selected.append(
                {
                    field: value
                    for field, value in candidate.items()
                    if field not in {"position", "score"}
                }
            )
            selected_keys.add(key)

    same_date_count = sum(
        item.get("date_relation") == "same_market_date" for item in selected
    )
    corroborated_categories = [
        {
            "category": category,
            "category_label": (
                _DRIVER_CATEGORIES.get(category, {}).get("label") or "其他市场事件"
            ),
            "same_date_sources": len(sources),
        }
        for category, sources in category_same_date_sources.items()
        if len(sources) >= 2
    ]
    coverage_status = (
        "same_date_multi_source"
        if corroborated_categories
        else "same_date_single_source"
        if same_date_count
        else "near_date_only"
        if selected
        else "unavailable"
    )
    return {
        "target_market_date": target_market_date,
        "coverage_status": coverage_status,
        "candidate_count": len(selected),
        "same_date_candidate_count": same_date_count,
        "source_count": len({item.get("source") for item in selected}),
        "corroborated_categories": corroborated_categories,
        "candidates": selected,
        "boundary": (
            "这里的事件只是在目标交易日附近被多个来源讨论的候选驱动。"
            "必须再与指数、市场广度、行业表现和正式公告核对；即使同日多来源一致，"
            "也不能据此宣称唯一原因或确定因果。"
        ),
    }
