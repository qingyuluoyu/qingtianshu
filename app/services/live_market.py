from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

try:
    import exchange_calendars as exchange_calendars
    import pandas as pd
except ImportError:  # pragma: no cover - production dependency, kept as safe fallback
    exchange_calendars = None
    pd = None

from app.catalog import LIVE_MARKET_CATALOG
from app.db import Database
from app.providers.market import (
    EastmoneyGlobalIndexProvider,
    ProviderError,
    SinaGoldProvider,
    YahooMarketProvider,
)
from app.utils import utc_now


_CALENDAR_CACHE: dict[str, Any] = {}


def _exchange_calendar(name: str) -> Any:
    if exchange_calendars is None:
        raise RuntimeError("exchange_calendars dependency is unavailable")
    if name not in _CALENDAR_CACHE:
        _CALENDAR_CACHE[name] = exchange_calendars.get_calendar(name)
    return _CALENDAR_CACHE[name]


class LiveMarketService:
    def __init__(
        self,
        database: Database,
        yahoo_provider: YahooMarketProvider,
        gold_provider: SinaGoldProvider,
        global_index_provider: EastmoneyGlobalIndexProvider | None = None,
    ):
        self.database = database
        self.yahoo_provider = yahoo_provider
        self.gold_provider = gold_provider
        self.global_index_provider = global_index_provider

    def snapshot(self) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        with ThreadPoolExecutor(max_workers=len(LIVE_MARKET_CATALOG)) as executor:
            futures = {
                executor.submit(self._fetch_one, item, now): item
                for item in LIVE_MARKET_CATALOG
            }
            markets = []
            for future in as_completed(futures):
                item = futures[future]
                try:
                    markets.append(future.result())
                except Exception as exc:
                    markets.append(self._unavailable(item, now, exc))

        order = {item["key"]: index for index, item in enumerate(LIVE_MARKET_CATALOG)}
        markets.sort(key=lambda item: (not item.get("is_open", False), order[item["key"]]))
        calendar_keys = {
            item["key"] for item in LIVE_MARKET_CATALOG if item.get("calendar")
        }
        stock_calendars_verified = all(
            item.get("calendar_status") == "verified"
            for item in markets
            if item.get("key") in calendar_keys
        )
        return {
            "generated_at": utc_now(),
            "refresh_after_seconds": 30,
            "session_method": (
                "股票市场按交易所日历判断，包含节假日、午间休市和提前收盘；"
                "伦敦金、美元指数、布伦特原油、美债收益率等OTC品种按工作日近24小时规则判断"
                if stock_calendars_verified
                else "交易所日历暂未完整覆盖，部分市场已安全降级到常规时段；"
                "伦敦金、美元指数、布伦特原油、美债收益率等OTC品种按工作日近24小时规则判断"
            ),
            "coverage": {
                "requested": len(markets),
                "available": sum(item["status"] == "available" for item in markets),
                "open": sum(bool(item.get("is_open")) for item in markets),
            },
            "markets": markets,
        }

    def _fetch_one(self, item: dict[str, Any], now: datetime) -> dict[str, Any]:
        if item.get("provider") == "sina_global_futures":
            history = self.gold_provider.fetch_intraday(item.get("symbol", "XAU"))
        elif (
            item.get("provider") == "eastmoney_global_index"
            and self.global_index_provider is not None
        ):
            history = self.global_index_provider.fetch_intraday(item["symbol"])
        else:
            history = self.yahoo_provider.fetch_history(
                item["symbol"], range_name="1d", interval="1m"
            )
        points = history.get("points") or []
        if not points:
            raise ProviderError("上游没有返回当日分钟数据")
        interval = history.get("coverage", {}).get("interval") or history.get(
            "data_granularity", "1m"
        )
        self.database.upsert_market_bars(
            symbol=item["symbol"],
            interval=interval,
            points=points,
            source=history["source"],
            fetched_at=history["fetched_at"],
        )
        latest = points[-1]
        previous_close = history.get("previous_close")
        pct_change = None
        if previous_close not in (None, 0):
            pct_change = round((float(latest["close"]) / float(previous_close) - 1) * 100, 4)
        session = market_session_details(item, now)
        latest_time = datetime.fromisoformat(latest["timestamp"])
        delay_seconds = max(0, int((now - latest_time.astimezone(timezone.utc)).total_seconds()))
        freshness = freshness_label(
            session["is_open"], delay_seconds, history.get("is_stale", False)
        )
        return {
            **{key: item[key] for key in ("key", "name", "instrument", "symbol", "timezone", "currency")},
            "status": "available",
            **session,
            "latest_price": latest["close"],
            "previous_close": previous_close,
            "pct_change": pct_change,
            "market_timestamp": latest["timestamp"],
            "fetched_at": history["fetched_at"],
            "delay_seconds": delay_seconds,
            "freshness": freshness,
            "interval": interval,
            "source": history["source"],
            "is_stale": history.get("is_stale", False),
            "warnings": history.get("warnings", []),
            "points": points,
        }

    def _unavailable(
        self, item: dict[str, Any], now: datetime, exc: Exception
    ) -> dict[str, Any]:
        interval = "5m" if item.get("provider") == "sina_global_futures" else "1m"
        stored = self.database.get_market_bars(item["symbol"], interval, limit=800)
        session = market_session_details(item, now)
        if stored:
            latest = stored[-1]
            return {
                **{key: item[key] for key in ("key", "name", "instrument", "symbol", "timezone", "currency")},
                "status": "degraded",
                **session,
                "latest_price": latest["close"],
                "previous_close": None,
                "pct_change": None,
                "market_timestamp": latest["timestamp"],
                "fetched_at": latest["fetched_at"],
                "delay_seconds": max(
                    0,
                    int(
                        (
                            now
                            - datetime.fromisoformat(latest["timestamp"]).astimezone(timezone.utc)
                        ).total_seconds()
                    ),
                ),
                "freshness": "database_fallback",
                "interval": interval,
                "source": latest["source"],
                "is_stale": True,
                "warnings": [f"实时上游失败，返回数据库最近分钟线：{type(exc).__name__}"],
                "points": stored,
            }
        return {
            **{key: item[key] for key in ("key", "name", "instrument", "symbol", "timezone", "currency")},
            "status": "unavailable",
            **session,
            "latest_price": None,
            "previous_close": None,
            "pct_change": None,
            "market_timestamp": None,
            "fetched_at": utc_now(),
            "delay_seconds": None,
            "freshness": "unavailable",
            "interval": interval,
            "source": None,
            "is_stale": False,
            "warnings": [str(exc)],
            "points": [],
        }


