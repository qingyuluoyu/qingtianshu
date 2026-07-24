from __future__ import annotations

from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient

from app.db import Database


def _create_user(client: TestClient, name: str) -> dict:
    response = client.post("/users", json={"name": name})
    assert response.status_code == 201
    return response.json()


def _add_stock(client: TestClient, thesis: str) -> None:
    response = client.post(
        "/me/watchlist",
        json={
            "symbol": "000063",
            "name": "中兴通讯",
            "market": "A股",
            "thesis": thesis,
        },
    )
    assert response.status_code == 200


def _evidence() -> dict:
    return {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "display_name": "中兴通讯",
        "generated_at": "2026-07-23T10:00:00+08:00",
        "provenance": {
            "market_timestamp": "2026-07-22T15:00:00+08:00",
            "source": "历史日线源",
            "source_url": "https://example.invalid/daily",
        },
        "fundamentals": {
            "generated_at": "2026-07-23T09:00:00+08:00",
            "summary": {
                "latest_report": {
                    "report_date": "2026-03-31",
                    "announcement_date": "2026-04-25",
                    "source": "结构化财务源",
                    "source_url": "https://example.invalid/report",
                }
            },
        },
        "evidence_debate": {
            "bull_case": [
                {
                    "claim": "近20日价格动量仍为正",
                    "evidence": "20日收益为 8.0%",
                    "source": "deterministic_price_metrics",
                }
            ],
            "bear_case": [
                {
                    "claim": "最新报告期利润同比承压",
                    "evidence": "2026年一季度净利润同比下降 12.0%",
                    "source": "structured_fundamentals",
                    "action": "核对下一报告期利润与经营现金流是否同步改善。",
                }
            ],
            "risk_committee": [
                {
                    "risk": "订单兑现仍缺少可交叉核验的数据",
                    "evidence": "当前证据包没有订单分产品兑现明细",
                    "source": "research_frame",
                    "action": "阅读下一期公告并核验订单兑现口径。",
                }
            ],
        },
        "research_frame": {
            "missing_information": ["补齐下一报告期经营现金流数据"]
        },
        "conditional_outlook": {
            "invalidation": "价格与经营现金流同时跌破当前研究假设时重新判断。",
            "scenarios": [
                {
                    "name": "下行风险",
                    "condition": "收盘跌破关键参考位且经营现金流继续恶化",
                    "meaning": "原判断需要失效处理并重新核验证据。",
                }
            ],
        },
    }


def _run(
    app,
    user_id: str,
    status: str,
    message: str,
    evidence: dict,
    *,
    intent: str = "stock_research",
) -> dict:
    database = app.state.database
    run = database.create_run(
        user_id,
        intent,
        "economy",
        {"message": message},
        app.state.settings.workspace_root,
    )
    database.finish_run(
        run["id"],
        user_id,
        status,
        evidence,
        "当前证据支持继续研究，但利润承压且订单兑现仍需核验。",
        {"prompt_tokens": 1, "completion_tokens": 1},
    )
    return database.get_run(run["id"], user_id)


def test_structured_answer_persists_public_citations_and_requires_completed_run(app):
    client = TestClient(app)
    user = _create_user(client, "Structured AI Evidence")
    _add_stock(client, "原判断：关注订单、利润和经营现金流")
    conversation = app.state.database.create_conversation(user["id"], "结构化研究")
    evidence = _evidence()
    message = "分析中兴通讯并形成判断草稿，供我确认，不要直接修改正式判断。"

    preview = _run(app, user["id"], "preview", message, evidence)
    partial = app.state.structured_ai.build_and_persist(
        user_id=user["id"],
        run=preview,
        evidence=evidence,
        answer=preview["answer"],
        message=message,
        conversation_id=conversation["id"],
        symbol="000063.SZ",
    )

    assert partial["status"] == "partial"
    assert partial["candidate_writebacks"] == []
    assert partial["confirmed_facts"]
    assert partial["evidence_based_inferences"][0][
        "supporting_citation_ids"
    ]
    assert partial["counter_evidence_and_risks"]
    assert partial["invalidation_conditions"]
    assert partial["next_evidence_tasks"]
    assert partial["citations"]
    assert all(
        "user_id" not in item
        and "run_id" not in item
        and "source_key" not in item
        for item in partial["citations"]
    )

    completed = _run(app, user["id"], "completed", message, evidence)
    structured = app.state.structured_ai.build_and_persist(
        user_id=user["id"],
        run=completed,
        evidence=evidence,
        answer=completed["answer"],
        message=message,
        conversation_id=conversation["id"],
        symbol="000063.SZ",
    )

    assert structured["status"] == "complete"
    assert len(structured["candidate_writebacks"]) == 1
    candidate = structured["candidate_writebacks"][0]
    assert candidate["status"] == "pending_confirmation"
    assert "user_id" not in candidate
    assert "workspace_id" not in candidate
    assert "conversation_id" not in candidate
    assert "run_id" not in candidate


