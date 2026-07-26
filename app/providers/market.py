from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
import math
import re
from statistics import median, quantiles
import threading
from typing import Any, Callable
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests

try:
    import exchange_calendars as exchange_calendars
except ImportError:  # pragma: no cover - runtime dependency with safe fallback
    exchange_calendars = None

try:
    import pandas as pd
except ImportError:  # pragma: no cover - optional for spreadsheet source parsing
    pd = None

from app.db import Database
from app.utils import utc_now


class ProviderError(RuntimeError):
    pass


_DAILY_SESSION_CLOSE = {
    "Asia/Shanghai": (15, 0),
    "Asia/Hong_Kong": (16, 0),
    "Asia/Tokyo": (15, 30),
    "Asia/Seoul": (15, 30),
    "America/New_York": (16, 0),
    "Europe/London": (16, 30),
    "Europe/Berlin": (17, 30),
    "Australia/Sydney": (16, 0),
    "Asia/Kolkata": (15, 30),
}


def _valid_ohlc(point: dict[str, Any]) -> bool:
    close = _number(point.get("close"))
    if close is None:
        return False
    open_value = _number(point.get("open"))
    high = _number(point.get("high"))
    low = _number(point.get("low"))
    anchors = [value for value in (open_value, close) if value is not None]
    tolerance = max(1e-8, abs(close) * 1e-8)
    if high is not None and low is not None and high + tolerance < low:
        return False
    if high is not None and anchors and high + tolerance < max(anchors):
        return False
    if low is not None and anchors and low - tolerance > min(anchors):
        return False
    return True


def _is_incomplete_daily_bar(
    timestamp: str,
    timezone_name: str,
    *,
    now: datetime | None = None,
) -> bool:
    close_time = _DAILY_SESSION_CLOSE.get(timezone_name)
    if not timestamp or close_time is None:
        return False
    try:
        market_zone = ZoneInfo(timezone_name)
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        reference = now or datetime.now(timezone.utc)
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=timezone.utc)
        local_bar = parsed.astimezone(market_zone)
        local_now = reference.astimezone(market_zone)
    except (TypeError, ValueError, KeyError):
        return False
    if local_bar.date() != local_now.date():
        return False
    completed_after = local_now.replace(
        hour=close_time[0],
        minute=close_time[1],
        second=0,
        microsecond=0,
    ) + timedelta(minutes=15)
    return local_now < completed_after