def market_session(
    market: dict[str, Any], now_utc: datetime | None = None
) -> tuple[bool, str, datetime]:
    details = market_session_details(market, now_utc)
    return details["is_open"], details["session_label"], datetime.fromisoformat(
        details["market_local_time"]
    )


def market_session_details(
    market: dict[str, Any], now_utc: datetime | None = None
) -> dict[str, Any]:
    now_utc = now_utc or datetime.now(timezone.utc)
    local_now = now_utc.astimezone(ZoneInfo(market["timezone"]))
    calendar_name = market.get("calendar")
    if calendar_name:
        try:
            calendar = _exchange_calendar(str(calendar_name))
            if pd is None:
                raise RuntimeError("pandas dependency is unavailable")
            minute = pd.Timestamp(now_utc).floor("min")
            session_day = pd.Timestamp(local_now.date())
            first_session = calendar.first_session
            last_session = calendar.last_session
            if session_day < first_session or session_day > last_session:
                raise ValueError("calendar coverage does not include current date")
            if not calendar.is_session(session_day):
                return _session_payload(
                    local_now,
                    is_open=False,
                    label="休市",
                    status="holiday",
                    method="exchange_calendar_v1",
                    calendar_name=str(calendar_name),
                    calendar_status="verified",
                    coverage_end=str(last_session.date()),
                )

            session_open = calendar.session_open(session_day)
            session_close = calendar.session_close(session_day)
            break_start = calendar.session_break_start(session_day)
            break_end = calendar.session_break_end(session_day)
            is_open = bool(calendar.is_open_on_minute(minute, ignore_breaks=False))
            if is_open:
                label = "交易中"
                status = "open"
            elif minute < session_open:
                label = "未开盘"
                status = "pre_open"
            elif not pd.isna(break_start) and not pd.isna(break_end) and break_start <= minute < break_end:
                label = "午间休市"
                status = "break"
            else:
                label = "已收盘"
                status = "closed"
            return _session_payload(
                local_now,
                is_open=is_open,
                label=label,
                status=status,
                method="exchange_calendar_v1",
                calendar_name=str(calendar_name),
                calendar_status="verified",
                coverage_end=str(last_session.date()),
                session_open=_local_iso(session_open, market["timezone"]),
                session_close=_local_iso(session_close, market["timezone"]),
                break_start=(
                    None
                    if pd.isna(break_start)
                    else _local_iso(break_start, market["timezone"])
                ),
                break_end=(
                    None if pd.isna(break_end) else _local_iso(break_end, market["timezone"])
                ),
            )
        except Exception:
            fallback = _weekday_session(market, local_now)
            fallback.update(
                {
                    "session_method": "weekday_schedule_fallback_v1",
                    "calendar_name": str(calendar_name),
                    "calendar_status": "fallback",
                    "calendar_coverage_end": None,
                }
            )
            return fallback

    result = _weekday_session(market, local_now)
    configured_break = _configured_daily_break(market, now_utc)
    if result["is_open"] and configured_break is not None:
        result = _session_payload(
            local_now,
            is_open=False,
            label="每日维护",
            status="break",
            method="otc_daily_break_v1",
            break_start=configured_break["break_start"],
            break_end=configured_break["break_end"],
        )
    result.update(
        {
            "session_method": (
                "otc_daily_break_v1"
                if configured_break is not None and not result["is_open"]
                else "otc_weekday_schedule_v1"
            ),
            "calendar_name": None,
            "calendar_status": "otc_schedule",
            "calendar_coverage_end": None,
        }
    )
    return result


