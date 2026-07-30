from __future__ import annotations

from datetime import datetime
import html
import json
import re
from typing import Any, Callable
from zoneinfo import ZoneInfo

import requests

from app.catalog import RESEARCH_TARGETS, SECURITY_NAME_ALIASES, normalize_symbol
from app.providers.market import ProviderError
from app.utils import utc_now


_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
_LOW_SIGNAL_NEWS_RE = re.compile(
    r"(?:目标价|券商评级|评级观察|获推荐|强烈推荐|买入评级|卖出评级)",
    re.IGNORECASE,
)
_DIRECT_ANNOUNCEMENT_PRIORITY: tuple[tuple[int, re.Pattern[str]], ...] = (
    (100, re.compile(r"投资者关系活动记录表|业绩说明会|调研")),
    (95, re.compile(r"立案|处罚|调查|问询函|监管函|诉讼|仲裁|风险提示")),
    (90, re.compile(r"业绩预告|业绩快报|经营情况|产销|订单|中标|重大合同")),
    (75, re.compile(r"回购|增持|减持|质押|分红|权益分派|重大事项")),
    (65, re.compile(r"收购|并购|重组|出售资产|定增|可转债|担保|借款|授信")),
)


def _announcement_excerpt(value: Any, limit: int = 900) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"[\u3000\xa0]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) < 40:
        return ""
    return text[: max(120, limit)].rstrip("，；：、 ")


