from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import threading
import time
from typing import Any

from app.catalog import RESEARCH_TARGETS, SECURITY_NAME_ALIASES, normalize_symbol
from app.utils import utc_now


_PERIOD_CONFIG = {
    "1m": {"range": "1d", "interval": "1m", "bucket": "minute"},
    "1d": {"range": "1y", "interval": "1d", "bucket": "day"},
    "1w": {"range": "2y", "interval": "1d", "bucket": "week"},
    "1M": {"range": "5y", "interval": "1d", "bucket": "month"},
    "1Y": {"range": "max", "interval": "1d", "bucket": "year"},
}


class StockDashboardService:
    """Real-data adapter for the high-fidelity stock score page."""

    def __init__(
        self,
        *,
        market_provider: Any,
        fundamentals_service: Any,
        tushare_client: Any | None = None,
        catalog_ttl_seconds: int = 21_600,
    ) -> None:
        self.market_provider = market_provider
        self.fundamentals_service = fundamentals_service
        self.tushare_client = tushare_client
        self.catalog_ttl_seconds = max(300, catalog_ttl_seconds)
        self._catalog_lock = threading.Lock()
        self._catalog_cache: tuple[float, list[dict[str, Any]]] | None = None
        self._kline_cache_lock = threading.Lock()
        self._kline_cache: dict[
            tuple[str, str, int, str], tuple[float, dict[str, Any]]
        ] = {}

    @staticmethod
    def period_config(period: str) -> dict[str, str]:
        config = _PERIOD_CONFIG.get(period)
        if config is None:
            raise ValueError("不支持的 K 线周期")
        return dict(config)

    def search(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        keyword = query.strip()
        if not keyword:
            return []
        limit = max(1, min(int(limit), 20))
        folded = _fold(keyword)
        digits = "".join(character for character in keyword if character.isdigit())
        ranked: list[tuple[int, str, dict[str, Any]]] = []
        for item in self._stock_catalog():
            symbol = str(item.get("symbol") or "")
            code = symbol.split(".", 1)[0]
            name = str(item.get("name") or "")
            spelling = str(item.get("spelling") or "")
            searchable = (_fold(symbol), _fold(code), _fold(name), _fold(spelling))
            if not any(folded in value for value in searchable):
                continue
            rank = 50
            if folded in {_fold(symbol), _fold(code), _fold(name)}:
                rank = 0
            elif digits and code == digits:
                rank = 1
            elif _fold(name).startswith(folded):
                rank = 5
            elif _fold(code).startswith(folded):
                rank = 8
            elif _fold(spelling).startswith(folded):
                rank = 12
            ranked.append((rank, code, item))
        ranked.sort(key=lambda row: (row[0], row[1]))
        return [dict(item) for _, _, item in ranked[:limit]]

    def profile(self, symbol: str) -> dict[str, Any]:
        """Return the catalog identity used by watchlist and stock-search views."""
        canonical = normalize_symbol(symbol)
        if canonical.endswith((".SS", ".SZ", ".BJ")):
            return self._identity(canonical, valuation={})

        target = RESEARCH_TARGETS.get(canonical) or {}
        return {
            "symbol": canonical,
            "internalSymbol": canonical,
            "name": target.get("name") or canonical,
            "exchange": None,
            "market": target.get("market"),
            "area": None,
            "industry": None,
            "listDate": None,
        }

    def score_card(
        self, symbol: str, *, allow_remote: bool = True
    ) -> dict[str, Any]:
        canonical = _canonical_a_share(symbol)
        get_cached_fundamentals = getattr(
            self.fundamentals_service, "get_cached_packet", None
        )
        fundamentals = (
            get_cached_fundamentals(canonical)
            if not allow_remote and callable(get_cached_fundamentals)
            else self.fundamentals_service.get_packet(canonical)
        )
        valuation = dict(fundamentals.get("valuation") or {})
        periods = list(fundamentals.get("financial_periods") or [])
        latest_report = periods[0] if periods else {}
        identity = self._identity(canonical, valuation=valuation)

        intraday: dict[str, Any] = {}
        intraday_warning = None
        try:
            if allow_remote:
                intraday = self.market_provider.fetch_history(
                    canonical,
                    range_name="1d",
                    interval="1m",
                )
            else:
                read_cached = getattr(
                    self.market_provider, "read_cached_history", None
                )
                if callable(read_cached):
                    intraday = read_cached(
                        canonical,
                        range_name="1d",
                        interval="1m",
                        allow_stale=True,
                    ) or {}
        except Exception as exc:
            intraday_warning = f"分时行情暂不可用：{type(exc).__name__}"

        points = list(intraday.get("points") or [])
        latest = points[-1] if points else {}
        previous_close = intraday.get("previous_close")
        if previous_close is None:
            previous_close = valuation.get("previous_close")
        price = latest.get("close")
        if price is None:
            price = valuation.get("price")
        pct_change = _pct_change(price, previous_close)
        if pct_change is None:
            pct_change = valuation.get("pct_change")

        valid_volumes = [
            int(point["volume"])
            for point in points
            if isinstance(point.get("volume"), (int, float))
            and float(point["volume"]) >= 0
        ]
        volume_shares = sum(valid_volumes) if valid_volumes else None
        amount_cny = (
            sum(
                float(point["close"]) * float(point["volume"])
                for point in points
                if isinstance(point.get("close"), (int, float))
                and isinstance(point.get("volume"), (int, float))
                and float(point["volume"]) >= 0
            )
            if valid_volumes
            else None
        )
        opens = [
            float(point["open"])
            for point in points
            if isinstance(point.get("open"), (int, float))
        ]
        highs = [
            float(point["high"])
            for point in points
            if isinstance(point.get("high"), (int, float))
        ]
        lows = [
            float(point["low"])
            for point in points
            if isinstance(point.get("low"), (int, float))
        ]
        warnings = list(fundamentals.get("warnings") or [])
        if intraday_warning:
            warnings.append(intraday_warning)
        if amount_cny is not None:
            warnings.append("成交额按分钟成交量与分钟收盘价汇总，为近似值。")

        market_timestamp = (
            intraday.get("market_timestamp")
            or latest.get("timestamp")
            or valuation.get("market_timestamp")
        )
        quote_status = "available" if price is not None and market_timestamp else "partial"
        financial_status = "available" if latest_report.get("report_date") else "unavailable"
        return {
            "symbol": _external_symbol(canonical),
            "internalSymbol": canonical,
            "identity": identity,
            "quote": {
                "price": price,
                "change": (
                    round(float(price) - float(previous_close), 4)
                    if price is not None and previous_close is not None
                    else None
                ),
                "changePct": pct_change,
                "open": opens[0] if opens else None,
                "previousClose": previous_close,
                "high": max(highs) if highs else None,
                "low": min(lows) if lows else None,
                "volumeShares": volume_shares,
                "amountCny": round(amount_cny, 2) if amount_cny is not None else None,
                "turnoverRatePct": valuation.get("turnover_rate_pct"),
                "totalMarketCapCny": valuation.get("total_market_cap"),
                "marketTimestamp": market_timestamp,
                "source": "Yahoo Finance 分钟行情 + 腾讯实时估值",
            },
            "metrics": {
                "peTtm": valuation.get("pe_ttm"),
                "pbLf": valuation.get("pb"),
                "roeWeightedReport": latest_report.get("roe_weighted_pct"),
                "revenueYoy": latest_report.get("revenue_yoy_pct"),
                "parentNetProfitYoy": latest_report.get("net_profit_yoy_pct"),
                "reportDate": latest_report.get("report_date"),
                "reportName": latest_report.get("report_date_name"),
                "periodBasis": latest_report.get("period_basis"),
                "valuationTimestamp": valuation.get("market_timestamp"),
                "valuationSource": valuation.get("source"),
                "financialSource": latest_report.get("source"),
                "roeTtmAvailable": False,
            },
            "generatedAt": utc_now(),
            "cache": {
                "state": (
                    "fresh"
                    if intraday and not intraday.get("is_stale")
                    else "stale"
                    if intraday or valuation
                    else "warming"
                ),
                "refreshing": False,
                "dataAsOf": market_timestamp,
            },
            "dataStatus": {
                "quote": quote_status,
                "financials": financial_status,
                "valuation": "available" if valuation else "unavailable",
            },
            "officialSearch": {
                "cninfoQuery": identity["name"],
                "filingsLabel": "巨潮资讯：按证券名称检索公告与财报",
                "researchLabel": "研报检索：按证券名称检索",
            },
            "warnings": list(dict.fromkeys(warnings)),
        }

    def kline(
        self,
        symbol: str,
        *,
        period: str = "1d",
        limit: int = 80,
        adjust: str = "qfq",
        allow_remote: bool = True,
    ) -> dict[str, Any]:
        canonical = _canonical_a_share(symbol)
        config = _PERIOD_CONFIG.get(period)
        if config is None:
            raise ValueError("不支持的 K 线周期")
        limit = max(1, min(int(limit), 240))
        cache_key = (canonical, period, limit, adjust)
        cache_ttl = 8 if period == "1m" else 120
        now = time.monotonic()
        stale_packet: dict[str, Any] | None = None
        with self._kline_cache_lock:
            cached = self._kline_cache.get(cache_key)
            if cached is not None:
                expires_at, cached_packet = cached
                if expires_at > now:
                    result = deepcopy(cached_packet)
                    result["cache"] = {"state": "hit", "ttlSeconds": cache_ttl}
                    return result
                if expires_at + cache_ttl * 5 > now:
                    stale_packet = cached_packet
        try:
            if allow_remote:
                packet = self.market_provider.fetch_history(
                    canonical,
                    range_name=config["range"],
                    interval=config["interval"],
                )
            else:
                read_cached = getattr(
                    self.market_provider, "read_cached_history", None
                )
                packet = (
                    read_cached(
                        canonical,
                        range_name=config["range"],
                        interval=config["interval"],
                        allow_stale=True,
                    )
                    if callable(read_cached)
                    else None
                )
                if packet is None:
                    return {
                        "symbol": _external_symbol(canonical),
                        "period": period,
                        "adjustment": adjust,
                        "source": None,
                        "marketTimestamp": None,
                        "fetchedAt": None,
                        "warnings": [],
                        "data": [],
                        "cache": {
                            "state": "warming",
                            "ttlSeconds": cache_ttl,
                        },
                    }
        except Exception:
            if stale_packet is None:
                raise
            result = deepcopy(stale_packet)
            result["warnings"] = list(
                dict.fromkeys(
                    [
                        *list(result.get("warnings") or []),
                        "K线上游刷新失败，已返回最近一次成功数据。",
                    ]
                )
            )
            result["cache"] = {"state": "stale", "ttlSeconds": cache_ttl}
            return result
        points = [
            _adjusted_point(point, use_adjustment=period != "1m" and adjust == "qfq")
            for point in (packet.get("points") or [])
        ]
        points = [point for point in points if point is not None]
        if config["bucket"] not in {"minute", "day"}:
            points = _aggregate(points, config["bucket"])
        points = points[-limit:]
        if not points:
            raise RuntimeError("没有可用的 K 线数据")
        adjustment = (
            "上游复权收盘价比例校正"
            if period != "1m" and adjust == "qfq"
            else "不复权"
        )
        result = {
            "symbol": _external_symbol(canonical),
            "period": period,
            "adjustment": adjustment,
            "source": packet.get("source"),
            "marketTimestamp": points[-1]["time"],
            "fetchedAt": packet.get("fetched_at"),
            "warnings": packet.get("warnings") or [],
            "data": points,
            "cache": {
                "state": "stale" if packet.get("is_stale") else "fresh",
                "ttlSeconds": cache_ttl,
            },
        }
        with self._kline_cache_lock:
            if len(self._kline_cache) >= 512:
                self._kline_cache = {
                    key: value
                    for key, value in self._kline_cache.items()
                    if value[0] > now
                }
            self._kline_cache[cache_key] = (
                time.monotonic() + cache_ttl,
                deepcopy(result),
            )
        return result

    def _identity(
        self, canonical: str, *, valuation: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            record = next(
                (
                    item
                    for item in self._stock_catalog()
                    if item.get("internalSymbol") == canonical
                ),
                None,
            )
        except Exception:
            record = None
        if record is not None:
            return dict(record)
        target = RESEARCH_TARGETS.get(canonical) or {}
        return {
            "symbol": _external_symbol(canonical),
            "internalSymbol": canonical,
            "name": valuation.get("name") or target.get("name") or canonical,
            "exchange": "BSE"
            if canonical.endswith(".BJ")
            else "SSE"
            if canonical.endswith(".SS")
            else "SZSE",
            "market": _board_name(canonical),
            "area": None,
            "industry": None,
            "listDate": None,
        }

    def _stock_catalog(self) -> list[dict[str, Any]]:
        now = time.monotonic()
        if self._catalog_cache and self._catalog_cache[0] > now:
            return self._catalog_cache[1]
        with self._catalog_lock:
            now = time.monotonic()
            if self._catalog_cache and self._catalog_cache[0] > now:
                return self._catalog_cache[1]
            database = getattr(self.market_provider, "database", None)
            if database is not None:
                cached = database.get_cache("stock-catalog:a-share:v1")
                if cached is not None and isinstance(cached.get("items"), list):
                    records = list(cached["items"])
                    self._catalog_cache = (
                        now + self.catalog_ttl_seconds,
                        records,
                    )
                    return records
            records = self._fetch_stock_catalog()
            if database is not None and records:
                database.put_cache(
                    "stock-catalog:a-share:v1",
                    {"items": records},
                    max(86_400, self.catalog_ttl_seconds),
                )
            self._catalog_cache = (
                now + self.catalog_ttl_seconds,
                records,
            )
            return records

    def prewarm_catalog(self) -> None:
        self._stock_catalog()

    def _fetch_stock_catalog(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        stock_basic = getattr(self.tushare_client, "stock_basic", None)
        if callable(stock_basic):
            frame = stock_basic(
                exchange="",
                list_status="L",
                fields=(
                    "ts_code,symbol,name,area,industry,market,"
                    "list_date,exchange,cnspell"
                ),
            )
            for row in frame.to_dict(orient="records"):
                ts_code = str(row.get("ts_code") or "").strip().upper()
                if not _is_listed_a_share(ts_code):
                    continue
                canonical = normalize_symbol(ts_code)
                records.append(
                    {
                        "symbol": _external_symbol(canonical),
                        "internalSymbol": canonical,
                        "name": str(row.get("name") or ts_code.split(".", 1)[0]),
                        "exchange": row.get("exchange"),
                        "market": row.get("market") or _board_name(canonical),
                        "area": row.get("area"),
                        "industry": row.get("industry"),
                        "listDate": row.get("list_date"),
                        "spelling": row.get("cnspell"),
                    }
                )
        # Always merge the small audited alias catalog. Some compatible
        # stock-basic providers return a partial universe; name routing for a
        # known security must not disappear merely because that partial list is
        # non-empty.
        seen: set[str] = {
            str(item.get("internalSymbol") or "")
            for item in records
            if item.get("internalSymbol")
        }
        for name, symbol in SECURITY_NAME_ALIASES.items():
            try:
                canonical = _canonical_a_share(symbol)
            except ValueError:
                continue
            if canonical in seen:
                continue
            seen.add(canonical)
            records.append(
                {
                    "symbol": _external_symbol(canonical),
                    "internalSymbol": canonical,
                    "name": name,
                    "exchange": None,
                    "market": _board_name(canonical),
                    "area": None,
                    "industry": None,
                    "listDate": None,
                    "spelling": None,
                }
            )
        records.sort(key=lambda item: str(item.get("symbol") or ""))
        return records


def _fold(value: Any) -> str:
    return (
        str(value or "")
        .strip()
        .lower()
        .replace(".", "")
        .replace(" ", "")
    )


def _canonical_a_share(symbol: str) -> str:
    canonical = normalize_symbol(symbol)
    if not canonical.endswith((".SS", ".SZ", ".BJ")):
        raise ValueError("个股评分库目前只支持 A 股证券")
    return canonical


def _external_symbol(symbol: str) -> str:
    return symbol[:-3] + ".SH" if symbol.endswith(".SS") else symbol


def _is_listed_a_share(ts_code: str) -> bool:
    code, _, exchange = ts_code.partition(".")
    if exchange == "SH":
        return code.startswith(("600", "601", "603", "605", "688", "689"))
    if exchange == "SZ":
        return code.startswith(("000", "001", "002", "003", "300", "301"))
    if exchange == "BJ":
        return code.startswith(("4", "8", "92"))
    return False


def _board_name(symbol: str) -> str:
    code = symbol.split(".", 1)[0]
    if symbol.endswith(".BJ"):
        return "北交所"
    if symbol.endswith(".SS") and code.startswith(("688", "689")):
        return "科创板"
    if symbol.endswith(".SZ") and code.startswith(("300", "301")):
        return "创业板"
    if symbol.endswith(".SS"):
        return "上证主板"
    return "深证主板"


def _pct_change(price: Any, previous_close: Any) -> float | None:
    if price is None or previous_close in (None, 0):
        return None
    return round((float(price) / float(previous_close) - 1) * 100, 4)


def _adjusted_point(
    point: dict[str, Any], *, use_adjustment: bool
) -> dict[str, Any] | None:
    values = [
        point.get("open"),
        point.get("high"),
        point.get("low"),
        point.get("close"),
    ]
    if not point.get("timestamp") or any(value is None for value in values):
        return None
    factor = 1.0
    if (
        use_adjustment
        and point.get("adjusted_close") is not None
        and float(point["close"]) != 0
    ):
        factor = float(point["adjusted_close"]) / float(point["close"])
    return {
        "time": str(point["timestamp"]),
        "open": round(float(point["open"]) * factor, 6),
        "high": round(float(point["high"]) * factor, 6),
        "low": round(float(point["low"]) * factor, 6),
        "close": round(float(point["close"]) * factor, 6),
        "volume": int(point.get("volume") or 0),
    }


def _aggregate(
    points: list[dict[str, Any]], bucket: str
) -> list[dict[str, Any]]:
    grouped: list[list[dict[str, Any]]] = []
    current_key: Any = None
    for point in points:
        timestamp = datetime.fromisoformat(str(point["time"]).replace("Z", "+00:00"))
        if bucket == "week":
            calendar = timestamp.isocalendar()
            key = (calendar.year, calendar.week)
        elif bucket == "month":
            key = (timestamp.year, timestamp.month)
        else:
            key = timestamp.year
        if key != current_key:
            grouped.append([])
            current_key = key
        grouped[-1].append(point)
    return [
        {
            "time": rows[-1]["time"],
            "open": rows[0]["open"],
            "high": max(row["high"] for row in rows),
            "low": min(row["low"] for row in rows),
            "close": rows[-1]["close"],
            "volume": sum(int(row.get("volume") or 0) for row in rows),
        }
        for rows in grouped
        if rows
    ]
