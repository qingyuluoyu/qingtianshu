from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

from app.providers.tavily_search import TavilySearchClient
from app.services.project_skill import ProjectSkillLoader


def _create_user(client, name: str = "AI研究用户") -> dict:
    response = client.post("/users", json={"name": name})
    assert response.status_code == 201
    return response.json()


def _fake_complete(prompt: str, *, max_tokens: int):
    if "最终综合写作" in prompt:
        return "这是读齐五维后生成的一次详细综合回答。", {"model": "fake-synthesis"}
    if "结构化研究小节" in prompt:
        payload = {
            "headline": "结构化维度结论",
            "facts": [
                {
                    "statement": "快照内事实",
                    "basis": "测试证据",
                    "as_of": "快照时间",
                }
            ],
            "interpretations": ["基于事实的推断"],
            "counterevidence": ["测试反证"],
            "gaps": [],
            "boundary": "仅限当前快照。",
        }
        return json.dumps(payload, ensure_ascii=False), {"model": "fake-dimension"}
    return "这是基于同一证据快照生成的主对话回答。", {"model": "fake-main"}


def test_ai_research_persists_run_dimensions_and_one_synthesis(client, app, monkeypatch):
    user = _create_user(client)
    monkeypatch.setattr(app.state.ai_research, "_complete", _fake_complete)

    created = client.post(
        "/me/ai-research/runs",
        json={
            "question": "未来一年的关键经营变量是什么？",
            "targets": [{"symbol": "000063", "name": "中兴通讯"}],
        },
    )
    assert created.status_code == 202
    run_id = created.json()["run_id"]
    conversation_id = created.json()["conversation_id"]

    main = client.get(f"/me/ai-research/runs/{run_id}")
    assert main.status_code == 200
    assert main.json()["status"] == "completed"
    assert main.json()["skill"]["name"] == "lao-li-trader-perspective"
    assert "主对话回答" in main.json()["main_answer"]
    assert all(
        item["status"] == "idle"
        for item in main.json()["dimensions"].values()
    )

    dimension = client.post(
        f"/me/ai-research/runs/{run_id}/dimensions/financial"
    )
    assert dimension.status_code == 202
    saved_dimension = client.get(f"/me/ai-research/runs/{run_id}").json()
    assert saved_dimension["dimensions"]["financial"]["status"] == "completed"
    assert (
        saved_dimension["dimensions"]["financial"]["result"]["headline"]
        == "结构化维度结论"
    )

    detailed = client.post(f"/me/ai-research/runs/{run_id}/detail")
    assert detailed.status_code == 202
    final = client.get(f"/me/ai-research/runs/{run_id}").json()
    assert final["detail_status"] == "completed"
    assert "一次详细综合回答" in final["detailed_answer"]
    assert all(
        item["status"] == "completed"
        for item in final["dimensions"].values()
    )

    restored = client.get(
        "/me/ai-research/runs/current",
        params={"conversation_id": conversation_id},
    )
    assert restored.status_code == 200
    assert restored.json()["item"]["run_id"] == run_id
    assert restored.json()["item"]["detailed_answer"] == final["detailed_answer"]

    conversation = client.get(f"/me/conversations/{conversation_id}").json()
    assert any(
        item["content"] == "基本面分析已完成 · 查看"
        and item["metadata"]["ai_research_run_id"] == run_id
        for item in conversation["messages"]
    )
    assert any(
        item["metadata"].get("kind") == "ai_research_detailed"
        and item["run_id"] == run_id
        for item in conversation["messages"]
    )

    generic_run = app.state.database.get_run(run_id, user["id"])
    assert generic_run["input"]["conversation_id"] == conversation_id
    assert generic_run["evidence"]["detail_status"] == "completed"
    assert (
        generic_run["evidence"]["snapshot"]["skill"]["name"]
        == "lao-li-trader-perspective"
    )


