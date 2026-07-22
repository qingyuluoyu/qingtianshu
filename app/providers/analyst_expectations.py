from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Callable

import requests

from app.catalog import normalize_symbol
from app.providers.market import ProviderError
from app.utils import utc_now


_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


class AShareAnalystExpectationsProvider:
    """Fetch A-share broker-consensus and report metadata without target prices."""

    CONSENSUS_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    REPORT_URL = "https://reportapi.eastmoney.com/report/list"

    def __init__(
        self,
        http_get: Callable[..., Any] = requests.get,
        today_fn: Callable[[], date] = date.today,
    ):
        self.http_get = http_get
        self.today_fn = today_fn

    def fetch(self, symbol: str, report_limit: int = 20) -> dict[str, Any]:
        canonical, code = _a_share_identity(symbol)
        consensus = self._fetch_consensus(code)
        reports, current_year = self._fetch_reports(code, report_limit)
        if consensus is None and not reports:
            raise ProviderError("未取得可核验的分析师一致预期或个股研报")
        name = (
            (consensus or {}).get("SECURITY_NAME_ABBR")
            or (reports[0].get("stock_name") if reports else None)
            or code
        )
        return {
            "symbol": canonical,
            "name": name,
            "industry": (consensus or {}).get("INDUSTRY_BOARD")
            or (reports[0].get("industry") if reports else None),
            "rating_window": "近六个月",
            "rating_organization_count": _integer(
                (consensus or {}).get("RATING_ORG_NUM")
            ),
            "rating_counts": {
                "buy": _integer((consensus or {}).get("RATING_BUY_NUM")) or 0,
                "add": _integer((consensus or {}).get("RATING_ADD_NUM")) or 0,
                "neutral": _integer(
                    (consensus or {}).get("RATING_NEUTRAL_NUM")
                )
                or 0,
                "reduce": _integer(
                    (consensus or {}).get("RATING_REDUCE_NUM")
                )
                or 0,
                "sell": _integer((consensus or {}).get("RATING_SALE_NUM")) or 0,
            },
            "forecast_eps": _consensus_forecasts(consensus or {}),
            "reports": reports,
            "report_current_year": current_year,
            "fetched_at": utc_now(),
            "sources": [
                {
                    "name": "Eastmoney Broker Consensus",
                    "url": "https://data.eastmoney.com/report/profitforecast.jshtml",
                    "scope": "券商研报统计与盈利预测汇总",
                },
                {
                    "name": "Eastmoney Stock Research Reports",
                    "url": f"https://data.eastmoney.com/report/{code}.html",
                    "scope": "个股研报标题、机构、评级与EPS预测字段",
                },
            ],
        }

    def _fetch_consensus(self, code: str) -> dict[str, Any] | None:
        response = self.http_get(
            self.CONSENSUS_URL,
            params={
                "reportName": "RPT_WEB_RESPREDICT",
                "columns": "WEB_RESPREDICT",
                "pageNumber": 1,
                "pageSize": 20,
                "sortTypes": -1,
                "sortColumns": "RATING_ORG_NUM",
                "p": 1,
                "pageNo": 1,
                "pageNum": 1,
                "filter": f'(SECURITY_CODE="{code}")',
            },
            headers={"User-Agent": _UA, "Referer": "https://data.eastmoney.com/"},
            timeout=15,
        )
        response.raise_for_status()
        try:
            payload = response.json()
        except Exception as exc:
            raise ProviderError("分析师一致预期响应不是有效 JSON") from exc
        rows = (payload.get("result") or {}).get("data") or []
        return rows[0] if rows else None

    def _fetch_reports(
        self, code: str, report_limit: int
    ) -> tuple[list[dict[str, Any]], int]:
        today = self.today_fn()
        response = self.http_get(
            self.REPORT_URL,
            params={
                "industryCode": "*",
                "pageSize": max(20, min(report_limit, 100)),
                "industry": "*",
                "rating": "*",
                "ratingChange": "*",
                "beginTime": (today - timedelta(days=550)).isoformat(),
                "endTime": (today + timedelta(days=1)).isoformat(),
                "pageNo": 1,
                "fields": "",
                "qType": 0,
                "orgCode": "",
                "code": code,
                "rcode": "",
                "p": 1,
                "pageNum": 1,
                "pageNumber": 1,
            },
            headers={"User-Agent": _UA, "Referer": "https://data.eastmoney.com/"},
            timeout=15,
        )
        response.raise_for_status()
        try:
            payload = response.json()
        except Exception as exc:
            raise ProviderError("个股研报响应不是有效 JSON") from exc
        current_year = _integer(payload.get("currentYear")) or today.year
        reports = []
        for row in (payload.get("data") or [])[:report_limit]:
            info_code = str(row.get("infoCode") or "").strip()
            reports.append(
                {
                    "title": str(row.get("title") or "").strip(),
                    "stock_name": str(row.get("stockName") or "").strip(),
                    "institution": str(row.get("orgSName") or "").strip(),
                    "published_at": _date(row.get("publishDate")),
                    "rating": str(
                        row.get("emRatingName") or row.get("sRatingName") or ""
                    ).strip(),
                    "previous_rating": str(
                        row.get("lastEmRatingName") or ""
                    ).strip(),
                    "industry": str(row.get("indvInduName") or "").strip(),
                    "researchers": str(row.get("researcher") or "").strip(),
                    "forecast_eps": [
                        {
                            "year": current_year,
                            "value": _number(row.get("predictThisYearEps")),
                        },
                        {
                            "year": current_year + 1,
                            "value": _number(row.get("predictNextYearEps")),
                        },
                        {
                            "year": current_year + 2,
                            "value": _number(row.get("predictNextTwoYearEps")),
                        },
                    ],
                    "report_url": (
                        f"https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf"
                        if info_code
                        else None
                    ),
                }
            )
        reports.sort(key=lambda item: item.get("published_at") or "", reverse=True)
        return reports, current_year


def _a_share_identity(symbol: str) -> tuple[str, str]:
    canonical = normalize_symbol(symbol)
    if not canonical.endswith((".SS", ".SZ")):
        raise ValueError("分析师一致预期当前只支持 A 股证券")
    return canonical, canonical.split(".", 1)[0]


def _consensus_forecasts(row: dict[str, Any]) -> list[dict[str, Any]]:
    forecasts = []
    for index in range(1, 5):
        year = _integer(row.get(f"YEAR{index}"))
        value = _number(row.get(f"EPS{index}"))
        if year is None or value is None:
            continue
        mark = str(row.get(f"YEAR_MARK{index}") or "").upper()
        forecasts.append(
            {
                "year": year,
                "value": value,
                "kind": "actual" if mark == "A" else "estimate",
            }
        )
    return forecasts


def _number(value: Any) -> float | None:
    if value in (None, "", "--"):
        return None
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return None


def _integer(value: Any) -> int | None:
    if value in (None, "", "--"):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _date(value: Any) -> str | None:
    if not value:
        return None
    return str(value).split(" ", 1)[0]
