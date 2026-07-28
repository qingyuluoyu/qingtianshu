from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.services.agent import AgentService
from app.services.research_plan import ResearchPlanService
from app.utils import utc_now


def _create_user(client, name: str = "网页体验用户") -> dict:
    response = client.post("/users", json={"name": name})
    assert response.status_code == 201
    return response.json()


def test_research_plan_routes_price_financial_shareholder_and_comprehensive():
    service = ResearchPlanService()

    price = service.build("中兴通讯今天为什么大跌")
    common_price_wording = service.build("中兴通讯最近为什么下跌")
    financial = service.build("中兴通讯的利润和现金流怎么变了")
    shareholder = service.build("中兴通讯股东户数有什么变化")
    comprehensive = service.build("全面分析中兴通讯")
    research_priority = service.build("中兴通讯现在值得继续研究什么？")

    assert price["focus"] == "price_cause"
    assert price["required_modules"] == [
        "market",
        "company_information",
        "event_timeline",
    ]
    assert price["optional_modules"] == []
    assert price["selected_skills"] == [
        "a-share-information",
        "event-timeline",
    ]
    assert common_price_wording["focus"] == "price_cause"
    assert "earnings_quality" not in price["selected_modules"]
    assert "analyst_expectations" not in price["selected_modules"]
    assert financial["focus"] == "financial"
    assert {"earnings_quality", "financial_drivers"}.issubset(
        financial["required_modules"]
    )
    assert shareholder["focus"] == "shareholder"
    assert "shareholder_structure" in shareholder["required_modules"]
    assert comprehensive["focus"] == "comprehensive"
    assert comprehensive["selected_modules"] == list(service.MODULE_LABELS)
    assert research_priority["focus"] == "comprehensive"
    assert "analyst_expectations" in research_priority["selected_modules"]


def test_research_plan_inherits_focus_for_short_followup():
    plan = ResearchPlanService().build(
        "那主要风险呢？",
        conversation_history=[
            {"role": "user", "content": "中兴通讯股东户数有什么变化？"},
            {"role": "assistant", "content": "已说明最近披露。"},
        ],
    )

    assert plan["focus"] == "shareholder"
    assert "中兴通讯股东户数" in plan["effective_question"]


def test_price_question_uses_scoped_modules_and_private_stock_workspace(
    client, app, monkeypatch
):
    user = _create_user(client)

    for index, (source_key, title, content) in enumerate(
        (
            (
                "peer-operating:000063.SZ",
                "中兴通讯同行经营比较",
                "中兴通讯 固定同行经营比较 旧财务数字 123456",
            ),
            (
                "shareholder-structure:000063.SZ",
                "中兴通讯股东结构",
                "中兴通讯 股东结构 股东户数 旧快照 654321",
            ),
            (
                "event-timeline:000063.SZ",
                "中兴通讯旧事件脉络",
                "中兴通讯 旧事件脉络 历史事件 2025-01-01",
            ),
        )
    ):
        app.state.database.upsert_knowledge_document(
            document_id=f"price-cause-stale-{index}",
            owner_user_id=None,
            scope="common",
            title=title,
            original_name=f"price-cause-stale-{index}.md",
            mime_type="text/markdown",
            content=content,
            source_key=source_key,
        )

    def unexpected_heavy_module(*args, **kwargs):
        raise AssertionError("price plan must not call unrelated heavy module")

    monkeypatch.setattr(
        app.state.research_evidence.earnings_quality,
        "get_packet",
        unexpected_heavy_module,
    )
    monkeypatch.setattr(
        app.state.research_evidence.financial_drivers,
        "get_packet",
        unexpected_heavy_module,
    )
    monkeypatch.setattr(
        app.state.research_evidence.shareholders,
        "get_packet",
        unexpected_heavy_module,
    )

    response = client.post(
        "/me/chat",
        json={"message": "中兴通讯今天为什么大跌", "execute_agent": False},
    )

    assert response.status_code == 200
    payload = response.json()
    evidence = payload["evidence"]
    assert payload["intent"] == "stock_research"
    assert evidence["research_plan"]["focus"] == "price_cause"
    assert "fundamentals" not in evidence["module_statuses"]
    assert "earnings_quality" not in evidence["module_statuses"]
    assert evidence["stock_workspace_context"]["symbol"] == "000063.SZ"
    assert evidence["stock_workspace_context"]["formal_thesis"]["summary"]
    run = app.state.database.get_run(payload["run_id"], user["id"])
    assert run["input"]["research_plan"]["focus"] == "price_cause"
    prompt = (
        Path(app.state.database.get_user(user["id"])["workspace_path"])
        / "runs"
        / payload["run_id"]
        / "prompt.md"
    ).read_text(encoding="utf-8")
    assert "# Event Timeline" in prompt
    assert "# Fundamental Evidence" not in prompt
    assert "# Evidence Debate" not in prompt
    assert "# Conditional Outlook" not in prompt
    assert "# Shareholder Structure" not in prompt
    assert "# Earnings Quality" not in prompt
    assert "个股涨跌原因回答合同" in prompt
    assert "中兴通讯同行经营比较" not in prompt
    assert "中兴通讯股东结构" not in prompt
    assert "中兴通讯旧事件脉络" not in prompt
    assert "# User Memory Context" not in prompt
    assert len(prompt) < 20_000


