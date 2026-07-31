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
    assert "不使用 Markdown 小标题" in prompt
    assert "主要推力、主导力量、决定了个股方向" in prompt
    assert "证据不足时也不强行二选一" in prompt
    assert "解释了为什么跑输、压制弹性" in prompt
    assert "行业成分涨跌广度不是" in prompt
    assert "资金涌入白酒、板块受到资金关注" in prompt
    assert "不得扩大成\n“公司层面没有独立利好" in prompt
    assert "账面利润未获验证" in prompt
    assert "特别针对" in prompt
    assert "如果真有抛售盘面应该更明显" in prompt
    assert "结尾在当前分层结论处结束" in prompt


def test_stock_price_cause_followup_uses_three_natural_paragraph_contract():
    prompt = _append(
        intent="stock_research",
        message=(
            "那你现在最有把握能确认的两件事是什么？最不能确认的一件事是什么？"
            "不要重复所有数字，像继续聊天一样回答。"
        ),
        prompt_evidence={
            "research_plan": {
                "focus": "price_cause",
                "primary_focus": "price_cause",
                "contextual_followup": True,
                "effective_question": "北方国际7月30日上涨更像行业还是公司因素？",
            }
        },
    )

    assert "个股连续追问最后核对" in prompt
    assert "不是新的综合诊股" in prompt
    assert "不是在询问当前股价" in prompt
    assert "followup_answer_frame 是本轮唯一回答框架" in prompt
    assert "最终只写三个自然短段落" in prompt
    assert "不使用 Markdown 标题、编号、项目符号" in prompt
    assert "第一段只说第一件最有把握确认的事" in prompt
    assert "不要复述上一轮全部数字" in prompt
    assert "不得引入 MA60、MA20、RSI、MACD" in prompt
    assert "无法在行业和公司因素之间强行二选一" in prompt
    assert "不得扩大成“没有任何公司相关因素" in prompt
    assert "是否提前消化解禁" in prompt
    assert "不要用反问句列出新的原因候选" in prompt
    assert "绝不能由" in prompt
    assert "没有公司额外利空、卖压不突出" in prompt
    assert "不评价公告内容积极或消极" in prompt


def test_financial_quality_followup_stays_conversational_and_avoids_cash_labels():
    prompt = _append(
        intent="stock_research",
        message=(
            "你刚才说了很多数据，真正值得我改变判断的是哪两三件？"
            "哪些只是会计口径、报告期错位或者短期节奏？"
            "别重复整份财报，直接和我讲重点。"
        ),
        prompt_evidence={
            "research_plan": {
                "focus": "quality_review",
                "primary_focus": "quality_review",
                "contextual_followup": True,
            }
        },
    )

    assert "财报质量连续追问最后核对" in prompt
    assert "不是重写一份完整财报" in prompt
    assert "利润有无现金支撑、是否兑现、是否落袋" in prompt
    assert "不能直接解释当季利润变化" in prompt
    assert "本轮自然对话表达要求" in prompt
    assert "不要使用 Markdown 小标题、加粗标签、编号、项目符号" in prompt


def test_financial_quality_followup_obeys_exact_fact_count_without_third_section():
    prompt = _append(
        intent="stock_research",
        message=(
            "别再复述整份财报和所有数字。真正会改变你判断的两个事实是什么？"
            "如果只能继续跟踪一项，你选哪项，为什么？像我们接着聊。"
        ),
        prompt_evidence={
            "research_plan": {
                "focus": "quality_review",
                "primary_focus": "quality_review",
                "contextual_followup": True,
            }
        },
    )

    assert "正文必须恰好回答 2 个事实" in prompt
    assert "每个事实用一个自然段表达" in prompt
    assert "这句话不是第三个事实" in prompt
    assert "不得另起“补充线索”" in prompt
    assert "本轮自然对话表达要求" in prompt


def test_natural_analyst_style_request_uses_paragraphs_without_report_scaffolding():
    prompt = _append(
        intent="stock_research",
        message=(
            "中兴通讯最新财报到底好不好？像分析师和我聊天一样写，"
            "不要写成报告目录。"
        ),
        prompt_evidence={"research_plan": {"focus": "quality_review"}},
    )

    assert "本轮自然对话表达要求" in prompt
    assert "用连贯自然段组织" in prompt
    assert "不说“好，我们直接聊”" in prompt


