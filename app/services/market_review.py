from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta
import json
import re
import time as monotonic_time
from typing import Any
from zoneinfo import ZoneInfo

from app.db import Database
from app.providers.llm_gateway import LLMGatewayClient, LLMGatewayError
from app.providers.market_review import (
    CninfoMarketAnnouncementProvider,
    MARKET_MARKER,
    OfficialMarketInformationProvider,
    infer_affected_sectors,
)
from app.utils import utc_now


SHANGHAI = ZoneInfo("Asia/Shanghai")
SECTION_KEYS = ("core_events", "highlights", "risks", "watch_directions")
RISK_TERMS = (
    "风险提示",
    "立案",
    "处罚",
    "退市",
    "减持",
    "预亏",
    "下修",
    "终止",
    "违约",
)
POSITIVE_TERMS = ("中标", "合同", "回购", "增持", "预增", "创新高", "获批")
SOURCE_URLS = {
    "中国证监会": "https://www.csrc.gov.cn/csrc/c100028/common_xq_list.shtml",
    "国家统计局": "https://www.stats.gov.cn/sj/zxfb/",
    "中国人民银行": "https://www.pbc.gov.cn/goutongjiaoliu/113456/113469/index.html",
}
INDEX_SERIES = (
    ("000001.SH", "上证指数"),
    ("399001.SZ", "深证成指"),
    ("399006.SZ", "创业板指"),
    ("000300.SH", "沪深300"),
    ("000688.SH", "科创50"),
)
STYLE_SERIES = (
    ("159967.SZ", "成长风格（创成长ETF）"),
    ("510300.SH", "均衡风格（沪深300ETF）"),
    ("510030.SH", "价值风格（价值ETF）"),
)
TUSHARE_DOCS = {
    "index": "https://tushare.pro/document/2?doc_id=95",
    "fund": "https://tushare.pro/document/2?doc_id=127",
    "sector": "https://tushare.pro/document/2?doc_id=327",
    "daily": "https://tushare.pro/document/2?doc_id=27",
    "moneyflow": "https://tushare.pro/document/2?doc_id=170",
    "north": "https://tushare.pro/document/2?doc_id=47",
    "margin": "https://tushare.pro/document/2?doc_id=58",
}


def week_bounds(now: datetime) -> tuple[date, date]:
    local = now.astimezone(SHANGHAI)
    start = local.date() - timedelta(days=local.weekday())
    return start, start + timedelta(days=6)


def is_weekly_formal_due(now: datetime) -> bool:
    local = now.astimezone(SHANGHAI)
    return local.weekday() == 4 and local.time() >= time(15, 10)


