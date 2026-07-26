from __future__ import annotations

import app.services.agent as agent_module
from app.services.agent import AgentService
from app.services.agent_evidence_compaction import (
    compact_market_brief_evidence,
    compact_market_conversation_history,
    compact_stock_knowledge_context,
    evidence_for_prompt,
)


def test_market_compaction_preserves_explicit_session_alignment() -> None:
    compact = compact_market_brief_evidence(
        {
            "type": "market_brief",
            "user_question": "美股为什么收盘跌了",
            "analysis_target": {
                "market_date": "2025-04-09",
                "market_key": "us",
            },
            "question_focus": {"key": "market_cause"},
            "market_drivers": {
                "market_key": "us",
                "question_focus": "market_cause",
            },
            "indices": [
                {
                    "symbol": "^GSPC",
                    "name": "标普500",
                    "group": "us",
                    "market_date": "2025-04-09",
                    "market_timestamp": "2025-04-10T00:00:00+00:00",
                    "same_date_as_analysis_target": True,
                    "coverage": {"interval": "1d"},
                    "metrics": {"return_1d_pct": 0.313},
                }
            ],
        }
    )

    assert compact["indices"] == [
        {
            "symbol": "^GSPC",
            "name": "标普500",
            "same_date_as_analysis_target": True,
            "market_date": "2025-04-09",
            "metrics": {"return_1d_pct": 0.313},
        }
    ]


def test_agent_service_delegates_market_compaction_to_pure_module(
    monkeypatch,
) -> None:
    evidence = {"type": "market_brief"}
    captured = {}

    def fake_compact(value):
        captured["evidence"] = value
        return {"delegated": True}

    monkeypatch.setattr(agent_module, "compact_market_brief_evidence", fake_compact)

    assert AgentService._compact_market_brief_evidence(evidence) == {"delegated": True}
    assert captured["evidence"] is evidence


def test_public_prompt_evidence_removes_private_fields_recursively() -> None:
    evidence = {
        "type": "market_brief",
        "source": "private-provider",
        "nested": {
            "url": "https://internal.example",
            "value": 3,
            "rows": [
                {"provider": "private", "label": "公开事实"},
            ],
        },
    }

    assert evidence_for_prompt(evidence) == {
        "type": "market_brief",
        "nested": {
            "value": 3,
            "rows": [{"label": "公开事实"}],
        },
    }


def test_market_history_keeps_only_recent_user_questions() -> None:
    history = [
        {"role": "user", "content": f"问题{i}"}
        if i % 2 == 0
        else {"role": "assistant", "content": f"旧回答{i}"}
        for i in range(12)
    ]

    assert compact_market_conversation_history(history) == [
        {"role": "user", "content": "问题4"},
        {"role": "user", "content": "问题6"},
        {"role": "user", "content": "问题8"},
        {"role": "user", "content": "问题10"},
    ]


def test_agent_service_delegates_stock_research_compaction(
    monkeypatch,
) -> None:
    evidence = {"type": "stock_research", "symbol": "000063.SZ"}
    captured = {}

    def fake_compact(value):
        captured["evidence"] = value
        return {"symbol": "000063.SZ", "delegated": True}

    monkeypatch.setattr(agent_module, "compact_stock_research_evidence", fake_compact)

    assert AgentService._compact_stock_research_evidence(evidence) == {
        "symbol": "000063.SZ",
        "delegated": True,
    }
    assert captured["evidence"] is evidence


def test_stock_knowledge_prioritizes_user_material_and_caps_excerpts() -> None:
    context = {
        "query": "中兴通讯",
        "items": [
            {"title": "通用资料一", "scope": "common", "excerpt": "甲" * 600},
            {"title": "用户资料", "scope": "user", "excerpt": "乙" * 600},
            {"title": "通用资料二", "scope": "common", "excerpt": "丙" * 600},
            {"title": "通用资料三", "scope": "common", "excerpt": "丁" * 600},
        ],
    }

    compact = compact_stock_knowledge_context(context)

    assert [item["title"] for item in compact["items"]] == [
        "用户资料",
        "通用资料一",
        "通用资料二",
    ]
    assert all(len(item["excerpt"]) == 500 for item in compact["items"])