class AShareInformationProvider:
    ANNOUNCEMENT_URL = "https://np-anotice-stock.eastmoney.com/api/security/ann"
    ANNOUNCEMENT_CONTENT_URL = (
        "https://np-cnotice-stock.eastmoney.com/api/content/ann"
    )
    SINA_NEWS_URL = "https://vip.stock.finance.sina.com.cn/corp/view/vCB_AllNewsStock.php"
    GUBA_URL = "https://guba.eastmoney.com/list,{code}.html"

    def __init__(self, http_get: Callable[..., Any] = requests.get):
        self.http_get = http_get

    def fetch_announcements(self, symbol: str, limit: int = 20) -> list[dict[str, Any]]:
        canonical, code, _ = _a_share_identity(symbol)
        response = self.http_get(
            self.ANNOUNCEMENT_URL,
            params={
                "sr": -1,
                "page_size": min(max(limit, 1), 50),
                "page_index": 1,
                "ann_type": "A",
                "client_source": "web",
                "stock_list": code,
            },
            headers={"User-Agent": _UA, "Referer": "https://data.eastmoney.com/"},
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        items = []
        for row in ((payload.get("data") or {}).get("list") or [])[:limit]:
            title = _clean(row.get("title_ch") or row.get("title"))
            article_code = row.get("art_code")
            if not title or not article_code:
                continue
            items.append(
                {
                    "symbol": canonical,
                    "category": "announcement",
                    "title": title,
                    "summary": "公司公告；应优先于媒体解读和社区讨论。",
                    "source": "Eastmoney Announcements",
                    "url": f"https://data.eastmoney.com/notices/detail/{code}/{article_code}.html",
                    "published_at": _datetime_iso(
                        row.get("display_time") or row.get("notice_date")
                    ),
                    "engagement": None,
                    "fetched_at": utc_now(),
                    "article_code": str(article_code),
                }
            )
        self._attach_direct_announcement_excerpts(items)
        return items

    def _attach_direct_announcement_excerpts(
        self, items: list[dict[str, Any]], limit: int = 3
    ) -> None:
        """Hydrate a few decision-relevant announcements with company text.

        Announcement titles are useful for discovery but cannot support an
        operating conclusion. Fetching every attachment would slow routine
        refreshes, so only a bounded set of high-signal disclosures receives a
        first-page direct excerpt. The excerpt is persisted in ``summary`` and
        can therefore be retrieved by the Agent without replaying a generated
        research report.
        """

        ranked: list[tuple[int, int, dict[str, Any]]] = []
        for index, item in enumerate(items):
            title = str(item.get("title") or "")
            priority = max(
                (
                    score
                    for score, pattern in _DIRECT_ANNOUNCEMENT_PRIORITY
                    if pattern.search(title)
                ),
                default=0,
            )
            if priority:
                ranked.append((-priority, index, item))
        selected = [item for _, _, item in sorted(ranked)[: max(1, limit)]]

        for item in selected:
            article_code = str(item.get("article_code") or "").strip()
            if not article_code:
                continue
            try:
                response = self.http_get(
                    self.ANNOUNCEMENT_CONTENT_URL,
                    params={
                        "art_code": article_code,
                        "client_source": "web",
                        "page_index": 1,
                    },
                    headers={
                        "User-Agent": _UA,
                        "Referer": "https://data.eastmoney.com/",
                    },
                    timeout=15,
                )
                response.raise_for_status()
                data = (response.json() or {}).get("data") or {}
                excerpt = _announcement_excerpt(data.get("notice_content"))
                if not excerpt:
                    continue
                item["summary"] = f"公司公告原文摘录：{excerpt}"
                item["direct_content_status"] = "available"
                item["attach_url"] = data.get("attach_url_web") or data.get(
                    "attach_url"
                )
            except Exception:
                # The title remains a valid discovery record. A failed direct
                # excerpt must not make the whole company-information refresh
                # unavailable.
                item["direct_content_status"] = "title_only"

    def fetch_company_news(self, symbol: str, limit: int = 30) -> list[dict[str, Any]]:
        canonical, code, market_prefix = _a_share_identity(symbol)
        subject_terms = _company_subject_terms(canonical)
        response = self.http_get(
            self.SINA_NEWS_URL,
            params={"symbol": f"{market_prefix}{code}", "Page": 1},
            headers={"User-Agent": _UA, "Referer": "https://finance.sina.com.cn/"},
            timeout=15,
        )
        response.raise_for_status()
        content = response.content.decode("gb18030", errors="replace")
        block_match = re.search(
            r'<div\s+class="datelist"><ul>(.*?)</ul>', content, flags=re.DOTALL | re.IGNORECASE
        )
        if not block_match:
            raise ProviderError("新浪个股资讯列表格式无法识别")
        block = block_match.group(1)
        pattern = re.compile(
            r"(\d{4}-\d{2}-\d{2})&nbsp;(\d{2}:\d{2}).*?"
            r"<a[^>]+href=['\"]([^'\"]+)['\"][^>]*>(.*?)</a>",
            flags=re.DOTALL | re.IGNORECASE,
        )
        items = []
        seen = set()
        for date_text, time_text, url, raw_title in pattern.findall(block):
            title = _clean(raw_title)
            if not title or url in seen:
                continue
            folded_title = title.casefold()
            if _LOW_SIGNAL_NEWS_RE.search(title) or not any(
                term in folded_title for term in subject_terms
            ):
                continue
            seen.add(url)
            items.append(
                {
                    "symbol": canonical,
                    "category": "news",
                    "title": title,
                    "summary": None,
                    "source": "Sina Finance Company News",
                    "url": html.unescape(url),
                    "published_at": _datetime_iso(f"{date_text} {time_text}:00"),
                    "engagement": None,
                    "fetched_at": utc_now(),
                }
            )
            if len(items) >= limit:
                break
        return items

    def fetch_guba_posts(self, symbol: str, limit: int = 30) -> list[dict[str, Any]]:
        canonical, code, _ = _a_share_identity(symbol)
        response = self.http_get(
            self.GUBA_URL.format(code=code),
            headers={
                "User-Agent": _UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Referer": "https://guba.eastmoney.com/",
            },
            timeout=15,
        )
        response.raise_for_status()
        match = re.search(r"var\s+article_list\s*=\s*(\{.*?\});", response.text, re.DOTALL)
        if not match:
            raise ProviderError("东方财富股吧 article_list 缺失")
        payload = json.loads(match.group(1))
        items = []
        for row in (payload.get("re") or [])[:limit]:
            if str(row.get("stockbar_code") or "") != code:
                continue
            title = _clean(row.get("post_title"))
            post_id = row.get("post_id")
            if not title or not post_id:
                continue
            reads = _integer(row.get("post_click_count")) or 0
            comments = _integer(row.get("post_comment_count")) or 0
            items.append(
                {
                    "symbol": canonical,
                    "category": "social",
                    "title": title,
                    "summary": f"东方财富股吧讨论：{reads} 阅读，{comments} 评论",
                    "source": "Eastmoney Guba",
                    "url": f"https://guba.eastmoney.com/news,{code},{post_id}.html",
                    "published_at": _datetime_iso(
                        row.get("post_publish_time") or row.get("post_display_time")
                    ),
                    "engagement": float(reads + comments * 5),
                    "fetched_at": utc_now(),
                }
            )
        return items


def _a_share_identity(symbol: str) -> tuple[str, str, str]:
    canonical = normalize_symbol(symbol)
    if canonical.endswith(".SS"):
        return canonical, canonical[:-3], "sh"
    if canonical.endswith(".SZ"):
        return canonical, canonical[:-3], "sz"
    raise ValueError("A股信息源只支持 .SS/.SZ 证券")


def _company_subject_terms(symbol: str) -> set[str]:
    canonical = normalize_symbol(symbol)
    terms = {canonical.casefold(), canonical.split(".", 1)[0].casefold()}
    target_name = RESEARCH_TARGETS.get(canonical, {}).get("name")
    if target_name:
        terms.add(str(target_name).casefold())
    terms.update(
        alias.casefold()
        for alias, target in SECURITY_NAME_ALIASES.items()
        if target == canonical
    )
    return {term for term in terms if term}


def _clean(value: Any) -> str:
    text = re.sub(r"<[^>]+>", "", str(value or ""))
    return html.unescape(text).replace("\xa0", " ").strip()


def _datetime_iso(value: Any) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r":\d{3}$", "", str(value).strip())
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    return parsed.isoformat(timespec="seconds")


def _integer(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
