from __future__ import annotations

from types import SimpleNamespace

from app.services.advisor_lab import AdvisorLabPolicy, build_advisor_lab_snapshot


def _prepared() -> SimpleNamespace:
    return SimpleNamespace(
        conversation_id="conversation-1",
        history=[
            {
                "id": "message-1",
                "role": "user",
                "content": "请分析中兴通讯的短期风险。",
            }
        ],
        symbols=["000063.SZ"],
        symbol="000063.SZ",
        prior_intent="stock_research",
        contextual_followup=True,
        stock_context_followup=True,
        model_tier="economy",
        knowledge_context={
            "items": [
                {
                    "document_id": "doc-1",
                    "title": "公司公告摘要",
                    "source_key": "filing",
                    "content": "可展示的资料摘要",
                    "workspace_path": "C:/private/path",
                    "api_key": "must-not-leak",
                }
            ],
            "coverage": {"status": "covered"},
        },
    )


def test_snapshot_whitelists_context_and_redacts_internal_values() -> None:
    snapshot = build_advisor_lab_snapshot(
        prepared=_prepared(),
        intent="stock_research",
        evidence={
            "type": "stock_research",
            "market_date": "2026-08-03",
            "api_key": "must-not-leak",
            "prompt": "must-not-leak",
            "sources": [{"title": "公开公告", "published_at": "2026-08-02"}],
        },
        policy_events=[],
        run={"id": "run-1", "status": "completed", "usage": {"tokens": 12}},
    )

    assert snapshot["snapshot_version"] == "advisor_lab_context_v1"
    assert snapshot["routing"]["symbol"] == "000063.SZ"
    assert snapshot["actual_context"]["conversation_history"][0]["content"] == (
        "请分析中兴通讯的短期风险。"
    )
    assert snapshot["actual_context"]["knowledge_items"][0]["title"] == "公司公告摘要"
    assert snapshot["execution"] == {
        "run_id": "run-1",
        "status": "completed",
        "usage": {"tokens": 12},
    }
    assert "api_key" not in repr(snapshot)
    assert "workspace_path" not in repr(snapshot)
    assert "must-not-leak" not in repr(snapshot)


def test_policy_blocks_business_write_operations() -> None:
    assert AdvisorLabPolicy.blocked_operation("把 000063 加入自选")
    assert AdvisorLabPolicy.blocked_operation("请记住我持有 000063")
    assert AdvisorLabPolicy.blocked_operation("生成一份研究报告")
    assert AdvisorLabPolicy.blocked_operation("确认写回研究结论")
    assert AdvisorLabPolicy.blocked_operation("创建一个买入操作")
    assert AdvisorLabPolicy.blocked_operation("今天市场怎么样") is None