class MarketReviewService:
    NEWS_RETRY_SECONDS = 6 * 60 * 60

    def __init__(
        self,
        database: Database,
        today_dashboard: Any,
        settings: Any,
        *,
        tushare_client: Any | None = None,
        official_provider: Any | None = None,
        announcement_provider: Any | None = None,
    ) -> None:
        self.database = database
        self.today_dashboard = today_dashboard
        self.settings = settings
        self.tushare_client = tushare_client
        self.official_provider = (
            official_provider or OfficialMarketInformationProvider()
        )
        self.announcement_provider = (
            announcement_provider or CninfoMarketAnnouncementProvider()
        )
        self.gateway = LLMGatewayClient(settings)
        self._news_disabled_until = 0.0
        self._news_disabled_reason: str | None = None
        self._metrics_cache: dict[str, Any] | None = None
        self._metrics_cache_until = 0.0

    def latest(self, *, refresh_if_empty: bool = True) -> dict[str, Any]:
        start, end = week_bounds(datetime.now(tz=SHANGHAI))
        formal = self.database.get_market_review_snapshot(
            period_start=start.isoformat(),
            period_end=end.isoformat(),
            status="formal",
        )
        if formal is not None and self._metrics_are_current(formal.get("metrics")):
            return formal
        candidate = self.database.get_market_review_snapshot(
            period_start=start.isoformat(),
            period_end=end.isoformat(),
            status="candidate",
        )
        if (
            candidate is not None
            and self._metrics_are_current(candidate.get("metrics"))
        ) or not refresh_if_empty:
            return candidate or self._empty(start, end)
        if formal is not None:
            return self.refresh_candidates(
                status="formal",
                use_llm_clustering=True,
            )
        return self.refresh_candidates()

    def refresh_candidates(
        self,
        *,
        now: datetime | None = None,
        status: str = "candidate",
        use_llm_clustering: bool = False,
    ) -> dict[str, Any]:
        now = now or datetime.now(tz=SHANGHAI)
        start, end = week_bounds(now)
        fetch_end = now.astimezone(SHANGHAI).date()
        fetch_start = min(start, fetch_end)

        with ThreadPoolExecutor(max_workers=4) as executor:
            official_future = executor.submit(self.official_provider.fetch, 12)
            announcement_future = executor.submit(
                self.announcement_provider.fetch,
                fetch_start,
                fetch_end,
                limit=40,
            )
            metrics_future = executor.submit(self._market_metrics, now)
            calendar_future = executor.submit(self._calendar_events, now)

            official = self._safe_packet(official_future, "官方信息")
            announcements = self._safe_packet(announcement_future, "巨潮资讯")
            metrics = self._safe_metrics(metrics_future)
            calendar = self._safe_packet(calendar_future, "Tushare cn_schedule")

        news = self._tushare_news(now)
        evidence = self._dedupe_items(
            [
                *(official.get("items") or []),
                *(announcements.get("items") or []),
                *(news.get("items") or []),
            ]
        )
        if evidence:
            self.database.upsert_news_items(evidence)
        conclusions = self._build_conclusions(
            evidence=evidence,
            calendar_items=calendar.get("items") or [],
            dashboard={
                "industryRotation": metrics.get("industry_rotation") or [],
            },
        )
        generation_mode = "deterministic_extract"
        if use_llm_clustering and self.gateway.enabled:
            clustered = self._cluster_with_llm(conclusions)
            if clustered is not None:
                conclusions = clustered
                generation_mode = "llm_evidence_clustering"
        source_status = {
            **(official.get("sources") or {}),
            **(announcements.get("sources") or {}),
            "Tushare cn_schedule": calendar.get("status") or {
                "available": bool(calendar.get("items")),
                "items": len(calendar.get("items") or []),
            },
            "Tushare news": news.get("status") or {
                "available": bool(news.get("items")),
                "items": len(news.get("items") or []),
            },
            "Tushare 行情与板块": {
                "available": bool(metrics.get("indices")),
                "items": (
                    len(metrics.get("indices") or [])
                    + len(metrics.get("industry_rotation") or [])
                ),
                "market_date": metrics.get("market_date"),
                "errors": metrics.get("module_errors") or {},
            },
        }
        snapshot = {
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "status": status,
            "generation_mode": generation_mode,
            "source_status": source_status,
            "metrics": metrics,
            "conclusions": conclusions,
            "generated_at": utc_now(),
        }
        return self.database.save_market_review_snapshot(snapshot)

    def create_formal_if_due(
        self, *, now: datetime | None = None
    ) -> dict[str, Any] | None:
        now = now or datetime.now(tz=SHANGHAI)
        if not is_weekly_formal_due(now):
            return None
        start, end = week_bounds(now)
        existing = self.database.get_market_review_snapshot(
            period_start=start.isoformat(),
            period_end=end.isoformat(),
            status="formal",
        )
        if existing is not None:
            return existing
        return self.refresh_candidates(
            now=now,
            status="formal",
            use_llm_clustering=True,
        )

    @staticmethod
    def _safe_packet(future: Any, source: str) -> dict[str, Any]:
        try:
            packet = future.result()
            if isinstance(packet, dict):
                return packet
        except Exception as exc:
            return {
                "items": [],
                "sources": {
                    source: {
                        "available": False,
                        "items": 0,
                        "error": type(exc).__name__,
                    }
                },
            }
        return {"items": [], "sources": {source: {"available": False, "items": 0}}}

    @staticmethod
    def _safe_metrics(future: Any) -> dict[str, Any]:
        try:
            result = future.result()
            return result if isinstance(result, dict) else {}
        except Exception as exc:
            return {"module_errors": {"tushare_market": type(exc).__name__}}

    @staticmethod
    def _metrics_are_current(metrics: Any) -> bool:
        return (
            isinstance(metrics, dict)
            and "funds" in metrics
            and "styles" in metrics
            and "review_scores" in metrics
        )

    def _market_metrics(self, now: datetime) -> dict[str, Any]:
        if self.tushare_client is None:
            return {
                "indices": [],
                "industry_rotation": [],
                "market_overview": {},
                "funds": {},
                "styles": [],
                "review_scores": {},
                "module_errors": {"tushare": "not_configured"},
                "generated_at": utc_now(),
            }
        current = monotonic_time.monotonic()
        if self._metrics_cache is not None and current < self._metrics_cache_until:
            return self._metrics_cache

        local = now.astimezone(SHANGHAI)
        week_start, _ = week_bounds(local)
        start_text = week_start.strftime("%Y%m%d")
        end_text = local.date().strftime("%Y%m%d")
        series_codes = tuple(
            dict.fromkeys(code for code, _ in (*INDEX_SERIES, *STYLE_SERIES))
        )
        module_errors: dict[str, str] = {}

        style_codes = {code for code, _ in STYLE_SERIES}

        def fetch_index(code: str) -> tuple[str, list[dict[str, Any]]]:
            try:
                frame = self.tushare_client.query(
                    "fund_daily" if code in style_codes else "index_daily",
                    ts_code=code,
                    start_date=start_text,
                    end_date=end_text,
                    fields="ts_code,trade_date,close,pre_close,pct_chg",
                )
                return code, frame.to_dict("records")
            except Exception as exc:
                return code, [{"_error": type(exc).__name__}]

        index_records: dict[str, list[dict[str, Any]]] = {}
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(fetch_index, code) for code in series_codes]
            for future in futures:
                code, records = future.result()
                if records and records[0].get("_error"):
                    module_errors[f"index:{code}"] = str(records[0]["_error"])
                    records = []
                index_records[code] = records
        # Some Tushare-compatible gateways occasionally return an empty frame
        # under concurrent load without raising. Refill only the missing series
        # sequentially so a transient blank is never cached as a valid result.
        for code in series_codes:
            if index_records.get(code):
                continue
            _, records = fetch_index(code)
            if records and not records[0].get("_error"):
                index_records[code] = records
                module_errors.pop(f"index:{code}", None)

        index_map = {
            code: self._summarize_index(code, name, index_records.get(code) or [])
            for code, name in INDEX_SERIES
        }
        style_map = {
            code: self._summarize_index(code, name, index_records.get(code) or [])
            for code, name in STYLE_SERIES
        }
        indices = [
            index_map[code]
            for code, _ in INDEX_SERIES
            if index_map.get(code) is not None
        ]
        market_date = max(
            (str(item.get("marketDate") or "") for item in indices),
            default=end_text,
        )

        def safe_query(name: str, **params: Any) -> list[dict[str, Any]]:
            try:
                rows = self.tushare_client.query(name, **params).to_dict("records")
                module_errors.pop(name, None)
                return rows
            except Exception as exc:
                module_errors[name] = type(exc).__name__
                return []

        def nonempty_query(name: str, **params: Any) -> list[dict[str, Any]]:
            rows = safe_query(name, **params)
            if not rows:
                rows = safe_query(name, **params)
            if not rows and name not in module_errors:
                module_errors[name] = "empty_response"
            return rows

        def fetch_sectors() -> list[dict[str, Any]]:
            classified = nonempty_query(
                "index_classify",
                level="L1",
                src="SW2021",
                fields="index_code,industry_name,level",
            )
            rows = nonempty_query(
                "sw_daily",
                start_date=start_text,
                end_date=end_text,
                fields="ts_code,trade_date,name,close,pct_change",
            )
            allowed = {
                str(row.get("index_code") or ""): str(
                    row.get("industry_name") or ""
                )
                for row in classified
            }
            grouped: dict[str, list[dict[str, Any]]] = {}
            for row in rows:
                code = str(row.get("ts_code") or "")
                if allowed and code not in allowed:
                    continue
                grouped.setdefault(code, []).append(row)
            result = []
            for code, values in grouped.items():
                values.sort(key=lambda item: str(item.get("trade_date") or ""))
                first, latest = values[0], values[-1]
                first_close = _number(first.get("close"))
                first_pct = _number(first.get("pct_change"))
                latest_close = _number(latest.get("close"))
                base = (
                    first_close / (1 + first_pct / 100)
                    if first_close is not None
                    and first_pct is not None
                    and first_pct != -100
                    else first_close
                )
                change = (
                    (latest_close / base - 1) * 100
                    if latest_close is not None and base not in (None, 0)
                    else None
                )
                if change is None:
                    continue
                result.append(
                    {
                        "code": code,
                        "name": allowed.get(code)
                        or str(latest.get("name") or code),
                        "changePct": round(change, 2),
                        "marketTimestamp": self._trade_date_iso(
                            latest.get("trade_date")
                        ),
                        "source": "Tushare 申万行业日线",
                        "url": TUSHARE_DOCS["sector"],
                    }
                )
            result.sort(key=lambda item: item["changePct"], reverse=True)
            return result

        def fetch_main_moneyflow() -> list[dict[str, Any]]:
            params = {
                "trade_date": query_date,
                "fields": "ts_code,trade_date,net_mf_amount",
            }
            rows = safe_query("moneyflow", **params)
            if not rows:
                rows = safe_query("moneyflow", **params)
            if not rows and "moneyflow" not in module_errors:
                module_errors["moneyflow"] = "empty_response"
            return rows

        query_date = market_date.replace("-", "")
        with ThreadPoolExecutor(max_workers=5) as executor:
            sector_future = executor.submit(fetch_sectors)
            daily_future = executor.submit(
                nonempty_query,
                "daily",
                trade_date=query_date,
                fields="ts_code,trade_date,pct_chg",
            )
            north_future = executor.submit(
                nonempty_query,
                "moneyflow_hsgt",
                start_date=start_text,
                end_date=end_text,
                fields="trade_date,north_money",
            )
            margin_future = executor.submit(
                nonempty_query,
                "margin",
                start_date=start_text,
                end_date=end_text,
                fields="trade_date,exchange_id,rzmre,rzche",
            )
            main_future = executor.submit(fetch_main_moneyflow)
            sectors = sector_future.result()
            daily_rows = daily_future.result()
            north_rows = north_future.result()
            margin_rows = margin_future.result()
            main_rows = main_future.result()

        market_overview = self._market_structure(daily_rows, query_date)
        funds = self._fund_metrics(
            main_rows=main_rows,
            north_rows=north_rows,
            margin_rows=margin_rows,
            market_date=query_date,
        )
        styles = [
            style_map[code]
            for code, _ in STYLE_SERIES
            if style_map.get(code) is not None
        ]
        review_scores = self._review_scores(indices, market_overview, funds)
        result = {
            "indices": indices,
            "industry_rotation": sectors,
            "market_overview": market_overview,
            "funds": funds,
            "styles": styles,
            "review_scores": review_scores,
            "module_errors": module_errors,
            "market_date": market_date,
            "generated_at": utc_now(),
        }
        self._metrics_cache = result
        self._metrics_cache_until = monotonic_time.monotonic() + 300
        return result

    @staticmethod
    def _summarize_index(
        code: str, name: str, records: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        rows = [row for row in records if _number(row.get("close")) is not None]
        if not rows:
            return None
        rows.sort(key=lambda item: str(item.get("trade_date") or ""))
        first, latest = rows[0], rows[-1]
        first_close = _number(first.get("close"))
        first_pre_close = _number(first.get("pre_close"))
        first_pct = _number(first.get("pct_chg"))
        base = first_pre_close
        if base is None and first_close is not None and first_pct not in (None, -100):
            base = first_close / (1 + first_pct / 100)
        latest_close = _number(latest.get("close"))
        change_pct = (
            (latest_close / base - 1) * 100
            if latest_close is not None and base not in (None, 0)
            else None
        )
        return {
            "code": code,
            "name": name,
            "value": round(latest_close, 2) if latest_close is not None else None,
            "changePct": round(change_pct, 2) if change_pct is not None else None,
            "changePoints": (
                round(latest_close - base, 2)
                if latest_close is not None and base is not None
                else None
            ),
            "trend": [round(float(row["close"]), 2) for row in rows],
            "marketDate": MarketReviewService._trade_date_text(
                latest.get("trade_date")
            ),
            "source": (
                "Tushare 场内基金日线"
                if code in {item[0] for item in STYLE_SERIES}
                else "Tushare 指数日线"
            ),
            "url": (
                TUSHARE_DOCS["fund"]
                if code in {item[0] for item in STYLE_SERIES}
                else TUSHARE_DOCS["index"]
            ),
        }

    @staticmethod
    def _market_structure(
        rows: list[dict[str, Any]], market_date: str
    ) -> dict[str, Any]:
        changes = [
            value
            for value in (_number(row.get("pct_chg")) for row in rows)
            if value is not None
        ]
        total = len(changes)
        rising = sum(value > 0 for value in changes)
        flat = sum(value == 0 for value in changes)
        falling = sum(value < 0 for value in changes)
        rate = lambda count: round(count / total * 100, 2) if total else 0.0
        return {
            "total": total,
            "rising": rising,
            "risingRate": rate(rising),
            "flat": flat,
            "flatRate": rate(flat),
            "falling": falling,
            "fallingRate": rate(falling),
            "marketDate": MarketReviewService._trade_date_text(market_date),
            "source": "Tushare A股日线",
            "url": TUSHARE_DOCS["daily"],
            "data_status": "available" if total else "unavailable",
        }

    @staticmethod
    def _fund_metrics(
        *,
        main_rows: list[dict[str, Any]],
        north_rows: list[dict[str, Any]],
        margin_rows: list[dict[str, Any]],
        market_date: str,
    ) -> dict[str, Any]:
        def summed(rows: list[dict[str, Any]], field: str) -> float | None:
            values = [
                value
                for value in (_number(row.get(field)) for row in rows)
                if value is not None
            ]
            return sum(values) if values else None

        main = summed(main_rows, "net_mf_amount")
        north = summed(north_rows, "north_money")
        financing_values = []
        for row in margin_rows:
            buy, repay = _number(row.get("rzmre")), _number(row.get("rzche"))
            if buy is not None and repay is not None:
                financing_values.append(buy - repay)
        financing = sum(financing_values) if financing_values else None
        return {
            "main": {
                "label": "主力资金（最近交易日）",
                "value": round(main / 10000, 2) if main is not None else None,
                "unit": "亿元",
                "status": "available" if main is not None else "unavailable",
                "marketDate": MarketReviewService._trade_date_text(market_date),
                "source": "Tushare 个股资金流向",
                "url": TUSHARE_DOCS["moneyflow"],
            },
            "north": {
                "label": "北向资金（本周累计）",
                "value": round(north / 100, 2) if north is not None else None,
                "unit": "亿元",
                "status": "available" if north is not None else "unavailable",
                "source": "Tushare 沪深港通资金流向",
                "url": TUSHARE_DOCS["north"],
            },
            "financing": {
                "label": "融资净买入（本周累计）",
                "value": (
                    round(financing / 100000000, 2)
                    if financing is not None
                    else None
                ),
                "unit": "亿元",
                "status": "available" if financing is not None else "unavailable",
                "source": "Tushare 融资融券交易汇总",
                "url": TUSHARE_DOCS["margin"],
            },
            "etf": {
                "label": "ETF净流入",
                "value": None,
                "unit": "亿元",
                "status": "unavailable",
                "reason": "当前数据源无可核验的ETF净流入记录",
                "source": "待接入可核验的ETF资金接口",
                "url": "",
            },
        }

    @staticmethod
    def _review_scores(
        indices: list[dict[str, Any]],
        market: dict[str, Any],
        funds: dict[str, Any],
    ) -> dict[str, Any]:
        rising_rate = float(market.get("risingRate") or 0)
        falling_rate = float(market.get("fallingRate") or 0)
        changes = [
            value
            for value in (_number(item.get("changePct")) for item in indices)
            if value is not None
        ]
        trend = (
            sum(value > 0 for value in changes) / len(changes) * 100
            if changes
            else 0
        )
        fund_signs = []
        for key in ("main", "north", "financing"):
            value = _number((funds.get(key) or {}).get("value"))
            if value is not None:
                fund_signs.append(1 if value > 0 else -1 if value < 0 else 0)
        fund_score = (
            50 + 25 * sum(fund_signs) / len(fund_signs)
            if fund_signs
            else 50
        )
        return {
            "labels": ["赚钱效应", "资金面", "情绪面", "风险水平", "趋势强度"],
            "values": [
                round(rising_rate, 1),
                round(max(0, min(100, fund_score)), 1),
                round(rising_rate, 1),
                round(falling_rate, 1),
                round(trend, 1),
            ],
            "method": (
                "赚钱效应/情绪面=上涨家数占比；资金面=主力、北向、融资净额方向评分；"
                "风险水平=下跌家数占比；趋势强度=五大指数本周上涨占比。"
            ),
            "source": "Tushare 行情指标规则计算",
        }

    @staticmethod
    def _trade_date_text(value: Any) -> str | None:
        text = re.sub(r"\D", "", str(value or ""))
        if len(text) != 8:
            return None
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"

    @staticmethod
    def _trade_date_iso(value: Any) -> str | None:
        text = MarketReviewService._trade_date_text(value)
        return f"{text}T15:00:00+08:00" if text else None

    def _calendar_events(
        self, now: datetime
    ) -> dict[str, Any]:
        if self.tushare_client is None:
            return {
                "items": [],
                "status": {"available": False, "items": 0, "reason": "not_configured"},
            }
        local = now.astimezone(SHANGHAI)
        months = {
            local.strftime("%Y%m"),
            (local.replace(day=28) + timedelta(days=4)).strftime("%Y%m"),
        }
        frames = []
        for month in sorted(months):
            frames.append(self.tushare_client.query("cn_schedule", m=month))
        items = []
        seen = set()
        for frame in frames:
            for row in frame.to_dict("records"):
                raw_date = str(row.get("publish_date") or "")
                if not re.fullmatch(r"\d{8}", raw_date):
                    continue
                publish_date = datetime.strptime(raw_date, "%Y%m%d").date()
                if publish_date < local.date() or publish_date > local.date() + timedelta(days=14):
                    continue
                title = str(row.get("title") or "").strip()
                source = str(row.get("issuing_org") or "官方发布机构").strip()
                key = (raw_date, title, source)
                if not title or key in seen:
                    continue
                seen.add(key)
                event_id = f"calendar:{raw_date}:{len(items)}"
                url = next(
                    (
                        value
                        for name, value in SOURCE_URLS.items()
                        if name in source or source in name
                    ),
                    "https://tushare.pro/document/2?doc_id=461",
                )
                items.append(
                    {
                        "id": event_id,
                        "title": title,
                        "source": source,
                        "url": url,
                        "published_at": datetime.combine(
                            publish_date, time.min, tzinfo=SHANGHAI
                        ).isoformat(),
                        "affected_sectors": infer_affected_sectors(title),
                    }
                )
        items.sort(key=lambda item: item["published_at"])
        return {
            "items": items,
            "status": {"available": True, "items": len(items)},
        }

    def _tushare_news(self, now: datetime) -> dict[str, Any]:
        if self.tushare_client is None:
            return {
                "items": [],
                "status": {"available": False, "items": 0, "reason": "not_configured"},
            }
        if monotonic_time.monotonic() < self._news_disabled_until:
            return {
                "items": [],
                "status": {
                    "available": False,
                    "items": 0,
                    "reason": self._news_disabled_reason or "temporarily_unavailable",
                    "retry_after_seconds": round(
                        self._news_disabled_until - monotonic_time.monotonic()
                    ),
                },
            }
        end = now.astimezone(SHANGHAI)
        start = end - timedelta(minutes=10)
        try:
            frame = self.tushare_client.query(
                "news",
                src="cls",
                start_date=start.strftime("%Y-%m-%d %H:%M:%S"),
                end_date=end.strftime("%Y-%m-%d %H:%M:%S"),
            )
        except Exception as exc:
            self._news_disabled_until = (
                monotonic_time.monotonic() + self.NEWS_RETRY_SECONDS
            )
            self._news_disabled_reason = type(exc).__name__
            return {
                "items": [],
                "status": {
                    "available": False,
                    "items": 0,
                    "reason": "permission_or_provider_unavailable",
                },
            }
        items = []
        for index, row in enumerate(frame.to_dict("records")):
            title = str(row.get("title") or row.get("content") or "").strip()
            if not title:
                continue
            published_at = str(row.get("datetime") or "")
            items.append(
                {
                    "id": f"tushare-news:{published_at}:{index}",
                    "symbol": MARKET_MARKER,
                    "category": "market_news",
                    "title": title[:500],
                    "summary": str(row.get("content") or "")[:1000] or None,
                    "source": "Tushare news / 财联社",
                    "url": "https://tushare.pro/document/2?doc_id=143",
                    "published_at": published_at or None,
                    "engagement": None,
                    "fetched_at": utc_now(),
                    "affected_sectors": infer_affected_sectors(title),
                }
            )
        return {
            "items": items,
            "status": {"available": True, "items": len(items)},
        }

    def _build_conclusions(
        self,
        *,
        evidence: list[dict[str, Any]],
        calendar_items: list[dict[str, Any]],
        dashboard: dict[str, Any],
    ) -> dict[str, list[dict[str, Any]]]:
        official = [
            item
            for item in evidence
            if item.get("category") == "official_market"
        ]
        announcements = [
            item
            for item in evidence
            if item.get("category") == "announcement"
        ]
        news = [
            item
            for item in evidence
            if item.get("category") == "market_news"
        ]
        core_candidates = [
            *official,
            *[item for item in announcements if self._has_terms(item, RISK_TERMS + POSITIVE_TERMS)],
            *news,
        ]
        core_candidates.sort(key=self._event_score, reverse=True)
        core_events = [self._extractive(item) for item in core_candidates[:6]]

        sectors = dashboard.get("industryRotation") or []
        highlights = []
        risks = [
            self._extractive(item)
            for item in announcements
            if self._has_terms(item, RISK_TERMS)
        ][:4]
        for item in sectors:
            change = _number(item.get("changePct"))
            if change is None:
                continue
            conclusion = self._sector_conclusion(item, change)
            if change > 0 and len(highlights) < 4:
                highlights.append(conclusion)
            elif change < 0 and len(risks) < 4:
                risks.append(conclusion)
        if not highlights:
            highlights.extend(
                self._extractive(item)
                for item in official
                if self._has_terms(item, POSITIVE_TERMS)
            )
        watch_directions = [
            self._extractive(item, prefix="关注")
            for item in calendar_items[:6]
        ]
        return {
            "core_events": core_events[:6],
            "highlights": highlights[:4],
            "risks": risks[:4],
            "watch_directions": watch_directions[:6],
        }

    @staticmethod
    def _has_terms(item: dict[str, Any], terms: tuple[str, ...]) -> bool:
        text = f"{item.get('title') or ''} {item.get('summary') or ''}"
        return any(term in text for term in terms)

    @staticmethod
    def _event_score(item: dict[str, Any]) -> tuple[int, str]:
        text = f"{item.get('title') or ''} {item.get('summary') or ''}"
        material_terms = (
            "资本市场",
            "货币政策",
            "金融市场运行",
            "监管",
            "处罚",
            "立案",
            "风险提示",
            "经济数据",
            "利率",
            "降准",
            "发布",
            "公告",
            "业绩预告",
        )
        ceremonial_terms = ("会见", "出席", "致辞", "走访", "座谈")
        score = sum(2 for term in material_terms if term in text)
        score -= sum(3 for term in ceremonial_terms if term in text)
        if item.get("category") == "official_market":
            score += 2
        return score, str(item.get("published_at") or "")

    @staticmethod
    def _extractive(
        item: dict[str, Any], *, prefix: str | None = None
    ) -> dict[str, Any]:
        title = re.sub(r"\s+", " ", str(item.get("title") or "")).strip()
        text = f"{prefix}{title}" if prefix else title
        return {
            "text": text[:500],
            "source": str(item.get("source") or "来源待确认"),
            "published_at": item.get("published_at"),
            "url": str(item.get("url") or ""),
            "affected_sectors": item.get("affected_sectors")
            or infer_affected_sectors(title),
            "evidence_ids": [str(item.get("id") or item.get("url") or title)],
        }

    @staticmethod
    def _sector_conclusion(item: dict[str, Any], change: float) -> dict[str, Any]:
        name = str(item.get("name") or "未知板块")
        direction = "上涨" if change > 0 else "下跌"
        published_at = item.get("marketTimestamp")
        return {
            "text": f"{name}板块当前{direction} {abs(change):.2f}%",
            "source": str(item.get("source") or "市场板块行情"),
            "published_at": published_at,
            "url": "https://data.eastmoney.com/bkzj/",
            "affected_sectors": [name],
            "evidence_ids": [f"sector:{name}:{published_at or 'latest'}"],
        }

    def _cluster_with_llm(
        self, conclusions: dict[str, list[dict[str, Any]]]
    ) -> dict[str, list[dict[str, Any]]] | None:
        index: dict[str, tuple[str, dict[str, Any]]] = {}
        compact = []
        for section, items in conclusions.items():
            for item in items:
                evidence_id = str((item.get("evidence_ids") or [""])[0])
                if not evidence_id:
                    continue
                index[evidence_id] = (section, item)
                compact.append(
                    {
                        "id": evidence_id,
                        "suggested_section": section,
                        "title": item["text"],
                        "source": item["source"],
                        "affected_sectors": item["affected_sectors"],
                    }
                )
        if not compact:
            return None
        prompt = (
            "只对以下证据ID进行聚类和排序，不得生成任何新文字或新ID。"
            "返回严格JSON对象，键只能是core_events、highlights、risks、watch_directions，"
            "值是证据ID数组。每个ID最多出现一次。\n证据："
            + json.dumps(compact, ensure_ascii=False)
        )
        try:
            answer, _ = self.gateway.complete(
                prompt=prompt,
                temperature=0,
                max_tokens=700,
                timeout_seconds=min(45, self.settings.llm_gateway_timeout_seconds),
            )
            parsed = _parse_json_object(answer)
        except (LLMGatewayError, ValueError, TypeError, json.JSONDecodeError):
            return None
        used = set()
        result = {key: [] for key in SECTION_KEYS}
        for section in SECTION_KEYS:
            identifiers = parsed.get(section)
            if not isinstance(identifiers, list):
                continue
            for identifier in identifiers:
                key = str(identifier)
                record = index.get(key)
                if record is not None and record[0] == section and key not in used:
                    result[section].append(record[1])
                    used.add(key)
        for section in SECTION_KEYS:
            for item in conclusions[section]:
                key = str((item.get("evidence_ids") or [""])[0])
                if key and key not in used:
                    result[section].append(item)
                    used.add(key)
        return result

    @staticmethod
    def _dedupe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result = []
        seen = set()
        for item in items:
            key = item.get("url") or item.get("id") or item.get("title")
            if not key or key in seen:
                continue
            seen.add(key)
            result.append(item)
        result.sort(
            key=lambda item: item.get("published_at") or item.get("fetched_at") or "",
            reverse=True,
        )
        return result

    @staticmethod
    def _public_metrics(dashboard: dict[str, Any]) -> dict[str, Any]:
        return {
            "indices": dashboard.get("indices") or [],
            "market_overview": dashboard.get("marketOverview") or {},
            "industry_rotation": dashboard.get("industryRotation") or [],
            "trading_activity": dashboard.get("tradingActivity") or {},
            "module_errors": dashboard.get("moduleErrors") or {},
            "generated_at": dashboard.get("generatedAt"),
        }

    @staticmethod
    def _empty(start: date, end: date) -> dict[str, Any]:
        return {
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "status": "candidate",
            "generation_mode": "empty",
            "source_status": {},
            "metrics": {},
            "conclusions": {key: [] for key in SECTION_KEYS},
            "generated_at": utc_now(),
        }


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_json_object(value: str) -> dict[str, Any]:
    text = value.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("LLM聚类结果不是对象")
    return parsed
