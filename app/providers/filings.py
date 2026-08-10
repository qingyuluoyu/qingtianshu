from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import hashlib
import html
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
_REPORT_COLUMNS = {
    "一季度报告全文",
    "半年度报告全文",
    "三季度报告全文",
    "年度报告全文",
}
_REPORT_TITLE_RE = re.compile(
    r"(?P<year>20\d{2})\s*年\s*(?P<kind>第一季度|一季度|半年度|中期|第三季度|三季度|年度)报告"
)
_EXCLUDED_TITLE_RE = re.compile(r"(?:摘要|英文版|取消|提示性公告|审计报告)")
_NON_REPORT_TITLE_RE = re.compile(r"(?:预约披露|披露时间)")


class AShareFilingProvider:
    """Discover and retrieve complete A-share financial-report text."""

    ANNOUNCEMENT_URL = "https://np-anotice-stock.eastmoney.com/api/security/ann"
    CONTENT_URL = "https://np-cnotice-stock.eastmoney.com/api/content/ann"

    def __init__(
        self,
        http_get: Callable[..., Any] = requests.get,
        *,
        max_content_pages: int = 300,
        max_announcement_pages: int = 8,
    ):
        self.http_get = http_get
        self.max_content_pages = max(1, max_content_pages)
        self.max_announcement_pages = max(1, max_announcement_pages)

    def list_financial_reports(
        self, symbol: str, limit: int = 3
    ) -> list[dict[str, Any]]:
        canonical, code = _a_share_identity(symbol)
        requested_limit = max(1, limit)
        reports = []
        seen_article_codes = set()
        for page_index in range(1, self.max_announcement_pages + 1):
            response = self.http_get(
                self.ANNOUNCEMENT_URL,
                params={
                    "sr": -1,
                    "page_size": 50,
                    "page_index": page_index,
                    "ann_type": "A",
                    "client_source": "web",
                    "stock_list": code,
                },
                headers={"User-Agent": _UA, "Referer": "https://data.eastmoney.com/"},
                timeout=20,
            )
            response.raise_for_status()
            payload = response.json()
            rows = (payload.get("data") or {}).get("list") or []
            for row in rows:
                title = _clean(row.get("title_ch") or row.get("title"))
                article_code = str(row.get("art_code") or "").strip()
                columns = {
                    _clean(item.get("column_name"))
                    for item in (row.get("columns") or [])
                    if item.get("column_name")
                }
                parsed = _parse_report_identity(title)
                if (
                    not article_code
                    or article_code in seen_article_codes
                    or not title
                    or _EXCLUDED_TITLE_RE.search(title)
                    or (
                        not columns.intersection(_REPORT_COLUMNS)
                        and (
                            parsed is None
                            or _NON_REPORT_TITLE_RE.search(title) is not None
                        )
                    )
                ):
                    continue
                document_type, report_period = parsed or _identity_from_columns(columns)
                if document_type is None:
                    continue
                published_at = _datetime_iso(
                    row.get("display_time") or row.get("notice_date")
                )
                reports.append(
                    {
                        "symbol": canonical,
                        "article_code": article_code,
                        "title": title,
                        "document_type": document_type,
                        "report_period": report_period,
                        "notice_date": published_at[:10] if published_at else None,
                        "published_at": published_at,
                        "source": "company_filing",
                        "source_url": (
                            f"https://data.eastmoney.com/notices/detail/"
                            f"{code}/{article_code}.html"
                        ),
                    }
                )
                seen_article_codes.add(article_code)
                if len(reports) >= requested_limit:
                    return reports
            if not rows:
                break
        return reports

    def fetch_document(self, report: dict[str, Any]) -> dict[str, Any]:
        article_code = str(report.get("article_code") or "").strip()
        if not article_code:
            raise ValueError("财报候选缺少 article_code")
        first = self._fetch_content_page(article_code, 1)
        total_pages = _integer(first.get("page_size")) or 1
        requested_pages = min(total_pages, self.max_content_pages)
        parts = [str(first.get("notice_content") or "")]
        seen_hashes = {
            hashlib.sha256(parts[0].encode("utf-8")).hexdigest()
        } if parts[0] else set()
        page_numbers = list(range(2, requested_pages + 1))
        if page_numbers:
            with ThreadPoolExecutor(max_workers=min(8, len(page_numbers))) as executor:
                remaining_pages = list(
                    executor.map(
                        lambda page_index: self._fetch_content_page(
                            article_code, page_index
                        ),
                        page_numbers,
                    )
                )
        else:
            remaining_pages = []
        for page in remaining_pages:
            content = str(page.get("notice_content") or "")
            if not content:
                continue
            page_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            if page_hash in seen_hashes:
                continue
            seen_hashes.add(page_hash)
            parts.append(content)
        content_text = _clean_content("\n\n".join(parts))
        if len(content_text) < 100:
            raise ProviderError("财报正文为空或过短")
        title = _clean(first.get("notice_title")) or str(report.get("title") or "")
        parsed = _parse_report_identity(title)
        document_type, report_period = parsed or (
            report.get("document_type"),
            report.get("report_period"),
        )
        notice_date = _datetime_iso(first.get("notice_date"))
        warnings = []
        if total_pages > self.max_content_pages:
            warnings.append(
                f"报告共 {total_pages} 页文本，当前安全上限保留前 {self.max_content_pages} 页。"
            )
        return {
            **report,
            "title": title,
            "document_type": document_type or "financial_report",
            "report_period": report_period,
            "notice_date": (notice_date or report.get("notice_date") or "")[:10] or None,
            "published_at": notice_date or report.get("published_at"),
            "content_text": content_text,
            "attach_url": first.get("attach_url") or first.get("attach_url_web"),
            "content_hash": hashlib.sha256(
                content_text.encode("utf-8")
            ).hexdigest(),
            "source": "company_filing",
            "warnings": warnings,
            "fetched_at": utc_now(),
        }

    def _fetch_content_page(
        self, article_code: str, page_index: int
    ) -> dict[str, Any]:
        response = self.http_get(
            self.CONTENT_URL,
            params={
                "art_code": article_code,
                "client_source": "web",
                "page_index": page_index,
            },
            headers={"User-Agent": _UA, "Referer": "https://data.eastmoney.com/"},
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data") or {}
        if not data:
            raise ProviderError(f"财报正文第 {page_index} 页缺失")
        return data


def _a_share_identity(symbol: str) -> tuple[str, str]:
    canonical = normalize_symbol(symbol)
    if not canonical.endswith((".SS", ".SZ")):
        raise ValueError("A股财报全文只支持 .SS/.SZ 证券")
    return canonical, canonical[:-3]


def _parse_report_identity(title: str) -> tuple[str, str] | None:
    match = _REPORT_TITLE_RE.search(title)
    if not match:
        return None
    year = match.group("year")
    kind = match.group("kind")
    if kind in {"第一季度", "一季度"}:
        return "first_quarter", f"{year}-03-31"
    if kind in {"半年度", "中期"}:
        return "half_year", f"{year}-06-30"
    if kind in {"第三季度", "三季度"}:
        return "third_quarter", f"{year}-09-30"
    return "annual", f"{year}-12-31"


def _identity_from_columns(
    columns: set[str],
) -> tuple[str | None, str | None]:
    for column in columns:
        if column == "一季度报告全文":
            return "first_quarter", None
        if column == "半年度报告全文":
            return "half_year", None
        if column == "三季度报告全文":
            return "third_quarter", None
        if column == "年度报告全文":
            return "annual", None
    return None, None


def _datetime_iso(value: Any) -> str | None:
    if not value:
        return None
    text = str(value).strip().replace(":000", "")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    return parsed.isoformat(timespec="seconds")


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def _clean_content(value: str) -> str:
    text = html.unescape(value).replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u3000", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text.strip()


def _integer(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