def market_quote_semantics(
    market_key: str,
    market_timestamp: str | None,
    *,
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    """Describe whether a quote is intraday, post-close, or from a prior session.

    A quote can be newer than the latest stored daily bar without still being
    intraday.  This happens routinely just after an exchange closes, while the
    provider's final quote has arrived but the complete daily bar has not.  The
    distinction is user-facing evidence, so keep it deterministic and tied to
    the same exchange calendar used by the live-market dashboard.
    """

    market = next(
        (item for item in LIVE_MARKET_CATALOG if item.get("key") == market_key),
        None,
    )
    if market is None or not market_timestamp:
        return {}
    try:
        parsed = datetime.fromisoformat(str(market_timestamp).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ZoneInfo(str(market["timezone"])))
    except (TypeError, ValueError, KeyError):
        return {}

    quote_session = market_session_details(
        market, parsed.astimezone(timezone.utc)
    )
    current_session = market_session_details(market, now_utc)
    quote_local = parsed.astimezone(ZoneInfo(str(market["timezone"])))
    quote_date = quote_local.date().isoformat()
    current_date = str(current_session.get("market_local_time") or "")[:10]
    quote_status = str(quote_session.get("session_status") or "")
    current_status = str(current_session.get("session_status") or "")

    if quote_status in {"open", "break"}:
        basis = "intraday_snapshot"
        label = "盘中最新报价"
        is_intraday = True
    elif quote_status == "closed":
        basis = "post_close_snapshot"
        label = "收盘后最新报价"
        is_intraday = False
    elif quote_date < current_date:
        basis = "previous_session_snapshot"
        label = "上一交易时段报价"
        is_intraday = False
    else:
        basis = "latest_quote_snapshot"
        label = "最新报价"
        is_intraday = False

    return {
        "quote_basis": basis,
        "quote_label": label,
        "is_intraday": is_intraday,
        "quote_session_status": quote_status or None,
        "quote_session_label": quote_session.get("session_label"),
        "current_session_status": current_status or None,
        "current_session_label": current_session.get("session_label"),
        "market_date": quote_date,
        "market_timezone": market.get("timezone"),
        "complete_daily_bar_confirmed": False,
    }


def previous_market_session_date(
    market_key: str, market_date: str | None
) -> str | None:
    """Return the immediately preceding exchange session for a market date."""

    market = next(
        (item for item in LIVE_MARKET_CATALOG if item.get("key") == market_key),
        None,
    )
    if market is None or not market_date:
        return None
    calendar_name = market.get("calendar")
    if calendar_name and pd is not None:
        try:
            calendar = _exchange_calendar(str(calendar_name))
            session = pd.Timestamp(str(market_date))
            if calendar.is_session(session):
                return str(calendar.previous_session(session).date())
        except Exception:
            pass
    try:
        candidate = datetime.fromisoformat(str(market_date)).date() - timedelta(days=1)
    except ValueError:
        return None
    weekdays = set(market.get("weekdays") or range(5))
    for _ in range(10):
        if candidate.weekday() in weekdays:
            return candidate.isoformat()
        candidate -= timedelta(days=1)
    return None


def _configured_daily_break(
    market: dict[str, Any], now_utc: datetime
) -> dict[str, str] | None:
    timezone_name = str(market.get("daily_break_timezone") or "").strip()
    breaks = list(market.get("daily_breaks") or [])
    if not timezone_name or not breaks:
        return None
    local_break_time = now_utc.astimezone(ZoneInfo(timezone_name))
    current = local_break_time.time().replace(tzinfo=None)
    for start_text, end_text in breaks:
        start = time.fromisoformat(start_text)
        end = time.fromisoformat(end_text)
        if start <= current < end:
            local_date = local_break_time.date().isoformat()
            return {
                "break_start": f"{local_date}T{start_text}:00{local_break_time.strftime('%z')}",
                "break_end": f"{local_date}T{end_text}:00{local_break_time.strftime('%z')}",
            }
    return None


def _weekday_session(market: dict[str, Any], local_now: datetime) -> dict[str, Any]:
    if local_now.weekday() not in market["weekdays"]:
        return _session_payload(
            local_now,
            is_open=False,
            label="休市",
            status="holiday",
            method="weekday_schedule_v1",
        )
    current = local_now.time().replace(tzinfo=None)
    sessions = [
        (time.fromisoformat(start_text), time.fromisoformat(end_text))
        for start_text, end_text in market["sessions"]
    ]
    for start, end in sessions:
        if start <= current <= end:
            return _session_payload(
                local_now,
                is_open=True,
                label="交易中",
                status="open",
                method="weekday_schedule_v1",
            )
    if sessions and current < sessions[0][0]:
        label = "未开盘"
        status = "pre_open"
    elif any(
        sessions[index][1] < current < sessions[index + 1][0]
        for index in range(len(sessions) - 1)
    ):
        label = "午间休市"
        status = "break"
    else:
        label = "已收盘"
        status = "closed"
    return _session_payload(
        local_now,
        is_open=False,
        label=label,
        status=status,
        method="weekday_schedule_v1",
    )


def _session_payload(
    local_now: datetime,
    *,
    is_open: bool,
    label: str,
    status: str,
    method: str,
    calendar_name: str | None = None,
    calendar_status: str | None = None,
    coverage_end: str | None = None,
    session_open: str | None = None,
    session_close: str | None = None,
    break_start: str | None = None,
    break_end: str | None = None,
) -> dict[str, Any]:
    return {
        "is_open": is_open,
        "session_label": label,
        "session_status": status,
        "market_local_time": local_now.isoformat(timespec="seconds"),
        "session_method": method,
        "calendar_name": calendar_name,
        "calendar_status": calendar_status,
        "calendar_coverage_end": coverage_end,
        "session_open": session_open,
        "session_close": session_close,
        "break_start": break_start,
        "break_end": break_end,
    }


def _local_iso(timestamp: Any, timezone_name: str) -> str:
    return timestamp.tz_convert(timezone_name).isoformat()


def freshness_label(is_open: bool, delay_seconds: int, is_stale: bool) -> str:
    if is_stale:
        return "stale_cache"
    if not is_open:
        return "closed_snapshot"
    if delay_seconds <= 180:
        return "near_realtime"
    if delay_seconds <= 900:
        return "delayed"
    return "stale"