class YahooMarketProvider:
    BASE_URL = "https://query1.finance.yahoo.com/v8/finance/chart"

    def __init__(
        self,
        database: Database,
        ttl_seconds: int = 300,
        http_get: Callable[..., Any] = requests.get,
    ):
        self.database = database
        self.ttl_seconds = ttl_seconds
        self.http_get = http_get

    def read_cached_history(
        self,
        symbol: str,
        range_name: str = "1y",
        interval: str = "1d",
        *,
        allow_stale: bool = True,
    ) -> dict[str, Any] | None:
        """Read a persisted snapshot without ever calling the upstream."""
        cache_key = f"yahoo:{symbol}:{range_name}:{interval}"
        cached = self.database.get_cache(cache_key, allow_stale=allow_stale)
        if cached is None or "regular_market_timestamp" not in cached:
            return None
        cached, removed = self._sanitize_history(
            cached, symbol=symbol, interval=interval
        )
        if removed:
            self.database.delete_market_bars(symbol, interval, removed)
        return cached

    def fetch_history(
        self,
        symbol: str,
        range_name: str = "1y",
        interval: str = "1d",
    ) -> dict[str, Any]:
        cache_key = f"yahoo:{symbol}:{range_name}:{interval}"
        cached = self.database.get_cache(cache_key)
        if cached is not None and "regular_market_timestamp" not in cached:
            # Older cache entries predate the quote-time field used to distinguish
            # an intraday snapshot from the latest complete daily bar.
            cached = None
        if cached is not None:
            cached, removed = self._sanitize_history(
                cached, symbol=symbol, interval=interval
            )
            if removed:
                self.database.delete_market_bars(symbol, interval, removed)
                self.database.put_cache(cache_key, cached, self.ttl_seconds)
            self._persist_history(cached, symbol=symbol, interval=interval)
            return cached

        try:
            response = self.http_get(
                f"{self.BASE_URL}/{quote(symbol, safe='')}",
                params={"range": range_name, "interval": interval, "events": "div,splits"},
                headers={"User-Agent": "QingshuFinanceAgentDemo/0.1"},
                timeout=15,
            )
            response.raise_for_status()
            payload = response.json()
            result = self._parse_chart(symbol, range_name, interval, payload)
            result, removed = self._sanitize_history(
                result, symbol=symbol, interval=interval
            )
            if removed:
                self.database.delete_market_bars(symbol, interval, removed)
            self.database.put_cache(cache_key, result, self.ttl_seconds)
            self._persist_history(result, symbol=symbol, interval=interval)
            return result
        except Exception as exc:
            stale = self.database.get_cache(cache_key, allow_stale=True)
            if stale is not None:
                stale, removed = self._sanitize_history(
                    stale, symbol=symbol, interval=interval
                )
                if removed:
                    self.database.delete_market_bars(symbol, interval, removed)
                stale.setdefault("warnings", []).append(f"Yahoo 请求失败：{type(exc).__name__}")
                self._persist_history(stale, symbol=symbol, interval=interval)
                return stale
            raise ProviderError(f"Yahoo 行情不可用：{type(exc).__name__}: {exc}") from exc

    def _persist_history(
        self, history: dict[str, Any], *, symbol: str, interval: str
    ) -> None:
        points = history.get("points") or []
        if not points:
            return
        self.database.upsert_market_bars(
            symbol,
            interval,
            points,
            str(history.get("source") or "market history"),
            str(history.get("fetched_at") or utc_now()),
        )

    @staticmethod
    def _sanitize_history(
        history: dict[str, Any],
        *,
        symbol: str,
        interval: str,
        now: datetime | None = None,
    ) -> tuple[dict[str, Any], list[str]]:
        payload = deepcopy(history)
        points = list(payload.get("points") or [])
        kept: list[dict[str, Any]] = []
        removed_timestamps: list[str] = []
        invalid_ohlc = 0
        incomplete_daily = 0
        timezone_name = str(payload.get("timezone") or "")
        for point in points:
            timestamp = str(point.get("timestamp") or "")
            if not _valid_ohlc(point):
                invalid_ohlc += 1
                if timestamp:
                    removed_timestamps.append(timestamp)
                continue
            if interval == "1d" and _is_incomplete_daily_bar(
                timestamp,
                timezone_name,
                now=now,
            ):
                incomplete_daily += 1
                if timestamp:
                    removed_timestamps.append(timestamp)
                continue
            kept.append(point)
        if not kept:
            raise ProviderError(f"Yahoo {symbol} 没有可用的完整行情记录")
        warnings = list(payload.get("warnings") or [])
        if invalid_ohlc:
            warnings.append(
                f"上游有 {invalid_ohlc} 根 OHLC 自相矛盾的记录，已跳过。"
            )
        if incomplete_daily:
            warnings.append(
                f"上游有 {incomplete_daily} 根当前交易日未完成日线，已保留上一完整交易日。"
            )
        payload["warnings"] = warnings
        payload["points"] = kept
        payload["market_timestamp"] = kept[-1]["timestamp"]
        coverage = dict(payload.get("coverage") or {})
        coverage.update(
            {
                "points": len(kept),
                "first_timestamp": kept[0]["timestamp"],
                "last_timestamp": kept[-1]["timestamp"],
                "dropped_invalid_ohlc": invalid_ohlc,
                "dropped_incomplete_daily": incomplete_daily,
            }
        )
        payload["coverage"] = coverage
        return payload, list(dict.fromkeys(removed_timestamps))

    @staticmethod
    def _parse_chart(
        symbol: str,
        range_name: str,
        interval: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        chart = payload.get("chart") or {}
        if chart.get("error"):
            raise ProviderError(f"Yahoo 返回错误：{chart['error']}")
        results = chart.get("result") or []
        if not results:
            raise ProviderError("Yahoo 未返回行情记录")

        root = results[0]
        meta = root.get("meta") or {}
        regular_market_time = _integer(meta.get("regularMarketTime"))
        timestamps = root.get("timestamp") or []
        quotes = ((root.get("indicators") or {}).get("quote") or [{}])[0]
        adjclose_rows = ((root.get("indicators") or {}).get("adjclose") or [{}])[0]
        adjcloses = adjclose_rows.get("adjclose") or []
        points: list[dict[str, Any]] = []
        dropped = 0

        for index, timestamp in enumerate(timestamps):
            close = _at(quotes.get("close"), index)
            if close is None or not _finite(close):
                dropped += 1
                continue
            point = {
                "timestamp": datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat(timespec="seconds"),
                "open": _number(_at(quotes.get("open"), index)),
                "high": _number(_at(quotes.get("high"), index)),
                "low": _number(_at(quotes.get("low"), index)),
                "close": _number(close),
                "adjusted_close": _number(_at(adjcloses, index)) if adjcloses else None,
                "volume": _integer(_at(quotes.get("volume"), index)),
            }
            points.append(point)

        if not points:
            raise ProviderError("Yahoo 行情全部为空")

        warnings = []
        if dropped:
            warnings.append(f"上游有 {dropped} 个无收盘价记录，已跳过。")
        return {
            "symbol": symbol,
            "display_name": meta.get("longName") or meta.get("shortName") or symbol,
            "currency": meta.get("currency"),
            "exchange": meta.get("exchangeName") or meta.get("fullExchangeName"),
            "timezone": meta.get("exchangeTimezoneName"),
            "previous_close": _number(
                meta.get("chartPreviousClose") or meta.get("previousClose")
            ),
            "regular_market_price": _number(meta.get("regularMarketPrice")),
            "regular_market_timestamp": (
                datetime.fromtimestamp(
                    regular_market_time, tz=timezone.utc
                ).isoformat(timespec="seconds")
                if regular_market_time is not None
                else None
            ),
            "data_granularity": meta.get("dataGranularity") or interval,
            "source": "Yahoo Finance Chart",
            "source_url": YahooMarketProvider.BASE_URL,
            "market_timestamp": points[-1]["timestamp"],
            "fetched_at": utc_now(),
            "is_stale": False,
            "cache_hit": False,
            "coverage": {
                "requested_range": range_name,
                "interval": interval,
                "points": len(points),
                "first_timestamp": points[0]["timestamp"],
                "last_timestamp": points[-1]["timestamp"],
            },
            "warnings": warnings,
            "points": points,
        }


class TencentChinaIndexProvider:
    """Daily history fallback for the main A-share indices."""

    URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    SYMBOLS = {
        "000001.SS": {"quote_symbol": "sh000001", "name": "上证综指", "exchange": "SSE"},
        "399001.SZ": {"quote_symbol": "sz399001", "name": "深证成指", "exchange": "SZSE"},
        "399006.SZ": {"quote_symbol": "sz399006", "name": "创业板指", "exchange": "SZSE"},
        "000300.SS": {"quote_symbol": "sh000300", "name": "沪深300", "exchange": "SSE"},
        "000905.SS": {"quote_symbol": "sh000905", "name": "中证500", "exchange": "SSE"},
    }
    RANGE_COUNTS = {
        "5d": 10,
        "1mo": 35,
        "3mo": 100,
        "6mo": 160,
        "1y": 300,
        "2y": 550,
        "5y": 1300,
        "10y": 2600,
        "max": 5000,
    }

    def __init__(
        self,
        database: Database,
        ttl_seconds: int = 300,
        http_get: Callable[..., Any] = requests.get,
    ):
        self.database = database
        self.ttl_seconds = ttl_seconds
        self.http_get = http_get

    def supports(self, symbol: str) -> bool:
        return symbol in self.SYMBOLS

    def fetch_history(
        self,
        symbol: str,
        range_name: str = "1y",
        interval: str = "1d",
    ) -> dict[str, Any]:
        config = self.SYMBOLS.get(symbol)
        if config is None:
            raise ProviderError("腾讯A股指数日线源不支持该标的")
        if interval != "1d":
            raise ProviderError("腾讯A股指数源当前只提供日线历史")
        count = self.RANGE_COUNTS.get(range_name, self.RANGE_COUNTS["1y"])
        cache_key = f"tencent:china-index:{symbol}:{range_name}:{interval}"
        cached = self.database.get_cache(cache_key)
        if cached is not None:
            self._persist_history(cached, symbol=symbol)
            return cached

        quote_symbol = str(config["quote_symbol"])
        try:
            response = self.http_get(
                self.URL,
                params={"param": f"{quote_symbol},day,,,{count},qfq"},
                headers={
                    "User-Agent": "Mozilla/5.0 QingshuFinanceAgentDemo/0.1",
                    "Referer": "https://gu.qq.com/",
                },
                timeout=15,
            )
            response.raise_for_status()
            result = self._parse(symbol, config, range_name, response.json())
            self.database.put_cache(cache_key, result, self.ttl_seconds)
            self._persist_history(result, symbol=symbol)
            return result
        except Exception as exc:
            stale = self.database.get_cache(cache_key, allow_stale=True)
            if stale is not None:
                stale.setdefault("warnings", []).append(
                    f"A股指数日线刷新失败：{type(exc).__name__}"
                )
                self._persist_history(stale, symbol=symbol)
                return stale
            if isinstance(exc, ProviderError):
                raise
            raise ProviderError(
                f"A股指数日线不可用：{type(exc).__name__}: {exc}"
            ) from exc

    def _persist_history(self, history: dict[str, Any], *, symbol: str) -> None:
        points = list(history.get("points") or [])
        if not points:
            return
        self.database.upsert_market_bars(
            symbol,
            "1d",
            points,
            str(history.get("source") or "A-share index daily history"),
            str(history.get("fetched_at") or utc_now()),
        )

    @staticmethod
    def _parse(
        symbol: str,
        config: dict[str, str],
        range_name: str,
        payload: dict[str, Any],
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if payload.get("code") not in {0, "0", None}:
            raise ProviderError("腾讯A股指数日线返回错误")
        quote_symbol = str(config["quote_symbol"])
        data = (payload.get("data") or {}).get(quote_symbol) or {}
        rows = data.get("qfqday") or data.get("day") or []
        shanghai = ZoneInfo("Asia/Shanghai")
        points = []
        dropped_invalid = 0
        dropped_incomplete = 0
        for row in rows:
            if not isinstance(row, list) or len(row) < 5:
                dropped_invalid += 1
                continue
            try:
                local_date = datetime.strptime(str(row[0]), "%Y-%m-%d").replace(
                    hour=9,
                    minute=30,
                    tzinfo=shanghai,
                )
            except ValueError:
                dropped_invalid += 1
                continue
            point = {
                "timestamp": local_date.astimezone(timezone.utc).isoformat(
                    timespec="seconds"
                ),
                "open": _number(row[1]),
                "close": _number(row[2]),
                "adjusted_close": _number(row[2]),
                "high": _number(row[3]),
                "low": _number(row[4]),
                "volume": _integer(row[5]) if len(row) > 5 else None,
            }
            if not _valid_ohlc(point):
                dropped_invalid += 1
                continue
            if _is_incomplete_daily_bar(
                point["timestamp"],
                "Asia/Shanghai",
                now=now,
            ):
                dropped_incomplete += 1
                continue
            points.append(point)
        if not points:
            raise ProviderError(f"腾讯A股指数日线未返回 {symbol} 的完整记录")
        warnings = []
        if dropped_invalid:
            warnings.append(f"上游有 {dropped_invalid} 根无效日线，已跳过。")
        if dropped_incomplete:
            warnings.append(
                f"上游有 {dropped_incomplete} 根当前交易日未完成日线，已保留上一完整交易日。"
            )
        return {
            "symbol": symbol,
            "display_name": config["name"],
            "currency": "CNY",
            "exchange": config["exchange"],
            "timezone": "Asia/Shanghai",
            "previous_close": points[-2]["close"] if len(points) > 1 else None,
            "regular_market_price": points[-1]["close"],
            "data_granularity": "1d",
            "source": "Tencent A-share index daily bars",
            "source_url": TencentChinaIndexProvider.URL,
            "market_timestamp": points[-1]["timestamp"],
            "fetched_at": utc_now(),
            "is_stale": False,
            "cache_hit": False,
            "coverage": {
                "requested_range": range_name,
                "interval": "1d",
                "points": len(points),
                "first_timestamp": points[0]["timestamp"],
                "last_timestamp": points[-1]["timestamp"],
                "dropped_invalid_ohlc": dropped_invalid,
                "dropped_incomplete_daily": dropped_incomplete,
            },
            "warnings": warnings,
            "points": points,
        }


class EastmoneySectorProvider:
    URL = "https://push2.eastmoney.com/api/qt/clist/get"
    HISTORY_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    CACHE_KEY = "eastmoney:sectors:100"
    UPSTREAM_LIMIT = 100

    def __init__(
        self,
        database: Database,
        ttl_seconds: int = 60,
        http_get: Callable[..., Any] = requests.get,
    ):
        self.database = database
        self.ttl_seconds = ttl_seconds
        self.http_get = http_get
        self._refresh_lock = threading.Lock()

    def fetch_sector_history(
        self,
        code: str,
        days: int = 5,
        *,
        allow_remote: bool = True,
    ) -> dict[str, Any]:
        normalized = str(code or "").strip().upper()
        if not re.fullmatch(r"BK\d{4}", normalized):
            raise ProviderError("东方财富板块代码格式无效")
        days = max(3, min(int(days), 20))
        cache_key = f"eastmoney:sector-history:{normalized}:{days}"
        cached = self.database.get_cache(cache_key)
        if cached is not None:
            result = deepcopy(cached)
            result["cache_hit"] = True
            return result
        if not allow_remote:
            return {
                "code": normalized,
                "status": "unavailable",
                "source": "Eastmoney sector daily history",
                "cache_hit": False,
                "points": [],
                "warnings": ["板块历史缓存尚未建立。"],
            }
        params = {
            "secid": f"90.{normalized}",
            "klt": 101,
            "fqt": 1,
            "lmt": days,
            "end": "20500101",
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        }
        try:
            response = self.http_get(
                self.HISTORY_URL,
                params=params,
                headers={
                    "User-Agent": "Mozilla/5.0 QingshuFinanceAgent/1.0",
                    "Referer": "https://quote.eastmoney.com/",
                },
                timeout=6,
            )
            response.raise_for_status()
            rows = ((response.json().get("data") or {}).get("klines") or [])
            points = []
            for row in rows:
                fields = str(row).split(",")
                if (
                    len(fields) < 3
                    or not re.fullmatch(r"20\d{2}-\d{2}-\d{2}", fields[0])
                ):
                    continue
                close = _number(fields[2])
                if close is None:
                    continue
                points.append(
                    {
                        "market_date": fields[0],
                        "close": float(close),
                    }
                )
            points = sorted(points, key=lambda item: item["market_date"])[-days:]
            if len(points) < 3:
                raise ProviderError("东方财富板块历史少于三个有效交易日")
            result = {
                "code": normalized,
                "status": "available",
                "source": "Eastmoney sector daily history",
                "source_url": self.HISTORY_URL,
                "fetched_at": utc_now(),
                "cache_hit": False,
                "points": points,
                "warnings": [],
            }
            self.database.put_cache(cache_key, result, ttl_seconds=21_600)
            return result
        except Exception as exc:
            stale = self.database.get_cache(cache_key, allow_stale=True)
            if stale is not None:
                result = deepcopy(stale)
                result["cache_hit"] = True
                result.setdefault("warnings", []).append(
                    f"板块历史刷新失败，沿用缓存：{type(exc).__name__}"
                )
                return result
            if isinstance(exc, ProviderError):
                raise
            raise ProviderError(
                f"东方财富板块历史不可用：{type(exc).__name__}: {exc}"
            ) from exc

    def fetch_hot_sectors(self, limit: int = 20) -> dict[str, Any]:
        limit = max(1, min(limit, 100))
        cached = self.database.get_cache(self.CACHE_KEY)
        if cached is not None:
            return self._slice(cached, limit)

        with self._refresh_lock:
            cached = self.database.get_cache(self.CACHE_KEY)
            if cached is not None:
                return self._slice(cached, limit)
            params = {
                "pn": 1,
                "pz": self.UPSTREAM_LIMIT,
                "po": 1,
                "np": 1,
                "ut": "bd1d9ddb04089700cf9c27f6f7426281",
                "fltt": 2,
                "invt": 2,
                "fid": "f3",
                "fs": "m:90+t:2+f:!50",
                "fields": "f12,f14,f2,f3,f6,f62,f104,f105,f106,f124",
            }
            try:
                response = self.http_get(
                    self.URL,
                    params=params,
                    headers={
                        "User-Agent": "Mozilla/5.0 QingshuFinanceAgentDemo/0.1",
                        "Referer": "https://quote.eastmoney.com/center/boardlist.html",
                    },
                    timeout=15,
                )
                response.raise_for_status()
                result = self._parse(response.json(), self.UPSTREAM_LIMIT)
                self.database.put_cache(self.CACHE_KEY, result, self.ttl_seconds)
                return self._slice(result, limit)
            except Exception as exc:
                stale = self.database.get_cache(
                    self.CACHE_KEY, allow_stale=True
                )
                if stale is not None:
                    stale.setdefault("warnings", []).append(
                        f"东方财富请求失败：{type(exc).__name__}"
                    )
                    return self._slice(stale, limit)
                raise ProviderError(
                    f"东方财富板块数据不可用：{type(exc).__name__}: {exc}"
                ) from exc

    @staticmethod
    def _slice(packet: dict[str, Any], limit: int) -> dict[str, Any]:
        result = deepcopy(packet)
        result["sectors"] = list(result.get("sectors") or [])[:limit]
        coverage = dict(result.get("coverage") or {})
        coverage["returned"] = len(result["sectors"])
        result["coverage"] = coverage
        return result

    @staticmethod
    def _parse(payload: dict[str, Any], limit: int) -> dict[str, Any]:
        data = payload.get("data") or {}
        raw_rows = data.get("diff") or []
        if isinstance(raw_rows, dict):
            raw_rows = list(raw_rows.values())
        sectors = []
        market_timestamps = []
        for row in raw_rows[:limit]:
            update_epoch = row.get("f124")
            if isinstance(update_epoch, (int, float)) and update_epoch > 0:
                market_timestamps.append(int(update_epoch))
            sectors.append(
                {
                    "code": row.get("f12"),
                    "name": row.get("f14"),
                    "latest": _number(row.get("f2")),
                    "pct_change": _number(row.get("f3")),
                    "turnover": _number(row.get("f6")),
                    "main_net_inflow": _number(row.get("f62")),
                    "advancers": _integer(row.get("f104")),
                    "decliners": _integer(row.get("f105")),
                    "unchanged": _integer(row.get("f106")),
                }
            )
        if not sectors:
            raise ProviderError("东方财富未返回板块记录")
        market_timestamp = None
        if market_timestamps:
            market_timestamp = datetime.fromtimestamp(
                max(market_timestamps), tz=timezone.utc
            ).isoformat(timespec="seconds")
        return {
            "source": "Eastmoney A-share sector ranking",
            "source_url": EastmoneySectorProvider.URL,
            "market_timestamp": market_timestamp,
            "fetched_at": utc_now(),
            "is_stale": False,
            "cache_hit": False,
            "coverage": {
                "returned": len(sectors),
                "total_available": data.get("total"),
                "ranking_field": "pct_change",
            },
            "warnings": [],
            "sectors": sectors,
        }


class CSIIndustryIndexProvider:
    SEARCH_URL = "https://searchapi.eastmoney.com/api/suggest/get"
    SEARCH_TOKEN = "D43BF722C8E33BDC906FB84D85E326E8"
    BASIC_INFO_URL = (
        "https://www.csindex.com.cn/csindex-home/indexInfo/index-basic-info"
    )
    DETAILS_URL = (
        "https://www.csindex.com.cn/csindex-home/indexInfo/index-details-data"
    )
    HISTORY_URL = "https://www.csindex.com.cn/csindex-home/perf/index-perf"
    COMPONENT_HISTORY_URL = (
        "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    )
    SINA_COMPONENT_HISTORY_URL = (
        "https://quotes.sina.cn/cn/api/json_v2.php/"
        "CN_MarketData.getKLineData"
    )
    INDUSTRY_INDEX_ALIASES = {
        "电池": {
            "search_term": "931719",
            "index_code": "931719",
            "index_name": "CS电池",
            "note": (
                "东方财富行业“电池”映射到中证电池主题指数；两套分类体系并非完全同口径。"
            ),
        },
        "白酒Ⅱ": {
            "search_term": "399997",
            "index_code": "399997",
            "index_name": "中证白酒",
            "note": (
                "东方财富二级行业“白酒Ⅱ”映射到中证白酒指数；以官方样本核验覆盖范围。"
            ),
        },
        "银行Ⅱ": {
            "search_term": "399986",
            "index_code": "399986",
            "index_name": "中证银行",
            "note": (
                "东方财富二级行业“银行Ⅱ”映射到中证银行指数；两套分类体系并非完全同口径。"
            ),
        },
    }

    def __init__(
        self,
        database: Database,
        ttl_seconds: int = 3600,
        http_get: Callable[..., Any] = requests.get,
    ):
        self.database = database
        self.ttl_seconds = ttl_seconds
        self.http_get = http_get

    def fetch(
        self, industry_name: str, market_date: str | None = None
    ) -> dict[str, Any]:
        industry_name = str(industry_name or "").strip()
        if not industry_name:
            raise ProviderError("公司行业名称为空")
        cache_key = f"csi:industry-index:{industry_name}"
        cached = self.database.get_cache(cache_key)
        if cached is not None:
            cached = self._ensure_mapping_metadata(cached, industry_name)
            self._persist_history(cached)
            return self._attach_component_analysis(cached, market_date)

        headers = {
            "User-Agent": "Mozilla/5.0 QingshuFinanceAgentDemo/0.1",
            "Referer": "https://www.csindex.com.cn/",
        }
        mapping = self._mapping_plan(industry_name)
        try:
            search_response = self.http_get(
                self.SEARCH_URL,
                params={
                    "input": mapping["search_term"],
                    "type": 14,
                    "count": 50,
                    "token": self.SEARCH_TOKEN,
                },
                headers=headers,
                timeout=15,
            )
            search_response.raise_for_status()
            candidate = self._select_index_candidate(
                industry_name,
                search_response.json(),
                expected_code=mapping.get("index_code"),
            )
            index_code = candidate["Code"]

            basic_response = self.http_get(
                f"{self.BASIC_INFO_URL}/{index_code}",
                headers=headers,
                timeout=15,
            )
            basic_response.raise_for_status()
            basic_payload = basic_response.json()
            basic_info = basic_payload.get("data") or {}
            if str(basic_payload.get("code")) != "200" or not basic_info:
                raise ProviderError("中证指数基础信息不可用")

            details_response = self.http_get(
                self.DETAILS_URL,
                params={"fileLang": 2, "indexCode": index_code},
                headers=headers,
                timeout=15,
            )
            details_response.raise_for_status()
            detail_data = (details_response.json().get("data") or {})
            constituent_url = self._material_url(detail_data, "样本列表")
            weight_url = self._material_url(detail_data, "样本权重")
            if not constituent_url or not weight_url:
                raise ProviderError("中证指数样本或权重文件缺失")

            constituent_response = self.http_get(
                constituent_url, headers=headers, timeout=20
            )
            constituent_response.raise_for_status()
            weight_response = self.http_get(
                weight_url, headers=headers, timeout=20
            )
            weight_response.raise_for_status()
            constituents = self._parse_constituents(
                constituent_response.content,
                weight_response.content,
            )

            local_today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
            history_response = self.http_get(
                self.HISTORY_URL,
                params={
                    "indexCode": index_code,
                    "startDate": (local_today - timedelta(days=370)).strftime(
                        "%Y%m%d"
                    ),
                    "endDate": local_today.strftime("%Y%m%d"),
                },
                headers=headers,
                timeout=15,
            )
            history_response.raise_for_status()
            points = self._parse_history(history_response.json())
            fetched_at = utc_now()
            items = constituents["items"]
            result = {
                "type": "industry_index",
                "status": "available",
                "industry_name": industry_name,
                "index_code": index_code,
                "quote_id": candidate["QuoteID"],
                "index_name": (
                    basic_info.get("indexShortNameCn") or candidate["Name"]
                ),
                "index_full_name": basic_info.get("indexFullNameCn"),
                "index_description": basic_info.get("indexCnDesc"),
                "currency": basic_info.get("currencyCn") or "人民币",
                "publish_date": basic_info.get("publishDate"),
                "adjustment_frequency": basic_info.get("adjFreqCn"),
                "industry_mapping": {
                    "input_name": industry_name,
                    "match_type": mapping["match_type"],
                    "search_term": mapping["search_term"],
                    "official_index_name": (
                        basic_info.get("indexShortNameCn") or candidate["Name"]
                    ),
                    "note": mapping.get("note"),
                },
                "source": "CSI official constituents and public index history",
                "source_url": f"{self.BASIC_INFO_URL}/{index_code}",
                "constituent_source_url": constituent_url,
                "weight_source_url": weight_url,
                "history_source_url": self.HISTORY_URL,
                "market_timestamp": points[-1]["timestamp"],
                "fetched_at": fetched_at,
                "is_stale": False,
                "cache_hit": False,
                "coverage": {
                    "history_points": len(points),
                    "first_market_date": points[0]["market_date"],
                    "last_market_date": points[-1]["market_date"],
                    "constituents": len(items),
                    "weights_available": sum(
                        item.get("weight_pct") is not None for item in items
                    ),
                },
                "constituents_as_of": constituents["constituents_as_of"],
                "weights_as_of": constituents["weights_as_of"],
                "constituents": items,
                "points": points,
                "warnings": [
                    "行业指数用于描述该行业样本整体价格表现；指数涨跌不等于成分股涨跌家数。",
                    "样本名单和权重按中证指数官网文件日期保存，调整频率以官方说明为准。",
                ],
            }
            if mapping["match_type"] == "verified_alias":
                result["warnings"].append(str(mapping.get("note") or ""))
            self.database.put_cache(cache_key, result, self.ttl_seconds)
            self._persist_history(result)
            return self._attach_component_analysis(result, market_date)
        except Exception as exc:
            stale = self.database.get_cache(cache_key, allow_stale=True)
            if stale is not None:
                stale = self._ensure_mapping_metadata(stale, industry_name)
                stale.setdefault("warnings", []).append(
                    f"精确行业指数刷新失败：{type(exc).__name__}"
                )
                self._persist_history(stale)
                return self._attach_component_analysis(stale, market_date)
            if isinstance(exc, ProviderError):
                raise
            raise ProviderError(
                f"精确行业指数不可用：{type(exc).__name__}: {exc}"
            ) from exc

    @classmethod
    def _mapping_plan(cls, industry_name: str) -> dict[str, Any]:
        alias = cls.INDUSTRY_INDEX_ALIASES.get(industry_name)
        if alias is None:
            return {
                "match_type": "exact_name",
                "search_term": industry_name,
                "index_code": None,
                "note": None,
            }
        return {"match_type": "verified_alias", **alias}

    @classmethod
    def _ensure_mapping_metadata(
        cls, payload: dict[str, Any], industry_name: str
    ) -> dict[str, Any]:
        if payload.get("industry_mapping"):
            return payload
        mapping = cls._mapping_plan(industry_name)
        result = dict(payload)
        result["industry_mapping"] = {
            "input_name": industry_name,
            "match_type": mapping["match_type"],
            "search_term": mapping["search_term"],
            "official_index_name": payload.get("index_name"),
            "note": mapping.get("note"),
        }
        return result

    def _attach_component_analysis(
        self, payload: dict[str, Any], market_date: str | None
    ) -> dict[str, Any]:
        market_date = str(market_date or "").strip()
        if not market_date:
            return payload
        result = dict(payload)
        result["warnings"] = list(payload.get("warnings") or [])
        if not re.fullmatch(r"20\d{2}-\d{2}-\d{2}", market_date):
            result["component_analysis"] = {
                "status": "unavailable",
                "market_date": market_date or None,
                "boundary": "目标交易日格式无法识别，未抓取成分日线。",
            }
            return result

        cache_key = ":".join(
            [
                "csi",
                "industry-components",
                str(payload.get("index_code") or "unknown"),
                market_date,
                str(payload.get("constituents_as_of") or "unknown"),
                str(payload.get("weights_as_of") or "unknown"),
            ]
        )
        cached = self.database.get_cache(cache_key)
        if cached is not None:
            result["component_analysis"] = cached
            return result
        try:
            component_analysis = self._fetch_component_analysis(
                payload, market_date
            )
            local_today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
            target_date = datetime.strptime(market_date, "%Y-%m-%d").date()
            component_status = component_analysis.get("status")
            component_ttl = max(60, min(self.ttl_seconds, 600))
            if component_status == "available" and target_date < local_today:
                component_ttl = max(self.ttl_seconds, 86400)
            elif component_status == "partial" and target_date < local_today:
                component_ttl = max(self.ttl_seconds, 3600)
            self.database.put_cache(
                cache_key, component_analysis, component_ttl
            )
            result["component_analysis"] = component_analysis
        except Exception as exc:
            stale = self.database.get_cache(cache_key, allow_stale=True)
            if stale is not None:
                result["component_analysis"] = stale
                result["warnings"].append(
                    f"行业成分目标日行情刷新失败，沿用历史缓存：{type(exc).__name__}"
                )
            else:
                result["component_analysis"] = {
                    "status": "unavailable",
                    "market_date": market_date,
                    "boundary": (
                        "已取得官方样本名单，但目标交易日成分行情抓取失败，"
                        "不能确认行业涨跌家数或成分贡献。"
                    ),
                }
                result["warnings"].append(
                    f"行业成分目标日行情不可用：{type(exc).__name__}"
                )
        return result

    def _fetch_component_analysis(
        self, payload: dict[str, Any], market_date: str
    ) -> dict[str, Any]:
        constituents = list(payload.get("constituents") or [])
        if not constituents:
            raise ProviderError("官方行业样本为空，无法计算成分广度")
        target = datetime.strptime(market_date, "%Y-%m-%d").date()
        start_date = (target - timedelta(days=45)).isoformat()
        headers = {
            "User-Agent": "Mozilla/5.0 QingshuFinanceAgentDemo/0.1",
            "Referer": "https://gu.qq.com/",
        }

        def parsed_return(
            item: dict[str, Any],
            parsed: list[dict[str, Any]],
            *,
            source: str,
            source_url: str,
            adjustment: str,
        ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
            if not parsed:
                return None, {
                    "reason_code": "no_history",
                    "reason": "当前行情源未返回目标日前的日线历史",
                    "possible_causes": [
                        "该行情源暂不支持此证券",
                        "目标日前尚未上市",
                        "长期停牌或无成交记录",
                    ],
                    "source": source,
                }
            target_index = next(
                (
                    index
                    for index, row in enumerate(parsed)
                    if row["market_date"] == market_date
                ),
                None,
            )
            if target_index is None:
                return None, {
                    "reason_code": "target_bar_missing",
                    "reason": (
                        f"目标日 {market_date} 无可用日线；当前返回范围 "
                        f"{parsed[0]['market_date']} 至 {parsed[-1]['market_date']}"
                    ),
                    "possible_causes": [
                        "目标日停牌或无成交",
                        "目标日前尚未上市",
                        "行情源历史不完整",
                    ],
                    "source": source,
                }
            if target_index == 0:
                return None, {
                    "reason_code": "previous_bar_missing",
                    "reason": "目标日有行情，但缺少此前可比收盘价",
                    "possible_causes": [
                        "新上市证券历史较短",
                        "长期停牌后恢复交易",
                        "行情源返回窗口不足",
                    ],
                    "source": source,
                }
            current = parsed[target_index]
            previous = parsed[target_index - 1]
            if not previous["close"]:
                return None, {
                    "reason_code": "previous_close_invalid",
                    "reason": "上一交易日收盘价无效",
                    "possible_causes": ["行情源字段缺失或格式变化"],
                    "source": source,
                }
            pct_change = round(
                (float(current["close"]) / float(previous["close"]) - 1)
                * 100,
                4,
            )
            weight_pct = item.get("weight_pct")
            contribution = (
                round(float(weight_pct) * pct_change / 100, 4)
                if isinstance(weight_pct, (int, float))
                else None
            )
            return {
                "symbol": item.get("symbol"),
                "name": item.get("name"),
                "weight_pct": weight_pct,
                "market_date": market_date,
                "previous_market_date": previous["market_date"],
                "previous_close": previous["close"],
                "close": current["close"],
                "pct_change": pct_change,
                "estimated_contribution_pp": contribution,
                "source": source,
                "source_url": source_url,
                "adjustment": adjustment,
            }, None

        def fetch_component(item: dict[str, Any]) -> dict[str, Any]:
            quote_symbol = str(item.get("sina_symbol") or "").strip()
            if not quote_symbol:
                return {
                    "failure": {
                        "symbol": item.get("symbol"),
                        "name": item.get("name"),
                        "reason_code": "missing_quote_symbol",
                        "reason": "官方样本代码无法映射到公开行情代码",
                        "possible_causes": ["交易所或证券代码映射规则待补"],
                        "source_attempts": [],
                    }
                }

            attempts: list[dict[str, Any]] = []
            try:
                response = self.http_get(
                    self.COMPONENT_HISTORY_URL,
                    params={
                        "param": (
                            f"{quote_symbol},day,{start_date},{market_date},45,qfq"
                        )
                    },
                    headers=headers,
                    timeout=12,
                )
                response.raise_for_status()
                data = (response.json().get("data") or {}).get(quote_symbol) or {}
                raw_rows = data.get("qfqday") or data.get("day") or []
                tencent_rows = []
                for row in raw_rows:
                    if not isinstance(row, list) or len(row) < 3:
                        continue
                    close = _number(row[2])
                    if close is None:
                        continue
                    tencent_rows.append(
                        {
                            "market_date": str(row[0]),
                            "open": _number(row[1]),
                            "close": close,
                            "high": _number(row[3]) if len(row) > 3 else None,
                            "low": _number(row[4]) if len(row) > 4 else None,
                            "volume": _integer(row[5]) if len(row) > 5 else None,
                        }
                    )
                primary, diagnostic = parsed_return(
                    item,
                    tencent_rows,
                    source="Tencent adjusted daily bars",
                    source_url=self.COMPONENT_HISTORY_URL,
                    adjustment="qfq",
                )
                if primary is not None:
                    return {"row": primary}
                if diagnostic:
                    attempts.append(diagnostic)
            except Exception as exc:
                attempts.append(
                    {
                        "reason_code": "source_error",
                        "reason": f"腾讯复权日线请求失败：{type(exc).__name__}",
                        "possible_causes": ["网络、限流或上游格式变化"],
                        "source": "Tencent adjusted daily bars",
                    }
                )

            try:
                response = self.http_get(
                    self.SINA_COMPONENT_HISTORY_URL,
                    params={
                        "symbol": quote_symbol,
                        "scale": 240,
                        "ma": "no",
                        "datalen": 260,
                    },
                    headers={
                        "User-Agent": headers["User-Agent"],
                        "Referer": "https://finance.sina.com.cn/",
                    },
                    timeout=12,
                )
                response.raise_for_status()
                raw_rows = response.json() or []
                sina_rows = []
                for row in raw_rows if isinstance(raw_rows, list) else []:
                    if not isinstance(row, dict):
                        continue
                    close = _number(row.get("close"))
                    market_day = str(row.get("day") or "")[:10]
                    if close is None or not re.fullmatch(
                        r"20\d{2}-\d{2}-\d{2}", market_day
                    ):
                        continue
                    sina_rows.append(
                        {
                            "market_date": market_day,
                            "open": _number(row.get("open")),
                            "close": close,
                            "high": _number(row.get("high")),
                            "low": _number(row.get("low")),
                            "volume": _integer(row.get("volume")),
                        }
                    )
                fallback, diagnostic = parsed_return(
                    item,
                    sina_rows,
                    source="Sina unadjusted daily bars fallback",
                    source_url=self.SINA_COMPONENT_HISTORY_URL,
                    adjustment="unadjusted",
                )
                if fallback is not None:
                    fallback["fallback_reason"] = (
                        attempts[-1].get("reason") if attempts else None
                    )
                    return {"row": fallback}
                if diagnostic:
                    attempts.append(diagnostic)
            except Exception as exc:
                attempts.append(
                    {
                        "reason_code": "source_error",
                        "reason": f"新浪日线降级请求失败：{type(exc).__name__}",
                        "possible_causes": ["网络、限流或上游格式变化"],
                        "source": "Sina unadjusted daily bars fallback",
                    }
                )

            last_attempt = attempts[-1] if attempts else {}
            possible_causes = list(
                dict.fromkeys(
                    cause
                    for attempt in attempts
                    for cause in (attempt.get("possible_causes") or [])
                )
            )
            return {
                "failure": {
                    "symbol": item.get("symbol"),
                    "name": item.get("name"),
                    "reason_code": last_attempt.get("reason_code")
                    or "all_sources_failed",
                    "reason": last_attempt.get("reason")
                    or "两个公开行情源均未返回可比日线",
                    "possible_causes": possible_causes,
                    "source_attempts": attempts,
                }
            }

        rows = []
        failures = []
        with ThreadPoolExecutor(max_workers=min(8, len(constituents))) as executor:
            futures = {
                executor.submit(fetch_component, item): item
                for item in constituents
            }
            for future in as_completed(futures):
                item = futures[future]
                try:
                    outcome = future.result()
                    if outcome.get("row"):
                        rows.append(outcome["row"])
                    elif outcome.get("failure"):
                        failures.append(outcome["failure"])
                except Exception as exc:
                    failures.append(
                        {
                            "symbol": item.get("symbol"),
                            "name": item.get("name"),
                            "reason_code": "unexpected_error",
                            "reason": f"成分行情处理异常：{type(exc).__name__}",
                            "possible_causes": ["代码或上游返回格式需复核"],
                            "source_attempts": [],
                        }
                    )
        rows.sort(key=lambda item: str(item.get("symbol") or ""))
        total = len(constituents)
        available = len(rows)
        coverage_ratio = round(available / total, 4) if total else 0.0
        returns = [float(item["pct_change"]) for item in rows]
        advancers = sum(value > 0 for value in returns)
        decliners = sum(value < 0 for value in returns)
        unchanged = sum(value == 0 for value in returns)
        advance_ratio = round(advancers / available, 4) if available else 0.0
        decline_ratio = round(decliners / available, 4) if available else 0.0
        minimum_net = max(3, round(available * 0.1)) if available else 0
        if advance_ratio >= 0.65 and advancers - decliners >= minimum_net:
            breadth_state = "普涨"
        elif decline_ratio >= 0.65 and decliners - advancers >= minimum_net:
            breadth_state = "普跌"
        elif advancers > decliners:
            breadth_state = "上涨家数占优"
        elif decliners > advancers:
            breadth_state = "下跌家数占优"
        else:
            breadth_state = "涨跌家数接近"
        analysis_status = (
            "available"
            if available == total and total > 0
            else "partial"
            if available
            else "unavailable"
        )
        primary_adjusted_returns = sum(
            item.get("adjustment") == "qfq" for item in rows
        )
        fallback_unadjusted_returns = sum(
            item.get("adjustment") == "unadjusted" for item in rows
        )
        contribution_rows = [
            item
            for item in rows
            if isinstance(item.get("estimated_contribution_pp"), (int, float))
        ]
        estimated_total = round(
            sum(float(item["estimated_contribution_pp"]) for item in contribution_rows),
            4,
        )
        index_point = next(
            (
                point
                for point in (payload.get("points") or [])
                if point.get("market_date") == market_date
            ),
            None,
        )
        index_return = (index_point or {}).get("pct_change")
        reconciliation_gap = (
            round(float(index_return) - estimated_total, 4)
            if isinstance(index_return, (int, float))
            and contribution_rows
            else None
        )
        positive = sorted(
            (
                item
                for item in contribution_rows
                if float(item["estimated_contribution_pp"]) > 0
            ),
            key=lambda item: float(item["estimated_contribution_pp"]),
            reverse=True,
        )[:5]
        negative = sorted(
            (
                item
                for item in contribution_rows
                if float(item["estimated_contribution_pp"]) < 0
            ),
            key=lambda item: float(item["estimated_contribution_pp"]),
        )[:5]
        return {
            "status": analysis_status,
            "market_date": market_date,
            "source": "Tencent adjusted daily bars with CSI official constituents and weights",
            "source_url": self.COMPONENT_HISTORY_URL,
            "fetched_at": utc_now(),
            "coverage": {
                "constituents": total,
                "available_returns": available,
                "missing_returns": total - available,
                "coverage_ratio": coverage_ratio,
                "weights_available": len(contribution_rows),
                "primary_adjusted_returns": primary_adjusted_returns,
                "fallback_unadjusted_returns": fallback_unadjusted_returns,
            },
            "breadth": {
                "status": analysis_status,
                "market_date": market_date,
                "total_constituents": total,
                "available_returns": available,
                "advancers": advancers,
                "decliners": decliners,
                "unchanged": unchanged,
                "advance_ratio": advance_ratio,
                "decline_ratio": decline_ratio,
                "median_pct_change": (
                    round(median(returns), 4) if returns else None
                ),
                "state": breadth_state if available else "不可用",
                "classification_method": (
                    "普涨或普跌要求对应方向占有效样本至少65%，且涨跌净差至少为"
                    "有效样本的10%（最少3只）；覆盖不完整时只作为部分样本描述。"
                ),
            },
            "contribution": {
                "status": analysis_status,
                "market_date": market_date,
                "weights_as_of": payload.get("weights_as_of"),
                "estimated_total_contribution_pp": (
                    estimated_total if contribution_rows else None
                ),
                "official_index_return_pct": index_return,
                "reconciliation_gap_pp": reconciliation_gap,
                "top_positive": positive,
                "top_negative": negative,
                "boundary": (
                    "贡献度按官方权重文件与目标日复权涨跌幅静态相乘估算，"
                    "不是中证官方逐日归因；权重漂移、公司行动和样本调整会形成对账差。"
                    + (
                        f"其中 {fallback_unadjusted_returns} 只成分使用新浪未复权日线降级；"
                        "若目标日前后存在除权除息，其单日收益与贡献可能偏离复权口径。"
                        if fallback_unadjusted_returns
                        else ""
                    )
                ),
            },
            "components": rows,
            "failures": failures[:20],
            "boundary": (
                "成分广度使用当前取得的官方样本名单回看目标日；若目标日前后发生样本调整，"
                "仍需历史样本档案复核。覆盖不完整时不得声称完整行业普涨或普跌。"
                + (
                    f"其中 {fallback_unadjusted_returns} 只成分使用未复权日线降级，"
                    "系统保留来源与口径标记。"
                    if fallback_unadjusted_returns
                    else ""
                )
            ),
        }

    def _persist_history(self, payload: dict[str, Any]) -> None:
        index_code = str(payload.get("index_code") or "").strip()
        points = payload.get("points") or []
        if not index_code or not points:
            return
        self.database.upsert_market_bars(
            f"CSI{index_code}",
            "1d",
            points,
            payload.get("source") or "CSI industry index",
            payload.get("fetched_at") or utc_now(),
        )

    @staticmethod
    def _select_index_candidate(
        industry_name: str,
        payload: dict[str, Any],
        expected_code: str | None = None,
    ) -> dict[str, Any]:
        rows = ((payload.get("QuotationCodeTable") or {}).get("Data") or [])
        exact = [
            row
            for row in rows
            if (
                str(row.get("Code") or "").strip() == expected_code
                if expected_code
                else str(row.get("Name") or "").strip() == industry_name
            )
            and row.get("SecurityTypeName") == "指数"
            and re.fullmatch(r"\d{6}", str(row.get("Code") or ""))
            and str(row.get("QuoteID") or "").strip()
        ]
        if not exact:
            raise ProviderError(
                f"没有找到与“{industry_name}”精确匹配的官方行业指数"
            )
        return exact[0]

    @staticmethod
    def _material_url(payload: dict[str, Any], key: str) -> str | None:
        rows = payload.get(key) or []
        if not rows:
            return None
        return str(rows[0].get("filePath") or "").strip() or None

    @staticmethod
    def _parse_constituents(
        constituent_content: bytes, weight_content: bytes
    ) -> dict[str, Any]:
        if pd is None:
            raise ProviderError("当前运行环境缺少行业样本表解析依赖")
        try:
            constituents = pd.read_excel(
                BytesIO(constituent_content), engine="xlrd"
            )
            weights = pd.read_excel(BytesIO(weight_content), engine="xlrd")
        except Exception as exc:
            raise ProviderError(
                f"行业样本表无法解析：{type(exc).__name__}"
            ) from exc

        def column(frame: Any, prefix: str) -> str:
            match = next(
                (name for name in frame.columns if str(name).startswith(prefix)),
                None,
            )
            if match is None:
                raise ProviderError(f"行业样本表缺少字段：{prefix}")
            return str(match)

        cons_code = column(constituents, "成份券代码")
        cons_name = column(constituents, "成份券名称")
        cons_exchange = column(constituents, "交易所")
        cons_date = column(constituents, "日期")
        weight_code = column(weights, "成份券代码")
        weight_value = column(weights, "权重")
        weight_date = column(weights, "日期")

        def security_code(value: Any) -> str:
            try:
                return str(int(float(value))).zfill(6)
            except (TypeError, ValueError) as exc:
                raise ProviderError("行业样本证券代码无法解析") from exc

        weight_map = {
            security_code(row[weight_code]): _number(row[weight_value])
            for _, row in weights.iterrows()
        }
        items = []
        for _, row in constituents.iterrows():
            code = security_code(row[cons_code])
            exchange = str(row[cons_exchange] or "").strip()
            suffix = (
                ".SS"
                if "上海" in exchange
                else ".SZ"
                if "深圳" in exchange
                else ".BJ"
                if "北京" in exchange
                else ""
            )
            sina_prefix = (
                "sh"
                if suffix == ".SS"
                else "sz"
                if suffix == ".SZ"
                else "bj"
                if suffix == ".BJ"
                else ""
            )
            items.append(
                {
                    "symbol": f"{code}{suffix}" if suffix else code,
                    "sina_symbol": (
                        f"{sina_prefix}{code}" if sina_prefix else None
                    ),
                    "name": str(row[cons_name] or "").strip(),
                    "exchange": exchange,
                    "weight_pct": weight_map.get(code),
                }
            )
        if not items:
            raise ProviderError("官方行业指数样本为空")

        def file_date(frame: Any, name: str) -> str | None:
            values = [
                str(value).split(".", 1)[0]
                for value in frame[name].dropna()
            ]
            digits = re.sub(r"\D", "", values[0]) if values else ""
            return (
                f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
                if len(digits) >= 8
                else None
            )

        return {
            "constituents_as_of": file_date(constituents, cons_date),
            "weights_as_of": file_date(weights, weight_date),
            "items": items,
        }

    @staticmethod
    def _parse_history(payload: dict[str, Any]) -> list[dict[str, Any]]:
        rows = payload.get("data") or []
        points = []
        for row in rows:
            raw_date = re.sub(r"\D", "", str(row.get("tradeDate") or ""))
            if len(raw_date) < 8:
                continue
            market_date = (
                f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
            )
            close = _number(row.get("close"))
            if close is None:
                continue
            points.append(
                {
                    "market_date": market_date,
                    "timestamp": f"{market_date}T15:00:00+08:00",
                    "open": _number(row.get("open")),
                    "close": close,
                    "adjusted_close": close,
                    "high": _number(row.get("high")),
                    "low": _number(row.get("low")),
                    "volume": _integer(row.get("tradingVol")),
                    "amount_100m_cny": _number(row.get("tradingValue")),
                    "pct_change": _number(row.get("changePct")),
                    "price_change": _number(row.get("change")),
                    "constituent_count": _integer(row.get("consNumber")),
                }
            )
        if not points:
            raise ProviderError("精确行业指数没有返回历史日线")
        return points


class SinaIndustrySectorProvider:
    URL = "https://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php"

    def __init__(
        self,
        database: Database,
        ttl_seconds: int = 60,
        http_get: Callable[..., Any] = requests.get,
    ):
        self.database = database
        self.ttl_seconds = ttl_seconds
        self.http_get = http_get

    def fetch_hot_sectors(self, limit: int = 20) -> dict[str, Any]:
        limit = max(1, min(limit, 100))
        cache_key = f"sina:industry-sectors:{limit}"
        cached = self.database.get_cache(cache_key)
        if cached is not None:
            return cached
        try:
            response = self.http_get(
                self.URL,
                headers={
                    "User-Agent": "Mozilla/5.0 QingshuFinanceAgentDemo/0.1",
                    "Referer": "https://finance.sina.com.cn/",
                },
                timeout=15,
            )
            response.raise_for_status()
            content = response.content.decode("gb18030", errors="replace")
            result = self._parse(content, limit)
            self.database.put_cache(cache_key, result, self.ttl_seconds)
            return result
        except Exception as exc:
            stale = self.database.get_cache(cache_key, allow_stale=True)
            if stale is not None:
                stale.setdefault("warnings", []).append(f"新浪行业请求失败：{type(exc).__name__}")
                return stale
            raise ProviderError(f"新浪行业板块数据不可用：{type(exc).__name__}: {exc}") from exc

    @staticmethod
    def _parse(content: str, limit: int) -> dict[str, Any]:
        match = re.search(r"=\s*(\{.*\})\s*;?\s*$", content, flags=re.DOTALL)
        if not match:
            raise ProviderError("新浪行业数据格式无法识别")
        raw = json.loads(match.group(1))
        sectors = []
        for value in raw.values():
            fields = value.split(",")
            if len(fields) < 13:
                continue
            sectors.append(
                {
                    "code": fields[0],
                    "name": fields[1],
                    "member_count": _integer(fields[2]),
                    "average_price": _number(fields[3]),
                    "price_change": _number(fields[4]),
                    "pct_change": _number(fields[5]),
                    "volume": _integer(fields[6]),
                    "turnover": _number(fields[7]),
                    "leading_symbol": fields[8],
                    "leading_name": fields[12],
                    "latest": None,
                    "main_net_inflow": None,
                    "advancers": None,
                    "decliners": None,
                    "unchanged": None,
                }
            )
        sectors = [item for item in sectors if item["pct_change"] is not None]
        sectors.sort(key=lambda item: item["pct_change"], reverse=True)
        sectors = sectors[:limit]
        if not sectors:
            raise ProviderError("新浪未返回可排序的行业板块记录")
        return {
            "source": "Sina Finance A-share industry ranking",
            "source_url": SinaIndustrySectorProvider.URL,
            "market_timestamp": None,
            "fetched_at": utc_now(),
            "is_stale": False,
            "cache_hit": False,
            "coverage": {
                "returned": len(sectors),
                "total_available": len(raw),
                "ranking_field": "pct_change",
            },
            "warnings": [
                "降级源不提供明确市场时间，仅记录抓取时间。",
                "降级源不提供主力资金和上涨/下跌家数字段。",
            ],
            "sectors": sectors,
        }


class ResilientSectorProvider:
    def __init__(
        self,
        primary: EastmoneySectorProvider,
        fallback: SinaIndustrySectorProvider,
    ):
        self.primary = primary
        self.fallback = fallback

    def fetch_hot_sectors(self, limit: int = 20) -> dict[str, Any]:
        try:
            return self.primary.fetch_hot_sectors(limit=limit)
        except ProviderError as primary_error:
            result = self.fallback.fetch_hot_sectors(limit=limit)
            result.setdefault("warnings", []).insert(
                0,
                f"东方财富主源不可用，已降级到新浪行业板块：{type(primary_error.__cause__).__name__ if primary_error.__cause__ else 'ProviderError'}",
            )
            result["degraded_from"] = "Eastmoney A-share sector ranking"
            return result

    def fetch_sector_history(
        self,
        code: str,
        days: int = 5,
        *,
        allow_remote: bool = True,
    ) -> dict[str, Any]:
        return self.primary.fetch_sector_history(
            code,
            days=days,
            allow_remote=allow_remote,
        )


class SinaMarketBreadthProvider:
    COUNT_URL = (
        "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        "Market_Center.getHQNodeStockCount"
    )
    DATA_URL = (
        "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        "Market_Center.getHQNodeData"
    )
    NODE = "hs_a"
    PAGE_SIZE = 100
    CACHE_KEY = "sina:a-share-market-breadth:hs_a"
    LAST_USABLE_CACHE_KEY = "sina:a-share-market-breadth:last-usable"
    LAST_USABLE_TTL_SECONDS = 7 * 24 * 60 * 60

    def __init__(
        self,
        database: Database,
        ttl_seconds: int = 300,
        http_get: Callable[..., Any] = requests.get,
        max_workers: int = 8,
    ):
        self.database = database
        self.ttl_seconds = ttl_seconds
        self.http_get = http_get
        self.max_workers = max(1, min(int(max_workers), 12))

    def fetch_breadth(self) -> dict[str, Any]:
        cache_key = self.CACHE_KEY
        cached = self.database.get_cache(cache_key)
        if cached is not None:
            resolved = self._resolve_zero_placeholder(
                self._with_derived_ratios(self._with_inferred_market_date(cached))
            )
            # Do not renew the cache on a read. Background refresh runs much
            # more frequently than the TTL; sliding the expiry here would keep
            # an old all-market snapshot alive indefinitely and prevent a real
            # upstream refresh.
            if resolved != cached:
                self.database.update_cache_payload_preserving_expiry(
                    cache_key, resolved
                )
            if resolved.get("status") == "available":
                return self._attach_history_comparison(resolved)
            return resolved

        headers = {
            "User-Agent": "Mozilla/5.0 QingshuFinanceAgentDemo/0.1",
            "Referer": "https://finance.sina.com.cn/",
        }
        try:
            count_response = self.http_get(
                self.COUNT_URL,
                params={"node": self.NODE},
                headers=headers,
                timeout=10,
            )
            count_response.raise_for_status()
            total_expected = self._parse_count(count_response.json())
            page_count = math.ceil(total_expected / self.PAGE_SIZE)

            def fetch_page(page: int) -> tuple[int, list[dict[str, Any]]]:
                response = self.http_get(
                    self.DATA_URL,
                    params={
                        "page": page,
                        "num": self.PAGE_SIZE,
                        "sort": "symbol",
                        "asc": 1,
                        "node": self.NODE,
                        "symbol": "",
                        "_s_r_a": "page",
                    },
                    headers=headers,
                    timeout=15,
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, list):
                    raise ProviderError(f"新浪A股第{page}页格式无法识别")
                return page, payload

            pages: dict[int, list[dict[str, Any]]] = {}
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {
                    executor.submit(fetch_page, page): page
                    for page in range(1, page_count + 1)
                }
                for future in as_completed(futures):
                    page, rows = future.result()
                    pages[page] = rows
            all_rows = [
                row
                for page in range(1, page_count + 1)
                for row in pages.get(page, [])
            ]
            result = self._parse(all_rows, total_expected=total_expected)
            result = self._resolve_zero_placeholder(result)
            if result.get("status") == "available":
                result = self._attach_history_comparison(result)
            self.database.put_cache(cache_key, result, self.ttl_seconds)
            return result
        except Exception as exc:
            stale = self.database.get_cache(cache_key, allow_stale=True)
            if stale is not None:
                stale.setdefault("warnings", []).append(
                    f"新浪A股广度请求失败：{type(exc).__name__}"
                )
                resolved = self._resolve_zero_placeholder(
                    self._with_derived_ratios(self._with_inferred_market_date(stale))
                )
                if resolved.get("status") == "available":
                    return self._attach_history_comparison(resolved)
                return resolved
            raise ProviderError(
                f"新浪A股全市场广度不可用：{type(exc).__name__}: {exc}"
            ) from exc

    def _resolve_zero_placeholder(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._is_usable_completed_snapshot(payload):
            self.database.put_cache(
                self.LAST_USABLE_CACHE_KEY,
                payload,
                self.LAST_USABLE_TTL_SECONDS,
            )
            return payload
        if not self._is_zero_placeholder(payload):
            return payload

        fallback = self.database.get_cache(
            self.LAST_USABLE_CACHE_KEY, allow_stale=True
        )
        if not self._is_usable_completed_snapshot(fallback):
            fallback = next(
                (
                    item
                    for item in self.database.list_market_breadth_snapshots(limit=21)
                    if self._is_usable_completed_snapshot(item)
                ),
                None,
            )
        if fallback is not None:
            resolved = deepcopy(fallback)
            resolved["cache_hit"] = True
            resolved["served_as_previous_close"] = True
            resolved["snapshot_mode"] = "previous_completed_session"
            resolved.setdefault("warnings", []).append(
                "盘前或上游占位快照全部为零，已保留上一完整交易日的全市场广度、成交额与涨跌分布。"
            )
            return resolved

        unavailable = deepcopy(payload)
        unavailable["status"] = "unavailable"
        unavailable["snapshot_mode"] = "zero_placeholder_rejected"
        unavailable["breadth"] = {}
        unavailable["turnover"] = {"status": "unavailable"}
        unavailable["distribution"] = {"status": "unavailable"}
        unavailable["exchange_breakdown"] = {}
        unavailable.setdefault("warnings", []).append(
            "盘前或上游占位快照全部为零，且尚无上一完整交易日快照；当前拒绝确认全市场广度。"
        )
        return unavailable

    @staticmethod
    def _is_zero_placeholder(payload: dict[str, Any] | None) -> bool:
        if not isinstance(payload, dict):
            return False
        breadth = payload.get("breadth") or {}
        turnover = payload.get("turnover") or {}
        total = breadth.get("total")
        return (
            isinstance(total, int)
            and total > 0
            and breadth.get("advancers") == 0
            and breadth.get("decliners") == 0
            and breadth.get("unchanged") == total
            and turnover.get("total_amount_cny") == 0
        )

    @classmethod
    def _is_usable_completed_snapshot(
        cls, payload: dict[str, Any] | None
    ) -> bool:
        if not isinstance(payload, dict) or payload.get("status") != "available":
            return False
        breadth = payload.get("breadth") or {}
        turnover = payload.get("turnover") or {}
        total = breadth.get("total")
        directional = (breadth.get("advancers") or 0) + (
            breadth.get("decliners") or 0
        )
        return (
            isinstance(total, int)
            and total > 0
            and directional > 0
            and isinstance(turnover.get("total_amount_cny"), (int, float))
            and turnover.get("total_amount_cny") > 0
        )

    @staticmethod
    def _parse_count(payload: Any) -> int:
        try:
            count = int(str(payload).strip().strip('"'))
        except (TypeError, ValueError) as exc:
            raise ProviderError("新浪A股总数格式无法识别") from exc
        if count <= 0:
            raise ProviderError("新浪A股总数为空")
        return count

    @staticmethod
    def _with_derived_ratios(payload: dict[str, Any]) -> dict[str, Any]:
        breadth = payload.get("breadth") or {}
        total = breadth.get("total")
        unchanged = breadth.get("unchanged")
        if (
            isinstance(total, int)
            and total > 0
            and isinstance(unchanged, int)
            and breadth.get("unchanged_ratio") is None
        ):
            breadth["unchanged_ratio"] = round(unchanged / total, 4)
        return payload

    @classmethod
    def _with_inferred_market_date(
        cls, payload: dict[str, Any]
    ) -> dict[str, Any]:
        fetched_at = str(payload.get("fetched_at") or "")
        latest_tick_time = str(
            (payload.get("coverage") or {}).get("latest_tick_time") or ""
        )
        inferred = cls._infer_market_date(fetched_at, latest_tick_time)
        if inferred:
            payload["market_date"] = inferred
        return payload

    @staticmethod
    def _infer_market_date(
        fetched_at: str, latest_tick_time: str | None
    ) -> str | None:
        try:
            fetched = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=timezone.utc)
        local_now = fetched.astimezone(ZoneInfo("Asia/Shanghai"))

        tick_seconds: int | None = None
        try:
            tick = datetime.strptime(str(latest_tick_time), "%H:%M:%S")
            tick_seconds = tick.hour * 3600 + tick.minute * 60 + tick.second
        except (TypeError, ValueError):
            pass
        local_seconds = (
            local_now.hour * 3600 + local_now.minute * 60 + local_now.second
        )
        tick_looks_like_prior_close = (
            tick_seconds is not None and tick_seconds > local_seconds + 1800
        )

        if exchange_calendars is not None and pd is not None:
            try:
                calendar = exchange_calendars.get_calendar("XSHG")
                local_day = pd.Timestamp(local_now.date())
                if calendar.is_session(local_day):
                    session = local_day
                    session_open = calendar.session_open(local_day)
                    before_open = pd.Timestamp(fetched) < session_open
                    if before_open or tick_looks_like_prior_close:
                        session = calendar.previous_session(local_day)
                else:
                    session = calendar.date_to_session(
                        local_day, direction="previous"
                    )
                return session.date().isoformat()
            except (ValueError, TypeError, KeyError):
                pass

        inferred = local_now.date()
        if tick_looks_like_prior_close or local_now.hour < 9:
            inferred -= timedelta(days=1)
            while inferred.weekday() >= 5:
                inferred -= timedelta(days=1)
        return inferred.isoformat()

    def _attach_history_comparison(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:
        turnover = payload.get("turnover") or {}
        if (
            turnover.get("status") != "available"
            or not payload.get("market_date")
            or self._is_zero_placeholder(payload)
        ):
            return payload
        self.database.upsert_market_breadth_snapshot(payload)
        history = self.database.list_market_breadth_snapshots(limit=21)
        market_date = str(payload.get("market_date") or "")
        prior = [
            item
            for item in history
            if str(item.get("market_date") or "") < market_date
            and ((item.get("turnover") or {}).get("status") == "available")
        ]
        current_total = turnover.get("total_amount_cny")
        comparison: dict[str, Any] = {
            "status": "building_history",
            "previous_market_date": None,
            "previous_total_amount_cny": None,
            "change_vs_previous_pct": None,
            "previous_5d_average_amount_cny": None,
            "change_vs_previous_5d_average_pct": None,
            "previous_20d_average_amount_cny": None,
            "change_vs_previous_20d_average_pct": None,
            "available_prior_sessions": len(prior),
            "method": (
                "只比较本系统按同一沪深京全市场快照口径保存的历史交易日；"
                "历史不足时不判断放量或缩量。"
            ),
        }
        if isinstance(current_total, (int, float)) and prior:
            previous = prior[0]
            previous_total = (previous.get("turnover") or {}).get(
                "total_amount_cny"
            )
            comparison.update(
                {
                    "status": "available",
                    "previous_market_date": previous.get("market_date"),
                    "previous_total_amount_cny": previous_total,
                    "change_vs_previous_pct": self._relative_change_pct(
                        current_total, previous_total
                    ),
                }
            )
            for sessions, prefix in ((5, "previous_5d"), (20, "previous_20d")):
                totals = [
                    (item.get("turnover") or {}).get("total_amount_cny")
                    for item in prior[:sessions]
                ]
                totals = [
                    float(value)
                    for value in totals
                    if isinstance(value, (int, float)) and value > 0
                ]
                if len(totals) == sessions:
                    average = sum(totals) / sessions
                    comparison[f"{prefix}_average_amount_cny"] = round(
                        average, 2
                    )
                    comparison[
                        f"change_vs_{prefix}_average_pct"
                    ] = self._relative_change_pct(current_total, average)
        turnover["history_comparison"] = comparison
        self.database.upsert_market_breadth_snapshot(payload)
        return payload

    @staticmethod
    def _relative_change_pct(current: Any, previous: Any) -> float | None:
        if not isinstance(current, (int, float)) or not isinstance(
            previous, (int, float)
        ):
            return None
        if previous == 0:
            return None
        return round((float(current) / float(previous) - 1) * 100, 4)

    @staticmethod
    def _parse(
        rows: list[dict[str, Any]], *, total_expected: int
    ) -> dict[str, Any]:
        unique_rows = {
            str(row.get("symbol") or "").strip(): row
            for row in rows
            if str(row.get("symbol") or "").strip()
        }
        if len(unique_rows) != total_expected:
            raise ProviderError(
                f"新浪A股广度覆盖不完整：{len(unique_rows)}/{total_expected}"
            )

        counts = {"advancers": 0, "decliners": 0, "unchanged": 0}
        exchanges: dict[str, dict[str, int]] = {
            "shanghai": {"total": 0, **counts, "valid_amount": 0, "amount_cny": 0},
            "shenzhen": {"total": 0, **counts, "valid_amount": 0, "amount_cny": 0},
            "beijing": {"total": 0, **counts, "valid_amount": 0, "amount_cny": 0},
        }
        latest_tick_time = None
        valid = 0
        valid_amount = 0
        total_amount = 0.0
        changes: list[float] = []
        for symbol, row in unique_rows.items():
            change = _number(row.get("changepercent"))
            if change is None:
                continue
            valid += 1
            changes.append(float(change))
            direction = (
                "advancers" if change > 0 else "decliners" if change < 0 else "unchanged"
            )
            counts[direction] += 1
            exchange = (
                "shanghai"
                if symbol.startswith("sh")
                else "shenzhen"
                if symbol.startswith("sz")
                else "beijing"
                if symbol.startswith("bj")
                else None
            )
            if exchange:
                exchanges[exchange]["total"] += 1
                exchanges[exchange][direction] += 1
            amount = _number(row.get("amount"))
            if amount is not None and amount >= 0:
                valid_amount += 1
                total_amount += float(amount)
                if exchange:
                    exchanges[exchange]["valid_amount"] += 1
                    exchanges[exchange]["amount_cny"] += int(round(amount))
            tick_time = str(row.get("ticktime") or "").strip()
            if tick_time and (latest_tick_time is None or tick_time > latest_tick_time):
                latest_tick_time = tick_time

        if valid != total_expected:
            raise ProviderError(
                f"新浪A股涨跌字段覆盖不完整：{valid}/{total_expected}"
            )
        advance_ratio = counts["advancers"] / valid
        decline_ratio = counts["decliners"] / valid
        unchanged_ratio = counts["unchanged"] / valid
        quartile_values = quantiles(changes, n=4, method="inclusive")
        distribution_bins = {
            "strong_advancers_ge_3": sum(value >= 3 for value in changes),
            "mild_advancers_gt_0_lt_3": sum(0 < value < 3 for value in changes),
            "unchanged": counts["unchanged"],
            "mild_decliners_lt_0_gt_neg3": sum(-3 < value < 0 for value in changes),
            "strong_decliners_le_neg3": sum(value <= -3 for value in changes),
        }
        distribution_bin_ratios = {
            key: round(value / valid, 4)
            for key, value in distribution_bins.items()
        }
        net_advancers = counts["advancers"] - counts["decliners"]
        if advance_ratio >= 0.65 and net_advancers >= 500:
            breadth_state = "普涨"
        elif decline_ratio >= 0.65 and net_advancers <= -500:
            breadth_state = "普跌"
        elif net_advancers > 0:
            breadth_state = "上涨家数占优"
        elif net_advancers < 0:
            breadth_state = "下跌家数占优"
        else:
            breadth_state = "涨跌均衡"
        fetched_at = utc_now()
        market_date = SinaMarketBreadthProvider._infer_market_date(
            fetched_at, latest_tick_time
        )
        exchange_amount_total = sum(
            item["amount_cny"] for item in exchanges.values()
        )
        turnover_complete = (
            valid_amount == total_expected
            and abs(total_amount - exchange_amount_total) <= 1
        )
        return {
            "source": "Sina Finance all A-share snapshot",
            "source_url": SinaMarketBreadthProvider.DATA_URL,
            "market_timestamp": None,
            "fetched_at": fetched_at,
            "market_date": market_date,
            "is_stale": False,
            "cache_hit": False,
            "status": "available",
            "scope": "all_a_shares_including_beijing",
            "coverage": {
                "expected": total_expected,
                "returned": len(unique_rows),
                "valid_change": valid,
                "coverage_ratio": round(valid / total_expected, 4),
                "node": SinaMarketBreadthProvider.NODE,
                "latest_tick_time": latest_tick_time,
            },
            "breadth": {
                "total": valid,
                **counts,
                "net_advancers": net_advancers,
                "advance_ratio": round(advance_ratio, 4),
                "decline_ratio": round(decline_ratio, 4),
                "unchanged_ratio": round(unchanged_ratio, 4),
                "state": breadth_state,
                "classification_method": (
                    "普涨/普跌要求上涨或下跌比例至少65%，且涨跌家数净差至少500；"
                    "否则只描述哪一方向家数占优。"
                ),
            },
            "turnover": {
                "status": "available" if turnover_complete else "incomplete",
                "currency": "CNY",
                "unit": "yuan",
                "total_amount_cny": int(round(total_amount)),
                "total_amount_100m_cny": round(total_amount / 100_000_000, 2),
                "coverage": {
                    "expected": total_expected,
                    "valid_amount": valid_amount,
                    "coverage_ratio": round(valid_amount / total_expected, 4),
                    "exchange_sum_matches": abs(total_amount - exchange_amount_total)
                    <= 1,
                },
                "exchanges": {
                    key: {
                        "amount_cny": item["amount_cny"],
                        "amount_100m_cny": round(
                            item["amount_cny"] / 100_000_000, 2
                        ),
                        "valid_amount": item["valid_amount"],
                    }
                    for key, item in exchanges.items()
                },
                "interpretation": (
                    "成交额是当日累计成交金额，不是资金净流入、机构意图或未来方向信号。"
                ),
            },
            "distribution": {
                "status": "available",
                "coverage": {
                    "expected": total_expected,
                    "valid_change": valid,
                    "coverage_ratio": round(valid / total_expected, 4),
                },
                "median_pct_change": round(float(median(changes)), 4),
                "p25_pct_change": round(float(quartile_values[0]), 4),
                "p75_pct_change": round(float(quartile_values[2]), 4),
                "bins": distribution_bins,
                "bin_ratios": distribution_bin_ratios,
                "method": (
                    "使用全体有效个股涨跌幅的中位数与四分位数；"
                    "固定±3%分档只用于描述当日分布，不是预测或交易阈值。"
                ),
            },
            "exchange_breakdown": exchanges,
            "warnings": [
                "该快照按新浪沪深京A股列表逐页汇总，包含北交所；"
                "停牌或涨跌幅字段缺失时会拒绝确认全市场广度。"
            ],
        }


class EastmoneyGlobalIndexProvider:
    """Current-minute index bars for markets delayed by Yahoo's free feed."""

    URL = "https://push2delay.eastmoney.com/api/qt/stock/trends2/get"
    SYMBOLS = {
        "000001.SS": {
            "secid": "1.000001",
            "name": "上证综指",
            "currency": "CNY",
            "exchange": "SSE",
            "timezone": "Asia/Shanghai",
        },
        "399001.SZ": {
            "secid": "0.399001",
            "name": "深证成指",
            "currency": "CNY",
            "exchange": "SZSE",
            "timezone": "Asia/Shanghai",
        },
        "399006.SZ": {
            "secid": "0.399006",
            "name": "创业板指",
            "currency": "CNY",
            "exchange": "SZSE",
            "timezone": "Asia/Shanghai",
        },
        "000688.SS": {
            "secid": "1.000688",
            "name": "科创50",
            "currency": "CNY",
            "exchange": "SSE",
            "timezone": "Asia/Shanghai",
        },
        "^N225": {
            "secid": "100.N225",
            "name": "日经225",
            "currency": "JPY",
            "exchange": "JPX",
            "timezone": "Asia/Tokyo",
        },
        "^KS11": {
            "secid": "100.KS11",
            "name": "韩国KOSPI",
            "currency": "KRW",
            "exchange": "KRX",
            "timezone": "Asia/Seoul",
        },
    }

    def __init__(
        self,
        database: Database,
        ttl_seconds: int = 20,
        http_get: Callable[..., Any] = requests.get,
    ):
        self.database = database
        self.ttl_seconds = ttl_seconds
        self.http_get = http_get

    def fetch_intraday(self, symbol: str) -> dict[str, Any]:
        config = self.SYMBOLS.get(symbol)
        if config is None:
            raise ProviderError("东方财富全球指数分钟源不支持该标的")
        cache_key = f"eastmoney:global-index:{symbol}:1m"
        cached = self.database.get_cache(cache_key)
        if cached is not None:
            return cached
        params = {
            "secid": config["secid"],
            "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
            "iscr": "0",
            "ndays": "1",
        }
        try:
            response = self.http_get(
                self.URL,
                params=params,
                headers={
                    "User-Agent": "Mozilla/5.0 QingshuFinanceAgentDemo/0.1",
                    "Referer": "https://quote.eastmoney.com/center/gridlist.html",
                },
                timeout=15,
            )
            response.raise_for_status()
            result = self._parse(symbol, config, response.json())
            self.database.put_cache(cache_key, result, self.ttl_seconds)
            return result
        except Exception as exc:
            stale = self.database.get_cache(cache_key, allow_stale=True)
            if stale is not None:
                stale.setdefault("warnings", []).append(
                    f"全球指数分钟请求失败：{type(exc).__name__}"
                )
                return stale
            raise ProviderError(
                f"全球指数分钟数据不可用：{type(exc).__name__}: {exc}"
            ) from exc

    @staticmethod
    def _parse(
        symbol: str, config: dict[str, str], payload: dict[str, Any]
    ) -> dict[str, Any]:
        data = payload.get("data") or {}
        rows = data.get("trends") or []
        if not rows:
            raise ProviderError("全球指数分钟源未返回记录")
        shanghai = ZoneInfo("Asia/Shanghai")
        points_by_timestamp: dict[str, dict[str, Any]] = {}
        for raw in rows:
            fields = str(raw).split(",")
            if len(fields) < 5:
                continue
            try:
                local_time = datetime.strptime(fields[0], "%Y-%m-%d %H:%M").replace(
                    tzinfo=shanghai
                )
            except ValueError:
                continue
            values = [_number(value) for value in fields[1:5]]
            if any(value is None for value in values):
                continue
            timestamp = local_time.astimezone(timezone.utc).isoformat(
                timespec="seconds"
            )
            points_by_timestamp[timestamp] = {
                "timestamp": timestamp,
                "open": values[0],
                "close": values[1],
                "high": values[2],
                "low": values[3],
                "adjusted_close": None,
                "volume": _integer(fields[5]) if len(fields) > 5 else None,
                "amount": _number(fields[6]) if len(fields) > 6 else None,
            }
        points = [points_by_timestamp[key] for key in sorted(points_by_timestamp)]
        if not points:
            raise ProviderError("全球指数分钟记录无法解析")
        return {
            "symbol": symbol,
            "display_name": data.get("name") or config["name"],
            "currency": config["currency"],
            "exchange": config["exchange"],
            "timezone": config["timezone"],
            "previous_close": _number(data.get("preClose")),
            "regular_market_price": points[-1]["close"],
            "data_granularity": "1m",
            "source": "Eastmoney global index minute",
            "source_url": EastmoneyGlobalIndexProvider.URL,
            "market_timestamp": points[-1]["timestamp"],
            "fetched_at": utc_now(),
            "is_stale": False,
            "cache_hit": False,
            "coverage": {
                "requested_range": "1d",
                "interval": "1m",
                "points": len(points),
                "first_timestamp": points[0]["timestamp"],
                "last_timestamp": points[-1]["timestamp"],
            },
            "warnings": [],
            "points": points,
        }


class SinaGoldProvider:
    MINUTE_URL = (
        "https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20qingshu_xau=/"
        "GlobalFuturesService.getGlobalFuturesMinLine"
    )

    def __init__(
        self,
        database: Database,
        ttl_seconds: int = 20,
        http_get: Callable[..., Any] = requests.get,
    ):
        self.database = database
        self.ttl_seconds = ttl_seconds
        self.http_get = http_get

    def fetch_intraday(self) -> dict[str, Any]:
        cache_key = "sina:xau:intraday:5m"
        cached = self.database.get_cache(cache_key)
        if cached is not None:
            return cached
        try:
            response = self.http_get(
                self.MINUTE_URL,
                params={"symbol": "XAU"},
                headers={
                    "User-Agent": "Mozilla/5.0 QingshuFinanceAgentDemo/0.1",
                    "Referer": "https://finance.sina.com.cn/",
                },
                timeout=15,
            )
            response.raise_for_status()
            content = response.content.decode("gb18030", errors="replace")
            result = self._parse(content)
            self.database.put_cache(cache_key, result, self.ttl_seconds)
            return result
        except Exception as exc:
            stale = self.database.get_cache(cache_key, allow_stale=True)
            if stale is not None:
                stale.setdefault("warnings", []).append(f"新浪伦敦金请求失败：{type(exc).__name__}")
                return stale
            raise ProviderError(f"新浪伦敦金分钟数据不可用：{type(exc).__name__}: {exc}") from exc

    @staticmethod
    def _parse(content: str) -> dict[str, Any]:
        match = re.search(r"var\s+qingshu_xau=\((\{.*\})\)\s*;?", content, flags=re.DOTALL)
        if not match:
            raise ProviderError("新浪伦敦金分钟数据格式无法识别")
        payload = json.loads(match.group(1))
        rows = payload.get("minLine_1d") or []
        if not rows:
            raise ProviderError("新浪伦敦金未返回分钟记录")

        previous_close = None
        if rows and rows[0] and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(rows[0][0])):
            previous_close = _number(rows[0][1])

        raw_points = []
        shanghai = ZoneInfo("Asia/Shanghai")
        for row in rows:
            if len(row) < 6:
                continue
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(row[0])):
                continue
            timestamp_text = str(row[-1])
            try:
                timestamp = datetime.strptime(timestamp_text, "%Y-%m-%d %H:%M:%S").replace(
                    tzinfo=shanghai
                )
            except ValueError:
                continue
            price = _number(row[1])
            if price is None:
                continue
            raw_points.append((timestamp, price))
        if not raw_points:
            raise ProviderError("新浪伦敦金分钟记录无法解析")

        latest_date = max(timestamp.date() for timestamp, _ in raw_points)
        current_day = [(timestamp, price) for timestamp, price in raw_points if timestamp.date() == latest_date]
        buckets: dict[datetime, list[float]] = {}
        for timestamp, price in current_day:
            minute = timestamp.minute - timestamp.minute % 5
            bucket = timestamp.replace(minute=minute, second=0, microsecond=0)
            buckets.setdefault(bucket, []).append(price)
        points = [
            {
                "timestamp": bucket.astimezone(timezone.utc).isoformat(timespec="seconds"),
                "open": prices[0],
                "high": max(prices),
                "low": min(prices),
                "close": prices[-1],
                "adjusted_close": None,
                "volume": None,
            }
            for bucket, prices in sorted(buckets.items())
        ]
        fetched_at = utc_now()
        return {
            "symbol": "XAU",
            "display_name": "伦敦金（现货黄金）",
            "currency": "USD",
            "exchange": "LIFFE reference",
            "timezone": "Europe/London",
            "previous_close": previous_close,
            "regular_market_price": points[-1]["close"],
            "data_granularity": "5m",
            "source": "Sina Global Futures XAU",
            "source_url": SinaGoldProvider.MINUTE_URL,
            "market_timestamp": points[-1]["timestamp"],
            "fetched_at": fetched_at,
            "is_stale": False,
            "cache_hit": False,
            "coverage": {
                "requested_range": "1d",
                "interval": "5m",
                "points": len(points),
                "first_timestamp": points[0]["timestamp"],
                "last_timestamp": points[-1]["timestamp"],
            },
            "warnings": ["分钟线由新浪 XAU 一分钟价格聚合为五分钟 OHLC。"],
            "points": points,
        }


def _at(values: Any, index: int) -> Any:
    if not isinstance(values, list) or index >= len(values):
        return None
    return values[index]


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _number(value: Any) -> float | None:
    return round(float(value), 6) if _finite(value) else None


def _integer(value: Any) -> int | None:
    return int(float(value)) if _finite(value) else None
