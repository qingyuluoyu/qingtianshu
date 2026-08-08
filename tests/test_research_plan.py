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


def test_deep_price_cause_request_keeps_question_scoped_evidence_plan():
    plan = ResearchPlanService().build(
        "请深度分析中兴通讯今天的涨跌究竟更像行业因素还是公司自身因素。"
        "不要套模板，结合最新价格、通信设备行业、财务、现金流、公告和市场情绪，"
        "给出信息量充分但自然的结论；如果近期直接驱动没有证据，"
        "请明确区分背景和直接原因。"
    )

    assert plan["focus"] == "mixed"
    assert plan["selected_modules"] == [
        "market",
        "company_information",
        "event_timeline",
        "fundamentals",
        "earnings_quality",
        "financial_drivers",
    ]
    assert "business_structure" not in plan["selected_modules"]
    assert "shareholder_structure" not in plan["selected_modules"]
    assert "analyst_expectations" not in plan["selected_modules"]
    assert "peer_comparison" not in plan["selected_modules"]
    assert "outlook_calibration" not in plan["selected_modules"]
    assert "evidence-debate" not in plan["selected_skills"]
    assert plan["answer_requirements"][1] == (
        "区分同日价格表现、基本面背景和仍未确认的直接驱动"
    )


def test_deep_price_cause_adds_structured_finance_without_explicit_finance_terms():
    plan = ResearchPlanService().build(
        "北方国际7月30日上涨更像行业还是公司因素？请深度分析，信息量要大。"
    )

    assert plan["focus"] == "price_cause"
    assert plan["selected_modules"] == [
        "market",
        "company_information",
        "event_timeline",
        "fundamentals",
        "earnings_quality",
        "financial_drivers",
    ]
    assert "evidence-debate" not in plan["selected_skills"]


def test_price_cause_followup_inherits_prior_scope_without_full_stock_report():
    service = ResearchPlanService()
    first_question = (
        "北方国际7月30日上涨，究竟更像行业因素还是公司因素？"
        "请做一次深度分析，结合行情、事件和财务，信息量要大，"
        "但用自然对话的方式直接回答。"
    )
    followup = (
        "那你现在最有把握能确认的两件事是什么？最不能确认的一件事是什么？"
        "不要重复所有数字，像继续聊天一样回答。"
    )

    plan = service.build(
        followup,
        conversation_history=[
            {"role": "user", "content": first_question},
            {"role": "assistant", "content": "上一轮回答"},
        ],
    )

    assert plan["focus"] == "price_cause"
    assert plan["primary_focus"] == "price_cause"
    assert plan["contextual_followup"] is True
    assert plan["effective_question"].startswith(first_question)
    assert plan["selected_modules"] == [
        "market",
        "company_information",
        "event_timeline",
        "fundamentals",
        "earnings_quality",
        "financial_drivers",
    ]
    assert "business_structure" not in plan["selected_modules"]
    assert "shareholder_structure" not in plan["selected_modules"]
    assert "analyst_expectations" not in plan["selected_modules"]
    assert "peer_comparison" not in plan["selected_modules"]
    assert plan["selected_skills"] == ["a-share-information", "event-timeline"]


def test_business_topic_switch_ignores_negated_price_words_and_uses_specialist_plan():
    service = ResearchPlanService()

    first = service.build(
        "先不谈涨跌了，这家公司主要靠什么业务赚钱？请用普通投资者能理解的方式说。"
    )
    followup = service.build(
        "那茅台酒和系列酒的差别是什么？收入结构变化说明了什么，"
        "哪些结论不能直接推出？不要给股价和技术指标。"
    )

    for plan in (first, followup):
        assert plan["focus"] == "business"
        assert plan["primary_focus"] == "business"
        assert plan["selected_modules"] == ["business_structure"]
        assert plan["selected_skills"] == ["business-structure"]
        assert "market" not in plan["selected_modules"]
        assert "fundamentals" not in plan["selected_modules"]


def test_business_question_keeps_explicit_cashflow_as_a_second_focus():
    plan = ResearchPlanService().build(
        "主营收入结构发生了什么变化，这和经营现金流、净利润有什么关系？"
    )

    assert plan["focus"] == "mixed"
    assert "business_structure" in plan["selected_modules"]
    assert "financial_drivers" in plan["selected_modules"]


def test_business_growth_question_uses_segments_and_financials_without_market():
    plan = ResearchPlanService().build(
        "别写报告，直接聊聊宁德时代这半年增长到底靠什么。储能真的是第二"
        "增长曲线，还是只是占比变大？把财报和管理层解释分开说。"
    )

    assert plan["focus"] == "business_growth"
    assert plan["primary_focus"] == "business_growth"
    assert plan["selected_modules"] == [
        "fundamentals",
        "earnings_quality",
        "financial_drivers",
        "business_structure",
        "company_information",
        "event_timeline",
    ]
    assert "market" not in plan["selected_modules"]
    assert "business-structure" in plan["selected_skills"]