def test_multi_target_ai_research_only_allows_main_conversation(client, app, monkeypatch):
    _create_user(client, "多标的研究用户")
    monkeypatch.setattr(app.state.ai_research, "_complete", _fake_complete)

    created = client.post(
        "/me/ai-research/runs",
        json={
            "question": "比较两家公司的经营质量",
            "targets": [
                {"symbol": "000063.SZ", "name": "中兴通讯"},
                {"symbol": "300308.SZ", "name": "中际旭创"},
            ],
        },
    )
    assert created.status_code == 202
    run_id = created.json()["run_id"]
    current = client.get(f"/me/ai-research/runs/{run_id}").json()

    assert current["multi_target"] is True
    assert all(
        item["status"] == "disabled"
        for item in current["dimensions"].values()
    )
    detail = client.post(f"/me/ai-research/runs/{run_id}/detail")
    assert detail.status_code == 409
    assert detail.json()["detail"] == "多标的仅支持主对话综合"


def test_queued_ai_research_can_be_cancelled_through_user_api(client, app):
    user = _create_user(client, "取消研究用户")
    stored_user = app.state.database.get_user(user["id"])
    conversation = app.state.database.create_conversation(user["id"], "研究")
    run, _ = app.state.database.create_ai_research_submission(
        user_id=user["id"],
        conversation_id=conversation["id"],
        idempotency_key="cancel-through-api-0001",
        request_fingerprint="cancel-through-api",
        targets=[{"symbol": "000063.SZ", "name": "中兴通讯"}],
        question="取消这个研究",
        snapshot={},
        dimensions={},
        workspace_path=stored_user["workspace_path"],
    )

    response = client.post(f"/me/ai-research/runs/{run['run_id']}/cancel")

    assert response.status_code == 202
    payload = response.json()
    assert payload["run_id"] == run["run_id"]
    assert payload["task_id"] == run["task_id"]
    assert payload["execution_status"] == "cancelled"
    assert (
        app.state.database.get_research_task(run["task_id"])["status"]
        == "cancelled"
    )


def test_queued_ai_research_builds_snapshot_only_inside_worker_handler(
    client, app, monkeypatch
):
    from app.services.research_dispatcher import ResearchDispatcher

    user = _create_user(client, "队列执行用户")
    conversation = app.state.database.create_conversation(user["id"], "研究")

    class Queue:
        def publish_pending(self, limit=100):
            return 1

    run = ResearchDispatcher(app.state.database, Queue()).submit(
        user_id=user["id"],
        conversation_id=conversation["id"],
        targets=[{"symbol": "000063.SZ", "name": "中兴通讯"}],
        question="研究经营质量",
        idempotency_key="queued-worker-handler-0001",
    )
    task = app.state.database.claim_research_task(run["task_id"], "test-worker")
    monkeypatch.setattr(app.state.ai_research, "_complete", _fake_complete)

    assert run["snapshot"] == {}
    assert app.state.ai_research.execute_queued_main(task) is True
    saved = app.state.database.get_ai_research_run(user["id"], run["run_id"])
    assert saved["snapshot"]["captured_at"]
    assert saved["snapshot"]["items"][0]["target"]["symbol"] == "000063.SZ"
    assert saved["status"] == "completed"


