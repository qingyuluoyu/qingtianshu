from __future__ import annotations

from datetime import datetime
import re
from typing import Any, Callable
from zoneinfo import ZoneInfo

import requests

from app.catalog import normalize_symbol
from app.providers.market import ProviderError
from app.utils import utc_now


_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
_MARKET_LIST_TITLE_RE = re.compile(
    r"(?:after hours|pre-market|premarket)?\s*most active|"
    r"most active for|option activity|market movers|stocks moving",
    re.IGNORECASE,
)
_LOW_SIGNAL_STOCK_PICK_RE = re.compile(
    r"(?:price target|analyst rating|earnings preview|poised to outperform|"
    r"stocks? to buy|stocks? to sell|buy right now|i['’]m buying|"
    r"i['’]d buy|stock is a buy|^prediction:)",
    re.IGNORECASE,
)


class NasdaqCompanyNewsProvider:
    NEWS_URL = "https://api.nasdaq.com/api/news/topic/articlebysymbol"

    def __init__(self, http_get: Callable[..., Any] = requests.get):
        self.http_get = http_get

    def fetch_company_news(self, symbol: str, limit: int = 20) -> list[dict[str, Any]]:
        canonical = normalize_symbol(symbol)
        if canonical.endswith((".SS", ".SZ")):
            raise ProviderError("Nasdaq 新闻源不用于 A 股证券")
        response = self.http_get(
            self.NEWS_URL,
            params={
                "q": f"{canonical.lower()}|stocks",
                "limit": max(1, min(limit * 3, 50)),
                "offset": 0,
            },
            headers={
                "User-Agent": _UA,
                "Accept": "application/json, text/plain, */*",
                "Referer": "https://www.nasdaq.com/",
            },
            timeout=20,
        )
        response.raise_for_status()
        try:
            payload = response.json()
        except Exception as exc:
            raise ProviderError("Nasdaq 公司新闻不是有效 JSON") from exc
        rows = ((payload.get("data") or {}).get("rows") or [])
        fetched_at = utc_now()
        items = []
        for row in rows:
            title = str(row.get("title") or "").strip()
            description = str(row.get("description") or "").strip()
            if _MARKET_LIST_TITLE_RE.search(title):
                continue
            title_terms = {
                canonical.lower(),
                "nvidia" if canonical == "NVDA" else canonical.lower(),
            }
            direct_title_mention = any(
                term in title.lower() for term in title_terms
            )
            if not direct_title_mention or _LOW_SIGNAL_STOCK_PICK_RE.search(title):
                continue
            relative_url = str(row.get("url") or "").strip()
            if not title or not relative_url:
                continue
            published_at = None
            try:
                published_at = (
                    datetime.strptime(str(row.get("created")), "%b %d, %Y")
                    .replace(tzinfo=ZoneInfo("America/New_York"))
                    .isoformat(timespec="seconds")
                )
            except (TypeError, ValueError):
                pass
            publisher = str(row.get("publisher") or "Nasdaq News").strip()
            items.append(
                {
                    "symbol": canonical,
                    "category": "global_news",
                    "title": title,
                    "summary": description or None,
                    "source": f"Nasdaq News / {publisher}",
                    "url": (
                        relative_url
                        if relative_url.startswith("http")
                        else f"https://www.nasdaq.com{relative_url}"
                    ),
                    "published_at": published_at,
                    "engagement": None,
                    "fetched_at": fetched_at,
                }
            )
            if len(items) >= limit:
                break
        if not items:
            raise ProviderError("Nasdaq 未返回目标公司的相关资讯")
        return items