def test_quality_review_focus_uses_disclosures_financials_cashflow_and_business_only():
    service = ResearchPlanService()

    plan = service.build(
        "这家公司为什么进入经营改善候选？请结合同报告期财务、"
        "经营现金流和主营结构判断改善是否有质量。"
    )

    assert plan["focus"] == "quality_review"
    assert plan["required_modules"] == [
        "fundamentals",
        "earnings_quality",
        "financial_drivers",
        "business_structure",
        "company_information",
        "event_timeline",
    ]
    assert "market" not in plan["selected_modules"]
    assert "peer_comparison" not in plan["selected_modules"]
    assert "analyst_expectations" not in plan["selected_modules"]
    assert plan["selected_skills"] == ["quality-review", "a-share-filing-evidence"]
    assert "evidence-debate" not in plan["selected_skills"]


def test_plain_financial_quality_question_ignores_style_and_negated_price_words():
    plan = ResearchPlanService().build(
        "中兴通讯最新财报到底好不好？请把收入、利润、经营现金流、毛利率、"
        "主营结构和最重要的反方事实讲清楚。像分析师和我聊天一样写，"
        "不要写成报告目录，也不要给股价和技术指标。"
    )

    assert plan["focus"] == "quality_review"
    assert plan["primary_focus"] == "quality_review"
    assert "market" not in plan["selected_modules"]
    assert "analyst_expectations" not in plan["selected_modules"]
    assert plan["selected_skills"] == [
        "quality-review",
        "a-share-filing-evidence",
    ]


def test_natural_quality_wording_does_not_fall_back_to_mixed_or_market():
    plan = ResearchPlanService().build(
        "宁德时代最新财报究竟好不好？不要按指标逐项念。先告诉我哪些改善是"
        "真实经营进展，哪些只是利润表漂亮或短期因素，再把现金流、毛利率、"
        "存货和主营结构讲透。像分析师聊天，不给股价和技术指标。"
    )

    assert plan["focus"] == "quality_review"
    assert plan["primary_focus"] == "quality_review"
    assert "market" not in plan["selected_modules"]
    assert "peer_comparison" not in plan["selected_modules"]
    assert plan["selected_skills"] == [
        "quality-review",
        "a-share-filing-evidence",
    ]


def test_financial_quality_followup_inherits_prior_focus_despite_financial_words():
    first_question = (
        "中兴通讯最新财报到底好不好？请把收入、利润、经营现金流、毛利率、"
        "主营结构和最重要的反方事实讲清楚。像分析师和我聊天一样写，"
        "不要写成报告目录，也不要给股价和技术指标。"
    )
    plan = ResearchPlanService().build(
        "你刚才说了很多数据，真正值得我改变判断的是哪两三件？"
        "哪些只是会计口径、报告期错位或者短期节奏？别重复整份财报。",
        conversation_history=[
            {"role": "user", "content": first_question},
            {"role": "assistant", "content": "上一轮回答"},
        ],
    )

    assert plan["focus"] == "quality_review"
    assert plan["primary_focus"] == "quality_review"
    assert plan["contextual_followup"] is True
    assert plan["effective_question"].startswith(first_question)
    assert "market" not in plan["selected_modules"]
    assert "analyst_expectations" not in plan["selected_modules"]


def test_financial_quality_followup_recognizes_explicit_continue_chat_wording():
    first_question = (
        "中兴通讯最新财报到底好不好？请把收入、利润、经营现金流、毛利率、"
        "主营结构和最重要的反方事实讲清楚。"
    )
    plan = ResearchPlanService().build(
        "别再复述整份财报和所有数字。真正会改变你判断的两个事实是什么？"
        "如果只能继续跟踪一项，你选哪项，为什么？像我们接着聊。",
        conversation_history=[
            {"role": "user", "content": first_question},
            {"role": "assistant", "content": "上一轮回答"},
        ],
    )

    assert plan["focus"] == "quality_review"
    assert plan["primary_focus"] == "quality_review"
    assert plan["contextual_followup"] is True
    assert plan["effective_question"].startswith(first_question)
    assert "market" not in plan["selected_modules"]
    assert "analyst_expectations" not in plan["selected_modules"]


def test_quality_review_reanswer_inherits_focus_despite_negated_report_word():
    first_question = (
        "中兴通讯最新财报到底好不好？请把收入、利润、经营现金流、毛利率、"
        "主营结构和最重要的反方事实讲清楚。"
    )
    plan = ResearchPlanService().build(
        "请重答上一问。只说真正会改变判断的事实，以及暂时更像会计口径或"
        "短期节奏的部分；别复述整份财报，也别写成报告目录。",
        conversation_history=[
            {"role": "user", "content": first_question},
            {"role": "assistant", "content": "上一轮回答"},
        ],
    )

    assert plan["focus"] == "quality_review"
    assert plan["primary_focus"] == "quality_review"
    assert plan["contextual_followup"] is True
    assert plan["effective_question"].startswith(first_question)
    assert "market" not in plan["selected_modules"]


