from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from app.catalog import INDEX_BY_SYMBOL
from app.db import Database
from app.providers.market import (
    CSIIndustryIndexProvider,
    EastmoneyCapitalFlowProvider,
    EastmoneyGlobalIndexProvider,
    EastmoneySectorProvider,
    ProviderError,
    SinaGoldProvider,
    SinaIndustrySectorProvider,
    SinaMarketBreadthProvider,
    TencentChinaIndexQuoteProvider,
    TencentChinaIndexProvider,
    YahooMarketProvider,
)
from app.providers.market_news import GoogleNewsMarketProvider
from app.services.market_news import _rank_for_focus


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_star_50_is_a_first_class_china_index():
    assert INDEX_BY_SYMBOL["000688.SS"]["name"] == "科创50"
    assert TencentChinaIndexProvider.SYMBOLS["000688.SS"] == {
        "quote_symbol": "sh000688",
        "name": "科创50",
        "exchange": "SSE",
    }


def test_tencent_china_index_quote_parser_keeps_realtime_fields_separate_from_daily_bars():
    parsed = TencentChinaIndexQuoteProvider._parse(
        "v_sh000001=\"1~上证指数~000001~3348.37~3339.06~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~20260807143005~9.31~0.28\";\n"
        "v_sz399001=\"51~深证成指~399001~10197.46~10230.54~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~20260807143005~-33.08~-0.32\";\n",
        ["000001.SS", "399001.SZ"],
    )

    assert parsed["000001.SS"]["price"] == 3348.37
    assert parsed["000001.SS"]["previous_close"] == 3339.06
    assert parsed["000001.SS"]["change"] == 9.31
    assert parsed["000001.SS"]["pct_change"] == 0.28
    assert parsed["000001.SS"]["data_granularity"] == "realtime_quote"
    assert parsed["000001.SS"]["market_timestamp"] == "2026-08-07T14:30:05+08:00"
    assert parsed["399001.SZ"]["pct_change"] == -0.32


def test_tencent_china_index_quote_provider_marks_expired_quote_cache_as_stale(tmp_path: Path):
    database = Database(tmp_path / "workspaces")
    database.initialize()

    class QuoteResponse:
        content = (
            'v_sh000001="1~上证指数~000001~3348.37~3339.06~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~20260807143005~9.31~0.28";'
        ).encode("gb18030")

        def raise_for_status(self):
            return None

    provider = TencentChinaIndexQuoteProvider(
        database, ttl_seconds=0, http_get=lambda *args, **kwargs: QuoteResponse()
    )
    provider.fetch_quotes(["000001.SS"])
    provider.http_get = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("network unavailable"))

    stale = provider.fetch_quotes(["000001.SS"])

    assert stale["000001.SS"]["is_stale"] is True


