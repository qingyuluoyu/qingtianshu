from __future__ import annotations

from dataclasses import replace

from app.providers.market import ProviderError
from app.services.stock_intelligence import StockIntelligenceService


def test_stock_external_searches_use_current_stock_keyword(client):
    response = client.get(
        "/api/v1/stocks/news",
        params={"symbol": "300750.SZ"},
    )

    assert response.status_code == 200
    packet = response.json()
    assert len(packet["items"]) == 7
    assert {item["source"] for item in packet["items"]} == {
        "巨潮资讯",
        "东方财富",
        "同花顺",
        "财联社",
        "雪球",
        "理杏仁",
        "新浪财经",
    }
    assert all("300750" in item["url"] for item in packet["items"])


def test_curated_insights_explain_missing_tavily_key(client, app, monkeypatch):
    monkeypatch.setattr(
        app.state.stock_intelligence.fallback_search,
        "search",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            ProviderError("fallback unavailable")
        ),
    )
    response = client.get(
        "/api/v1/stocks/curated-insights",
        params={"symbol": "300750.SZ"},
    )

    assert response.status_code == 200
    packet = response.json()
    assert packet["status"] == "not_configured"
    assert packet["items"] == []
    assert packet["refreshIntervalDays"] == 3
    assert "Tavily API Key 未配置" in packet["warning"]


def test_curated_insights_select_only_five_and_reuse_three_day_cache(
    app, settings, monkeypatch
):
    configured = replace(
        settings,
        tavily_enabled=True,
        tavily_api_key="tvly-test-only",
        llm_gateway_enabled=True,
        llm_gateway_api_key="llm-test-only",
    )
    service = StockIntelligenceService(
        app.state.database,
        lambda symbol: {
            "symbol": "002624.SZ",
            "name": "完美世界",
            "industry": "游戏",
        },
        configured,
    )
    calls = {"search": 0}
    search_results = [
        {
            "title": f"游戏行业信息 {index}",
            "url": f"https://example.com/news/{index}",
            "content": f"第 {index} 条行业经营信息",
            "score": 1 - index * 0.03,
            "published_date": "2026-07-24",
            "source_domain": "example.com",
        }
        for index in range(8)
    ]

    def fake_search(**_):
        calls["search"] += 1
        return {
            "status": "completed",
            "query": "游戏行业",
            "searched_at": "2026-07-24T00:00:00+00:00",
            "results": search_results,
            "warning": None,
        }

    monkeypatch.setattr(service.search, "safe_search_target", fake_search)
    monkeypatch.setattr(
        service.gateway,
        "complete",
        lambda **_: (
            '{"items":['
            '{"source_index":3,"type":"供需","title":"需求变化","summary":"关注用户需求变化"},'
            '{"source_index":1,"type":"政策","title":"政策变化","summary":"关注政策边际变化"}'
            "]}",
            {},
        ),
    )

    first = service.curated_insights("002624.SZ")
    second = service.curated_insights("002624.SZ")

    assert len(first["items"]) == 5
    assert first["selectionMethod"] == "llm"
    assert first["items"][0]["title"] == "需求变化"
    assert second["cache"]["state"] == "hit"
    assert calls["search"] == 1


def test_curated_insights_use_rss_fallback_without_tavily_key(
    app, settings, monkeypatch
):
    configured = replace(
        settings,
        tavily_enabled=False,
        tavily_api_key="",
        llm_gateway_enabled=True,
        llm_gateway_api_key="llm-test-only",
    )
    service = StockIntelligenceService(
        app.state.database,
        lambda symbol: {
            "symbol": "002624.SZ",
            "name": "完美世界",
            "industry": "游戏",
        },
        configured,
    )
    monkeypatch.setattr(
        service.fallback_search,
        "search",
        lambda *args, **kwargs: {
            "query": "游戏行业",
            "fetched_at": "2026-07-24T00:00:00+00:00",
            "items": [
                {
                    "title": f"游戏行业资讯 {index}",
                    "url": f"https://news.example/{index}",
                    "source": "测试媒体",
                    "published_at": "2026-07-24T00:00:00+00:00",
                }
                for index in range(7)
            ],
        },
    )
    monkeypatch.setattr(
        service.gateway,
        "complete",
        lambda **_: (
            '{"items":[{"source_index":0,"type":"行业",'
            '"title":"重点变化","summary":"值得跟踪"}]}',
            {},
        ),
    )

    packet = service.curated_insights("002624.SZ", force=True)

    assert packet["status"] == "completed"
    assert packet["search"]["provider"] == "google_news_rss"
    assert len(packet["items"]) == 5
