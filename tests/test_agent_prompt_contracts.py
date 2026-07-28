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


def test_general_research_adds_financial_advisor_contract():
    prompt = _append(
        intent="general_research",
        message="基金和ETF有什么区别，哪个更适合我？",
    )

    assert "金融顾问与教育者回答要求" in prompt
    assert "第一段先直接回答用户当前问题" in prompt
    assert "底层资产、收益" in prompt
    assert "主要亏损方式、流动性、费用" in prompt
    assert "最多追问两个问题" in prompt
    assert "年龄和资金金额" in prompt
    assert "都不能单独决定适合性" in prompt
    assert "不得为了举例自行创造百分比、金额、持有年限" in prompt
    assert "不要先声称" in prompt
    assert "必须先读取 financial_advisor_context" in prompt
    assert "不得根据退休或年龄推断用户没有工资收入" in prompt


def test_confirmed_profile_contract_uses_known_facts_without_reasking() -> None:
    prompt = _append(
        intent="general_research",
        prompt_evidence={
            "financial_advisor_context": {
                "status": "needs_profile",
                "provided_fields": ["资金使用时间", "可接受回撤"],
                "missing_fields": ["已有资产"],
                "confirmed_risk_profile": {"version_no": 1},
            }
        },
    )

    assert "不得说“没有确认风险画像”" in prompt
    assert "不得重新追问 provided_fields" in prompt
    assert "再从 missing_fields 中最多追问两个" in prompt
    assert "产品类型最多列三类" in prompt
    assert "不要扩写成产品百科" in prompt


def test_fund_etf_concept_contract_preserves_category_and_rule_boundaries() -> None:
    prompt = _append(
        intent="general_research",
        message="基金和ETF到底是什么关系？ETF是不是一定到账更快？",
        prompt_evidence={
            "financial_advisor_context": {"status": "concept_only"}
        },
    )

    assert "基金与ETF概念精度合同" in prompt
    assert "ETF是基金的一种" in prompt
    assert "不得把“基金”和ETF写成两个互斥类别" in prompt
    assert "常见场外开放式基金与场内ETF" in prompt
    assert "按交易日基金净值确认申购赎回" in prompt
    assert "一天只有一个净值" in prompt
    assert "不得写“价格每一秒变化”" in prompt
    assert "不得写成卖出后一定更快到账" in prompt
    assert "几个工作日" in prompt
    assert "180—320个中文字" in prompt
    assert "不增加汽车等类比" in prompt
    assert "不为凑结构强制列满三项" in prompt
    assert "不得泛称" in prompt
    assert "纯概念问题" in prompt
    assert "不追问风险画像" in prompt


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
    assert "不得以“同日价格与市场对照”" in prompt
    assert "没有内容的部分直接省略" in prompt
    assert "市场买卖力量自然变化" in prompt
    assert "不得据此安慰用户“不必担心、公司没事”" in prompt
    assert '禁止写“更像行业普跌中的跟随' in prompt


def test_stock_research_separates_official_and_media_sources_without_fixed_counts():
    prompt = _append(
        intent="stock_research",
        message="中兴通讯现在最需要关注什么？",
    )

    assert "个股证据表达一致性" in prompt
    assert "不能在列出正式披露后又把整组材料统称为“媒体线索”" in prompt
    assert "不要在正文前预告“以下三项、最核心的三个证据”等固定数量" in prompt
    assert "正文不得照搬这些称呼" in prompt
    assert "从风险角度看" in prompt


def test_market_cause_answers_before_explaining_evidence_layers():
    prompt = _append(
        intent="market_brief",
        message="美股为什么收盘跌了？",
        prompt_evidence={"question_focus": {"key": "market_cause"}},
    )

    assert "第一段先用普通投资者能看懂的话直接说明" in prompt
    assert "涨跌原因回答必须先给结论" in prompt
    assert "第一传达句必须直接回答“为什么”" in prompt
    assert "第一传达句不得只罗列日期、指数名称和涨跌幅" in prompt
    assert "不要为满足模板单列空洞反方栏目" in prompt


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
