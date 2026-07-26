from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd

from app.db import Database
from app.services.market_review import (
    MarketReviewService,
    is_weekly_formal_due,
    week_bounds,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")


class FakeOfficialProvider:
    def fetch(self, limit_per_source=12):
        del limit_per_source
        return {
            "items": [
                {
                    "id": "official-1",
                    "symbol": "__MARKET_CHINA__",
                    "category": "official_market",
                    "title": "证监会发布资本市场监管安排",
                    "summary": None,
                    "source": "中国证监会",
                    "url": "https://www.csrc.gov.cn/example",
                    "published_at": "2026-07-23T00:00:00+08:00",
                    "fetched_at": "2026-07-23T01:00:00+00:00",
                    "affected_sectors": ["全市场"],
                }
            ],
            "sources": {"中国证监会": {"available": True, "items": 1}},
        }


class FakeAnnouncementProvider:
    def fetch(self, start_date, end_date, *, limit=40):
        assert start_date <= end_date
        assert limit == 40
        return {
            "items": [
                {
                    "id": "announcement-1",
                    "symbol": "__MARKET_CHINA__",
                    "category": "announcement",
                    "title": "示例公司：关于股票交易风险提示的公告",
                    "summary": "000001",
                    "source": "巨潮资讯",
                    "url": "https://static.cninfo.com.cn/example.pdf",
                    "published_at": "2026-07-23T18:00:00+08:00",
                    "fetched_at": "2026-07-23T10:00:00+00:00",
                    "affected_sectors": ["全市场"],
                }
            ],
            "sources": {"巨潮资讯": {"available": True, "items": 1}},
        }


class FakeDashboard:
    def dashboard(self):
        return {
            "indices": [
                {
                    "code": "000001.SH",
                    "name": "上证主板",
                    "value": 3500.0,
                    "changePct": 0.8,
                    "source": "测试指数源",
                }
            ],
            "marketOverview": {
                "total": 5200,
                "rising": 3000,
                "risingRate": 57.69,
                "flat": 200,
                "flatRate": 3.85,
                "falling": 2000,
                "fallingRate": 38.46,
                "source": "测试广度源",
            },
            "industryRotation": [
                {
                    "name": "半导体",
                    "changePct": 2.5,
                    "marketTimestamp": "2026-07-24T14:55:00+08:00",
                    "source": "测试板块源",
                },
                {
                    "name": "煤炭",
                    "changePct": -1.2,
                    "marketTimestamp": "2026-07-24T14:55:00+08:00",
                    "source": "测试板块源",
                },
            ],
            "tradingActivity": {
                "data_status": "available",
                "latest": 12000,
                "activity_label": "较近7日均值放量",
                "source": "测试成交源",
            },
            "generatedAt": "2026-07-24T07:00:00+00:00",
        }


class FakeTushare:
    def query(self, api_name, **params):
        if api_name == "news":
            raise RuntimeError("独立付费接口暂不支持")
        if api_name == "cn_schedule":
            month = params["m"]
            if month == "202607":
                return pd.DataFrame(
                    [
                        {
                            "month": month,
                            "publish_date": "20260727",
                            "title": "采购经理指数月度报告",
                            "issuing_org": "国家统计局",
                            "data_api": "cn_pmi",
                        }
                    ]
                )
            return pd.DataFrame()
        if api_name == "index_daily":
            code = params["ts_code"]
            gain = {
                "000001.SH": 1.0,
                "399001.SZ": 2.0,
                "399006.SZ": 3.0,
                "000300.SH": 0.5,
                "000688.SH": -1.0,
            }[code]
            return pd.DataFrame(
                [
                    {
                        "ts_code": code,
                        "trade_date": "20260720",
                        "pre_close": 100,
                        "close": 100 + gain / 2,
                        "pct_chg": gain / 2,
                    },
                    {
                        "ts_code": code,
                        "trade_date": "20260724",
                        "pre_close": 100 + gain / 2,
                        "close": 100 + gain,
                        "pct_chg": gain / 2,
                    },
                ]
            )
        if api_name == "fund_daily":
            code = params["ts_code"]
            gain = {
                "159967.SZ": 1.5,
                "510300.SH": 0.5,
                "510030.SH": -0.5,
            }[code]
            return pd.DataFrame(
                [
                    {
                        "ts_code": code,
                        "trade_date": "20260720",
                        "pre_close": 1,
                        "close": 1 + gain / 200,
                        "pct_chg": gain / 2,
                    },
                    {
                        "ts_code": code,
                        "trade_date": "20260724",
                        "pre_close": 1 + gain / 200,
                        "close": 1 + gain / 100,
                        "pct_chg": gain / 2,
                    },
                ]
            )
        if api_name == "index_classify":
            return pd.DataFrame(
                [
                    {
                        "index_code": "801080.SI",
                        "industry_name": "半导体",
                        "level": "L1",
                    },
                    {
                        "index_code": "801950.SI",
                        "industry_name": "煤炭",
                        "level": "L1",
                    },
                ]
            )
        if api_name == "sw_daily":
            return pd.DataFrame(
                [
                    {
                        "ts_code": "801080.SI",
                        "trade_date": "20260720",
                        "name": "半导体",
                        "close": 101,
                        "pct_change": 1,
                    },
                    {
                        "ts_code": "801080.SI",
                        "trade_date": "20260724",
                        "name": "半导体",
                        "close": 102.5,
                        "pct_change": 1.49,
                    },
                    {
                        "ts_code": "801950.SI",
                        "trade_date": "20260720",
                        "name": "煤炭",
                        "close": 99,
                        "pct_change": -1,
                    },
                    {
                        "ts_code": "801950.SI",
                        "trade_date": "20260724",
                        "name": "煤炭",
                        "close": 98.8,
                        "pct_change": -0.2,
                    },
                ]
            )
        if api_name == "daily":
            return pd.DataFrame(
                [
                    {"ts_code": "000001.SZ", "trade_date": "20260724", "pct_chg": 1},
                    {"ts_code": "000002.SZ", "trade_date": "20260724", "pct_chg": 0},
                    {"ts_code": "600000.SH", "trade_date": "20260724", "pct_chg": -1},
                ]
            )
        if api_name == "moneyflow_hsgt":
            return pd.DataFrame(
                [
                    {"trade_date": "20260723", "north_money": 200},
                    {"trade_date": "20260724", "north_money": 300},
                ]
            )
        if api_name == "margin":
            return pd.DataFrame(
                [
                    {
                        "trade_date": "20260724",
                        "exchange_id": "SSE",
                        "rzmre": 300000000,
                        "rzche": 100000000,
                    }
                ]
            )
        if api_name == "moneyflow":
            return pd.DataFrame(
                [
                    {
                        "ts_code": "000001.SZ",
                        "trade_date": "20260724",
                        "net_mf_amount": 10000,
                    },
                    {
                        "ts_code": "600000.SH",
                        "trade_date": "20260724",
                        "net_mf_amount": -2000,
                    },
                ]
            )
        raise AssertionError(f"unexpected Tushare endpoint: {api_name}")


def settings():
    return SimpleNamespace(
        llm_gateway_enabled=False,
        llm_gateway_api_key="",
        llm_gateway_timeout_seconds=30,
    )


def test_market_review_persists_conclusion_evidence_without_inventing(tmp_path):
    database = Database(tmp_path / "app.db", tmp_path / "workspaces")
    database.initialize()
    service = MarketReviewService(
        database,
        FakeDashboard(),
        settings(),
        tushare_client=FakeTushare(),
        official_provider=FakeOfficialProvider(),
        announcement_provider=FakeAnnouncementProvider(),
    )

    snapshot = service.refresh_candidates(
        now=datetime(2026, 7, 24, 14, 30, tzinfo=SHANGHAI)
    )

    assert snapshot["status"] == "candidate"
    assert snapshot["source_status"]["Tushare news"]["available"] is False
    assert [item["name"] for item in snapshot["metrics"]["indices"]] == [
        "上证指数",
        "深证成指",
        "创业板指",
        "沪深300",
        "科创50",
    ]
    assert snapshot["metrics"]["industry_rotation"][0]["name"] == "半导体"
    assert snapshot["metrics"]["market_overview"]["total"] == 3
    assert snapshot["metrics"]["funds"]["north"]["value"] == 5.0
    assert snapshot["metrics"]["funds"]["etf"]["status"] == "unavailable"
    assert len(snapshot["metrics"]["styles"]) == 3
    assert len(snapshot["metrics"]["review_scores"]["values"]) == 5
    assert snapshot["conclusions"]["core_events"][0]["source"] in {
        "巨潮资讯",
        "中国证监会",
    }
    assert snapshot["conclusions"]["highlights"][0]["text"] == "半导体板块当前上涨 2.50%"
    assert snapshot["conclusions"]["risks"][0]["url"].startswith("https://")
    assert snapshot["conclusions"]["watch_directions"][0]["text"].startswith(
        "关注采购经理指数月度报告"
    )
    for section in snapshot["conclusions"].values():
        for item in section:
            assert item["source"]
            assert item["url"].startswith("https://")
            assert item["affected_sectors"]
            assert item["evidence_ids"]

    stored = database.get_market_review_snapshot(
        period_start="2026-07-20",
        period_end="2026-07-26",
        status="candidate",
    )
    assert stored is not None
    assert stored["conclusions"] == snapshot["conclusions"]


def test_weekly_formal_snapshot_is_created_only_after_friday_close(tmp_path):
    database = Database(tmp_path / "app.db", tmp_path / "workspaces")
    database.initialize()
    service = MarketReviewService(
        database,
        FakeDashboard(),
        settings(),
        tushare_client=FakeTushare(),
        official_provider=FakeOfficialProvider(),
        announcement_provider=FakeAnnouncementProvider(),
    )
    before_close = datetime(2026, 7, 24, 15, 0, tzinfo=SHANGHAI)
    after_close = datetime(2026, 7, 24, 15, 10, tzinfo=SHANGHAI)

    assert is_weekly_formal_due(before_close) is False
    assert service.create_formal_if_due(now=before_close) is None
    formal = service.create_formal_if_due(now=after_close)

    assert formal is not None
    assert formal["status"] == "formal"
    assert formal["generation_mode"] == "deterministic_extract"
    assert week_bounds(after_close)[0].isoformat() == formal["period_start"]


def test_tushare_news_failure_is_circuit_broken_between_candidate_refreshes(tmp_path):
    class CountingTushare(FakeTushare):
        news_calls = 0

        def query(self, api_name, **params):
            if api_name == "news":
                self.news_calls += 1
            return super().query(api_name, **params)

    tushare = CountingTushare()
    database = Database(tmp_path / "app.db", tmp_path / "workspaces")
    database.initialize()
    service = MarketReviewService(
        database,
        FakeDashboard(),
        settings(),
        tushare_client=tushare,
        official_provider=FakeOfficialProvider(),
        announcement_provider=FakeAnnouncementProvider(),
    )
    now = datetime(2026, 7, 24, 14, 30, tzinfo=SHANGHAI)

    service.refresh_candidates(now=now)
    service.refresh_candidates(now=now)

    assert tushare.news_calls == 1


def test_llm_clustering_cannot_move_evidence_between_review_sections(tmp_path):
    class FakeGateway:
        enabled = True

        def complete(self, **kwargs):
            del kwargs
            return (
                '{"core_events":["calendar-1"],"highlights":[],"risks":[],'
                '"watch_directions":[]}',
                {},
            )

    database = Database(tmp_path / "app.db", tmp_path / "workspaces")
    database.initialize()
    service = MarketReviewService(
        database,
        FakeDashboard(),
        settings(),
        official_provider=FakeOfficialProvider(),
        announcement_provider=FakeAnnouncementProvider(),
    )
    service.gateway = FakeGateway()
    direction = {
        "text": "关注官方日程",
        "source": "国家统计局",
        "published_at": "2026-07-27T00:00:00+08:00",
        "url": "https://www.stats.gov.cn/",
        "affected_sectors": ["全市场"],
        "evidence_ids": ["calendar-1"],
    }
    conclusions = {
        "core_events": [],
        "highlights": [],
        "risks": [],
        "watch_directions": [direction],
    }

    clustered = service._cluster_with_llm(conclusions)

    assert clustered is not None
    assert clustered["core_events"] == []
    assert clustered["watch_directions"] == [direction]
