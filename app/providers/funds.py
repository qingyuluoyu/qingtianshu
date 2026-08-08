from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Callable
from zoneinfo import ZoneInfo

import requests

from app.providers.market import ProviderError
from app.utils import utc_now


_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


def _number(value: Any) -> float | None:
    if value in (None, "", "--", "-"):
        return None
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return None


def _date(value: Any) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    return text.split(" ", 1)[0] if text else None


def _strip_highlight(value: Any) -> str:
    return re.sub(r"<[^>]+>", "", str(value or "")).strip()


def _asset_class(fund_type: str) -> str:
    folded = fund_type.casefold()
    if "货币" in fund_type:
        return "money_market"
    if "债券" in fund_type or "固收" in fund_type:
        return "fixed_income"
    if "混合" in fund_type:
        return "mixed"
    if "指数" in fund_type and "股票" in fund_type:
        return "equity_index"
    if "股票" in fund_type:
        return "equity"
    if "qdii" in folded or "海外" in fund_type:
        return "overseas"
    if any(term in fund_type for term in ("商品", "黄金", "原油")):
        return "commodity"
    if "reits" in folded or "reit" in folded:
        return "reit"
    return "other"


def _product_kind(code: str, name: str, purchase_status: str) -> str:
    if "ETF" in name.upper() or purchase_status == "场内交易":
        return "etf"
    if code.startswith(("50", "51", "52", "56", "58", "15", "16")):
        return "etf"
    return "fund"


def _eastmoney_secid(code: str) -> str:
    if code.startswith(("50", "51", "52", "56", "58")):
        return f"1.{code}"
    return f"0.{code}"