def test_normal_question_does_not_create_writeback_and_negated_request_is_respected(app):
    client = TestClient(app)
    user = _create_user(client, "Structured AI Intent")
    _add_stock(client, "正式判断保持不变")
    evidence = _evidence()

    for message in (
        "分析中兴通讯当前最强的反方证据。",
        "分析中兴通讯，但不要形成判断草稿。",
        "分析中兴通讯，但先不要创建观察任务。",
        "分析中兴通讯，但不要生成操作计划。",
    ):
        run = _run(app, user["id"], "completed", message, evidence)
        result = app.state.structured_ai.build_and_persist(
            user_id=user["id"],
            run=run,
            evidence=evidence,
            answer=run["answer"],
            message=message,
            conversation_id=None,
            symbol="000063.SZ",
        )
        assert result["candidate_writebacks"] == []


def test_action_plan_writeback_requires_confirmation_and_keeps_targets_empty(app):
    owner = TestClient(app)
    owner_user = _create_user(owner, "Structured AI Plan Owner")
    _add_stock(owner, "关注订单、利润和经营现金流")
    message = (
        "分析中兴通讯并生成操作计划，核验条件：如果下一期经营现金流继续恶化，"
        "由我重新评估是否减仓；不要填写目标价、数量或仓位。"
    )
    run = _run(app, owner_user["id"], "completed", message, _evidence())
    result = app.state.structured_ai.build_and_persist(
        user_id=owner_user["id"],
        run=run,
        evidence=_evidence(),
        answer=run["answer"],
        message=message,
        conversation_id=None,
        symbol="000063.SZ",
    )

    assert len(result["candidate_writebacks"]) == 1
    candidate = result["candidate_writebacks"][0]
    assert candidate["candidate_type"] == "action_plan"
    assert candidate["status"] == "pending_confirmation"
    assert candidate["payload"]["action_type"] == "reduce"
    assert "经营现金流继续恶化" in candidate["payload"]["trigger_text"]
    assert candidate["payload"]["target_quantity"] is None
    assert candidate["payload"]["target_amount"] is None
    assert candidate["payload"]["target_position_percent"] is None
    assert owner.get("/v1/stocks/000063/action-plans").json()["items"] == []

    path = f"/v1/ai-writebacks/{candidate['id']}"
    confirmed = owner.post(f"{path}/confirm")
    assert confirmed.status_code == 200
    plan = confirmed.json()["action_plan"]
    assert plan["status"] == "draft"
    assert plan["action_type"] == "reduce"
    assert plan["target_quantity"] is None
    assert plan["target_amount"] is None
    assert plan["target_position_percent"] is None
    assert owner.post(f"{path}/confirm").json()["action_plan"]["id"] == plan["id"]
    assert [
        item["id"]
        for item in owner.get("/v1/stocks/000063/action-plans").json()["items"]
    ] == [plan["id"]]

    stale_run = _run(app, owner_user["id"], "completed", message, _evidence())
    stale_result = app.state.structured_ai.build_and_persist(
        user_id=owner_user["id"],
        run=stale_run,
        evidence=_evidence(),
        answer=stale_run["answer"],
        message=message,
        conversation_id=None,
        symbol="000063.SZ",
    )
    stale_candidate = stale_result["candidate_writebacks"][0]
    _add_stock(owner, "正式判断已经由用户更新")
    stale_path = f"/v1/ai-writebacks/{stale_candidate['id']}"
    assert owner.post(f"{stale_path}/confirm").status_code == 409
    assert owner.get(stale_path).json()["status"] == "stale"
    assert len(owner.get("/v1/stocks/000063/action-plans").json()["items"]) == 1