def test_yahoo_provider_parses_and_caches(tmp_path: Path):
    database = Database(tmp_path / "workspaces")
    database.initialize()
    calls = []
    payload = {
        "chart": {
            "error": None,
            "result": [
                {
                    "meta": {
                        "currency": "CNY",
                        "exchangeName": "SHH",
                        "exchangeTimezoneName": "Asia/Shanghai",
                        "shortName": "SSE Composite",
                        "regularMarketTime": 1_700_086_400,
                    },
                    "timestamp": [1_700_000_000, 1_700_086_400],
                    "indicators": {
                        "quote": [
                            {
                                "open": [10, 11],
                                "high": [12, 13],
                                "low": [9, 10],
                                "close": [11, 12],
                                "volume": [100, 200],
                            }
                        ],
                        "adjclose": [{"adjclose": [11, 12]}],
                    },
                }
            ],
        }
    }

    def http_get(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeResponse(payload)

    provider = YahooMarketProvider(database, ttl_seconds=60, http_get=http_get)
    first = provider.fetch_history("000001.SS", range_name="1mo")
    second = provider.fetch_history("000001.SS", range_name="1mo")
    assert len(calls) == 1
    assert first["coverage"]["points"] == 2
    assert first["points"][-1]["close"] == 12
    assert first["regular_market_timestamp"] == "2023-11-15T22:13:20+00:00"
    assert second["cache_hit"] is True
    stored = database.get_market_bars("000001.SS", "1d", limit=10)
    assert len(stored) == 2
    assert stored[-1]["adjusted_close"] == 12


def test_yahoo_provider_returns_explicit_stale_cache_on_failure(tmp_path: Path):
    database = Database(tmp_path / "workspaces")
    database.initialize()
    payload = {
        "chart": {
            "error": None,
            "result": [
                {
                    "meta": {"currency": "USD"},
                    "timestamp": [1_700_000_000],
                    "indicators": {"quote": [{"close": [10.0]}]},
                }
            ],
        }
    }
    provider = YahooMarketProvider(
        database,
        ttl_seconds=-1,
        http_get=lambda *args, **kwargs: FakeResponse(payload),
    )
    provider.fetch_history("AAPL", range_name="1mo")

    def fail(*args, **kwargs):
        raise RuntimeError("network unavailable")

    provider.http_get = fail
    stale = provider.fetch_history("AAPL", range_name="1mo")
    assert stale["is_stale"] is True
    assert any("已过期缓存" in warning for warning in stale["warnings"])
    assert any("请求失败" in warning for warning in stale["warnings"])


def test_yahoo_provider_restores_newer_completed_bar_when_upstream_regresses(
    tmp_path: Path,
):
    database = Database(tmp_path / "workspaces")
    database.initialize()
    database.upsert_market_bars(
        "000065.SZ",
        "1d",
        [
            {
                "timestamp": "2026-07-28T01:30:00+00:00",
                "open": 9.2,
                "high": 9.24,
                "low": 8.98,
                "close": 9.04,
                "adjusted_close": 9.04,
                "volume": 20_000_000,
            }
        ],
        "earlier complete Yahoo response",
        "2026-07-28T08:00:00+00:00",
    )
    payload = {
        "chart": {
            "error": None,
            "result": [
                {
                    "meta": {
                        "currency": "CNY",
                        "exchangeTimezoneName": "Asia/Shanghai",
                        "regularMarketTime": 1_775_000_000,
                    },
                    "timestamp": [1_774_224_600, 1_774_311_000],
                    "indicators": {
                        "quote": [
                            {
                                "open": [8.98, 8.98],
                                "high": [9.29, 9.29],
                                "low": [8.86, 8.98],
                                "close": [8.89, 9.18],
                                "volume": [13_263_030, 14_413_200],
                            }
                        ],
                        "adjclose": [{"adjclose": [8.89, 9.18]}],
                    },
                }
            ],
        }
    }
    provider = YahooMarketProvider(
        database,
        ttl_seconds=60,
        http_get=lambda *args, **kwargs: FakeResponse(payload),
    )

    history = provider.fetch_history("000065.SZ", range_name="1mo")

    assert history["points"][-1]["timestamp"] == "2026-07-28T01:30:00+00:00"
    assert history["points"][-1]["close"] == 9.04
    assert history["coverage"]["restored_persisted_newer_bars"] == 1
    assert any("生产数据库补回" in warning for warning in history["warnings"])


def test_yahoo_history_rejects_invalid_and_incomplete_daily_bars():
    history = {
        "symbol": "000063.SZ",
        "timezone": "Asia/Shanghai",
        "market_timestamp": "2026-07-22T01:30:00+00:00",
        "warnings": [],
        "coverage": {"interval": "1d"},
        "points": [
            {
                "timestamp": "2026-07-20T01:30:00+00:00",
                "open": 33.0,
                "high": 34.0,
                "low": 32.0,
                "close": 33.5,
            },
            {
                "timestamp": "2026-07-21T01:30:00+00:00",
                "open": 33.8,
                "high": 35.0,
                "low": 32.4,
                "close": 34.88,
            },
            {
                "timestamp": "2026-07-22T01:30:00+00:00",
                "open": 38.97,
                "high": 35.67,
                "low": 34.11,
                "close": 35.36,
            },
        ],
    }

    sanitized, removed = YahooMarketProvider._sanitize_history(
        history,
        symbol="000063.SZ",
        interval="1d",
        now=datetime(2026, 7, 22, 1, 55, tzinfo=timezone.utc),
    )

    assert [point["timestamp"] for point in sanitized["points"]] == [
        "2026-07-20T01:30:00+00:00",
        "2026-07-21T01:30:00+00:00",
    ]
    assert removed == ["2026-07-22T01:30:00+00:00"]
    assert sanitized["coverage"]["dropped_invalid_ohlc"] == 1
    assert sanitized["coverage"]["dropped_incomplete_daily"] == 0
    assert sanitized["market_timestamp"] == "2026-07-21T01:30:00+00:00"


def test_yahoo_history_keeps_previous_session_before_current_close():
    history = {
        "symbol": "000001.SS",
        "timezone": "Asia/Shanghai",
        "market_timestamp": "2026-07-22T01:30:00+00:00",
        "warnings": [],
        "coverage": {"interval": "1d"},
        "points": [
            {
                "timestamp": "2026-07-21T01:30:00+00:00",
                "open": 3800.0,
                "high": 3880.0,
                "low": 3780.0,
                "close": 3864.0,
            },
            {
                "timestamp": "2026-07-22T01:30:00+00:00",
                "open": 3860.0,
                "high": 3880.0,
                "low": 3840.0,
                "close": 3870.0,
            },
        ],
    }

    sanitized, removed = YahooMarketProvider._sanitize_history(
        history,
        symbol="000001.SS",
        interval="1d",
        now=datetime(2026, 7, 22, 1, 55, tzinfo=timezone.utc),
    )

    assert len(sanitized["points"]) == 1
    assert sanitized["points"][0]["timestamp"].startswith("2026-07-21")
    assert removed == ["2026-07-22T01:30:00+00:00"]
    assert sanitized["coverage"]["dropped_incomplete_daily"] == 1


def test_tencent_china_index_provider_drops_current_incomplete_daily_bar():
    payload = {
        "code": 0,
        "data": {
            "sz399006": {
                "day": [
                    [
                        "2026-07-21",
                        "3469.22",
                        "3685.97",
                        "3687.15",
                        "3373.04",
                        "258922406",
                    ],
                    [
                        "2026-07-22",
                        "3644.98",
                        "3681.20",
                        "3694.90",
                        "3632.34",
                        "137642318",
                    ],
                ]
            }
        },
    }

    parsed = TencentChinaIndexProvider._parse(
        "399006.SZ",
        TencentChinaIndexProvider.SYMBOLS["399006.SZ"],
        "3mo",
        payload,
        now=datetime(2026, 7, 22, 3, 0, tzinfo=timezone.utc),
    )

    assert len(parsed["points"]) == 1
    assert parsed["points"][0]["close"] == 3685.97
    assert parsed["market_timestamp"] == "2026-07-21T01:30:00+00:00"
    assert parsed["coverage"]["dropped_incomplete_daily"] == 1


def test_tencent_china_index_provider_persists_and_caches(tmp_path: Path):
    database = Database(tmp_path / "workspaces")
    database.initialize()
    calls = []
    payload = {
        "code": 0,
        "data": {
            "sh000300": {
                "day": [
                    [
                        "2026-07-20",
                        "4575.67",
                        "4598.32",
                        "4628.80",
                        "4521.18",
                        "333116058",
                    ],
                    [
                        "2026-07-21",
                        "4630.85",
                        "4739.23",
                        "4739.23",
                        "4566.28",
                        "345403590",
                    ],
                ]
            }
        },
    }

    def http_get(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeResponse(payload)

    provider = TencentChinaIndexProvider(database, ttl_seconds=60, http_get=http_get)
    first = provider.fetch_history("000300.SS", range_name="3mo")
    second = provider.fetch_history("000300.SS", range_name="3mo")

    assert len(calls) == 1
    assert first["points"][-1]["close"] == 4739.23
    assert second["cache_hit"] is True
    stored = database.get_market_bars("000300.SS", "1d", limit=10)
    assert [item["close"] for item in stored] == [4598.32, 4739.23]


def test_eastmoney_provider_parses_sector_fields(tmp_path: Path):
    database = Database(tmp_path / "workspaces")
    database.initialize()
    payload = {
        "data": {
            "total": 496,
            "diff": [
                {
                    "f12": "BK0001",
                    "f14": "算力",
                    "f2": 1234.5,
                    "f3": 3.2,
                    "f62": 90000000,
                    "f104": 20,
                    "f105": 3,
                    "f106": 1,
                    "f124": 1_700_000_000,
                }
            ],
        }
    }
    provider = EastmoneySectorProvider(
        database,
        http_get=lambda *args, **kwargs: FakeResponse(payload),
    )
    result = provider.fetch_hot_sectors(limit=5)
    assert result["coverage"]["total_available"] == 496
    assert result["sectors"][0]["name"] == "算力"
    assert result["sectors"][0]["main_net_inflow"] == 90000000


def test_csi_industry_provider_accepts_alphanumeric_official_index_codes():
    payload = {
        "QuotationCodeTable": {
            "Data": [
                {
                    "Code": "H30184",
                    "Name": "半导体",
                    "QuoteID": "2.H30184",
                    "SecurityTypeName": "指数",
                }
            ]
        }
    }

    result = CSIIndustryIndexProvider._select_index_candidate("半导体", payload)

    assert result["Code"] == "H30184"


def test_csi_industry_provider_builds_official_constituents_and_history(
    tmp_path: Path, monkeypatch
):
    database = Database(tmp_path / "workspaces")
    database.initialize()
    calls = []
    search_payload = {
        "QuotationCodeTable": {
            "Data": [
                {
                    "Code": "931160",
                    "Name": "通信设备",
                    "QuoteID": "2.931160",
                    "SecurityTypeName": "指数",
                },
                {
                    "Code": "BK0448",
                    "Name": "通信设备",
                    "QuoteID": "90.BK0448",
                    "SecurityTypeName": "板块",
                },
            ]
        }
    }
    basic_payload = {
        "code": "200",
        "data": {
            "indexShortNameCn": "通信设备",
            "indexFullNameCn": "中证全指通信设备指数",
            "indexCnDesc": "反映通信设备行业上市公司证券的整体表现。",
            "currencyCn": "人民币",
            "publishDate": "2013-07-15",
            "adjFreqCn": "每半年",
        },
    }
    details_payload = {
        "code": "200",
        "data": {
            "样本列表": [{"filePath": "https://example.invalid/cons.xls"}],
            "样本权重": [{"filePath": "https://example.invalid/weight.xls"}],
        },
    }
    history_payload = {
        "data": [
            {
                "tradeDate": "20260720",
                "open": 20516.16,
                "close": 19546.69,
                "high": 20722.59,
                "low": 18906.22,
                "tradingVol": 2550141500,
                "tradingValue": 2103.48,
                "changePct": -1.42,
                "change": -281.91,
                "consNumber": 50,
            },
            {
                "tradeDate": "20260721",
                "open": 19761.72,
                "close": 21147.25,
                "high": 21164.17,
                "low": 18444.62,
                "tradingVol": 2974825100,
                "tradingValue": 2471.6,
                "changePct": 8.19,
                "change": 1600.56,
                "consNumber": 50,
            },
        ]
    }

    class BinaryResponse:
        def __init__(self, content: bytes):
            self.content = content

        def raise_for_status(self):
            return None

    def http_get(url, **kwargs):
        calls.append(url)
        if url == CSIIndustryIndexProvider.SEARCH_URL:
            return FakeResponse(search_payload)
        if url.endswith("/931160"):
            return FakeResponse(basic_payload)
        if url == CSIIndustryIndexProvider.DETAILS_URL:
            return FakeResponse(details_payload)
        if url.endswith("cons.xls"):
            return BinaryResponse(b"constituents")
        if url.endswith("weight.xls"):
            return BinaryResponse(b"weights")
        if url == CSIIndustryIndexProvider.HISTORY_URL:
            return FakeResponse(history_payload)
        if url == CSIIndustryIndexProvider.COMPONENT_HISTORY_URL:
            quote_symbol = kwargs["params"]["param"].split(",", 1)[0]
            rows = (
                [
                    ["2026-07-17", "38.97", "36.00", "39.26", "36.00", "100"],
                    ["2026-07-20", "36.00", "33.73", "36.18", "33.14", "90"],
                ]
                if quote_symbol == "sz000063"
                else [
                    ["2026-07-17", "49.50", "50.00", "50.50", "49.00", "80"],
                    ["2026-07-20", "50.20", "51.00", "51.50", "50.10", "95"],
                ]
            )
            return FakeResponse({"data": {quote_symbol: {"qfqday": rows}}})
        raise AssertionError(url)

    constituent_frame = pd.DataFrame(
        {
            "日期Date": [20260721, 20260721],
            "成份券代码Constituent Code": [63, 2281],
            "成份券名称Constituent Name": ["中兴通讯", "光迅科技"],
            "交易所Exchange": ["深圳证券交易所", "深圳证券交易所"],
        }
    )
    weight_frame = pd.DataFrame(
        {
            "日期Date": [20260630, 20260630],
            "成份券代码Constituent Code": [63, 2281],
            "权重(%)weight": [3.741, 3.99],
        }
    )

    def fake_read_excel(source, **kwargs):
        content = source.getvalue()
        return constituent_frame if content == b"constituents" else weight_frame

    monkeypatch.setattr("app.providers.market.pd.read_excel", fake_read_excel)
    provider = CSIIndustryIndexProvider(database, ttl_seconds=60, http_get=http_get)

    first = provider.fetch("通信设备", market_date="2026-07-20")
    second = provider.fetch("通信设备", market_date="2026-07-20")

    assert first["index_code"] == "931160"
    assert first["index_full_name"] == "中证全指通信设备指数"
    assert first["coverage"]["constituents"] == 2
    assert first["constituents"][0]["symbol"] == "000063.SZ"
    assert first["constituents"][0]["weight_pct"] == 3.741
    assert first["points"][0]["pct_change"] == -1.42
    component = first["component_analysis"]
    assert component["status"] == "available"
    assert component["coverage"]["available_returns"] == 2
    assert component["breadth"]["advancers"] == 1
    assert component["breadth"]["decliners"] == 1
    assert component["components"][0]["pct_change"] == -6.3056
    assert component["components"][0]["estimated_contribution_pp"] == -0.2359
    assert component["contribution"]["official_index_return_pct"] == -1.42
    assert second["cache_hit"] is True
    assert len(calls) == 8
    bars = database.get_market_bars("CSI931160", "1d", limit=10)
    assert [item["close"] for item in bars] == [19546.69, 21147.25]


def test_csi_industry_provider_uses_verified_cross_taxonomy_aliases():
    cases = {
        "电池": ("931719", "CS电池"),
        "白酒Ⅱ": ("399997", "中证白酒"),
        "银行Ⅱ": ("399986", "中证银行"),
    }
    for industry_name, (index_code, index_name) in cases.items():
        plan = CSIIndustryIndexProvider._mapping_plan(industry_name)
        candidate = CSIIndustryIndexProvider._select_index_candidate(
            industry_name,
            {
                "QuotationCodeTable": {
                    "Data": [
                        {
                            "Code": index_code,
                            "Name": index_name,
                            "QuoteID": f"2.{index_code}",
                            "SecurityTypeName": "指数",
                        }
                    ]
                }
            },
            expected_code=plan["index_code"],
        )

        assert plan["match_type"] == "verified_alias"
        assert candidate["Code"] == index_code


def test_csi_industry_components_fall_back_to_sina_for_bse_history(
    tmp_path: Path,
):
    database = Database(tmp_path / "workspaces")
    database.initialize()

    def http_get(url, **kwargs):
        if url == CSIIndustryIndexProvider.COMPONENT_HISTORY_URL:
            return FakeResponse({"data": {"bj920185": {"qfqday": [], "day": []}}})
        if url == CSIIndustryIndexProvider.SINA_COMPONENT_HISTORY_URL:
            return FakeResponse(
                [
                    {
                        "day": "2026-07-17",
                        "open": "21.08",
                        "high": "21.45",
                        "low": "20.37",
                        "close": "21.02",
                        "volume": "5018690",
                    },
                    {
                        "day": "2026-07-20",
                        "open": "21.23",
                        "high": "21.29",
                        "low": "19.96",
                        "close": "20.23",
                        "volume": "6715000",
                    },
                ]
            )
        raise AssertionError(url)

    provider = CSIIndustryIndexProvider(database, http_get=http_get)
    analysis = provider._fetch_component_analysis(
        {
            "index_code": "931719",
            "weights_as_of": "2026-06-30",
            "constituents": [
                {
                    "symbol": "920185.BJ",
                    "sina_symbol": "bj920185",
                    "name": "贝特瑞",
                    "weight_pct": 4.0,
                }
            ],
            "points": [{"market_date": "2026-07-20", "pct_change": -2.0}],
        },
        "2026-07-20",
    )

    assert analysis["status"] == "available"
    assert analysis["coverage"]["available_returns"] == 1
    assert analysis["coverage"]["primary_adjusted_returns"] == 0
    assert analysis["coverage"]["fallback_unadjusted_returns"] == 1
    assert analysis["failures"] == []
    assert analysis["components"][0]["source"].startswith("Sina")
    assert analysis["components"][0]["adjustment"] == "unadjusted"
    assert analysis["components"][0]["pct_change"] == -3.7583
    assert "未复权日线降级" in analysis["contribution"]["boundary"]


def test_csi_industry_components_keep_structured_failure_reasons(
    tmp_path: Path,
):
    database = Database(tmp_path / "workspaces")
    database.initialize()

    def http_get(url, **kwargs):
        if url == CSIIndustryIndexProvider.COMPONENT_HISTORY_URL:
            return FakeResponse({"data": {"bj999999": {"qfqday": [], "day": []}}})
        if url == CSIIndustryIndexProvider.SINA_COMPONENT_HISTORY_URL:
            return FakeResponse([])
        raise AssertionError(url)

    provider = CSIIndustryIndexProvider(database, http_get=http_get)
    analysis = provider._fetch_component_analysis(
        {
            "index_code": "999999",
            "weights_as_of": "2026-06-30",
            "constituents": [
                {
                    "symbol": "999999.BJ",
                    "sina_symbol": "bj999999",
                    "name": "缺失样本",
                    "weight_pct": 1.0,
                }
            ],
            "points": [],
        },
        "2026-07-20",
    )

    assert analysis["status"] == "unavailable"
    assert analysis["coverage"]["missing_returns"] == 1
    failure = analysis["failures"][0]
    assert failure["reason_code"] == "no_history"
    assert failure["reason"] == "当前行情源未返回目标日前的日线历史"
    assert "行情源暂不支持" in "；".join(failure["possible_causes"])
    assert len(failure["source_attempts"]) == 2


def test_eastmoney_global_index_provider_parses_current_minute_bars(
    tmp_path: Path,
):
    database = Database(tmp_path / "workspaces")
    database.initialize()
    payload = {
        "data": {
            "name": "日经225",
            "preClose": 64141.12,
            "trends": [
                "2026-07-21 08:00,64544.05,64544.05,64544.05,64544.05,0,0.00,64544.050",
                "2026-07-21 08:01,64544.05,64491.35,64544.05,64491.35,0,0.00,64517.700",
            ],
        }
    }
    provider = EastmoneyGlobalIndexProvider(
        database, http_get=lambda *args, **kwargs: FakeResponse(payload)
    )
    result = provider.fetch_intraday("^N225")
    assert result["display_name"] == "日经225"
    assert result["previous_close"] == 64141.12
    assert result["coverage"]["points"] == 2
    assert result["points"][-1]["open"] == 64544.05
    assert result["points"][-1]["close"] == 64491.35
    assert result["points"][-1]["high"] == 64544.05
    assert result["points"][-1]["low"] == 64491.35
    assert result["points"][-1]["timestamp"] == "2026-07-21T00:01:00+00:00"
    assert EastmoneyGlobalIndexProvider.SYMBOLS["000001.SS"]["secid"] == "1.000001"


def test_sina_fallback_parses_gb18030_industry_data(tmp_path: Path):
    database = Database(tmp_path / "workspaces")
    database.initialize()
    content = (
        "var S_Finance_bankuai_sinaindustry = {"
        '"new_a":"new_a,行业甲,10,12.3,0.2,2.5,1000,2000,sh600000,1,10,0.1,龙头甲",'
        '"new_b":"new_b,行业乙,12,8.3,-0.1,-1.5,900,1800,sz000001,1,9,0.1,龙头乙"};'
    ).encode("gb18030")

    class SinaResponse:
        def raise_for_status(self):
            return None

        @property
        def content(self):
            return content

    provider = SinaIndustrySectorProvider(
        database, http_get=lambda *args, **kwargs: SinaResponse()
    )
    result = provider.fetch_hot_sectors(limit=2)
    assert result["sectors"][0]["name"] == "行业甲"
    assert result["sectors"][0]["pct_change"] == 2.5
    assert result["sectors"][0]["main_net_inflow"] is None


def test_sina_market_breadth_provider_fetches_complete_snapshot_and_caches(
    tmp_path: Path,
):
    database = Database(tmp_path / "workspaces")
    database.initialize()
    rows = [
        {
            "symbol": "sh600000",
            "changepercent": 1.2,
            "amount": 1_000_000,
            "ticktime": "15:00:00",
        },
        {
            "symbol": "sz000001",
            "changepercent": -0.5,
            "amount": 2_000_000,
            "ticktime": "15:00:01",
        },
        {
            "symbol": "bj920001",
            "changepercent": 0,
            "amount": 3_000_000,
            "ticktime": "15:30:00",
        },
    ]
    calls = []

    def http_get(url, **kwargs):
        calls.append((url, kwargs.get("params")))
        if url == SinaMarketBreadthProvider.COUNT_URL:
            return FakeResponse("3")
        return FakeResponse(rows)

    provider = SinaMarketBreadthProvider(
        database,
        ttl_seconds=60,
        http_get=http_get,
        max_workers=2,
    )
    first = provider.fetch_breadth()
    fixed_expiry = "2099-01-01T00:00:00+00:00"
    with database.connect() as connection:
        connection.execute(
            "UPDATE market_cache SET expires_at = ? WHERE cache_key = ?",
            (fixed_expiry, SinaMarketBreadthProvider.CACHE_KEY),
        )
    second = provider.fetch_breadth()

    assert len(calls) == 2
    assert first["coverage"]["coverage_ratio"] == 1.0
    assert first["breadth"] == {
        "total": 3,
        "advancers": 1,
        "decliners": 1,
        "unchanged": 1,
        "net_advancers": 0,
        "advance_ratio": 0.3333,
        "decline_ratio": 0.3333,
        "unchanged_ratio": 0.3333,
        "limit_up_count": 0,
        "limit_down_count": 0,
        "limit_method": (
            "涨停近似口径：主板(sh60/sz00)涨跌幅≥9.8%、创业板(sz30)/"
            "科创板(sh68)≥19.8%、北交所(bj)≥29.8%计为涨停，跌停对称；"
            "阈值较交易所±10%/±20%/±30%限制留0.2个百分点余量；"
            "ST股(±5%)无法从快照字段区分，为近似统计。"
        ),
        "state": "涨跌均衡",
        "classification_method": (
            "普涨/普跌要求上涨或下跌比例至少65%，且涨跌家数净差至少500；"
            "否则只描述哪一方向家数占优。"
        ),
    }
    assert first["exchange_breakdown"]["beijing"]["unchanged"] == 1
    assert first["turnover"]["status"] == "available"
    assert first["turnover"]["total_amount_cny"] == 6_000_000
    assert first["turnover"]["amount_basis"] == {
        "raw_field": "amount",
        "raw_unit": "CNY_yuan_per_security",
        "raw_total": 6_000_000,
        "normalized_unit": "CNY_yuan",
        "normalized_total": 6_000_000,
        "display_unit": "CNY_100m_yuan",
        "display_total": 0.06,
        "scope": "all_a_shares_including_beijing",
        "market_date": first["market_date"],
        "aggregation": "sum_unique_security_turnover_v1",
    }
    assert first["turnover"]["coverage"]["exchange_sum_matches"] is True
    assert first["distribution"] == {
        "status": "available",
        "coverage": {
            "expected": 3,
            "valid_change": 3,
            "coverage_ratio": 1.0,
        },
        "median_pct_change": 0.0,
        "p25_pct_change": -0.25,
        "p75_pct_change": 0.6,
        "bins": {
            "strong_advancers_ge_3": 0,
            "mild_advancers_gt_0_lt_3": 1,
            "unchanged": 1,
            "mild_decliners_lt_0_gt_neg3": 1,
            "strong_decliners_le_neg3": 0,
        },
        "bin_ratios": {
            "strong_advancers_ge_3": 0.0,
            "mild_advancers_gt_0_lt_3": 0.3333,
            "unchanged": 0.3333,
            "mild_decliners_lt_0_gt_neg3": 0.3333,
            "strong_decliners_le_neg3": 0.0,
        },
        "bins_7": {
            "le_neg7": 0,
            "gt_neg7_le_neg3": 0,
            "gt_neg3_lt_0": 1,
            "unchanged": 1,
            "gt_0_lt_3": 1,
            "ge_3_lt_7": 0,
            "ge_7": 0,
        },
        "bins_7_method": (
            "7桶分布按涨跌幅百分数划分：≤-7、(-7,-3]、(-3,0)、=0、"
            "(0,3)、[3,7)、≥7；下跌侧左开右闭、上涨侧左闭右开，"
            "与既有±3%五桶边界风格一致，只描述当日分布，"
            "不是预测或交易阈值。"
        ),
        "method": (
            "使用全体有效个股涨跌幅的中位数与四分位数；"
            "固定±3%分档只用于描述当日分布，不是预测或交易阈值。"
        ),
    }
    assert len(database.list_market_breadth_snapshots()) == 1
    assert second["cache_hit"] is True
    with database.connect() as connection:
        stored_expiry = connection.execute(
            "SELECT expires_at FROM market_cache WHERE cache_key = ?",
            (SinaMarketBreadthProvider.CACHE_KEY,),
        ).fetchone()["expires_at"]
    assert stored_expiry == fixed_expiry


def test_sina_market_breadth_counts_limits_bins_7_and_anomaly_candidates(
    tmp_path: Path,
):
    database = Database(tmp_path / "workspaces")
    database.initialize()
    rows = [
        # 主板涨停（≥9.8），且为异动候选；name 直通。
        {
            "symbol": "sh600000",
            "name": "浦发银行",
            "changepercent": 9.85,
            "amount": 200_000_000,
            "ticktime": "15:00:00",
        },
        # -9.79 未达到主板 -9.8 跌停阈值，但 |涨跌幅| ≥7 计入异动候选。
        {
            "symbol": "sz000001",
            "changepercent": -9.79,
            "amount": 100_000_000,
            "ticktime": "15:00:00",
        },
        # 创业板跌停（≤-19.8）。
        {
            "symbol": "sz300001",
            "changepercent": -19.85,
            "amount": 50_000_000,
            "ticktime": "15:00:00",
        },
        # 科创板 19.75 未达 19.8 涨停阈值，但 |涨跌幅| ≥7 计入异动候选。
        {
            "symbol": "sh688001",
            "changepercent": 19.75,
            "amount": 80_000_000,
            "ticktime": "15:00:00",
        },
        # 北交所涨停（≥29.8）。
        {
            "symbol": "bj920001",
            "changepercent": 29.85,
            "amount": 10_000_000,
            "ticktime": "15:00:00",
        },
        {
            "symbol": "sz002001",
            "changepercent": 0,
            "amount": 60_000_000,
            "ticktime": "15:00:00",
        },
        # 5 桶 strong_decliners_le_neg3，同时落入 7 桶 (-7,-3]。
        {
            "symbol": "sh601999",
            "changepercent": -3.0,
            "amount": 40_000_000,
            "ticktime": "15:00:00",
        },
        # 7 桶 [3,7)。
        {
            "symbol": "sh603999",
            "changepercent": 3.0,
            "amount": 30_000_000,
            "ticktime": "15:00:00",
        },
    ]

    def http_get(url, **kwargs):
        if url == SinaMarketBreadthProvider.COUNT_URL:
            return FakeResponse(str(len(rows)))
        return FakeResponse(rows)

    provider = SinaMarketBreadthProvider(
        database,
        ttl_seconds=60,
        http_get=http_get,
        max_workers=2,
    )
    result = provider.fetch_breadth()

    assert result["breadth"]["limit_up_count"] == 2
    assert result["breadth"]["limit_down_count"] == 1
    assert "0.2个百分点余量" in result["breadth"]["limit_method"]
    assert result["distribution"]["bins_7"] == {
        "le_neg7": 2,
        "gt_neg7_le_neg3": 1,
        "gt_neg3_lt_0": 0,
        "unchanged": 1,
        "gt_0_lt_3": 0,
        "ge_3_lt_7": 1,
        "ge_7": 3,
    }
    assert sum(result["distribution"]["bins_7"].values()) == len(rows)
    assert result["distribution"]["bins_7_method"]
    candidates = result["anomaly_candidates"]
    assert [item["symbol"] for item in candidates] == [
        "bj920001",
        "sz300001",
        "sh688001",
        "sh600000",
        "sz000001",
    ]
    assert [item["kind"] for item in candidates] == [
        "快速拉升",
        "快速下挫",
        "快速拉升",
        "快速拉升",
        "快速下挫",
    ]
    assert candidates[0]["name"] is None
    assert candidates[3]["name"] == "浦发银行"
    assert candidates[3]["pct_change"] == 9.85
    assert candidates[3]["amount_100m_cny"] == 2.0
    assert candidates[3]["tick_time"] == "15:00:00"


def test_sina_market_breadth_infers_previous_session_before_open():
    assert (
        SinaMarketBreadthProvider._infer_market_date(
            "2026-07-21T19:31:10+00:00", "15:36:00"
        )
        == "2026-07-21"
    )
    assert (
        SinaMarketBreadthProvider._infer_market_date(
            "2026-07-22T08:00:00+00:00", "15:36:00"
        )
        == "2026-07-22"
    )
    assert (
        SinaMarketBreadthProvider._infer_market_date(
            "2026-07-18T04:00:00+00:00", "15:36:00"
        )
        == "2026-07-17"
    )


def test_sina_market_breadth_reuses_last_completed_session_for_zero_placeholder(
    tmp_path: Path,
):
    database = Database(tmp_path / "workspaces")
    database.initialize()
    provider = SinaMarketBreadthProvider(database)
    usable = provider._parse(
        [
            {
                "symbol": "sh600000",
                "changepercent": 1.2,
                "amount": 1_000_000,
                "ticktime": "15:00:00",
            },
            {
                "symbol": "sz000001",
                "changepercent": -0.5,
                "amount": 2_000_000,
                "ticktime": "15:00:01",
            },
            {
                "symbol": "bj920001",
                "changepercent": 0,
                "amount": 3_000_000,
                "ticktime": "15:30:00",
            },
        ],
        total_expected=3,
    )
    placeholder = deepcopy(usable)
    placeholder["coverage"]["latest_tick_time"] = "09:10:00"
    placeholder["breadth"].update(
        {
            "advancers": 0,
            "decliners": 0,
            "unchanged": 3,
            "net_advancers": 0,
            "advance_ratio": 0.0,
            "decline_ratio": 0.0,
            "unchanged_ratio": 1.0,
        }
    )
    placeholder["turnover"]["total_amount_cny"] = 0
    placeholder["turnover"]["total_amount_100m_cny"] = 0.0
    database.put_cache(provider.LAST_USABLE_CACHE_KEY, usable, 3600)
    database.put_cache(provider.CACHE_KEY, placeholder, 3600)

    result = provider.fetch_breadth()

    assert result["status"] == "available"
    assert result["served_as_previous_close"] is True
    assert result["breadth"]["advancers"] == 1
    assert result["breadth"]["decliners"] == 1
    assert result["turnover"]["total_amount_cny"] == 6_000_000
    cached = database.get_cache(provider.CACHE_KEY)
    assert cached["breadth"]["advancers"] == 1
    assert len(database.list_market_breadth_snapshots()) == 1


def test_sina_market_breadth_rejects_zero_placeholder_without_fallback(
    tmp_path: Path,
):
    database = Database(tmp_path / "workspaces")
    database.initialize()
    provider = SinaMarketBreadthProvider(database)
    placeholder = provider._parse(
        [
            {
                "symbol": "sh600000",
                "changepercent": 0,
                "amount": 0,
                "ticktime": "09:10:00",
            },
            {
                "symbol": "sz000001",
                "changepercent": 0,
                "amount": 0,
                "ticktime": "09:10:00",
            },
        ],
        total_expected=2,
    )
    database.put_cache(provider.CACHE_KEY, placeholder, 3600)

    result = provider.fetch_breadth()

    assert result["status"] == "unavailable"
    assert result["snapshot_mode"] == "zero_placeholder_rejected"
    assert result["breadth"] == {}
    assert database.list_market_breadth_snapshots() == []


def test_market_breadth_history_ignores_future_dated_snapshot(tmp_path: Path):
    database = Database(tmp_path / "workspaces")
    database.initialize()
    provider = SinaMarketBreadthProvider(database)

    def snapshot(
        market_date: str, amount: int, latest_tick_time: str = "15:00:00"
    ) -> dict:
        return {
            "source": "test",
            "market_date": market_date,
            "fetched_at": f"{market_date}T08:00:00+00:00",
            "status": "available",
            "scope": "all_a_shares_including_beijing",
            "coverage": {
                "expected": 2,
                "returned": 2,
                "coverage_ratio": 1.0,
                "latest_tick_time": latest_tick_time,
            },
            "breadth": {
                "total": 2,
                "advancers": 1,
                "decliners": 1,
                "unchanged": 0,
            },
            "turnover": {
                "status": "available",
                "currency": "CNY",
                "unit": "yuan",
                "total_amount_cny": amount,
                "coverage": {"coverage_ratio": 1.0},
            },
        }

    database.upsert_market_breadth_snapshot(snapshot("2026-07-20", 100))
    database.upsert_market_breadth_snapshot(snapshot("2026-07-22", 999))

    payload = provider._attach_history_comparison(snapshot("2026-07-21", 120))
    comparison = payload["turnover"]["history_comparison"]

    assert comparison["previous_market_date"] == "2026-07-20"
    assert comparison["previous_total_amount_cny"] == 100
    assert comparison["change_vs_previous_pct"] == 20.0


def test_market_breadth_history_excludes_preopen_snapshot(tmp_path: Path):
    database = Database(tmp_path / "workspaces")
    database.initialize()
    provider = SinaMarketBreadthProvider(database)

    def snapshot(market_date: str, amount: int, tick: str) -> dict:
        return {
            "source": "test",
            "market_date": market_date,
            "fetched_at": f"{market_date}T08:00:00+00:00",
            "status": "available",
            "scope": "all_a_shares_including_beijing",
            "coverage": {
                "expected": 5530,
                "returned": 5530,
                "coverage_ratio": 1.0,
                "latest_tick_time": tick,
            },
            "breadth": {
                "total": 5530,
                "advancers": 2500,
                "decliners": 2900,
                "unchanged": 130,
            },
            "turnover": {
                "status": "available",
                "currency": "CNY",
                "unit": "yuan",
                "total_amount_cny": amount,
                "coverage": {"coverage_ratio": 1.0},
            },
        }

    database.upsert_market_breadth_snapshot(
        snapshot("2026-07-23", 20_278_178_800, "09:29:31")
    )

    payload = provider._attach_history_comparison(
        snapshot("2026-07-24", 1_944_224_878_192, "15:36:00")
    )
    comparison = payload["turnover"]["history_comparison"]

    assert comparison["status"] == "building_history"
    assert comparison["change_vs_previous_pct"] is None
    assert comparison["excluded_prior_sessions"] == [
        {
            "market_date": "2026-07-23",
            "reason": "incomplete_market_session",
            "latest_tick_time": "09:29:31",
            "total_amount_cny": 20_278_178_800,
        }
    ]


def test_market_breadth_history_rejects_order_of_magnitude_jump(tmp_path: Path):
    database = Database(tmp_path / "workspaces")
    database.initialize()
    provider = SinaMarketBreadthProvider(database)

    def completed_snapshot(market_date: str, amount: int) -> dict:
        return {
            "source": "test",
            "market_date": market_date,
            "fetched_at": f"{market_date}T08:00:00+00:00",
            "status": "available",
            "scope": "all_a_shares_including_beijing",
            "coverage": {
                "expected": 5530,
                "returned": 5530,
                "coverage_ratio": 1.0,
                "latest_tick_time": "15:00:00",
            },
            "breadth": {
                "total": 5530,
                "advancers": 2500,
                "decliners": 2900,
                "unchanged": 130,
            },
            "turnover": {
                "status": "available",
                "currency": "CNY",
                "unit": "yuan",
                "total_amount_cny": amount,
                "coverage": {"coverage_ratio": 1.0},
            },
        }

    database.upsert_market_breadth_snapshot(
        completed_snapshot("2026-07-23", 20_278_178_800)
    )
    payload = provider._attach_history_comparison(
        completed_snapshot("2026-07-24", 1_944_224_878_192)
    )
    comparison = payload["turnover"]["history_comparison"]

    assert comparison["status"] == "anomaly"
    assert comparison["anomaly_reason"] == "order_of_magnitude_mismatch"
    assert comparison["change_vs_previous_pct"] is None
    assert comparison["magnitude_ratio"] > 90


def test_sina_gold_provider_aggregates_minute_prices_to_five_minute_candles(
    tmp_path: Path,
):
    database = Database(tmp_path / "workspaces")
    database.initialize()
    payload = {
        "minLine_1d": [
            [
                "2026-07-21",
                "4000.0",
                "LIFFE",
                "",
                "06:00",
                "4001.0",
                "0",
                "0",
                "4001.0",
                "2026-07-21 06:00:00",
            ],
            ["06:00", "4001.0", "0", "0", "4001.0", "2026-07-21 06:00:00"],
            ["06:01", "4003.0", "0", "0", "4002.0", "2026-07-21 06:01:00"],
            ["06:04", "3999.0", "0", "0", "4001.0", "2026-07-21 06:04:00"],
            ["06:05", "4004.0", "0", "0", "4004.0", "2026-07-21 06:05:00"],
        ]
    }
    content = f"var qingshu_xau=({__import__('json').dumps(payload)});".encode(
        "gb18030"
    )

    class GoldResponse:
        def raise_for_status(self):
            return None

        @property
        def content(self):
            return content

    provider = SinaGoldProvider(
        database, http_get=lambda *args, **kwargs: GoldResponse()
    )
    result = provider.fetch_intraday()
    assert result["previous_close"] == 4000.0
    assert result["coverage"]["interval"] == "5m"
    assert len(result["points"]) == 2
    first = result["points"][0]
    assert first["open"] == 4001.0
    assert first["high"] == 4003.0
    assert first["low"] == 3999.0
    assert first["close"] == 3999.0


def test_background_job_runs_are_persisted(tmp_path: Path):
    database = Database(tmp_path / "workspaces")
    database.initialize()
    job_id = database.start_background_job("market_intraday_refresh")
    database.finish_background_job(
        job_id,
        "completed",
        summary={"available": 5, "requested": 5},
    )
    jobs = database.latest_background_jobs()
    assert len(jobs) == 1
    assert jobs[0]["status"] == "completed"
    assert jobs[0]["summary"]["available"] == 5


def test_global_market_news_provider_parses_timed_rss_items(monkeypatch):
    xml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <rss><channel><item>
      <title>US stocks retreat as investors lock in profits - Example Wire</title>
      <link>https://news.example/item-1</link>
      <pubDate>Mon, 20 Jul 2026 20:34:54 GMT</pubDate>
      <source>Example Wire</source>
    </item></channel></rss>"""

    class Response:
        content = xml

        def raise_for_status(self):
            return None

    monkeypatch.setattr(
        "app.providers.market_news.requests.get", lambda *args, **kwargs: Response()
    )
    packet = GoogleNewsMarketProvider().fetch("us")
    assert packet["market_label"] == "美国股市"
    assert (
        packet["items"][0]["title"] == "US stocks retreat as investors lock in profits"
    )
    assert packet["items"][0]["published_at"] == "2026-07-20T20:34:54+00:00"
    assert packet["items"][0]["category"] == "market_news"


def test_market_news_is_ranked_for_the_current_question_focus():
    items = [
        {"title": "A股收盘综述"},
        {"title": "多只宽基ETF成交放量，增量资金流入"},
        {"title": "半导体板块领涨，行业轮动加快"},
    ]

    volume = _rank_for_focus(items, "volume_flows")
    sectors = _rank_for_focus(items, "sector_rotation")

    assert volume[0]["title"].startswith("多只宽基ETF")
    assert sectors[0]["title"].startswith("半导体板块")


def test_eastmoney_capital_flow_provider_merges_shanghai_and_shenzhen(
    tmp_path: Path,
):
    database = Database(tmp_path / "workspaces")
    database.initialize()
    payloads = {
        "1.000001": {
            "data": {
                "name": "上证指数",
                "klines": [
                    "2026-08-06 09:31,1982208.0,9894800.0,-11677440.0,-179341568.0,-1579254608.0",
                    "2026-08-06 09:32,-5154893728.0,2387667088.0,2774221360.0,-1579254608.0,-3575639120.0",
                ],
            }
        },
        "0.399001": {
            "data": {
                "name": "深证成指",
                "klines": [
                    "2026-08-06 09:31,-1639563264.0,1655450112.0,-15886848.0,-1137595392.0,-501971872.0",
                    "2026-08-06 09:32,-11184897312.0,9614117280.0,1570780144.0,-6910168416.0,-4274728896.0",
                ],
            }
        },
    }

    def fake_get(url, params=None, **kwargs):
        return FakeResponse(payloads[params["secid"]])

    provider = EastmoneyCapitalFlowProvider(database, http_get=fake_get)
    result = provider.fetch_intraday()

    assert result["status"] == "available"
    assert result["is_stale"] is False
    assert len(result["points"]) == 2
    assert result["points"][0]["time"] == "2026-08-06T01:31:00+00:00"
    # 09:32 沪深主力净流入合计：(−5154893728 − 11184897312) / 1e8 = −163.4 亿元
    assert result["points"][-1]["main_net_inflow_100m_cny"] == -163.4
    assert result["market_timestamp"] == "2026-08-06T01:32:00+00:00"
    summary = result["summary"]
    assert summary["main_net_inflow_100m_cny"] == -163.4
    assert summary["shanghai_100m_cny"] == -51.55
    assert summary["shenzhen_100m_cny"] == -111.85
    assert summary["unit"] == "CNY_100m_yuan"
    assert "沪深" in summary["scope"]
    assert "亿元" in result["method"]
    assert "北向" in result["method"]


def test_eastmoney_capital_flow_provider_raises_without_data_or_cache(
    tmp_path: Path,
):
    database = Database(tmp_path / "workspaces")
    database.initialize()

    def failing_get(*args, **kwargs):
        raise ConnectionError("network down")

    provider = EastmoneyCapitalFlowProvider(database, http_get=failing_get)
    try:
        provider.fetch_intraday()
    except ProviderError as exc:
        assert "大盘资金流数据不可用" in str(exc)
    else:  # pragma: no cover - 不应到达
        raise AssertionError("预期抛出 ProviderError")


def test_eastmoney_capital_flow_provider_returns_stale_cache_on_failure(
    tmp_path: Path,
):
    database = Database(tmp_path / "workspaces")
    database.initialize()
    payloads = {
        "1.000001": {
            "data": {
                "klines": [
                    "2026-08-06 09:31,1982208.0,9894800.0,-11677440.0,-179341568.0,-1579254608.0",
                ]
            }
        },
        "0.399001": {
            "data": {
                "klines": [
                    "2026-08-06 09:31,-1639563264.0,1655450112.0,-15886848.0,-1137595392.0,-501971872.0",
                ]
            }
        },
    }
    provider = EastmoneyCapitalFlowProvider(
        database,
        ttl_seconds=0,
        http_get=lambda url, params=None, **kwargs: FakeResponse(
            payloads[params["secid"]]
        ),
    )
    fresh = provider.fetch_intraday()
    assert fresh["status"] == "available"

    def failing_get(*args, **kwargs):
        raise ConnectionError("network down")

    provider.http_get = failing_get
    stale = provider.fetch_intraday()
    assert stale["status"] == "available"
    assert stale["is_stale"] is True
    assert stale["points"] == fresh["points"]
    assert any("过期缓存" in warning for warning in stale["warnings"])


def test_sina_gold_provider_parses_brent_minute_line(tmp_path: Path):
    database = Database(tmp_path / "workspaces")
    database.initialize()
    payload = {
        "minLine_1d": [
            [
                "2026-08-06",
                "79.450",
                "ice",
                "",
                "08:00",
                "79.378",
                "31",
                "0",
                "79.235",
                "2026-08-06 08:00:00",
            ],
            ["08:00", "79.378", "31", "0", "79.235", "2026-08-06 08:00:00"],
            ["08:01", "79.339", "83", "0", "79.336", "2026-08-06 08:01:00"],
            ["08:05", "79.283", "12", "0", "79.334", "2026-08-06 08:05:00"],
        ]
    }
    content = f"var qingshu_oil=({__import__('json').dumps(payload)});".encode(
        "gb18030"
    )

    class OilResponse:
        def raise_for_status(self):
            return None

        @property
        def content(self):
            return content

    provider = SinaGoldProvider(
        database, http_get=lambda *args, **kwargs: OilResponse()
    )
    result = provider.fetch_intraday("OIL")
    assert result["symbol"] == "OIL"
    assert result["display_name"] == "布伦特原油（ICE连续合约）"
    assert result["previous_close"] == 79.45
    assert result["coverage"]["interval"] == "5m"
    assert len(result["points"]) == 2
    assert result["points"][0]["close"] == 79.339
    assert result["points"][-1]["close"] == 79.283


def test_eastmoney_global_index_provider_supports_new_global_symbols():
    assert EastmoneyGlobalIndexProvider.SYMBOLS["UDI"]["secid"] == "100.UDI"
    assert EastmoneyGlobalIndexProvider.SYMBOLS["US10Y"]["secid"] == "171.US10Y"
    assert EastmoneyGlobalIndexProvider.SYMBOLS["US10Y"]["currency"] == "PCT"
