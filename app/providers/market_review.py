from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, time
from html.parser import HTMLParser
import hashlib
import re
from typing import Any, Callable
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests

from app.providers.market import ProviderError
from app.utils import utc_now


SHANGHAI = ZoneInfo("Asia/Shanghai")
MARKET_MARKER = "__MARKET_CHINA__"


def infer_affected_sectors(text: str) -> list[str]:
    folded = str(text or "").casefold()
    mappings = (
        (("军工", "航空航天", "国防"), "国防军工"),
        (("创新药", "医药", "医疗", "生物"), "医药生物"),
        (("半导体", "芯片", "算力", "人工智能", "ai"), "科技"),
        (("光伏", "储能", "电池", "新能源", "锂"), "新能源"),
        (("银行", "券商", "保险", "证券"), "金融"),
        (("房地产", "地产"), "房地产"),
        (("煤炭", "石油", "有色", "黄金", "稀土"), "周期资源"),
        (("消费", "零售", "食品", "白酒"), "消费"),
    )
    sectors = [label for terms, label in mappings if any(term in folded for term in terms)]
    return sectors[:3] or ["全市场"]


class _AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._href: str | None = None
        self._title: str | None = None
        self._text: list[str] = []
        self.items: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() != "a":
            return
        self._href = next((value for key, value in attrs if key == "href"), None)
        self._title = next((value for key, value in attrs if key == "title"), None)
        self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() != "a" or self._href is None:
            return
        visible = re.sub(r"\s+", " ", "".join(self._text)).strip()
        attribute = re.sub(r"\s+", " ", self._title or "").strip()
        title = attribute if len(attribute) > len(visible) else visible
        if title:
            self.items.append((title, self._href))
        self._href = None
        self._title = None
        self._text = []


class OfficialMarketInformationProvider:
    SOURCES = (
        {
            "source": "中国证监会",
            "url": "https://www.csrc.gov.cn/csrc/c100028/common_xq_list.shtml",
            "allowed": ("/csrc/c100028/", "/content.shtml"),
        },
        {
            "source": "国家统计局",
            "url": "https://www.stats.gov.cn/sj/zxfb/",
            "allowed": ("/sj/zxfb/", "/t20"),
        },
        {
            "source": "中国人民银行",
            "url": "https://www.pbc.gov.cn/goutongjiaoliu/113456/113469/index.html",
            "allowed": ("/goutongjiaoliu/113456/113469/", "/index.html"),
        },
    )

    def __init__(
        self,
        http_get: Callable[..., Any] = requests.get,
        *,
        timeout_seconds: int = 6,
    ) -> None:
        self.http_get = http_get
        self.timeout_seconds = timeout_seconds

    def fetch(self, limit_per_source: int = 12) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        statuses: dict[str, dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=len(self.SOURCES)) as executor:
            futures = {
                executor.submit(self._fetch_source, config, limit_per_source): config
                for config in self.SOURCES
            }
            for future in as_completed(futures):
                config = futures[future]
                source = str(config["source"])
                try:
                    items = future.result()
                    results.extend(items)
                    statuses[source] = {"available": True, "items": len(items)}
                except Exception as exc:
                    statuses[source] = {
                        "available": False,
                        "items": 0,
                        "error": type(exc).__name__,
                    }
        results.sort(
            key=lambda item: item.get("published_at") or item.get("fetched_at") or "",
            reverse=True,
        )
        return {"items": results, "sources": statuses, "fetched_at": utc_now()}

    def _fetch_source(
        self, config: dict[str, Any], limit: int
    ) -> list[dict[str, Any]]:
        response = self.http_get(
            config["url"],
            timeout=self.timeout_seconds,
            headers={"User-Agent": "Mozilla/5.0 QingshuResearch/0.1"},
        )
        response.raise_for_status()
        encoding = getattr(response, "apparent_encoding", None)
        if encoding:
            response.encoding = encoding
        parser = _AnchorParser()
        parser.feed(response.text)
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for title, href in parser.items:
            if len(title) < 8 or not all(part in href for part in config["allowed"]):
                continue
            url = urljoin(config["url"], href)
            if url in seen:
                continue
            seen.add(url)
            published_at = _date_from_url(url)
            item_id = hashlib.sha256(url.encode("utf-8")).hexdigest()
            items.append(
                {
                    "id": item_id,
                    "symbol": MARKET_MARKER,
                    "category": "official_market",
                    "title": title[:500],
                    "summary": None,
                    "source": config["source"],
                    "url": url,
                    "published_at": published_at,
                    "engagement": None,
                    "fetched_at": utc_now(),
                    "affected_sectors": infer_affected_sectors(title),
                }
            )
            if len(items) >= limit:
                break
        if not items:
            raise ProviderError(f"{config['source']}未返回可识别信息")
        return items