def test_project_skill_loader_and_perfect_world_name_routing(
    client, app, settings, monkeypatch
):
    skill = ProjectSkillLoader(settings).load()
    assert skill is not None
    assert skill.name == "lao-li-trader-perspective"
    assert "板块主线资格 → 个股八项硬筛选" in skill.instructions
    assert "估值数据口径协议" in skill.instructions
    assert "每次诊股输出固定为6到7段，口语化叙述，不分段标题" in skill.instructions

    search = client.get("/api/v1/stocks/search", params={"q": "完美世界"})
    assert search.status_code == 200
    assert search.json()["items"][0]["internalSymbol"] == "002624.SZ"

    _create_user(client, "完美世界研究用户")
    captured_prompts: list[str] = []

    def capture_complete(prompt: str, *, max_tokens: int):
        captured_prompts.append(prompt)
        return _fake_complete(prompt, max_tokens=max_tokens)

    monkeypatch.setattr(app.state.ai_research, "_complete", capture_complete)
    monkeypatch.setattr(
        app.state.ai_research.web_search,
        "safe_search_target",
        lambda **_: {
            "provider": "tavily",
            "status": "completed",
            "query": "完美世界 002624.SZ 最新公告",
            "searched_at": "2026-07-24T10:00:00+00:00",
            "results": [
                {
                    "title": "完美世界股份有限公司公告",
                    "url": "https://example.com/perfect-world-announcement",
                    "content": "用于测试的联网证据。",
                    "score": 0.91,
                    "published_date": "2026-07-23",
                    "source_domain": "example.com",
                }
            ],
            "warning": None,
        },
    )
    created = client.post(
        "/me/ai-research/runs",
        json={
            "question": "研究完美世界未来的关键经营变量",
            "targets": [{"symbol": "002624.SZ", "name": "完美世界"}],
        },
    )
    assert created.status_code == 202
    assert created.json()["skill"]["active"] is True
    assert created.json()["web_search"]["status"] == "completed"
    assert created.json()["web_search"]["source_count"] == 1
    assert any(
        "# 老李 · A股主线与硬筛选交易操作系统" in prompt
        for prompt in captured_prompts
    )
    assert any(
        "https://example.com/perfect-world-announcement" in prompt
        and "# Tavily 联网证据规则" in prompt
        for prompt in captured_prompts
    )


def test_normal_chat_recognizes_perfect_world_and_injects_project_skill(
    client, app
):
    user = _create_user(client, "老李普通对话用户")
    response = client.post(
        "/me/chat",
        json={
            "message": "研究完美世界未来的关键经营变量",
            "execute_agent": False,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "stock_research"
    assert payload["evidence"]["symbol"] == "002624.SZ"

    run = app.state.database.get_run(payload["run_id"], user["id"])
    prompt_path = Path(run["workspace_path"]) / "runs" / run["id"] / "prompt.md"
    with prompt_path.open(encoding="utf-8") as handle:
        prompt = handle.read()
    assert "# 默认项目研究 Skill：lao-li-trader-perspective" in prompt
    assert "无需用户说出“老李视角”" in prompt


def test_tavily_search_client_uses_project_skill_and_normalizes_sources(
    settings, monkeypatch
):
    configured = replace(
        settings,
        tavily_enabled=True,
        tavily_api_key="tvly-test-only",
    )
    client = TavilySearchClient(configured)
    captured: dict = {}

    class FakeResponse:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {
                "request_id": "request-test",
                "response_time": 0.5,
                "results": [
                    {
                        "title": "官方公告",
                        "url": "https://www.szse.cn/disclosure/test",
                        "content": "  最新   公告内容  ",
                        "score": 0.93,
                    },
                    {
                        "title": "不安全链接",
                        "url": "javascript:alert(1)",
                        "content": "应被过滤",
                        "score": 1,
                    },
                ],
            }

    def fake_post(url, *, headers, json, timeout):
        captured.update(
            {
                "url": url,
                "headers": headers,
                "json": json,
                "timeout": timeout,
            }
        )
        return FakeResponse()

    monkeypatch.setattr(
        "app.providers.tavily_search.requests.post",
        fake_post,
    )
    result = client.search_target(
        target={"symbol": "002624.SZ", "name": "完美世界"},
        question="未来关键经营变量",
    )

    assert client.skill_metadata()["name"] == "tavily-search"
    assert result["status"] == "completed"
    assert len(result["results"]) == 1
    assert result["results"][0]["content"] == "最新 公告内容"
    assert captured["url"] == "https://api.tavily.com/search"
    assert captured["json"]["topic"] == "finance"
    assert captured["json"]["include_answer"] is False
    assert "tvly-test-only" not in json.dumps(result, ensure_ascii=False)
