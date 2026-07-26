from __future__ import annotations

from pathlib import Path

from app.db import Database
from app.services.market_news import MarketNewsService
from app.utils import utc_now


class RecordingMarketNewsProvider:
    def __init__(self, items: list[dict] | None = None):
        self.items = items or []
        self.calls: list[tuple[str, int]] = []

    def fetch(self, market_key: str, limit: int = 12) -> dict:
        self.calls.append((market_key, limit))
        return {
            "market_key": market_key,
            "market_label": "美国股市",
            "items": self.items[:limit],
            "fetched_at": utc_now(),
        }


def _news_item(
    item_id: str,
    *,
    title: str,
    source: str,
    published_at: str,
    fetched_at: str | None = None,
) -> dict:
    return {
        "id": item_id,
        "symbol": "__MARKET_US__",
        "category": "market_news",
        "title": title,
        "summary": None,
        "source": source,
        "url": f"https://example.com/{item_id}",
        "published_at": published_at,
        "engagement": None,
        "fetched_at": fetched_at or utc_now(),
    }


def test_market_news_uses_fresh_cache_and_builds_multi_source_causal_packet(
    tmp_path: Path,
):
    database = Database(tmp_path / "workspaces")
    database.initialize()
    database.upsert_news_items(
        [
            _news_item(
                "fed-1",
                title="US stocks fall as Fed signals rates may stay high",
                source="Example Wire",
                published_at="2026-07-24T20:10:00+00:00",
            ),
            _news_item(
                "fed-2",
                title="Wall Street slips after Powell comments on interest rates",
                source="Second News",
                published_at="2026-07-24T20:20:00+00:00",
            ),
        ]
    )
    provider = RecordingMarketNewsProvider()

    packet = MarketNewsService(database, provider).get_packet(
        "美股为什么跌",
        market_key="us",
        focus_key="market_cause",
        target_market_date="2026-07-24",
    )

    assert provider.calls == []
    assert packet["refresh_attempted"] is False
    assert packet["cache"]["status"] == "fresh"
    causal = packet["causal_evidence"]
    assert causal["coverage_status"] == "same_date_multi_source"
    assert causal["source_count"] == 2
    assert causal["same_date_candidate_count"] == 2
    assert causal["corroborated_categories"] == [
        {
            "category": "monetary_policy",
            "category_label": "货币政策与央行表态",
            "same_date_sources": 2,
        }
    ]
    assert all(
        item["support_level"] == "same_date_multi_source"
        for item in causal["candidates"]
    )


def test_market_news_force_refresh_replaces_empty_cache(tmp_path: Path):
    database = Database(tmp_path / "workspaces")
    database.initialize()
    provider = RecordingMarketNewsProvider(
        [
            _news_item(
                "macro-1",
                title="Stocks retreat after inflation data",
                source="Example Wire",
                published_at="2026-07-24T19:00:00+00:00",
            )
        ]
    )

    packet = MarketNewsService(database, provider).get_packet(
        "美股为什么跌",
        market_key="us",
        focus_key="market_cause",
        target_market_date="2026-07-24",
        force_refresh=True,
    )

    assert provider.calls == [("us", 20)]
    assert packet["refreshed"] is True
    assert packet["coverage"]["available"] == 1
    assert packet["causal_evidence"]["coverage_status"] == ("same_date_single_source")
    assert packet["causal_evidence"]["candidates"][0]["category_label"] == ("宏观数据")


def test_market_news_marks_cross_date_items_as_neighboring_leads(tmp_path: Path):
    database = Database(tmp_path / "workspaces")
    database.initialize()
    database.upsert_news_items(
        [
            _news_item(
                "older-1",
                title="Treasury yields rise before the next session",
                source="Example Wire",
                published_at="2026-07-23T20:10:00+00:00",
            )
        ]
    )

    packet = MarketNewsService(database, RecordingMarketNewsProvider()).get_packet(
        "美股为什么跌",
        market_key="us",
        focus_key="market_cause",
        target_market_date="2026-07-24",
    )

    causal = packet["causal_evidence"]
    assert causal["coverage_status"] == "near_date_only"
    assert causal["same_date_candidate_count"] == 0
    assert causal["candidates"][0]["date_relation"] == "adjacent_date"
    assert "不能据此宣称唯一原因" in causal["boundary"]


def test_market_news_recovers_target_session_beyond_latest_thirty_rows(
    tmp_path: Path,
):
    database = Database(tmp_path / "workspaces")
    database.initialize()
    newer = [
        _news_item(
            f"newer-{index}",
            title=f"Latest market update {index}",
            source=f"Newer Source {index}",
            published_at=f"2026-07-24T{20 + index % 3:02d}:{index % 60:02d}:00+00:00",
        )
        for index in range(40)
    ]
    target = [
        _news_item(
            "target-tech-1",
            title="Tech stocks tumble as oil tops $100 and spending worries rise",
            source="Target Wire",
            published_at="2026-07-23T20:10:00+00:00",
        ),
        _news_item(
            "target-tech-2",
            title="Nasdaq falls as mega-cap AI spending fears pressure technology shares",
            source="Second Target News",
            published_at="2026-07-23T20:20:00+00:00",
        ),
    ]
    database.upsert_news_items([*newer, *target])

    packet = MarketNewsService(database, RecordingMarketNewsProvider()).get_packet(
        "美股为什么跌",
        market_key="us",
        focus_key="market_cause",
        target_market_date="2026-07-23",
    )

    assert packet["selection"] == {
        "stored_considered": 42,
        "target_market_date": "2026-07-23",
        "same_date_available": 2,
        "strategy": "target_market_date_then_question_focus",
    }
    assert {item["id"] for item in packet["items"][:2]} == {
        "target-tech-1",
        "target-tech-2",
    }
    causal = packet["causal_evidence"]
    assert causal["coverage_status"] == "same_date_multi_source"
    assert causal["same_date_candidate_count"] == 2
    assert causal["corroborated_categories"] == [
        {
            "category": "technology_sector",
            "category_label": "科技与行业事件",
            "same_date_sources": 2,
        }
    ]
