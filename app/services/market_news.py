from __future__ import annotations

from typing import Any

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
    ) -> dict[str, Any]:
        market_key = market_key or self.infer_market(message)
        if market_key not in MARKET_NEWS_QUERIES:
            market_key = self.infer_market(message)
        marker = f"__MARKET_{market_key.upper()}__"
        fetch_limit = max(limit, 20) if focus_key in _FOCUS_TERMS else limit
        refreshed = False
        try:
            packet = self.provider.fetch(market_key, limit=fetch_limit)
            self.database.upsert_news_items(packet["items"])
            refreshed = True
        except ProviderError:
            packet = {
                "market_key": market_key,
                "market_label": MARKET_NEWS_QUERIES[market_key]["label"],
            }
        stored = self.database.list_news(
            symbol=marker,
            limit=max(limit * 3, 30) if focus_key in _FOCUS_TERMS else limit,
            categories=("market_news",),
        )
        ranked = _rank_for_focus(stored, focus_key)[:limit]
        return {
            "market_key": market_key,
            "market_label": packet["market_label"],
            "question_focus": focus_key or "market_overview",
            "generated_at": utc_now(),
            "refreshed": refreshed,
            "items": ranked,
            "coverage": {"available": len(ranked), "requested": limit},
            "interpretation": (
                "标题只能用于归纳市场正在讨论的驱动因素；"
                "单一标题不能独立证明涨跌因果。"
            ),
        }

    @staticmethod
    def infer_market(message: str) -> str:
        folded = message.casefold()
        if any(term in folded for term in ("伦敦金", "黄金", "xau")):
            return "gold"
        if any(term in folded for term in ("美股", "标普", "纳指", "道指", "nasdaq", "s&p")):
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
