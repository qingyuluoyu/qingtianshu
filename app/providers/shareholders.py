from __future__ import annotations

from datetime import date, datetime
from typing import Any, Callable

import requests

from app.catalog import normalize_symbol
from app.providers.market import ProviderError
from app.utils import utc_now


_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


class AShareShareholderProvider:
    HOLDER_HISTORY_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    TOP10_URL = (
        "https://emweb.securities.eastmoney.com/"
        "PC_HSF10/ShareholderResearch/PageSDGD"
    )

    def __init__(
        self,
        http_get: Callable[..., Any] = requests.get,
        today_fn: Callable[[], date] = date.today,
    ):
        self.http_get = http_get
        self.today_fn = today_fn

    def fetch(self, symbol: str, history_limit: int = 12) -> dict[str, Any]:
        canonical, security_code, provider_symbol = _identity(symbol)
        fetched_at = utc_now()
        holder_source_url = (
            f"https://data.eastmoney.com/gdhs/detail/{security_code}.html"
        )
        history_response = self.http_get(
            self.HOLDER_HISTORY_URL,
            params={
                "sortColumns": "END_DATE",
                "sortTypes": "-1",
                "pageSize": str(max(12, min(history_limit, 100))),
                "pageNumber": "1",
                "reportName": "RPT_HOLDERNUM_DET",
                "columns": (
                    "SECURITY_CODE,SECURITY_NAME_ABBR,END_DATE,INTERVAL_CHRATE,"
                    "AVG_MARKET_CAP,AVG_HOLD_NUM,TOTAL_MARKET_CAP,TOTAL_A_SHARES,"
                    "HOLD_NOTICE_DATE,HOLDER_NUM,PRE_HOLDER_NUM,HOLDER_NUM_CHANGE,"
                    "HOLDER_NUM_RATIO,PRE_END_DATE"
                ),
                "filter": f'(SECURITY_CODE="{security_code}")',
                "source": "WEB",
                "client": "WEB",
            },
            headers={"User-Agent": _UA, "Referer": holder_source_url},
            timeout=20,
        )
        history_response.raise_for_status()
        history_payload = history_response.json()
        history_rows = []
        for item in ((history_payload.get("result") or {}).get("data") or []):
            as_of = _date(item.get("END_DATE"))
            if as_of is None:
                continue
            history_rows.append(
                {
                    "as_of": as_of,
                    "previous_as_of": _date(item.get("PRE_END_DATE")),
                    "announced_at": _date(item.get("HOLD_NOTICE_DATE")),
                    "holder_count": _integer(item.get("HOLDER_NUM")),
                    "previous_holder_count": _integer(item.get("PRE_HOLDER_NUM")),
                    "holder_count_change": _integer(
                        item.get("HOLDER_NUM_CHANGE")
                    ),
                    "holder_count_change_pct": _number(
                        item.get("HOLDER_NUM_RATIO")
                    ),
                    "average_holding": _number(item.get("AVG_HOLD_NUM")),
                    "average_market_cap": _number(item.get("AVG_MARKET_CAP")),
                    "interval_price_change_pct": _number(
                        item.get("INTERVAL_CHRATE")
                    ),
                    "total_market_cap": _number(item.get("TOTAL_MARKET_CAP")),
                    "total_a_shares": _number(item.get("TOTAL_A_SHARES")),
                }
            )
        history_rows.sort(key=lambda item: item["as_of"], reverse=True)
        history_rows = history_rows[:history_limit]
        if not history_rows:
            raise ProviderError("股东户数历史数据为空")

        top_holders = []
        top10_report_date = None
        top_source_url = (
            "https://emweb.securities.eastmoney.com/PC_HSF10/"
            "ShareholderResearch/Index?type=web&code="
            f"{provider_symbol}"
        )
        attempted_report_dates = []
        for report_date in _recent_quarter_ends(self.today_fn(), count=8):
            attempted_report_dates.append(report_date)
            response = self.http_get(
                self.TOP10_URL,
                params={"code": provider_symbol, "date": report_date},
                headers={"User-Agent": _UA, "Referer": top_source_url},
                timeout=20,
            )
            response.raise_for_status()
            payload = response.json()
            parsed = []
            for item in payload.get("sdgd") or []:
                name = str(item.get("HOLDER_NAME") or "").strip()
                rank = _integer(item.get("HOLDER_RANK"))
                if not name or rank is None:
                    continue
                parsed.append(
                    {
                        "rank": rank,
                        "name": name,
                        "share_type": str(item.get("SHARES_TYPE") or "").strip()
                        or None,
                        "holding": _number(item.get("HOLD_NUM")),
                        "holding_ratio_pct": _number(
                            item.get("HOLD_NUM_RATIO")
                        ),
                        "holding_change": str(
                            item.get("HOLD_NUM_CHANGE") or ""
                        ).strip()
                        or None,
                        "holding_change_ratio_pct": _number(
                            item.get("CHANGE_RATIO")
                        ),
                    }
                )
            if parsed:
                parsed.sort(key=lambda item: item["rank"])
                top_holders = parsed[:10]
                top10_report_date = _date(
                    (payload.get("sdgd") or [{}])[0].get("END_DATE")
                ) or report_date
                break

        return {
            "symbol": canonical,
            "name": str(
                ((history_payload.get("result") or {}).get("data") or [{}])[0].get(
                    "SECURITY_NAME_ABBR"
                )
                or ""
            ).strip()
            or canonical,
            "holder_history": history_rows,
            "top10_report_date": top10_report_date,
            "top_holders": top_holders,
            "sources": [
                {
                    "source": "shareholder_count_disclosure",
                    "source_url": holder_source_url,
                },
                {
                    "source": "top_shareholders_disclosure",
                    "source_url": top_source_url,
                },
            ],
            "fetched_at": fetched_at,
            "coverage": {
                "holder_history_points": len(history_rows),
                "top_holders": len(top_holders),
                "attempted_top10_report_dates": attempted_report_dates,
            },
        }


def _identity(symbol: str) -> tuple[str, str, str]:
    canonical = normalize_symbol(symbol)
    if canonical.endswith(".SS"):
        return canonical, canonical[:-3], "SH" + canonical[:-3]
    if canonical.endswith(".SZ"):
        return canonical, canonical[:-3], "SZ" + canonical[:-3]
    raise ValueError("A股股东结构只支持 .SS/.SZ 证券")


def _recent_quarter_ends(today: date, count: int) -> list[str]:
    candidates = []
    for year in range(today.year, today.year - 4, -1):
        for month, day in ((12, 31), (9, 30), (6, 30), (3, 31)):
            candidate = date(year, month, day)
            if candidate <= today:
                candidates.append(candidate.isoformat())
    return sorted(candidates, reverse=True)[:count]


def _date(value: Any) -> str | None:
    if not value:
        return None
    text = str(value).strip()[:10]
    try:
        return datetime.fromisoformat(text).date().isoformat()
    except ValueError:
        return None


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _integer(value: Any) -> int | None:
    number = _number(value)
    if number is None:
        return None
    return int(number)
