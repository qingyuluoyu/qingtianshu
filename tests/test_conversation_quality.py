from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.db import Database
from app.services.conversation_quality import ConversationQualityService


def _create_run(
    database: Database,
    user: dict,
    *,
    intent: str = "market_brief",
    status: str = "completed",
    answer: str = "这是基于当前证据形成的针对性回答。",
    evidence: dict | None = None,
    usage: dict | None = None,
    seconds: int = 1,
    conversation_id: str | None = None,
) -> dict:
    run = database.create_run(
        user["id"],
        intent,
        "economy",
        {
            "message": "今天A股是什么行情？",
            "conversation_id": conversation_id,
        },
        Path(user["workspace_path"]),
    )
    database.finish_run(
        run["id"],
        user["id"],
        status,
        evidence or {},
        answer,
        usage=usage,
        error="测试降级" if status in {"guarded", "degraded", "failed"} else None,
    )
    finished = datetime.now(timezone.utc)
    started = finished - timedelta(seconds=seconds)
    with database.connect() as connection:
        connection.execute(
            "UPDATE runs SET created_at = ?, finished_at = ? WHERE id = ?",
            (started.isoformat(), finished.isoformat(), run["id"]),
        )
    return database.get_run(run["id"], user["id"])


def test_conversation_quality_detects_runtime_and_repeated_answer_issues(settings):
    database = Database(settings.database_path, settings.workspace_root)
    database.initialize()
    user = database.create_user("Quality User")
    conversation = database.create_conversation(user["id"], "行情复盘")
    repeated_answer = (
        "结论：当前更接近结构性行情。证据包括上涨下跌家数、成交额与个股涨跌幅分布；"
        "反方证据是指数强弱并不等于多数个股表现，仍需继续核对行业贡献与消息来源。"
        "这只解释当前市场截面，不把成交额写成资金净流入，也不据此预测下一交易日涨跌；"
        "后续应补齐指数成分贡献度，并持续观察同口径历史变化。"
    )
    first = _create_run(
        database,
        user,
        status="guarded",
        answer=repeated_answer,
        usage={
            "output_guard": {"repair": {"method": "drop_lines"}},
            "timings": {
                "routing_and_evidence_seconds": 2.0,
                "agent_setup_seconds": 0.5,
                "model_seconds": 30.0,
                "guard_seconds": 2.5,
                "request_total_seconds": 35.0,
                "first_token_seconds": 1.2,
                "first_visible_seconds": 2.4,
            },
        },
        seconds=35,
    )
    second = _create_run(
        database,
        user,
        answer=repeated_answer,
        usage={
            "timings": {
                "routing_and_evidence_seconds": 0.5,
                "agent_setup_seconds": 0.2,
                "model_seconds": 1.0,
                "guard_seconds": 0.3,
                "request_total_seconds": 2.0,
                "first_token_seconds": 0.4,
                "first_visible_seconds": 0.8,
            }
        },
        seconds=2,
    )
    for run in (first, second):
        database.add_conversation_message(
            user["id"],
            conversation["id"],
            "assistant",
            repeated_answer,
            intent="market_brief",
            run_id=run["id"],
        )

    payload = ConversationQualityService(database).analyze(user["id"])

    issue_keys = {item["key"] for item in payload["issues"]}
    assert {"run_fallbacks", "guard_repairs", "slow_answers", "repeated_answers"} <= issue_keys
    assert payload["summary"]["runs"] == 2
    assert payload["summary"]["conversations"] == 1
    assert payload["summary"]["quality_score"] is None
    assert payload["summary"]["diagnostic_score"] < 100
    assert payload["summary"]["quality_score_status"] == "insufficient_sample"
    assert payload["summary"]["timing_samples"] == 2
    assert payload["latency"]["p50_seconds"]["model_seconds"] == 15.5
    assert payload["latency"]["p50_seconds"]["request_total_seconds"] == 18.5
    assert payload["latency"]["p50_seconds"]["first_token_seconds"] == 0.8
    assert payload["latency"]["p50_seconds"]["first_visible_seconds"] == 1.6
    slow_issue = next(item for item in payload["issues"] if item["key"] == "slow_answers")
    assert "网页已反馈取证、生成、守卫和保存阶段" in slow_issue["detail"]
    assert "正文增量展示" in slow_issue["detail"]
    assert "首个安全可见片段" in slow_issue["next_step"]
    assert "首个模型片段" in payload["latency"]["boundary"]