def test_valuation_correction_inherits_prior_specialist_focus():
    first_question = (
        "宁德时代现在的估值有没有支撑？把PE、PB和同口径同行放在一起讲清楚。"
    )
    plan = ResearchPlanService().build(
        "你上段最大的毛病是把市场担心说得太确定。别替市场猜动机，只用财报"
        "和同行估值重新说：哪些风险已经确认，哪些只是可能解释？不要重复所有数字。",
        conversation_history=[
            {"role": "user", "content": first_question},
            {"role": "assistant", "content": "上一轮估值回答"},
        ],
    )

    assert plan["focus"] == "valuation_review"
    assert plan["primary_focus"] == "valuation_review"
    assert plan["contextual_followup"] is True
    assert plan["effective_question"].startswith(first_question)


def test_shareholder_topic_switch_drops_negated_financial_scope_and_market():
    plan = ResearchPlanService().build(
        "那先不谈财报了，股东结构最近有没有值得注意的变化？"
        "只说真实披露，也不要重复刚才的财务数据。"
    )

    assert plan["focus"] == "shareholder"
    assert plan["selected_modules"] == ["shareholder_structure"]
    assert plan["selected_skills"] == [
        "shareholder-structure",
        "evidence-debate",
    ]


def test_quality_review_correction_keeps_question_scoped_plan() -> None:
    plan = ResearchPlanService().build(
        "请重新核对经营改善候选：投资者关系记录表已明确写出"
        "‘库存增加主要是为下半年市场需求而提前备货’。请据此修正上一回答，"
        "区分公司已解释的备货原因，与仍需量化核验的库存分类、库龄、"
        "订单覆盖和跌价准备；同时保留毛利率、现金流和行业边界。"
    )

    assert plan["focus"] == "quality_review"
    assert plan["selected_modules"] == [
        "fundamentals",
        "earnings_quality",
        "financial_drivers",
        "business_structure",
        "company_information",
        "event_timeline",
    ]
    assert "market" not in plan["selected_modules"]
    assert "peer_comparison" not in plan["selected_modules"]
    assert plan["selected_skills"] == [
        "quality-review",
        "a-share-filing-evidence",
    ]


def test_quality_review_can_still_add_explicit_valuation_question():
    service = ResearchPlanService()

    plan = service.build("经营改善候选的改善质量如何，估值是不是也便宜？")

    assert plan["focus"] == "mixed"
    assert "peer_comparison" in plan["selected_modules"]


def test_valuation_candidate_uses_scoped_quality_and_peer_plan() -> None:
    plan = ResearchPlanService().build(
        "动力新科为什么进入估值约束候选？请核对PE、PB及数据日期，"
        "并结合同口径同行估值、最新财务、盈利质量、经营现金流和负债，"
        "判断是否存在低估值陷阱。"
    )

    assert plan["focus"] == "valuation_review"
    assert plan["required_modules"] == [
        "market",
        "fundamentals",
        "earnings_quality",
        "financial_drivers",
        "peer_comparison",
    ]
    assert "shareholder_structure" not in plan["selected_modules"]
    assert "outlook_calibration" not in plan["selected_modules"]
    assert "a-share-filing-evidence" in plan["selected_skills"]
    assert "financial-drivers" in plan["selected_skills"]


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


def test_financial_and_stabilization_followup_avoids_comprehensive_prompt():
    service = ResearchPlanService()

    plan = service.build(
        "请用三段话继续说明：财务压力能确认什么、不能解释什么，以及近5日走平为什么还不能叫企稳。"
    )

    assert plan["focus"] == "mixed"
    assert plan["selected_modules"] == [
        "fundamentals",
        "earnings_quality",
        "financial_drivers",
        "market",
    ]
    assert "business_structure" not in plan["selected_modules"]
    assert "shareholder_structure" not in plan["selected_modules"]
    assert "analyst_expectations" not in plan["selected_modules"]
    assert "company_information" not in plan["selected_modules"]
    assert "event_timeline" not in plan["selected_modules"]
    assert "outlook_calibration" not in plan["selected_modules"]
    assert "conditional-outlook" not in plan["selected_skills"]


def test_future_price_question_keeps_outlook_calibration_only_when_requested():
    service = ResearchPlanService()

    current = service.build("中兴通讯近5日走平算企稳吗？")
    future = service.build("中兴通讯后续走势怎么看？")

    assert current["focus"] == "price_action"
    assert "outlook_calibration" not in current["selected_modules"]
    assert "conditional-outlook" not in current["selected_skills"]
    assert future["focus"] == "price_action"
    assert "outlook_calibration" in future["selected_modules"]
    assert "conditional-outlook" in future["selected_skills"]