def test_focused_earnings_run_creates_action_plan_candidate_from_user_condition(app):
    owner = TestClient(app)
    owner_user = _create_user(owner, "Focused Earnings Plan Owner")
    _add_stock(owner, "关注经营现金流兑现")
    message = (
        "分析中兴通讯并生成操作计划，核验条件：如果下一期经营现金流继续恶化，"
        "由我重新评估是否减仓；不要填写目标价、数量或仓位。"
    )
    evidence = {
        "type": "earnings_quality",
        "symbol": "000063.SZ",
        "name": "中兴通讯",
        "generated_at": "2026-07-23T08:00:00+08:00",
        "latest_report": {"report_date": "2026-03-31"},
        "contradictions": ["经营现金流对归母净利润覆盖低于 0.8。"],
        "review_points": ["核验下一报告期经营现金流是否改善。"],
    }
    run = _run(
        app,
        owner_user["id"],
        "completed",
        message,
        evidence,
        intent="earnings_quality",
    )

    result = app.state.structured_ai.build_and_persist(
        user_id=owner_user["id"],
        run=run,
        evidence=evidence,
        answer=run["answer"],
        message=message,
        conversation_id=None,
        symbol="000063.SZ",
    )

    assert result["status"] == "complete"
    assert result["citations"]
    assert len(result["candidate_writebacks"]) == 1
    candidate = result["candidate_writebacks"][0]
    assert candidate["candidate_type"] == "action_plan"
    assert candidate["citation_ids"]
    assert candidate["payload"]["action_type"] == "reduce"
    assert candidate["payload"]["trigger_text"].count("经营现金流继续恶化") == 1
    assert "不要填写目标价" not in candidate["payload"]["trigger_text"]
    assert "低于 0.8" not in candidate["payload"]["trigger_text"]
    assert "本轮核验条件" not in candidate["payload"]["boundary"]
    assert candidate["payload"]["target_quantity"] is None
    assert candidate["payload"]["target_amount"] is None
    assert candidate["payload"]["target_position_percent"] is None


def test_observation_task_writeback_requires_confirmation_and_is_idempotent(app):
    owner = TestClient(app)
    owner_user = _create_user(owner, "Structured AI Observation Owner")
    _add_stock(owner, "关注利润、现金流和订单兑现")
    message = (
        "分析中兴通讯并把“继续核验经营现金流与订单兑现”"
        "保存为核验任务，供我确认。"
    )
    run = _run(app, owner_user["id"], "completed", message, _evidence())
    result = app.state.structured_ai.build_and_persist(
        user_id=owner_user["id"],
        run=run,
        evidence=_evidence(),
        answer=run["answer"],
        message=message,
        conversation_id=None,
        symbol="000063.SZ",
    )

    assert len(result["candidate_writebacks"]) == 1
    candidate = result["candidate_writebacks"][0]
    assert candidate["candidate_type"] == "observation_task"
    assert candidate["status"] == "pending_confirmation"
    assert candidate["payload"]["title"].startswith("中兴通讯")
    assert "继续核验经营现金流与订单兑现" in candidate["payload"]["description"]
    assert "经营现金流" in candidate["payload"]["description"]
    assert owner.get("/v1/observation-tasks").json()["items"] == []

    other = TestClient(app)
    _create_user(other, "Structured AI Observation Other")
    path = f"/v1/ai-writebacks/{candidate['id']}"
    assert other.get(path).status_code == 404
    assert other.post(f"{path}/confirm").status_code == 404

    confirmed = owner.post(f"{path}/confirm")
    assert confirmed.status_code == 200
    confirmed_payload = confirmed.json()
    assert confirmed_payload["status"] == "confirmed"
    task = confirmed_payload["observation_task"]
    assert task["status"] == "pending"
    assert task["source_type"] == "research_action"

    repeated = owner.post(f"{path}/confirm")
    assert repeated.status_code == 200
    assert repeated.json()["observation_task"]["id"] == task["id"]
    tasks = owner.get("/v1/stocks/000063/observation-tasks").json()["items"]
    assert [item["id"] for item in tasks] == [task["id"]]
    restored = owner.get(path).json()
    assert restored["status"] == "confirmed"


def test_observation_task_candidate_is_not_created_for_preview_run(app):
    client = TestClient(app)
    user = _create_user(client, "Structured AI Observation Preview")
    _add_stock(client, "等待核验")
    message = "把下一步创建为观察任务。"
    run = _run(app, user["id"], "preview", message, _evidence())
    result = app.state.structured_ai.build_and_persist(
        user_id=user["id"],
        run=run,
        evidence=_evidence(),
        answer=run["answer"],
        message=message,
        conversation_id=None,
        symbol="000063.SZ",
    )
    assert result["candidate_writebacks"] == []