def test_quality_review_uses_available_cashflow_company_explanation():
    prompt = _append(
        intent="stock_research",
        message="中兴通讯财报质量怎么样？请说明经营现金流。",
        prompt_evidence={"research_plan": {"focus": "quality_review"}},
    )

    assert "公司或管理层明确给出的解释" in prompt
    assert "公司原文已经解释变化时，明确写成公司口径" in prompt


def test_stock_price_cause_followup_can_answer_same_day_vs_slow_background():
    prompt = _append(
        intent="stock_research",
        message="哪些是7月30日当天事实，哪些只是慢变量背景？不要重复所有数字。",
        prompt_evidence={
            "research_plan": {
                "focus": "price_cause",
                "primary_focus": "price_cause",
                "contextual_followup": True,
            },
            "followup_answer_frame": {
                "requested_shape": "same_day_facts_vs_slow_variable_background"
            },
        },
    )

    assert "明确要区分“目标日当天事实”和" in prompt
    assert "最终写两到三个自然短段落" in prompt
    assert "第二段只用一句话概括 slow_variable_background" in prompt
    assert "最多保留一组" in prompt
    assert "行业资金涌入、资金流入板块" in prompt
    assert "不得把低于行业指数写成低于行业中位数" in prompt
    assert "最终只写三个自然短段落" not in prompt


def test_deep_price_move_contract_uses_publication_time_without_market_mind_reading():
    prompt = _append(
        intent="stock_research",
        model_tier="deep",
        message="北方国际7月30日上涨更像行业还是公司因素？请深度分析。",
    )

    assert "该公告在当天收盘后才公开" in prompt
    assert "交易时段内市场并不知晓" in prompt
    assert "限售股解禁通常意味着潜在抛压" in prompt
    assert "不得先插入目标日之后的 current_quote" in prompt
    assert "不得写“卖压不突出、跌幅被" in prompt
    assert "现金兑现尚可" in prompt


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


def test_deep_price_move_without_exact_industry_keeps_broad_indices_as_market():
    prompt = _append(
        intent="stock_research",
        model_tier="deep",
        message="北方国际为什么跌？请深度分析，信息量要大。",
        prompt_evidence={
            "stock_market_context": {
                "exact_industry_match_available": False,
                "exact_industry_index": {"status": "unavailable_for_target_date"},
            },
            "fundamentals": {"summary": {"report_date": "2026-03-31"}},
        },
    )

    assert "无法可靠比较行业因素" in prompt
    assert "代表性宽基指数只能称为市场对照" in prompt
    assert "不写“相对独立、独立行情、脱离市场”" in prompt
    assert "整个 A 股普跌" in prompt
    assert "已装配结构化财务与现金流证据" in prompt
    assert "成长股拖累较小" in prompt
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

    assert "大盘连续追问要求" in prompt
    assert "大盘标准回答要求" not in prompt
    assert "市场追问最后核对" in prompt
    assert "直接写两个完整短段落" in prompt
    assert "后续广度优势是否仍在" in prompt
    assert "只能说参与面变窄" in prompt
    assert "不补写情绪、买盘、底座或风格故事" in prompt
    assert "不决定所谓“修复动力”或“宽度支撑”" in prompt
    assert "不写反弹、同步回升节奏或已经持续数日" in prompt
    assert "主要指数与已有 MA20 的关系是否改善" in prompt
    assert "MA20 不是市场平均持仓成本" in prompt
    assert "不写“被均线压住、挡回来”" in prompt
    assert "不增加成交额、资讯、第三个变量" in prompt
    assert "回答必须以完整句子结束" in prompt