class EastmoneyFundProvider:
    """Fetch public fund and ETF facts with explicit field/time boundaries."""

    SEARCH_URL = "https://fundsuggest.eastmoney.com/FundSearch/api/FundSearchAPI.ashx"
    BASE_INFORMATION_URL = (
        "https://fundmobapi.eastmoney.com/FundMApi/FundBaseTypeInformation.ashx"
    )
    ETF_QUOTE_URL = "https://push2.eastmoney.com/api/qt/stock/get"
    TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q="
    SINA_QUOTE_URL = "https://hq.sinajs.cn/list="

    def __init__(self, http_get: Callable[..., Any] = requests.get) -> None:
        self.http_get = http_get

    def search(self, query: str, *, limit: int = 8) -> dict[str, Any]:
        keyword = str(query or "").strip()
        if not keyword:
            raise ValueError("请输入基金或ETF名称、简称或6位代码")
        response = self.http_get(
            self.SEARCH_URL,
            params={"m": 1, "key": keyword},
            headers={"User-Agent": _UA, "Referer": "https://fund.eastmoney.com/"},
            timeout=15,
        )
        response.raise_for_status()
        try:
            payload = response.json()
        except Exception as exc:
            raise ProviderError("基金产品搜索没有返回有效 JSON") from exc
        rows = payload.get("Datas") or []
        items: list[dict[str, Any]] = []
        for row in rows:
            code = str(row.get("CODE") or row.get("_id") or "").strip()
            if not re.fullmatch(r"\d{6}", code):
                continue
            base = row.get("FundBaseInfo") or {}
            name = _strip_highlight(
                row.get("NAME") or base.get("SHORTNAME") or row.get("HIGHTLIGHT")
            )
            fund_type = str(base.get("FTYPE") or "未分类")
            items.append(
                {
                    "code": code,
                    "name": name or code,
                    "fund_type": fund_type,
                    "asset_class": _asset_class(fund_type),
                    "product_kind": _product_kind(
                        code,
                        name,
                        "场内交易" if "ETF" in name.upper() else "",
                    ),
                    "fund_company": base.get("JJGS"),
                    "fund_manager": base.get("JJJL"),
                    "nav": _number(base.get("DWJZ")),
                    "nav_date": _date(base.get("FSRQ")),
                    "minimum_purchase_cny": _number(base.get("MINSG")),
                }
            )
            if len(items) >= max(1, min(int(limit), 20)):
                break
        return {
            "query": keyword,
            "items": items,
            "source": "Eastmoney Fund Search",
            "source_url": self.SEARCH_URL,
            "fetched_at": utc_now(),
            "warnings": [
                "搜索结果只用于定位产品，具体状态和数据时间需打开产品详情核验。"
            ],
        }

    def fetch_product(self, code: str) -> dict[str, Any]:
        canonical = str(code or "").strip()
        if not re.fullmatch(r"\d{6}", canonical):
            raise ValueError("基金或ETF代码必须是6位数字")
        response = self.http_get(
            self.BASE_INFORMATION_URL,
            params={
                "FCODE": canonical,
                "deviceid": "qingshu",
                "plat": "Iphone",
                "product": "EFund",
                "version": "6.3.8",
            },
            headers={"User-Agent": _UA, "Referer": "https://fund.eastmoney.com/"},
            timeout=15,
        )
        response.raise_for_status()
        try:
            payload = response.json()
        except Exception as exc:
            raise ProviderError("基金产品详情没有返回有效 JSON") from exc
        data = payload.get("Datas") or {}
        if int(payload.get("ErrCode") or 0) != 0 or not data:
            raise ProviderError("没有取得该基金或ETF的公开产品详情")

        name = str(data.get("SHORTNAME") or canonical).strip()
        purchase_status = str(data.get("SGZT") or "未知")
        kind = _product_kind(canonical, name, purchase_status)
        fund_type = str(data.get("FTYPE") or "未分类")
        fetched_at = utc_now()
        warnings = [
            "历史收益只描述截至对应净值日期的过去表现，不代表未来收益。",
            "页面申购费率可能是特定销售渠道折扣，不等于全部持有成本。",
        ]
        live_quote = None
        if kind == "etf":
            try:
                live_quote = self._fetch_etf_quote(canonical)
                warnings.extend(live_quote.pop("warnings", []))
            except Exception:
                warnings.append("ETF实时成交报价暂未取得，仍保留最近基金净值事实。")

        return {
            "code": canonical,
            "name": name,
            "product_kind": kind,
            "asset_class": _asset_class(fund_type),
            "fund_type": fund_type,
            "nav": _number(data.get("DWJZ")),
            "accumulated_nav": _number(data.get("LJJZ")),
            "nav_date": _date(data.get("FSRQ")),
            "daily_return_pct": _number(data.get("RZDF")),
            "returns": {
                "one_month_pct": _number(data.get("SYL_Y")),
                "three_month_pct": _number(data.get("SYL_3Y")),
                "six_month_pct": _number(data.get("SYL_6Y")),
                "one_year_pct": _number(data.get("SYL_1N")),
            },
            "return_ranks": {
                "one_month": {
                    "rank": _number(data.get("RANKM")),
                    "universe": _number(data.get("MSC")),
                },
                "three_month": {
                    "rank": _number(data.get("RANKQ")),
                    "universe": _number(data.get("QSC")),
                },
                "six_month": {
                    "rank": _number(data.get("RANKHY")),
                    "universe": _number(data.get("HYSC")),
                },
                "one_year": {
                    "rank": _number(data.get("RANKY")),
                    "universe": _number(data.get("YSC")),
                },
            },
            "purchase_status": purchase_status,
            "redemption_status": str(data.get("SHZT") or "未知"),
            "fees": {
                "listed_purchase_fee_pct": _number(
                    str(data.get("SOURCERATE") or "").replace("%", "")
                ),
                "current_channel_purchase_fee_pct": _number(
                    str(data.get("RATE") or "").replace("%", "")
                ),
                "scope": "申购页面展示费率；未包含管理费、托管费、销售服务费和赎回费",
            },
            "minimum_purchase_cny": _number(data.get("MINSG")),
            "minimum_recurring_purchase_cny": _number(data.get("MINDT")),
            "risk_level_upstream": str(data.get("RISKLEVEL") or "") or None,
            "net_assets_cny": _number(data.get("ENDNAV")),
            "fund_shares": _number(data.get("FEGM")),
            "fund_company": data.get("JJGS"),
            "fund_manager": data.get("JJJL"),
            "inception_date": _date(data.get("ISSBDATE")),
            "top_holdings_summary": [
                item.strip()
                for item in str(data.get("FUNDINVEST") or "").split(",")
                if item.strip()
            ][:12],
            "live_quote": live_quote,
            "source": "Eastmoney Fund Mobile API",
            "source_url": (
                "https://fundmobapi.eastmoney.com/FundMApi/"
                f"FundBaseTypeInformation.ashx?FCODE={canonical}"
            ),
            "fetched_at": fetched_at,
            "field_mapping": "eastmoney_fund_base_v1",
            "warnings": list(dict.fromkeys(warnings)),
        }

    def _fetch_etf_quote(self, code: str) -> dict[str, Any]:
        failures: list[Exception] = []
        for fetch in (
            self._fetch_etf_quote_eastmoney,
            self._fetch_etf_quote_tencent,
            self._fetch_etf_quote_sina,
        ):
            try:
                quote = fetch(code)
                if quote.get("price") is not None:
                    return quote
            except Exception as exc:
                failures.append(exc)
        raise ProviderError("ETF实时成交报价不可用") from failures[-1]

    def _fetch_etf_quote_eastmoney(self, code: str) -> dict[str, Any]:
        response = self.http_get(
            self.ETF_QUOTE_URL,
            params={
                "secid": _eastmoney_secid(code),
                "fields": (
                    "f43,f44,f45,f46,f47,f48,f57,f58,f59,f60,f124,f169,f170,f171"
                ),
            },
            headers={"User-Agent": _UA, "Referer": "https://quote.eastmoney.com/"},
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data") or {}
        if int(payload.get("rc") or 0) != 0 or not data:
            raise ProviderError("ETF实时成交报价不可用")
        decimals = int(data.get("f59") or 3)
        price_scale = float(10**decimals)
        market_timestamp = None
        raw_timestamp = data.get("f124")
        if isinstance(raw_timestamp, (int, float)) and raw_timestamp > 0:
            market_timestamp = (
                datetime.fromtimestamp(raw_timestamp, tz=timezone.utc)
                .astimezone(ZoneInfo("Asia/Shanghai"))
                .isoformat(timespec="seconds")
            )
        warnings = []
        if market_timestamp is None:
            warnings.append("ETF成交时间戳未返回；成交价仅标记为本次抓取快照。")
        return {
            "price": (
                round(float(data["f43"]) / price_scale, decimals)
                if data.get("f43") not in (None, "-")
                else None
            ),
            "previous_close": (
                round(float(data["f60"]) / price_scale, decimals)
                if data.get("f60") not in (None, "-")
                else None
            ),
            "pct_change": (
                round(float(data["f170"]) / 100.0, 4)
                if data.get("f170") not in (None, "-")
                else None
            ),
            "turnover_cny": _number(data.get("f48")),
            "volume": _number(data.get("f47")),
            "market_timestamp": market_timestamp,
            "fetched_at": utc_now(),
            "source": "Eastmoney Realtime Quote",
            "source_url": self.ETF_QUOTE_URL,
            "warnings": warnings,
        }

    @staticmethod
    def _quote_prefix(code: str) -> str:
        return (
            f"sh{code}"
            if code.startswith(("50", "51", "52", "56", "58"))
            else f"sz{code}"
        )

    def _fetch_etf_quote_tencent(self, code: str) -> dict[str, Any]:
        symbol = self._quote_prefix(code)
        response = self.http_get(
            f"{self.TENCENT_QUOTE_URL}{symbol}",
            headers={"User-Agent": _UA, "Referer": "https://stockapp.finance.qq.com/"},
            timeout=10,
        )
        response.raise_for_status()
        match = re.search(r'="([^"]*)"', response.text)
        if match is None:
            raise ProviderError("腾讯ETF成交报价格式异常")
        fields = match.group(1).split("~")
        if len(fields) < 36 or fields[2] != code:
            raise ProviderError("腾讯ETF成交报价字段不完整")
        market_timestamp = None
        if fields[30]:
            try:
                market_timestamp = (
                    datetime.strptime(fields[30], "%Y%m%d%H%M%S")
                    .replace(tzinfo=ZoneInfo("Asia/Shanghai"))
                    .isoformat(timespec="seconds")
                )
            except ValueError:
                market_timestamp = None
        volume = _number(fields[6])
        transaction_fields = fields[35].split("/")
        turnover = (
            _number(transaction_fields[2]) if len(transaction_fields) > 2 else None
        )
        warnings = []
        if market_timestamp is None:
            warnings.append("ETF成交时间戳未返回；成交价仅标记为本次抓取快照。")
        return {
            "price": _number(fields[3]),
            "previous_close": _number(fields[4]),
            "pct_change": _number(fields[32]),
            "turnover_cny": turnover,
            "volume": round(volume * 100, 4) if volume is not None else None,
            "market_timestamp": market_timestamp,
            "fetched_at": utc_now(),
            "source": "Tencent Realtime Quote",
            "source_url": f"{self.TENCENT_QUOTE_URL}{symbol}",
            "warnings": warnings,
        }

    def _fetch_etf_quote_sina(self, code: str) -> dict[str, Any]:
        symbol = self._quote_prefix(code)
        response = self.http_get(
            f"{self.SINA_QUOTE_URL}{symbol}",
            headers={"User-Agent": _UA, "Referer": "https://finance.sina.com.cn/"},
            timeout=10,
        )
        response.raise_for_status()
        match = re.search(r'="([^"]*)"', response.text)
        if match is None:
            raise ProviderError("新浪ETF成交报价格式异常")
        fields = match.group(1).split(",")
        if len(fields) < 32:
            raise ProviderError("新浪ETF成交报价字段不完整")
        price = _number(fields[3])
        previous_close = _number(fields[2])
        pct_change = None
        if price is not None and previous_close not in (None, 0):
            pct_change = round((price / previous_close - 1) * 100, 4)
        market_timestamp = None
        if fields[30] and fields[31]:
            try:
                market_timestamp = (
                    datetime.strptime(f"{fields[30]} {fields[31]}", "%Y-%m-%d %H:%M:%S")
                    .replace(tzinfo=ZoneInfo("Asia/Shanghai"))
                    .isoformat(timespec="seconds")
                )
            except ValueError:
                market_timestamp = None
        warnings = []
        if market_timestamp is None:
            warnings.append("ETF成交时间戳未返回；成交价仅标记为本次抓取快照。")
        return {
            "price": price,
            "previous_close": previous_close,
            "pct_change": pct_change,
            "turnover_cny": _number(fields[9]),
            "volume": _number(fields[8]),
            "market_timestamp": market_timestamp,
            "fetched_at": utc_now(),
            "source": "Sina Realtime Quote",
            "source_url": f"{self.SINA_QUOTE_URL}{symbol}",
            "warnings": warnings,
        }


__all__ = ["EastmoneyFundProvider"]
