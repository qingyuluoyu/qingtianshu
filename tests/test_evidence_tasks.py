from __future__ import annotations

from app.utils import utc_now


def _create_user(client, name: str = "补证测试用户") -> dict:
    response = client.post("/users", json={"name": name})
    assert response.status_code == 201
    return response.json()


def _stock_evidence(gaps: list[str]) -> dict:
    return {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "generated_at": utc_now(),
        "facts": ["测试行情事实"],
        "research_frame": {"missing_information": gaps},
        "evidence_readiness": {
            "status": "usable",
            "label": "核心证据可用",
            "coverage_ratio": 0.75,
            "missing_core_modules": [],
            "optional_gaps": gaps,
        },
        "analysis_board": {
            "readiness": {
                "status": "usable",
                "label": "核心证据可用",
                "coverage_ratio": 0.75,
                "missing_core_modules": [],
                "optional_gaps": gaps,
            },
            "modules": [],
        },
        "warnings": [],
    }


def test_capture_deduplicates_tasks_and_isolates_users(client, app):
    alice = _create_user(client, "Alice")
    conversation = app.state.database.create_conversation(alice["id"], "测试对话")
    evidence = _stock_evidence(["公司最新公告尚未接入"])

    first = app.state.evidence_tasks.capture_from_chat(
        user_id=alice["id"],
        conversation_id=conversation["id"],
        run_id=None,
        intent="stock_research",
        message="中兴通讯最近有什么新公告？",
        evidence=evidence,
        symbol="000063.SZ",
    )
    second = app.state.evidence_tasks.capture_from_chat(
        user_id=alice["id"],
        conversation_id=conversation["id"],
        run_id=None,
        intent="stock_research",
        message="再检查一次公告",
        evidence=evidence,
        symbol="000063.SZ",
    )
    assert first["captured"] == 1
    assert second["captured"] == 1
    assert app.state.database.evidence_task_summary(alice["id"])["total"] == 1

    bob = app.state.database.create_user("Bob")
    bob_conversation = app.state.database.create_conversation(bob["id"], "测试对话")
    app.state.evidence_tasks.capture_from_chat(
        user_id=bob["id"],
        conversation_id=bob_conversation["id"],
        run_id=None,
        intent="stock_research",
        message="中兴通讯最近有什么新公告？",
        evidence=evidence,
        symbol="000063.SZ",
    )
    assert app.state.database.evidence_task_summary(bob["id"])["total"] == 1
    assert client.get("/me/evidence-tasks").json()["summary"]["total"] == 1


def test_supported_task_resolves_into_long_term_user_knowledge(client, app):
    user = _create_user(client)
    conversation = app.state.database.create_conversation(user["id"], "公告补证")
    captured = app.state.evidence_tasks.capture_from_chat(
        user_id=user["id"],
        conversation_id=conversation["id"],
        run_id=None,
        intent="stock_research",
        message="中兴通讯最近有什么事件？",
        evidence=_stock_evidence(["新闻与事件影响尚未接入"]),
        symbol="000063.SZ",
    )
    assert captured["tasks"][0]["task_type"] == "a_share_information_refresh"
    assert captured["tasks"][0]["status"] == "pending"

    processed = client.post("/me/evidence-tasks/process?limit=5")
    assert processed.status_code == 200
    payload = processed.json()
    assert payload["summary"]["resolved"] == 1
    task = client.get("/me/evidence-tasks").json()["items"][0]
    assert task["status"] == "resolved"
    assert task["resolution_document_id"]

    documents = app.state.database.list_knowledge_documents(
        user["id"], include_content=True
    )
    resolved = next(
        item
        for item in documents
        if item.get("source_key") == f"evidence-task:{task['id']}"
    )
    assert "公司发布重大事项公告" in resolved["content"]
    assert "媒体线索需要回看原文" in resolved["content"]


def test_external_gap_remains_explicitly_unresolved(client, app):
    user = _create_user(client)
    conversation = app.state.database.create_conversation(user["id"], "行业补证")
    captured = app.state.evidence_tasks.capture_from_chat(
        user_id=user["id"],
        conversation_id=conversation["id"],
        run_id=None,
        intent="stock_research",
        message="行业供需对中兴通讯有什么影响？",
        evidence=_stock_evidence(["行业供需与客户订单证据尚未接入"]),
        symbol="000063.SZ",
    )
    task = captured["tasks"][0]
    assert task["task_type"] == "external_research"
    assert task["status"] == "pending_external"
    processed = client.post("/me/evidence-tasks/process?limit=5").json()
    assert processed["summary"]["processed"] == 0
    assert client.get("/me/evidence-tasks").json()["items"][0]["status"] == (
        "pending_external"
    )


def test_chat_creates_evidence_task_and_review_page_renders_lifecycle(
    client, app, monkeypatch
):
    _create_user(client)
    original_build = app.state.research_evidence.build

    def build_with_gap(user_id: str, symbol: str):
        evidence = original_build(user_id, symbol)
        gap = "公司最新公告尚未接入"
        evidence["research_frame"]["missing_information"] = [gap]
        evidence["evidence_readiness"]["optional_gaps"] = [gap]
        evidence["analysis_board"]["readiness"]["optional_gaps"] = [gap]
        return evidence

    monkeypatch.setattr(app.state.research_evidence, "build", build_with_gap)
    response = client.post(
        "/me/chat",
        json={"message": "中兴通讯目前还有哪些关键证据缺口？"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "stock_research"
    assert payload["evidence_tasks"]["captured"] >= 1
    task = next(
        item
        for item in payload["evidence_tasks"]["tasks"]
        if item["description"] == "公司最新公告尚未接入"
    )
    assert task["conversation_id"] == payload["conversation_id"]
    assert task["run_id"] == payload["run_id"]

    page = client.get("/demo").text
    assert "待补证与后台补齐" in page
    script = client.get("/static/high-fidelity-demo.js").text
    assert "watchRequest('/me/evidence-tasks?limit=50')" in script
    assert "function renderEvidenceTasks(data)" in script
    status = client.get("/system/background").json()
    assert status["evidence_task_refresh_seconds"] > 0