def test_market_experience_gap_uses_breadth_without_style_story():
    prompt = _append(
        intent="market_brief",
        message=(
            "今天为什么指数表现和大多数个股的体感不一样？"
            "请结合成交额自然回答。"
        ),
        prompt_evidence={
            "question_focus": {"key": "volume_flows"},
            "market_breadth": {"turnover": {"status": "available"}},
        },
    )

    assert "指数与多数个股体感差异回答要求" in prompt
    assert "用四个自然段直接交流" in prompt
    assert "成分权重贡献数据" in prompt
    assert "什么成分拖低或抬高了指数" in prompt
    assert "也不补写银行、保险、大盘蓝筹或权重股当天表现" in prompt
    assert "不能外推为每位投资者的账户" in prompt
    assert "不能说某个指数涨幅“落在个股分布底部" in prompt
    assert "不要说成交额与盘面“形成呼应”" in prompt
    assert "投资者可以安心、真实赚钱效应、账户普遍赚钱" in prompt
    assert "大盘标准回答要求" not in prompt
    assert "本轮市场结论最后核对" not in prompt


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

    assert "若公司已经解释库存增加或费用变化" in prompt
    assert "直接引用为公司口径" in prompt
    assert "不要" in prompt and "再次追加同一解释" in prompt
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
    assert "不得自行扩写成“53度飞天茅台”" in prompt
    assert "不得自行列举王子酒" in prompt
    assert "不得凭常识补写高端、中端" in prompt
    assert "不得把合计100%写成“前三大产品" in prompt
    assert "不得改写成\n“单位利润、每瓶利润" in prompt
    assert "比较两个分部时只说毛利率更高" in prompt
    assert "普通对话默认写两到三个自然段" in prompt
    assert "不要无关切换到投资适当性" in prompt
    assert "也不要邀请用户讨论“适不适合自己”" in prompt


def test_stock_research_business_focus_uses_business_contract_too():
    prompt = _append(
        intent="stock_research",
        message="先不谈涨跌，这家公司靠什么业务赚钱？",
        prompt_evidence={"research_plan": {"focus": "business"}},
    )

    assert "主营业务专项回答要求" in prompt
    assert "所有分部名称必须逐字沿用证据标签" in prompt


def test_business_structure_contract_must_answer_explicit_inference_limits():
    prompt = _append(
        intent="business_structure",
        message="收入结构变化说明了什么，哪些结论不能直接推出？",
    )

    assert "没有同行或行业分部基准时" in prompt
    assert "不得评价某项毛利率“在行业里" in prompt
    assert "这一问不得漏答" in prompt
    assert "最后一个自然段必须直接说明至少两项边界" in prompt
    assert "收入集中度上升不等于经营风险已经发生" in prompt


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
    assert "现金流回答要求" in prompt
    assert "至少说明经营现金流净额及其可比变化" in prompt
    assert "不必机械列全" in prompt
    assert "不把它们合并成“利润真假、回款恶化、现金效率”结论" in prompt
    assert "静态反事实利润桥" in prompt
    assert "静态测算" in prompt
    assert "不要单独生成一份现金流指标报告" in prompt
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

    assert "现金流回答要求" in prompt
    assert "经营现金流净额及其可比变化" in prompt


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


def test_quality_review_contract_prioritizes_natural_evidence_discussion():
    prompt = _append(
        intent="stock_research",
        message="经营改善候选的改善是否有质量？",
        prompt_evidence={"research_plan": {"focus": "quality_review"}},
    )

    assert "经营改善质量：自然分析要求" in prompt
    assert "不要强制固定四段、固定标题或固定顺序" in prompt
    assert "同一事实和同一公司解释只说一次" in prompt
    assert "选择最能回答本题的数字" in prompt
    assert "不必为满足模板把三组两期值全部塞进正文" in prompt
    assert "不要" in prompt and "再次追加同一解释" in prompt
    assert "输出前自然度核对" in prompt
    assert "不要为了核对补固定句式" in prompt
    assert prompt.rfind("输出前自然度核对") > prompt.rfind("财务问题必答字段")


def test_business_growth_contract_uses_segment_evidence_without_report_outline():
    prompt = _append(
        intent="stock_research",
        message="这半年增长靠什么，储能是不是第二增长曲线？别写报告。",
        prompt_evidence={"research_plan": {"focus": "business_growth"}},
    )

    assert "主营增长逻辑：自然分析要求" in prompt
    assert "优先使用 business_structure" in prompt
    assert "不得用公司整体营收增速替代某个分部的增长证据" in prompt
    assert "不报股价，不写分析师预期" in prompt
    assert "不使用编号、固定栏目" in prompt
    assert "不概括成“赚钱效率下降”" in prompt
    assert "不写“量撑价跌、价和利下降、量价齐升”" in prompt
    assert "不写“跟着行业" in prompt


def test_business_structure_growth_focus_uses_growth_contract_only():
    prompt = _append(
        intent="business_structure",
        message="这半年增长靠什么，储能算第二增长曲线了吗？",
        prompt_evidence={"research_plan": {"focus": "business_growth"}},
    )

    assert "主营增长逻辑：自然分析要求" in prompt
    assert "主营业务专项回答要求" not in prompt
    assert "不写数据抓取日期或取数时间" in prompt
    assert "“有三点”" in prompt


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