class CninfoMarketAnnouncementProvider:
    endpoint = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
    detail_base = "https://static.cninfo.com.cn/"

    def __init__(
        self,
        http_post: Callable[..., Any] = requests.post,
        *,
        timeout_seconds: int = 8,
    ) -> None:
        self.http_post = http_post
        self.timeout_seconds = timeout_seconds

    def fetch(
        self,
        start_date: date,
        end_date: date,
        *,
        limit: int = 40,
    ) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        errors: dict[str, str] = {}
        for column in ("szse", "sse"):
            try:
                response = self.http_post(
                    self.endpoint,
                    data={
                        "pageNum": 1,
                        "pageSize": min(50, max(10, limit)),
                        "column": column,
                        "tabName": "fulltext",
                        "plate": "",
                        "stock": "",
                        "searchkey": "",
                        "secid": "",
                        "category": "",
                        "trade": "",
                        "seDate": f"{start_date.isoformat()}~{end_date.isoformat()}",
                        "sortName": "",
                        "sortType": "",
                        "isHLtitle": "true",
                    },
                    timeout=self.timeout_seconds,
                    headers={
                        "User-Agent": "Mozilla/5.0 QingshuResearch/0.1",
                        "Referer": "https://www.cninfo.com.cn/",
                    },
                )
                response.raise_for_status()
                payload = response.json()
                rows.extend(payload.get("announcements") or [])
            except Exception as exc:
                errors[column] = type(exc).__name__
        items = []
        seen = set()
        for row in rows:
            title = re.sub(
                r"<[^>]+>",
                "",
                str(row.get("announcementTitle") or ""),
            ).strip()
            relative_url = str(row.get("adjunctUrl") or "").strip()
            if not title or not relative_url:
                continue
            url = urljoin(self.detail_base, relative_url)
            if url in seen:
                continue
            seen.add(url)
            published_at = _milliseconds_to_iso(row.get("announcementTime"))
            sec_name = str(row.get("secName") or "").strip()
            sec_code = str(row.get("secCode") or "").strip()
            item_id = hashlib.sha256(url.encode("utf-8")).hexdigest()
            sectors = infer_affected_sectors(title)
            if sectors == ["全市场"]:
                sectors = [sec_name or "相关公司"]
            items.append(
                {
                    "id": item_id,
                    "symbol": MARKET_MARKER,
                    "category": "announcement",
                    "title": f"{sec_name}：{title}" if sec_name else title,
                    "summary": sec_code or None,
                    "source": "巨潮资讯",
                    "url": url,
                    "published_at": published_at,
                    "engagement": None,
                    "fetched_at": utc_now(),
                    "affected_sectors": sectors,
                }
            )
        items.sort(key=lambda item: item.get("published_at") or "", reverse=True)
        return {
            "items": items[:limit],
            "sources": {
                "巨潮资讯": {
                    "available": bool(items),
                    "items": len(items[:limit]),
                    "errors": errors,
                }
            },
            "fetched_at": utc_now(),
        }


def _date_from_url(url: str) -> str | None:
    match = re.search(r"(20\d{2})[/-]?(\d{2})[/-]?(\d{2})", url)
    if not match:
        return None
    try:
        value = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None
    return datetime.combine(value, time.min, tzinfo=SHANGHAI).isoformat()


def _milliseconds_to_iso(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(float(value) / 1000, tz=SHANGHAI).isoformat()
    except (TypeError, ValueError, OSError):
        return None
