from app.services.agent_prompt_contracts import append_prompt_contracts


def _append(
    *,
    intent: str,
    message: str = "测试问题",
    evidence: dict | None = None,
    prompt_evidence: dict | None = None,
    model_tier: str = "economy",
    is_action_plan_request: bool = False,
) -> str:
    return append_prompt_contracts(
        "基础提示",
        intent=intent,
        message=message,
        evidence=evidence or {},
        prompt_evidence=prompt_evidence or {},
        model_tier=model_tier,
        is_action_plan_request=is_action_plan_request,
    )


def test_general_research_keeps_base_prompt_without_special_contracts():
    assert _append(intent="general_research") == "基础提示"


def test_watchlist_brief_adds_fresh_synthesis_contract_only_when_requested():
    without_contract = _append(intent="watchlist_brief")
    with_contract = _append(
        intent="watchlist_brief",
        evidence={"answer_contract": {"version": 1}},
    )

    assert "自选股每日研究摘要的时间与证据合同" not in without_contract
    assert "自选股每日研究摘要的时间与证据合同" in with_contract
    assert "不是预生成报告的原文回放" in with_contract


def test_stock_price_move_gets_concise_same_day_evidence_contract():
    prompt = _append(
        intent="stock_research",
        message="中兴通讯7月24日为什么下跌？",
    )

    assert "标准解读要求" in prompt
    assert "个股涨跌原因回答合同" in prompt
    assert "same_date_official_disclosures" in prompt
    assert "标准回答控制在约 250—500 个中文字" in prompt


def test_action_plan_contract_is_controlled_by_explicit_router_decision():
    without_plan = _append(
        intent="stock_research",
        message="帮我分析中兴通讯",
        is_action_plan_request=False,
    )
    with_plan = _append(
        intent="stock_research",
        message="创建操作计划",
        is_action_plan_request=True,
    )

    assert "用户确认式操作计划要求" not in without_plan
    assert "用户确认式操作计划要求" in with_plan


def test_market_focus_adds_only_the_relevant_market_contract():
    prompt = _append(
        intent="market_brief",
        prompt_evidence={
            "question_focus": {"key": "sector_rotation"},
            "market_breadth": {"status": "available"},
        },
    )

    assert "大盘标准回答要求" in prompt
    assert "完整上涨、下跌、平盘家数" in prompt
    assert "涨跌原因回答必须按证据层级组织" not in prompt
