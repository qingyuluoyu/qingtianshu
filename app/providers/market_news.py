from __future__ import annotations

from email.utils import parsedate_to_datetime
import hashlib
import html
import re
from typing import Any
from urllib.parse import urlencode
import xml.etree.ElementTree as ET

import requests

from app.providers.market import ProviderError
from app.utils import utc_now


MARKET_NEWS_QUERIES = {
    "us": {
        "label": "美国股市",
        "query": '"US stocks" market close when:2d',
        "locale": {"hl": "en-US", "gl": "US", "ceid": "US:en"},
    },
    "china": {
        "label": "A股",
        "query": "A股 收盘 市场 when:2d",
        "locale": {"hl": "zh-CN", "gl": "CN", "ceid": "CN:zh-Hans"},
    },
    "hong_kong": {
        "label": "港股",
        "query": "港股 恒生 收盘 when:2d",
        "locale": {"hl": "zh-CN", "gl": "HK", "ceid": "HK:zh-Hans"},
    },
    "japan": {
        "label": "日本股市",
        "query": 'Nikkei Japan stocks close when:2d',
        "locale": {"hl": "en-US", "gl": "US", "ceid": "US:en"},
    },
    "korea": {
        "label": "韩国股市",
        "query": 'KOSPI Korea stocks close when:2d',
        "locale": {"hl": "en-US", "gl": "US", "ceid": "US:en"},
    },
    "europe": {
        "label": "欧洲股市",
        "query": 'European stocks close STOXX when:2d',
        "locale": {"hl": "en-GB", "gl": "GB", "ceid": "GB:en"},
    },
    "gold": {
        "label": "伦敦金",
        "query": 'spot gold price market drivers when:2d',
        "locale": {"hl": "en-GB", "gl": "GB", "ceid": "GB:en"},
    },
}


class GoogleNewsMarketProvider:
    endpoint = "https://news.google.com/rss/search"

    def __init__(self, timeout_seconds: int = 12):
        self.timeout_seconds = timeout_seconds

    def fetch(self, market_key: str, limit: int = 12) -> dict[str, Any]:
        config = MARKET_NEWS_QUERIES.get(market_key)
        if config is None:
            raise ProviderError("不支持的市场资讯范围")
        params = {"q": config["query"], **config["locale"]}
        url = f"{self.endpoint}?{urlencode(params)}"
        try:
            response = requests.get(
                url,
                timeout=self.timeout_seconds,
                headers={"User-Agent": "Mozilla/5.0 QingshuResearch/0.1"},
            )
            response.raise_for_status()
            root = ET.fromstring(response.content)
        except (requests.RequestException, ET.ParseError) as exc:
            raise ProviderError("市场驱动资讯暂时无法刷新") from exc

        items = []
        for node in root.findall("./channel/item")[:limit]:
            title = html.unescape((node.findtext("title") or "").strip())
            link = (node.findtext("link") or "").strip()
            source = html.unescape((node.findtext("source") or "").strip())
            published = (node.findtext("pubDate") or "").strip()
            if not title or not link:
                continue
            if source and title.endswith(f" - {source}"):
                title = title[: -(len(source) + 3)].strip()
            try:
                published_at = parsedate_to_datetime(published).isoformat()
            except (TypeError, ValueError):
                published_at = None
            item_id = hashlib.sha256(
                f"{market_key}|{link}".encode("utf-8")
            ).hexdigest()
            items.append(
                {
                    "id": item_id,
                    "symbol": f"__MARKET_{market_key.upper()}__",
                    "category": "market_news",
                    "title": re.sub(r"\s+", " ", title)[:500],
                    "summary": None,
                    "source": source or "Market news",
                    "url": link,
                    "published_at": published_at,
                    "engagement": None,
                    "fetched_at": utc_now(),
                }
            )
        if not items:
            raise ProviderError("市场驱动资讯暂无有效条目")
        return {
            "market_key": market_key,
            "market_label": config["label"],
            "items": items,
            "fetched_at": utc_now(),
        }
