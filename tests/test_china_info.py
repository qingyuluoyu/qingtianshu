from __future__ import annotations

import json
from pathlib import Path

from app.db import Database
from app.providers.china_info import AShareInformationProvider
from app.services.china_info import score_social_sentiment


class FakeResponse:
    def __init__(self, *, payload=None, content: bytes = b"", text: str | None = None):
        self._payload = payload
        self.content = content
        self.text = text if text is not None else content.decode("utf-8", errors="replace")

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_a_share_provider_parses_announcements_news_and_social_posts():
    announcement_payload = {
        "data": {
            "list": [
                {
                    "art_code": "AN1",
                    "title": "贵州茅台:重大事项公告",
                    "display_time": "2026-07-20 20:00:00:000",
                }
            ]
        }
    }
    sina_html = """
    <div class="datelist"><ul>
    &nbsp;2026-07-20&nbsp;19:30&nbsp;<a target='_blank' href='https://example.com/news1'>飞天茅台提价</a><br>
    &nbsp;2026-07-20&nbsp;19:20&nbsp;<a target='_blank' href='https://example.com/news2'>某基金季度报告与市场观点</a><br>
    &nbsp;2026-07-20&nbsp;19:10&nbsp;<a target='_blank' href='https://example.com/news3'>贵州茅台目标价上调丨券商评级观察</a><br>
    </ul></div>
    """.encode("gb18030")
    guba_payload = {
        "re": [
            {
                "post_id": 1,
                "stockbar_code": "600519",
                "post_title": "提价利好，继续看多",
                "post_click_count": 100,
                "post_comment_count": 10,
                "post_publish_time": "2026-07-20 19:40:00",
            }
        ]
    }

    def http_get(url, **kwargs):
        if "anotice" in url:
            return FakeResponse(payload=announcement_payload)
        if "AllNewsStock" in url:
            return FakeResponse(content=sina_html)
        return FakeResponse(text=f"<script>var article_list={json.dumps(guba_payload)};</script>")

    provider = AShareInformationProvider(http_get=http_get)
    announcements = provider.fetch_announcements("600519.SS")
    news = provider.fetch_company_news("600519.SS")
    social = provider.fetch_guba_posts("600519.SS")
    assert announcements[0]["title"] == "贵州茅台:重大事项公告"
    assert len(news) == 1
    assert news[0]["title"] == "飞天茅台提价"
    assert social[0]["engagement"] == 150.0


def test_sentiment_is_transparent_and_persisted(tmp_path: Path):
    posts = [
        {"title": "回购利好，继续看多", "engagement": 100},
        {"title": "风险加大，准备看空", "engagement": 10},
        {"title": "今天成交量怎么样", "engagement": 1},
    ]
    snapshot = score_social_sentiment("600519.SS", posts)
    assert snapshot["sample_size"] == 3
    assert snapshot["positive_count"] == 1
    assert snapshot["negative_count"] == 1
    assert "不能单独用于价格预测" in snapshot["evidence"]["caveat"]

    database = Database(tmp_path / "db.sqlite", tmp_path / "workspaces")
    database.initialize()
    saved = database.save_sentiment_snapshot(snapshot)
    assert saved["method"] == "keyword_engagement_weighted_v1"
    assert saved["evidence"]["neutral_weight"] > 0


def test_news_upsert_accepts_source_name_change_for_stable_item_id(tmp_path: Path):
    database = Database(tmp_path / "db.sqlite", tmp_path / "workspaces")
    database.initialize()
    original = {
        "id": "stable-market-news-id",
        "symbol": "__MARKET_GOLD__",
        "category": "market_news",
        "title": "Gold market update",
        "summary": None,
        "source": "SMM Metal",
        "url": "https://example.com/gold-update",
        "published_at": "2026-07-21T08:00:00+00:00",
        "fetched_at": "2026-07-21T08:01:00+00:00",
    }
    renamed_source = {
        **original,
        "source": "Shanghai Metals Market",
        "fetched_at": "2026-07-21T08:02:00+00:00",
    }

    database.upsert_news_items([original])
    database.upsert_news_items([renamed_source])

    stored = database.list_news(
        symbol="__MARKET_GOLD__", categories=("market_news",)
    )
    assert len(stored) == 1
    assert stored[0]["id"] == "stable-market-news-id"
    assert stored[0]["source"] == "Shanghai Metals Market"
