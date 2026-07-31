from app.services.agent_prompt_contracts import append_prompt_contracts


def _append(
    *,
    intent: str,
    message: str = "测试问题",
    evidence: dict | None = None,
    prompt_evidence: dict | None = None,
    model_tier: str = "economy",
    is_action_plan_request: bool = False,
    conversation_history: list[dict] | None = None,
) -> str:
    return append_prompt_contracts(
        "基础提示",
        intent=intent,
        message=message,
        evidence=evidence or {},
        prompt_evidence=prompt_evidence or {},
        model_tier=model_tier,
        is_action_plan_request=is_action_plan_request,
        conversation_history=conversation_history,
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
        prompt_evidence={"financial_advisor_context": {"status": "concept_only"}},
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
    assert "direct_excerpt" in prompt
    assert "公司披露口径" in prompt
    assert "标准回答控制在约 250—500 个中文字" in prompt
    assert "不得以“同日价格与市场对照”" in prompt
    assert "没有内容的部分直接省略" in prompt
    assert "市场买卖力量自然变化" in prompt
    assert "不得据此安慰用户“不必担心、公司没事”" in prompt
    assert "禁止写“更像行业普跌中的跟随" in prompt


def test_stock_price_move_detects_deep_causal_comparison_wording():
    prompt = _append(
        intent="stock_research",
        model_tier="deep",
        message=(
            "请深度分析中兴通讯最近这次下跌：究竟更像行业拖累、"
            "公司基本面压力，还是市场情绪？信息量要大。"
        ),
    )

    assert "个股涨跌原因回答合同（深度）" in prompt
    assert "本轮结论最后核对" in prompt
    assert "这是用户明确要求的深度分析" in prompt
    assert "基本面是背景，近期直接驱动若无" in prompt
    assert "700—1100 个中文字" in prompt
    assert "最多使用两个自然小标题" in prompt
    assert "主要推力、主导力量、决定了个股方向" in prompt
    assert "证据不足时也不强行二选一" in prompt
    assert "解释了为什么跑输、压制弹性" in prompt
    assert "账面利润未获验证" in prompt
    assert "特别针对" in prompt
    assert "结尾在当前分层结论处结束" in prompt


def test_explicit_deep_stock_question_uses_deep_contract_on_economy_tier():
    prompt = _append(
        intent="stock_research",
        model_tier="economy",
        message=(
            "请深度分析中兴通讯今天的涨跌究竟更像行业因素还是公司因素，"
            "结合财务和现金流，信息量充分。"
        ),
    )

    assert "个股涨跌原因回答合同（深度）" in prompt
    assert "这是用户明确要求的深度分析" in prompt
    assert "700—1100 个中文字" in prompt
    assert "标准回答控制在约 250—500 个中文字" not in prompt
    assert "不能在行业和公司之间强行二选一" in prompt


def test_market_followup_adds_short_final_quality_check():
    prompt = _append(
        intent="market_brief",
        message="接下来最值得看什么？不要重复上一轮。",
        conversation_history=[
            {"role": "user", "content": "今天为什么反弹？"},
            {"role": "assistant", "content": "市场广度明显修复。"},
        ],
    )

    assert "市场追问最后核对" in prompt
    assert "旧的资讯标题不能被改造成未来观察指标" in prompt
    assert "不写权重托底、中小市值跟随或市场轮动" in prompt
    assert "不要使用小标题" in prompt
    assert "不得再引用具体上涨下跌家数、比例或成交额" in prompt
    assert "不增加第三项量能观察" in prompt
    assert "不得使用单日修复、情绪回暖、持续性存疑" in prompt
    assert "不要使用“涨跌各半、持续压倒、站稳、受阻、碰一下又被压回”" in prompt
    assert "主要指数与 MA20 的关系是否改善" in prompt


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


def test_quality_review_prompt_must_not_deny_explicit_inventory_explanation():
    prompt = _append(
        intent="stock_research",
        message="这家公司为什么进入经营改善候选？库存变化怎么理解？",
        prompt_evidence={"research_plan": {"focus": "quality_review"}},
    )

    assert "库存增加主要是为下半年市场需求" in prompt
    assert "而提前备货" in prompt
    assert "不得再写“公司未解释、原文未说明" in prompt
    assert "原因仍完全" in prompt
    assert "库存分类、库龄、订单覆盖和跌价准备" in prompt
    assert "边界提醒：边界提醒" in prompt
    assert "不得据标题自行写成“资金面压力" in prompt
    assert "不得反向写成“常规安排、正常融资" in prompt
    assert "只能说明披露存在、标题证据能确认的事项" in prompt
    assert "return_*d_base_date" in prompt
    assert "不得写成“窗口之前、偏早" in prompt
    assert "同一项披露只列一次" in prompt
    assert "不得换成“市场持续担忧" in prompt
    assert "不主动加入社区情绪、股吧样本" in prompt


def test_business_structure_contract_separates_dimensions_and_neutral_labels():
    prompt = _append(
        intent="business_structure",
        message="北方国际靠什么业务赚钱？",
    )

    assert "主营业务专项回答要求" in prompt
    assert "不得升级为“盈利能力改善”" in prompt
    assert "不得改称净利润、最终利润" in prompt
    assert "不得自行增加采购、运输等环节" in prompt
    assert "产品、地区和行业是三套独立维度" in prompt
    assert "不得合并成“境外工程" in prompt


def test_bound_screening_cashflow_question_preserves_snapshot_and_requires_cashflow():
    prompt = _append(
        intent="stock_research",
        message="这次回撤和财务、现金流、借款公告有什么关系，近5日走平能不能算企稳？",
        prompt_evidence={
            "stock_workspace_context": {
                "research_entry": {
                    "as_of_date": "2026-07-28",
                    "matched_reasons": ["近20日收益 -8.04%"],
                }
            }
        },
    )

    assert "进入研究空间时的筛选快照" in prompt
    assert "存在同日口径冲突" in prompt
    assert "不能擅自挑一个称为" in prompt
    assert "现金流问题必须直接作答" in prompt
    assert "本期经营现金流金额、可比期或" in prompt
    assert "不得只讨论营收、利润、财务费用或借款公告后跳过现金流" in prompt
    assert "不能据此概括为“盈利质量没有恶化" in prompt
    assert "不得把覆盖倍数改写成“利润有现金支撑" in prompt
    assert "金额下降而覆盖率上升时" in prompt
    assert "覆盖关系没有恶化" in prompt
    assert "比率上升也可能来自净利润下降更快" in prompt
    assert "不得把增加部分解释成借款利息、汇兑损失" in prompt
    assert "calculation_nature=static_counterfactual" in prompt
    assert "收入下降直接拉低毛利" in prompt
    assert "不得自动改写成" in prompt
    assert "回款节奏改善" in prompt
    assert "公司实际收到的钱少了" in prompt
    assert "财务问题必答字段" in prompt
    assert "至少给出营收同比与归母净利润同比" in prompt
    assert "企稳问题直接回答要求" in prompt
    assert "不得把中期偏弱改写成“下行趋势仍未改变”" in prompt
    assert "不要只给“等待均线和成交量" in prompt
    assert "不能写成确认企稳的必要或充分条件" in prompt
    assert "不得写“企稳至少需要" in prompt
    assert "不是预设的必过门槛" in prompt
    assert "只表示该收益窗口起止收盘价大致" in prompt
    assert "抛压减弱、多空打平" in prompt
    assert "不使用滚下山、喘息、打仗等类比" in prompt


def test_stock_followup_inherits_cashflow_contract_from_recent_user_question():
    prompt = _append(
        intent="stock_research",
        message="请继续说明这些财务压力能确认什么。",
        conversation_history=[
            {
                "role": "user",
                "content": "这次回撤与财务、经营现金流和公司事件有什么关系？",
            },
            {
                "role": "user",
                "content": "请继续说明这些财务压力能确认什么。",
            },
        ],
    )

    assert "现金流问题必须直接作答" in prompt
    assert "经营现金流金额、可比变化和覆盖关系" in prompt


def test_peer_valuation_contract_requires_compact_decision_facts() -> None:
    prompt = _append(
        intent="stock_research",
        message="宁德时代的PE和PB相对同行处于什么位置？",
        prompt_evidence={
            "user_question": "宁德时代的PE和PB相对同行处于什么位置？",
            "peer_comparison": {
                "metrics": {
                    "pe_ttm": {"subject_value": 21.27, "peer_median": 26.24},
                    "pb": {"subject_value": 4.77, "peer_median": 1.71},
                },
                "peers": [
                    {"name": "亿纬锂能", "pe_ttm": 26.24, "pb": 2.72},
                    {"name": "国轩高科", "pe_ttm": 21.3, "pb": 1.71},
                    {"name": "欣旺达", "pe_ttm": 42.32, "pb": 1.36},
                ],
            },
        },
    )

    assert "固定同行估值回答要求" in prompt
    assert "写清同行样本" in prompt
    assert "不必机械罗列每家公司全部倍数" in prompt
    assert "本标的数值和同行中位数" in prompt
    assert "相对比例不是必答项，只在有助于解释时自然补充" in prompt
    assert "相对比例不是必答项" in prompt
    assert "不得因为同报告期经营" in prompt
    assert "数据不足而声称同行估值没有取得" in prompt
    assert "估值没有取得或拒绝比较数值" in prompt


def test_valuation_review_contract_separates_pe_eps_units_and_disclosures() -> None:
    prompt = _append(
        intent="stock_research",
        message="动力新科为什么进入估值约束候选？是否存在低估值陷阱？",
        prompt_evidence={
            "research_plan": {"focus": "valuation_review"},
            "peer_comparison": {
                "method": "dynamic_same_day_peer_valuation_snapshot_v1",
                "metrics": {
                    "pe_ttm": {"subject_value": 2.43, "peer_median": 10.0},
                    "pb": {"subject_value": 1.18, "peer_median": 1.5},
                },
                "peers": [
                    {"name": "上汽集团", "pe_ttm": 8.0, "pb": 0.8},
                    {"name": "潍柴动力", "pe_ttm": 10.0, "pb": 1.5},
                    {"name": "长安汽车", "pe_ttm": 12.0, "pb": 1.9},
                ],
            },
        },
    )

    assert "估值约束专项：优先回答质量与自然表达" in prompt
    assert "不必套标题或复述筛选规则" in prompt
    assert "不设固定段落、标题数量或字数" in prompt
    assert "由某种盈利质量支撑、来自某种业务矛盾" in prompt
    assert "当前低倍数与哪些" in prompt
    assert "PE TTM、动态 PE、静态 PE 是不同估值口径" in prompt
    assert "PE TTM 是滚动十二个月口径" in prompt
    assert "不能用一季报、单季净利润" in prompt
    assert "每股收益使用“元/股”" in prompt
    assert "不猜测利润来源" in prompt
    assert "同日同行估值回答要求" in prompt
    assert "同一行业标签和市值接近度" in prompt
    assert "不必逐家公司罗列所有倍数" in prompt
    assert "回款缺口扩大、回款恶化" in prompt
    assert "不要先" in prompt and "表面上负债压力减轻" in prompt
    assert "没有绝对额证据时猜测资产扩张" in prompt
    assert "不外推为盈利持续" in prompt
    assert "最终输出一版连贯、有信息量" in prompt
    assert "估值回答最后核对" in prompt
    assert "低 PE 不能由盈利很薄、历史亏损" in prompt
    assert "不要为了满足核对增加标题" in prompt
    assert prompt.rfind("估值回答最后核对") > prompt.rfind("财务问题必答字段")


def test_quality_review_contract_blocks_price_and_debt_overinterpretation():
    prompt = _append(
        intent="stock_research",
        message="经营改善候选的改善是否有质量？",
        prompt_evidence={"research_plan": {"focus": "quality_review"}},
    )

    assert "经营改善质量专项回答合同" in prompt
    assert "改善质量较强、一般，或仍无法确认" in prompt
    assert "不得把上升改写成借款增加" in prompt
    assert "年报主营结构只可作为最近可得的业务基线" in prompt
    assert "不能直接认定一次性收益" in prompt
    assert "市场没有认可、尚未定价" in prompt
    assert "小标题不要预告固定数量" in prompt
    assert "不得写“利润增长依赖收入规模扩张”" in prompt
    assert "不得概括为“现金兑现效率走弱" in prompt
    assert "升级为该业务“盈利能力下降”" in prompt
    assert "不得称为“结构优化、结构升级或结构改善”" in prompt
    assert "不是同行或行业整体毛利率" in prompt
    assert "本期净利润同比增长时不得写“增收不增利”" in prompt
    assert "不得写成产品积压、出货放缓、去库压力" in prompt
    assert "不得称为“几乎/近乎停滞”" in prompt
    assert "几乎原地踏步" in prompt
    assert "收入转化为现金的效率出现落差" in prompt
    assert "收入增长没有转化为现金流入" in prompt
    assert "利润转化为现金的效率减弱" in prompt
    assert "本期经营现金流金额及同比" in prompt
    assert "存货分类、库龄和存货跌价准备" in prompt
    assert "不列“可能涉及库存节奏、备货因素" in prompt
    assert "不得写成当前变化“可能受这些因素影响”" in prompt
    assert "不得写收入增长拉动" in prompt
    assert "量增价减" in prompt
    assert "公司公告原文摘录" in prompt
    assert "不能判断改善质量是否优于行业" in prompt
    assert "输出前最后核对" in prompt
    assert "最终只输出一版连贯回答" in prompt
    assert "第一句必须以当前公司的中文名称开头" in prompt
    assert prompt.rfind("输出前最后核对") > prompt.rfind("财务问题必答字段")


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


def test_market_risk_question_with_why_keeps_cause_contract_and_final_check():
    prompt = _append(
        intent="market_brief",
        message="今天为什么和昨天反差这么大，并说明什么时候需要重新判断？",
        prompt_evidence={
            "question_focus": {"key": "market_risk"},
            "market_drivers": {"items": [{"title": "板块分化线索"}]},
        },
    )

    assert "涨跌原因回答必须先给结论" in prompt
    assert "不强制引用风险提示标题" in prompt
    assert "本轮市场结论最后核对" in prompt
    assert "不得把盘中反弹命名为技术性修复" in prompt
    assert "最终只写四个自然短段落" in prompt
    assert "700—950 个中文字" in prompt
    assert "技术性回补、超跌反弹、抛压释放" in prompt
    assert "情绪性逆转、单日修复、情绪整体回暖" in prompt
    assert "若今天的触发事件未取得" in prompt
    assert "盘中时间序列" in prompt
    assert "情绪释放式单日波动" in prompt
    assert "不要自行添加“六大指数、四个核心指数”等固定数量标签" in prompt
    assert "previous_return_1d_pct" in prompt
    assert "不能只用“此前同步下跌”代替数字" in prompt
    assert "不得罗列“几个来源、多少条来源”等检索统计" in prompt
    assert "不能在没有权重贡献证据时推出“并非权重股拉动”" in prompt
    assert "不切换到 MA60，不列均线点位" in prompt
    assert "不能再补“更像系统性抛售后的回弹" in prompt
    assert "不能写交易意愿回升" in prompt
    assert "只说“四个核心指数同步下跌”" not in prompt


def test_relative_industry_contract_hides_unselected_modules_and_fixed_day_thresholds():
    prompt = _append(
        intent="stock_research",
        message="宁德时代相对电池行业是增强还是走弱？",
        prompt_evidence={"research_plan": {"focus": "relative_industry"}},
    )

    assert "相对行业表现专项回答合同" in prompt
    assert "不得向用户展示“尚未接入、未接入" in prompt
    assert "固定天数门槛" in prompt
    assert "财务、存货、销售收现率机械堆进" in prompt
    assert "不是成分排名" in prompt
    assert "metrics.return_60d_pct" in prompt
    assert "必须直接使用 stock_minus_industry_pct" in prompt
    assert "后续交易日只形成新的同日判断" in prompt
    assert "持续多个" in prompt


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