def test_stock_research_uses_compact_runtime_skill_without_removing_full_rules():
    skill_dir = Path(__file__).parents[1] / "app" / "skills" / "stock-research"
    runtime_path = skill_dir / "PROMPT.md"
    full_path = skill_dir / "SKILL.md"

    assert runtime_path.exists()
    assert full_path.exists()
    assert AgentService._load_skill("stock-research") == runtime_path.read_text(
        encoding="utf-8"
    )
    assert runtime_path.stat().st_size < full_path.stat().st_size * 0.6


def test_price_cause_supporting_skills_use_compact_runtime_prompts():
    skills_root = Path(__file__).parents[1] / "app" / "skills"

    for skill_name in (
        "a-share-information",
        "event-timeline",
        "online-stock-research",
        "watchlist-stock-research",
    ):
        skill_dir = skills_root / skill_name
        runtime_path = skill_dir / "PROMPT.md"
        full_path = skill_dir / "SKILL.md"
        assert runtime_path.exists()
        assert full_path.exists()
        assert AgentService._load_skill(skill_name) == runtime_path.read_text(
            encoding="utf-8"
        )
        assert runtime_path.stat().st_size < full_path.stat().st_size * 0.75


def test_recent_stable_modules_are_reused_while_market_and_quote_refresh(
    client, app, monkeypatch
):
    user = _create_user(client, "Research reuse user")
    service = app.state.research_evidence
    reusable = service.build(user["id"], "000063.SZ")
    plan = app.state.research_plan.build("中兴通讯利润和现金流怎么变了")

    def must_not_reload(*args, **kwargs):
        raise AssertionError("recent reporting-period module should be reused")

    monkeypatch.setattr(service.earnings_quality, "get_packet", must_not_reload)
    monkeypatch.setattr(service.financial_drivers, "get_packet", must_not_reload)
    packet = service.build(
        user["id"],
        "000063.SZ",
        plan=plan,
        reusable_evidence=reusable,
        reusable_generated_at=utc_now(),
    )

    assert packet["module_statuses"]["market"]["status"] == "fresh"
    assert packet["module_statuses"]["fundamentals"]["status"] == "fresh"
    assert packet["module_statuses"]["earnings_quality"]["status"] == "reused"
    assert packet["module_statuses"]["financial_drivers"]["status"] == "reused"


