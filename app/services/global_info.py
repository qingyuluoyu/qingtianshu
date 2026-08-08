from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.catalog import normalize_symbol
from app.db import Database
from app.providers.global_info import NasdaqCompanyNewsProvider
from app.utils import utc_now


class GlobalInformationService:
    def __init__(self, database: Database, provider: NasdaqCompanyNewsProvider):
        self.database = database
        self.provider = provider

    def refresh_symbol(self, symbol: str) -> dict[str, Any]:
        canonical = normalize_symbol(symbol)
        items = self.provider.fetch_company_news(canonical)
        saved = self.database.upsert_news_items(items)
        polled_at = utc_now()
        return {
            "symbol": canonical,
            "refreshed_at": polled_at,
            "news_saved": saved,
            "sources": {
                "global_news": {
                    "status": "ok",
                    "items": len(items),
                    "polled_at": polled_at,
                }
            },
            "warnings": [],
        }

    def get_packet(
        self, symbol: str, refresh_max_age_seconds: int = 900
    ) -> dict[str, Any]:
        canonical = normalize_symbol(symbol)
        stored = self.database.list_news(
            canonical, limit=12, categories=("global_news",)
        )
        should_refresh = not stored
        if stored:
            try:
                fetched = datetime.fromisoformat(stored[0]["fetched_at"])
                should_refresh = datetime.now(timezone.utc) - fetched.astimezone(
                    timezone.utc
                ) > timedelta(seconds=refresh_max_age_seconds)
            except (TypeError, ValueError):
                should_refresh = True
        refresh = None
        warnings = []
        if should_refresh:
            try:
                refresh = self.refresh_symbol(canonical)
            except Exception as exc:
                warnings.append(f"全球公司新闻刷新未完成：{type(exc).__name__}")
            stored = self.database.list_news(
                canonical, limit=12, categories=("global_news",)
            )
        return {
            "symbol": canonical,
            "generated_at": utc_now(),
            "news": stored,
            "refresh": refresh,
            "warnings": warnings,
            "methodology": [
                "公司相关新闻来自 Nasdaq 聚合资讯，并保留原发布者和原文链接。",
                "媒体报道用于事件线索，不能替代公司公告或监管文件。",
            ],
        }