def test_li_zong_stock_screen_can_create_confirmable_observation_task(app):
    owner = TestClient(app)
    owner_user = _create_user(owner, "Structured AI Li Zong Owner")
    _add_stock(owner, "仅作为8/9研究观察")
    evidence = {
        "type": "stock_screen",
        "generated_at": "2026-07-24T00:00:00+00:00",
        "profile": {"key": "li_zong", "label": "李总策略"},
        "selection_mode": "symbol_check",
        "display_name": "中兴通讯",
        "strategy": {
            "version": {
                "rules": [
                    {"rule_id": "LZ-F-01", "label": "总市值严格大于150亿元"},
                    {"rule_id": "LZ-C-04", "label": "近十日无5%阴线"},
                ]
            }
        },
        "items": [
            {
                "name": "中兴通讯",
                "internal_symbol": "000063.SZ",
                "as_of_date": "2026-07-23",
                "status": "not_qualified",
                "rule_results": [
                    {
                        "rule_id": "LZ-F-01",
                        "status": "passed",
                        "evidence_date": "2026-07-23",
                    },
                    {
                        "rule_id": "LZ-C-04",
                        "status": "failed",
                        "evidence_date": "2026-07-23",
                    },
                ],
            }
        ],
        "data_meta": {"latest_completed_trade_date": "2026-07-23"},
    }
    message = (
        "请核验李总策略8/9观察结果，并把“继续跟踪5%阴线是否滑出”"
        "保存为核验任务。"
    )
    run = _run(app, owner_user["id"], "completed", message, evidence)

    result = app.state.structured_ai.build_and_persist(
        user_id=owner_user["id"],
        run=run,
        evidence=evidence,
        answer=run["answer"],
        message=message,
        conversation_id=None,
        symbol="000063.SZ",
    )

    assert result is not None
    assert result["status"] == "complete"
    assert result["confirmed_facts"]
    assert result["counter_evidence_and_risks"]
    assert len(result["candidate_writebacks"]) == 1
    candidate = result["candidate_writebacks"][0]
    assert candidate["candidate_type"] == "observation_task"
    assert "继续跟踪5%阴线是否滑出" in candidate["payload"]["description"]
    assert "重新核验" not in candidate["payload"]["description"]
    assert owner.get("/v1/observation-tasks").json()["items"] == []