def test_specialized_stock_agent_also_receives_formal_workspace_context(client):
    _create_user(client)

    response = client.post(
        "/me/chat",
        json={
            "message": "中兴通讯股东户数有什么变化",
            "execute_agent": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "shareholder_structure"
    context = payload["evidence"]["stock_workspace_context"]
    assert context["research_focus"] == "shareholder"
    assert context["formal_thesis"]["summary"]


def test_screening_entry_reaches_stock_agent_evidence_and_prompt(app):
    client = TestClient(app)
    user = _create_user(client, "Screening to Agent User")
    entry = {
        "source_kind": "stock_screen",
        "source_label": "经营改善候选",
        "display_name": "中兴通讯",
        "profile_key": "quality",
        "as_of_date": "2026-07-28",
        "candidate_status": "ready",
        "matched_reasons": ["营收同比保持增长", "毛利率高于模板下限"],
        "research_focus": "先核验改善是否来自主营并转化为现金流。",
        "attention_flags": ["净利润同比下降，需要先排除低质量增长。"],
        "missing_fields": ["最新公告原文", "现金流变化原因"],
    }
    created = client.post(
        "/me/deep-stock",
        json={"symbol": "000063", "entry_context": entry},
    )
    assert created.status_code == 201

    response = client.post(
        "/me/chat",
        json={
            "message": "中兴通讯为什么进入经营改善候选，这个逻辑还成立吗？",
            "conversation_id": created.json()["conversation_id"],
            "execute_agent": False,
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["intent"] == "stock_research"
    research_entry = payload["evidence"]["stock_workspace_context"][
        "research_entry"
    ]
    assert research_entry["source_label"] == "经营改善候选"
    assert research_entry["matched_reasons"] == entry["matched_reasons"]
    assert research_entry["research_focus"] == entry["research_focus"]
    assert research_entry["attention_flags"] == entry["attention_flags"]
    assert research_entry["missing_fields"] == entry["missing_fields"]

    prompt = (
        Path(app.state.database.get_user(user["id"])["workspace_path"])
        / "runs"
        / payload["run_id"]
        / "prompt.md"
    ).read_text(encoding="utf-8")
    assert "选股入口线索使用要求" in prompt
    assert "经营改善候选" in prompt
    assert "营收同比保持增长" in prompt
    assert "先核验改善是否来自主营并转化为现金流" in prompt
    assert "净利润同比下降" in prompt
    assert "现金流变化原因" in prompt


def test_required_module_failure_returns_partial_packet(client, app, monkeypatch):
    user = _create_user(client, "Research partial user")
    service = app.state.research_evidence
    plan = app.state.research_plan.build("中兴通讯利润和现金流怎么变了")

    def fail_driver(*args, **kwargs):
        raise RuntimeError("temporary module failure")

    monkeypatch.setattr(service.financial_drivers, "get_packet", fail_driver)
    packet = service.build(user["id"], "000063.SZ", plan=plan)

    assert packet["evidence_status"] == "partial"
    assert packet["module_statuses"]["financial_drivers"]["status"] == ("unavailable")
    assert packet["earnings_quality"]
    assert any("利润与现金流驱动" in item for item in packet["warnings"])


def test_private_stock_workspace_context_is_user_isolated(app):
    alice_client = TestClient(app)
    bob_client = TestClient(app)
    alice = _create_user(alice_client, "Research Alice")
    bob = _create_user(bob_client, "Research Bob")
    alice_client.post(
        "/me/watchlist",
        json={
            "symbol": "000063.SZ",
            "name": "中兴通讯",
            "market": "A股",
            "thesis": "Alice 只关注政企业务现金流",
        },
    )
    bob_client.post(
        "/me/watchlist",
        json={
            "symbol": "000063.SZ",
            "name": "中兴通讯",
            "market": "A股",
            "thesis": "Bob 只关注运营商资本开支",
        },
    )

    alice_chat = alice_client.post(
        "/me/chat",
        json={"message": "中兴通讯今天为什么跌", "execute_agent": False},
    ).json()
    bob_chat = bob_client.post(
        "/me/chat",
        json={"message": "中兴通讯今天为什么跌", "execute_agent": False},
    ).json()

    alice_thesis = alice_chat["evidence"]["stock_workspace_context"]["formal_thesis"][
        "summary"
    ]
    bob_thesis = bob_chat["evidence"]["stock_workspace_context"]["formal_thesis"][
        "summary"
    ]
    assert alice_thesis == "Alice 只关注政企业务现金流"
    assert bob_thesis == "Bob 只关注运营商资本开支"
    assert alice_thesis not in str(bob_chat["evidence"])
    assert bob_thesis not in str(alice_chat["evidence"])
    assert app.state.database.get_run(alice_chat["run_id"], alice["id"])
    assert app.state.database.get_run(bob_chat["run_id"], bob["id"])


def test_price_plan_prompt_compaction_caps_repeated_context():
    repeated_events = [
        {
            "event_type": "news",
            "title": f"事件 {index} " + "很长摘要" * 120,
            "published_at": f"2026-07-{23 - index:02d}",
            "source": "公开来源",
            "url": f"https://example.com/{index}",
        }
        for index in range(20)
    ]
    evidence = {
        "type": "stock_research",
        "research_plan": ResearchPlanService().build("中兴通讯今天为什么大跌"),
        "event_timeline": {
            "status": "available",
            "events": repeated_events,
            "risk_events": repeated_events,
            "supportive_events": repeated_events,
        },
        "knowledge_context": {
            "items": [
                {"title": f"资料 {index}", "excerpt": "资料正文" * 500}
                for index in range(5)
            ]
        },
    }

    compact = AgentService._compact_stock_research_evidence(evidence)

    assert len(compact["event_timeline"]["events"]) == 4
    assert "risk_events" not in compact["event_timeline"]
    assert "supportive_events" not in compact["event_timeline"]
    assert len(compact["knowledge_context"]["items"]) == 2
    assert all(
        len(item["excerpt"]) <= 600 for item in compact["knowledge_context"]["items"]
    )
