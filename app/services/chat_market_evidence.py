from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.services.chat_routing import (
    _market_key_from_history,
    _market_question_focus,
)
from app.services.market_news import MarketNewsService


_LIVE_MARKET_KEY = {
    "china": "china",
    "us": "us",
    "japan": "japan",
    "korea": "korea",
    "gold": "london_gold",
}


def _live_market_date(item: dict[str, Any]) -> str | None:
    timestamp = str(item.get("market_timestamp") or "").strip()
    if not timestamp:
        return None
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        timezone_name = str(item.get("timezone") or "UTC")
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ZoneInfo(timezone_name))
        return parsed.astimezone(ZoneInfo(timezone_name)).date().isoformat()
    except (TypeError, ValueError, KeyError):
        return timestamp[:10] or None


def _live_alignment(
    item: dict[str, Any] | None,
    *,
    target_market_date: str | None,
) -> dict[str, Any]:
    live_market_date = _live_market_date(item or {})
    if not live_market_date:
        status = "unavailable"
    elif not target_market_date:
        status = "target_date_unavailable"
    elif live_market_date == target_market_date:
        status = "same_market_date"
    elif live_market_date > target_market_date:
        status = "newer_than_analysis_target"
    else:
        status = "older_than_analysis_target"
    return {
        "status": status,
        "target_market_date": target_market_date,
        "live_market_date": live_market_date,
        "rule": (
            "分钟行情与完整日线日期不一致时只作为更新提示，"
            "不得并入目标交易日的涨跌原因和市场状态判断。"
        ),
    }


class ChatMarketEvidenceService:
    def __init__(self, *, analysis: Any, market_news: Any, live_markets: Any) -> None:
        self.analysis = analysis
        self.market_news = market_news
        self.live_markets = live_markets

    def build(
        self,
        *,
        message: str,
        history: list[dict[str, Any]],
        explicit_market_query: bool,
        explicit_industry_topic: str | None,
    ) -> dict[str, Any]:
        question_focus = _market_question_focus(message)
        focused_market_key = (
            MarketNewsService.infer_market(message)
            if explicit_market_query
            else _market_key_from_history(history)
        )
        evidence = self.analysis.market_brief(market_key=focused_market_key)
        evidence["user_question"] = message
        evidence["question_focus"] = question_focus
        target_market_date = (
            str((evidence.get("analysis_target") or {}).get("market_date") or "").strip()
            or None
        )
        evidence["market_drivers"] = self.market_news.get_packet(
            message,
            market_key=focused_market_key,
            focus_key=question_focus["key"],
            target_market_date=target_market_date,
        )

        if explicit_industry_topic:
            evidence["industry_focus"] = {
                "name": explicit_industry_topic,
                "market_scope": "A股",
                "requested_by_user": True,
            }
            evidence["industry_snapshot"] = self.analysis.industry_snapshot(
                explicit_industry_topic,
                market_date=target_market_date,
            )

        live_market_key = _LIVE_MARKET_KEY.get(
            str(evidence["market_drivers"].get("market_key") or "")
        )
        if live_market_key:
            try:
                live_snapshot = self.live_markets.snapshot()
                evidence["focused_live_market"] = next(
                    (
                        item
                        for item in live_snapshot.get("markets", [])
                        if item.get("key") == live_market_key
                    ),
                    None,
                )
            except Exception:
                evidence["focused_live_market"] = None
            evidence["live_alignment"] = _live_alignment(
                evidence.get("focused_live_market"),
                target_market_date=target_market_date,
            )
        return evidence


__all__ = ["ChatMarketEvidenceService"]
