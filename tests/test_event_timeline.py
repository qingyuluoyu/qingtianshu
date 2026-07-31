from __future__ import annotations

from pathlib import Path

from app.db import Database
from app.services.event_timeline import EventTimelineService


def _item(
    *,
    category: str,
    title: str,
    published_at: str,
    suffix: str,
    summary: str | None = None,
) -> dict:
    return {
        "symbol": "000063.SZ",
        "category": category,
        "title": title,
        "summary": summary,
        "source": "test",
        "url": f"https://example.invalid/{suffix}",
        "published_at": published_at,
        "engagement": None,
        "fetched_at": "2026-07-21T09:00:00+00:00",
    }


def test_event_timeline_classifies_persists_and_indexes_knowledge(tmp_path: Path):
    database = Database(tmp_path / "workspaces")
    database.initialize()
    database.upsert_news_items(
        [
            _item(
                category="announcement",
                title="关于回购公司股份的进展公告",
                published_at="2026-07-20T10:00:00+08:00",
                suffix="buyback",
                summary="公司公告原文摘录：截至公告日，公司已回购股份120万股。",
            ),
            _item(
                category="announcement",
                title="关于收到监管处罚决定的公告",
                published_at="2026-07-19T10:00:00+08:00",
                suffix="penalty",
            ),
            _item(
                category="news",
                title="公司发布新产品并披露产能计划",
                published_at="2026-07-18T10:00:00+08:00",
                suffix="product",
            ),
            _item(
                category="news",
                title="公司已完成本次回购股份实施",
                published_at="2026-07-20T11:00:00+08:00",
                suffix="buyback-news",
            ),
            _item(
                category="social",
                title="明天必涨",
                published_at="2026-07-18T11:00:00+08:00",
                suffix="social",
            ),
        ]
    )

    packet = EventTimelineService(database).get_packet("000063", refresh_sources=False)

    assert packet["status"] == "available"
    assert packet["coverage"] == {
        "stored_items_scanned": 4,
        "events_returned": 3,
        "official_events": 2,
        "media_events": 1,
        "risk_events": 1,
        "supportive_events": 1,
        "event_types": 3,
        "direct_excerpt_events": 1,
    }
    assert packet["supportive_events"][0]["event_type"] == "capital_return"
    assert packet["supportive_events"][0]["direct_excerpt"] == (
        "截至公告日，公司已回购股份120万股。"
    )
    assert packet["risk_events"][0]["event_type"] == "regulatory_legal"
    assert all("必涨" not in item["title"] for item in packet["events"])
    assert database.latest_event_timeline_snapshot("000063.SZ") is not None
    documents = database.list_knowledge_documents(None, include_content=True)
    document = next(
        item for item in documents if item["source_key"] == "event-timeline:000063.SZ"
    )
    assert document["title"] == "中兴通讯重要事件脉络"
    assert "公司已回购股份120万股" in document["content"]


def test_event_timeline_reserves_space_for_official_disclosures(tmp_path: Path):
    database = Database(tmp_path / "workspaces")
    database.initialize()
    newer_media = [
        _item(
            category="news",
            title=f"公司发布新产品进展{i}",
            published_at=f"2026-07-28T{23 - (i % 20):02d}:00:00+08:00",
            suffix=f"media-{i}",
        )
        for i in range(45)
    ]
    older_official = [
        _item(
            category="announcement",
            title=f"关于第{i}项重大合同的公告",
            published_at=f"2026-07-{20 - i:02d}T18:00:00+08:00",
            suffix=f"official-{i}",
            summary=f"公司公告原文摘录：第{i}项合同仍在正常履行。",
        )
        for i in range(3)
    ]
    database.upsert_news_items([*newer_media, *older_official])

    packet = EventTimelineService(database).get_packet(
        "000063.SZ", refresh_sources=False
    )

    official = [
        item
        for item in packet["events"]
        if item["evidence_level"] == "official_disclosure"
    ]
    assert len(packet["events"]) == 31
    assert len(official) == 3
    assert all(item.get("direct_excerpt") for item in official)


def test_event_timeline_api_chat_and_followup_keep_symbol_context(client):
    user = client.post("/users", json={"name": "Event Timeline User"}).json()
    api_response = client.get("/stocks/000063/event-timeline")

    assert api_response.status_code == 200
    assert api_response.json()["type"] == "event_timeline"

    first = client.post(
        f"/users/{user['id']}/chat",
        json={"message": "中兴通讯最近有什么重要事件和风险？"},
    )
    assert first.status_code == 200
    first_payload = first.json()
    assert first_payload["intent"] == "event_timeline"
    assert first_payload["evidence"]["symbol"] == "000063.SZ"
    assert "事件脉络" in first_payload["answer"]

    followup = client.post(
        f"/users/{user['id']}/chat",
        json={
            "message": "那哪些需要阅读原文复核？",
            "conversation_id": first_payload["conversation_id"],
        },
    )
    assert followup.status_code == 200
    followup_payload = followup.json()
    assert followup_payload["intent"] == "event_timeline"
    assert followup_payload["evidence"]["symbol"] == "000063.SZ"


def test_stock_research_packet_includes_persisted_event_timeline(app):
    user = app.state.database.create_user("Event Research User")

    evidence = app.state.research_evidence.build(user["id"], "000063.SZ")

    assert evidence["event_timeline"]["status"] == "available"
    news_module = next(
        item for item in evidence["analysis_board"]["modules"] if item["key"] == "news"
    )
    assert news_module["status"] == "ready"
    assert "事件脉络" in news_module["label"]