def test_database_migrates_existing_thesis_only_writeback_schema(tmp_path: Path):
    database_path = tmp_path / "legacy.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE ai_writeback_candidates (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                run_id TEXT NOT NULL,
                conversation_id TEXT,
                workspace_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                candidate_type TEXT NOT NULL CHECK(candidate_type IN ('thesis')),
                status TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                citation_ids_json TEXT NOT NULL DEFAULT '[]',
                base_version INTEGER NOT NULL,
                target_object_id TEXT,
                created_at TEXT NOT NULL,
                resolved_at TEXT,
                UNIQUE(user_id, run_id, candidate_type)
            )
            """
        )
    database = Database(database_path, tmp_path / "workspaces")
    database.initialize()
    with database.connect() as connection:
        schema = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'ai_writeback_candidates'"
        ).fetchone()["sql"]
    assert "observation_task" in schema
    assert "action_plan" in schema
    assert "review_draft" in schema


def test_writeback_confirm_reject_stale_and_user_isolation(app):
    owner = TestClient(app)
    owner_user = _create_user(owner, "Structured AI Owner")
    _add_stock(owner, "版本一：关注订单兑现")
    evidence = _evidence()

    def create_candidate() -> dict:
        message = "形成判断草稿，供我确认，不要直接修改正式判断。"
        run = _run(app, owner_user["id"], "completed", message, evidence)
        result = app.state.structured_ai.build_and_persist(
            user_id=owner_user["id"],
            run=run,
            evidence=evidence,
            answer=run["answer"],
            message=message,
            conversation_id=None,
            symbol="000063.SZ",
        )
        return result["candidate_writebacks"][0]

    candidate = create_candidate()
    other = TestClient(app)
    _create_user(other, "Structured AI Other")
    path = f"/v1/ai-writebacks/{candidate['id']}"
    assert other.get(path).status_code == 404
    assert other.post(f"{path}/confirm").status_code == 404
    assert other.post(f"{path}/reject").status_code == 404

    before = owner.get("/v1/stocks/000063/theses").json()["active"]
    confirmed = owner.post(f"{path}/confirm")
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "confirmed"
    assert "user_id" not in confirmed.json()
    after = owner.get("/v1/stocks/000063/theses").json()["active"]
    assert before["version_no"] == 1
    assert after["version_no"] == 2
    assert after["reason_text"] != before["reason_text"]

    rejected_candidate = create_candidate()
    active_before_reject = owner.get("/v1/stocks/000063/theses").json()["active"]
    rejected = owner.post(
        f"/v1/ai-writebacks/{rejected_candidate['id']}/reject"
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert owner.get("/v1/stocks/000063/theses").json()["active"] == (
        active_before_reject
    )

    stale_candidate = create_candidate()
    _add_stock(owner, "版本三：正式判断已由用户更新")
    stale_path = f"/v1/ai-writebacks/{stale_candidate['id']}"
    stale = owner.post(f"{stale_path}/confirm")
    assert stale.status_code == 409
    assert owner.get(stale_path).json()["status"] == "stale"


def test_chat_history_and_private_stream_include_structured_answer(client):
    _create_user(client, "Structured AI Chat")
    request_id = "structured-sse-001"
    response = client.post(
        "/me/chat",
        json={
            "message": "分析中兴通讯的支持证据、反方证据和失效条件。",
            "execute_agent": True,
            "request_id": request_id,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    structured = payload["structured_answer"]
    assert structured["contract_version"] == "structured_ai_response_v1"
    assert structured["citations"]
    conversation = client.get(
        f"/me/conversations/{payload['conversation_id']}"
    ).json()
    assistant = conversation["messages"][-1]
    assert assistant["metadata"]["structured_answer"] == structured

    stream = client.get(f"/me/chat/stream/{request_id}")
    assert stream.status_code == 200
    assert "agent_citation" in stream.text
    assert "agent_structured_partial" in stream.text
    assert "agent_stream_complete" in stream.text


def test_structured_failure_keeps_answer_and_emits_private_failed_event(
    client, app, monkeypatch
):
    _create_user(client, "Structured AI Failure")

    def fail_structured_answer(**kwargs):
        raise RuntimeError("synthetic structured failure")

    monkeypatch.setattr(
        app.state.structured_ai,
        "build_and_persist",
        fail_structured_answer,
    )
    request_id = "structured-failed-001"
    response = client.post(
        "/me/chat",
        json={
            "message": "分析中兴通讯当前的反方证据。",
            "execute_agent": True,
            "request_id": request_id,
        },
    )

    assert response.status_code == 200
    assert response.json()["answer"]
    assert response.json()["structured_answer"] is None
    stream = client.get(f"/me/chat/stream/{request_id}")
    assert "agent_structured_failed" in stream.text
    assert "agent_stream_complete" in stream.text


def test_refine_replaces_structured_answer_and_can_create_writeback(
    client, app, monkeypatch
):
    user = _create_user(client, "Structured AI Refine")
    _add_stock(client, "原判断：等待深化研究")
    message = "分析中兴通讯并形成判断草稿，供我确认，不要直接修改正式判断。"
    preview = client.post(
        "/me/chat",
        json={"message": message, "execute_agent": False},
    )
    assert preview.status_code == 200
    preview_payload = preview.json()
    assert preview_payload["structured_answer"]["candidate_writebacks"] == []

    def completed_run(**kwargs):
        evidence = kwargs["evidence"]
        return _run(app, user["id"], "completed", message, evidence)

    monkeypatch.setattr(app.state.agent, "run", completed_run)
    refined = client.post(
        "/me/chat/refine",
        json={
            "conversation_id": preview_payload["conversation_id"],
            "preview_run_id": preview_payload["run_id"],
            "assistant_message_id": preview_payload["assistant_message_id"],
            "model_tier": "economy",
        },
    )

    assert refined.status_code == 200
    refined_payload = refined.json()
    assert refined_payload["status"] == "completed"
    assert len(refined_payload["structured_answer"]["candidate_writebacks"]) == 1
    conversation = client.get(
        f"/me/conversations/{preview_payload['conversation_id']}"
    ).json()
    assert (
        conversation["messages"][-1]["metadata"]["structured_answer"]
        == refined_payload["structured_answer"]
    )