def test_relative_industry_question_uses_scoped_market_and_industry_plan():
    plan = ResearchPlanService().build(
        "宁德时代今天相对电池行业是增强还是走弱？请说明行业成分覆盖。"
    )

    assert plan["focus"] == "relative_industry"
    assert plan["required_modules"] == ["market", "analyst_expectations"]
    assert plan["selected_skills"] == []
    assert plan["module_labels"]["analyst_expectations"] == "所属行业指数与成分"
    assert "peer_comparison" not in plan["selected_modules"]
    assert "financial_drivers" not in plan["selected_modules"]


def test_named_cs_industry_index_keeps_relative_industry_plan():
    plan = ResearchPlanService().build(
        "用最新数据重新分析：宁德时代今天相对CS电池行业是增强还是走弱？"
    )

    assert plan["focus"] == "relative_industry"
    assert plan["required_modules"] == ["market", "analyst_expectations"]


def test_named_cs_index_without_industry_word_keeps_relative_industry_plan():
    plan = ResearchPlanService().build(
        "宁德时代今天相对CS电池指数是增强、同步还是走弱？"
    )

    assert plan["focus"] == "relative_industry"
    assert plan["required_modules"] == ["market", "analyst_expectations"]


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
        "industry": "通信设备",
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
    research_entry = payload["evidence"]["stock_workspace_context"]["research_entry"]
    assert research_entry["source_label"] == "经营改善候选"
    assert research_entry["industry"] == "通信设备"
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
    assert "通信设备" in prompt
    assert "营收同比保持增长" in prompt
    assert "先核验改善是否来自主营并转化为现金流" in prompt
    assert "净利润同比下降" in prompt
    assert "现金流变化原因" in prompt


def test_bound_screening_candidate_question_uses_full_stock_research_path(app):
    client = TestClient(app)
    user = _create_user(client, "Bound screening research user")
    created = client.post(
        "/me/deep-stock",
        json={
            "symbol": "000065.SZ",
            "entry_context": {
                "source_kind": "stock_screen",
                "source_label": "回撤后待复核候选",
                "display_name": "北方国际",
                "profile_key": "pullback",
                "as_of_date": "2026-07-28",
                "candidate_status": "ready",
                "matched_reasons": ["最近20日出现回撤"],
                "research_focus": "核验回撤是否有公司事件和现金流证据。",
                "attention_flags": ["短线停止下跌不等于已经企稳。"],
                "missing_fields": ["股价回撤的直接公司解释"],
            },
        },
    )
    assert created.status_code == 201

    question = (
        "北方国际最近20日下跌8.04%，这次回撤最可能与哪些已经确认的公司事件、"
        "财务和经营现金流变化有关？请先直接回答，再说明哪些原因目前没有证据；"
        "同时判断近5日0.00%能不能算企稳。请用普通投资者能看懂的话，"
        "不要复述选股卡片。"
    )
    response = client.post(
        "/me/chat",
        json={
            "message": question,
            "conversation_id": created.json()["conversation_id"],
            "execute_agent": False,
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    evidence = payload["evidence"]
    assert payload["intent"] == "stock_research"
    assert evidence["symbol"] == "000065.SZ"
    assert evidence["research_plan"]["focus"] == "mixed"
    assert "conditional_outlook" not in evidence["research_plan"]["selected_modules"]
    assert "conditional-outlook" not in evidence["research_plan"]["selected_skills"]
    assert set(evidence["research_plan"]["required_modules"]) == {
        "market",
        "fundamentals",
        "earnings_quality",
        "financial_drivers",
        "company_information",
        "event_timeline",
    }
    assert (
        evidence["stock_workspace_context"]["research_entry"]["source_label"]
        == "回撤后待复核候选"
    )
    assert "candidates" not in evidence
    assert "fundamentals" in evidence
    assert "earnings_quality" in evidence
    assert "financial_drivers" in evidence
    assert "a_share_information" in evidence
    assert "event_timeline" in evidence

    prompt = (
        Path(app.state.database.get_user(user["id"])["workspace_path"])
        / "runs"
        / payload["run_id"]
        / "prompt.md"
    ).read_text(encoding="utf-8")
    assert "# Fundamental Evidence" in prompt
    assert "# Earnings Quality" in prompt
    assert "# Financial Drivers" in prompt
    assert "# A-share Information Runtime" in prompt
    assert "# Event Timeline" in prompt
    assert "选股入口线索使用要求" in prompt
    assert '"a_share_information"' in prompt
    assert '"financial_drivers"' in prompt
    assert "不要把已有披露说成“没有事件证据”" in prompt


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