def test_rendered_source_metadata_prevents_false_missing_reference_issue(settings):
    database = Database(settings.database_path, settings.workspace_root)
    database.initialize()
    user = database.create_user("Referenced User")
    conversation = database.create_conversation(user["id"], "有引用的研究")
    evidence = {
        "knowledge_context": {
            "items": [{"title": "市场因果证据规则", "scope": "common"}]
        }
    }
    run = _create_run(database, user, evidence=evidence)
    database.add_conversation_message(
        user["id"],
        conversation["id"],
        "assistant",
        run["answer"],
        intent="market_brief",
        run_id=run["id"],
        metadata={
            "knowledge_sources": [
                {"title": "市场因果证据规则", "scope": "common"}
            ]
        },
    )

    payload = ConversationQualityService(database).analyze(user["id"])

    assert "missing_visible_references" not in {
        item["key"] for item in payload["issues"]
    }


def test_conversation_quality_persists_snapshot_and_workspace_json(settings):
    database = Database(settings.database_path, settings.workspace_root)
    database.initialize()
    user = database.create_user("Persistence User")

    payload = ConversationQualityService(database).analyze(user["id"])

    snapshot = database.latest_conversation_quality_snapshot(user["id"])
    output_path = (
        Path(user["workspace_path"])
        / "quality"
        / "conversation-review-latest.json"
    )
    assert snapshot is not None
    assert snapshot["payload"]["method"] == payload["method"]
    assert output_path.is_file()
    assert '"deterministic_conversation_quality_review_v3"' in output_path.read_text()


def test_conversation_quality_excludes_explicit_evaluation_scope(settings):
    database = Database(settings.database_path, settings.workspace_root)
    database.initialize()
    user = database.create_user("Evaluation Isolation User")
    user_conversation = database.create_conversation(user["id"], "正常研究")
    evaluation_conversation = database.create_conversation(
        user["id"], "开发验收", quality_scope="evaluation"
    )
    user_run = _create_run(
        database,
        user,
        conversation_id=user_conversation["id"],
    )
    evaluation_run = _create_run(
        database,
        user,
        status="guarded",
        seconds=35,
        conversation_id=evaluation_conversation["id"],
    )
    for conversation, run in (
        (user_conversation, user_run),
        (evaluation_conversation, evaluation_run),
    ):
        database.add_conversation_message(
            user["id"],
            conversation["id"],
            "assistant",
            run["answer"],
            intent="market_brief",
            run_id=run["id"],
        )

    payload = ConversationQualityService(database).analyze(user["id"])

    assert payload["summary"]["conversations"] == 1
    assert payload["summary"]["runs"] == 1
    assert payload["summary"]["excluded_evaluation_conversations"] == 1
    assert payload["summary"]["excluded_evaluation_messages"] == 1
    assert payload["summary"]["excluded_evaluation_runs"] == 1
    assert payload["evaluation"]["summary"]["runs"] == 1
    assert payload["evaluation"]["summary"]["run_statuses"]["guarded"] == 1
    assert "evaluation_fallbacks" in {
        item["key"] for item in payload["evaluation"]["issues"]
    }
    assert "run_fallbacks" not in {item["key"] for item in payload["issues"]}
    assert "slow_answers" not in {item["key"] for item in payload["issues"]}


def test_available_market_statistics_are_not_misclassified_as_data_gaps(settings):
    database = Database(settings.database_path, settings.workspace_root)
    database.initialize()
    user = database.create_user("Data Gap User")
    conversation = database.create_conversation(user["id"], "数据口径")
    database.add_conversation_message(
        user["id"],
        conversation["id"],
        "assistant",
        (
            "全市场成交额为29734.49亿元。个股涨跌幅分布的中位数为0.59%，"
            "当前仍缺少指数成分贡献度。"
        ),
    )

    payload = ConversationQualityService(database).analyze(user["id"])

    needs = {item["key"] for item in payload["data_needs"]}
    assert "market_turnover" not in needs
    assert "market_distribution" not in needs
    assert "index_contribution" in needs
