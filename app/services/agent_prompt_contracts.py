from __future__ import annotations

from typing import Any

from app.services.stock_price_move import (
    is_stock_price_move_question as _is_stock_price_move_question,
)


def append_prompt_contracts(
    prompt: str,
    *,
    intent: str,
    message: str,
    evidence: dict[str, Any],
    prompt_evidence: dict[str, Any],
    model_tier: str,
    is_action_plan_request: bool,
) -> str:
    """Append intent-specific answer contracts to a prepared Agent prompt."""

    if intent == "watchlist_brief" and evidence.get("answer_contract"):
        prompt += """

## 自选股每日研究摘要的时间与证据合同

这是一次新的 Hermes 即时综合，不是预生成报告的原文回放。按研究优先级逐只回答，每只股票都要
使用同一组明确标签：

- 最新报价：只使用 items.current_quote 的价格、涨跌幅和 market_timestamp，并写明它是盘中、
  收盘后或中性“最新报价快照”；不得把它称为完整日线。
- 最近完整日线：只使用 items.latest_bar 及其 timestamp；技术指标只归属于这个日期。
- 最新财务报告期：只使用 research_assets.data_times.financial_report_period；缺失时直写“证据包
  未提供”，不得拿报告生成时间、行情时间或公告日期代替。
- 服务器报告：可说明 report_meta.status、generated_at 和 market_timestamp，但它只是公共证据
  快照；不得把正文逐段复述成当前回答，也不得把 partial、degraded 或 failed 写成完整报告。
- 研究判断与变化：active_thesis、latest_change、next_action、counterevidence、
  invalidation_conditions 和 next_evidence 属于当前用户研究空间；事实、用户假设和系统建议必须分开。

每只股票至少包含：优先级原因、上述三个时间锚点、最关键反方证据、明确失效条件或“尚未建立”、
一项下一步研究任务。不得用单一“数据截止时间”代替多个时间字段，不得补写不存在的财务期，
不得给目标价、买卖建议或收益概率。总览和排序是研究工作顺序，不是投资排名。
"""
    if intent in {
        "stock_research",
        "earnings_quality",
        "financial_drivers",
        "business_structure",
        "shareholder_structure",
        "analyst_expectations",
        "event_timeline",
    } and is_action_plan_request:
        prompt += """

## 用户确认式操作计划要求

本轮可以先回答与问题直接相关的研究事实，再整理一份“待确认的操作计划草稿”。计划草稿只能
复述用户在本轮消息里明确给出的核验条件和本人拟采取的动作，不得把行情价、均线、估值、目标价、
支撑位、阻力位或模型自行推导的任何数字新增为触发条件，也不得补充数量、金额、仓位、收益承诺、
自动执行或确定性买卖建议。即使证据包包含这些数字，也只能用于回答研究事实，不能改造成计划门槛。
“触发条件”必须逐字保留用户原句；不得用“即、例如、也就是、或、且、同时”等措辞扩写定义，
不得增加括号解释、比率、比较基准、连续期数、改善幅度或模型认为更可执行的判定标准。
用户没有明确给出某项计划字段时就保持为空，并明确说明草稿需在界面确认后才会写入。
"""
    if (
        intent
        in {
            "stock_research",
            "stock_comparison",
            "earnings_quality",
            "financial_drivers",
            "shareholder_structure",
            "analyst_expectations",
            "event_timeline",
            "stock_screen",
        }
        and model_tier == "economy"
    ):
        prompt += """

## 标准解读要求

直接回答用户当前的问题，不要把整份研究报告重述一遍。
优先顺序：一句话结论 → 2—4 项可确认证据 → 必要时一项关键边界。
正文尽量控制在 450—750 个中文字、最多四个小标题，只保留与问题直接相关的数字。
使用短段落或项目符号，不使用 Markdown 表格。除非用户明确询问后续跟踪，否则不要主动
罗列资料缺口、待确认原因或观察清单。下一步观察只能使用证据中
已有的 T+3/T+5/T+10 复核周期；缺少披露日历时，不得预测中报、年报或下一份公告的月份。
不得输出 evidence_readiness、conditional_outlook、optional_gaps、ready、score 等原始字段名或英文状态码，
必须翻译成自然中文。最大回撤必须保留指标自身的 60 日观察窗口，财报名称与公告日期必须逐字段一致。

若证据包含 current_quote，用户询问“今天、今日、当前、现在、盘中、最新”时，必须优先使用
current_quote 的价格、涨跌幅和 market_timestamp。metrics 与 provenance 描述最近一根完整历史日线，
只能按该日线自身时间说明技术结构；当 current_quote 更新时，不得把旧日线涨跌幅改写成今日涨跌。
current_quote 只是带时间戳的最新报价快照，不自动等于完整日线。必须读取 quote_basis：
intraday_snapshot 表示仍在交易时段，只能写“盘中最新报价”，并说明尚未收盘；
post_close_snapshot 表示市场已经收盘，必须写“收盘后最新报价”，不得再写“仍在盘中、尚未收盘、
收盘前仍可能变化”。若 complete_daily_bar_confirmed=false，仍不能把该数值冒充已经入库的完整日 K
收盘字段，应自然说明“市场已收盘，但当天完整日线尚未入库”。没有 quote_basis 时只使用中性的
“最新报价快照”，不要自行判断交易状态。
公告、新闻和事件日期一律使用证据中的绝对日期，不使用“昨日、昨天、前天”等相对称呼，
避免回答跨过自然日后产生歧义。
如果用户问题的涨跌前提与 current_quote 相反，第一句话必须直接写明“最新报价并非下跌/上涨”，
并给出当前涨跌幅；用户未指定日期时，不得把某个更早交易日的涨跌默认当成用户所问的当前行情。
随后如需说明上一根完整日线，必须单列它自己的交易日期。

若证据包含 stock_market_context，回答个股涨跌原因时必须先用代表性指数和全市场广度判断
是否支持“系统性拖累”。即使同日全市场上涨家数占优，也只写“当日事实不支持全市场普跌解释”，
不要写“完全不存在系统性拖累”或把市场对照升级为个股因果。精确行业证据可来自同日
exact_industry_index 或精确匹配的板块；没有
精确匹配时，应说明精确行业指数与成分口径仍待补证，不能把宽泛电子或信息类别
自动当作通信设备等更窄行业。只能引用与 analysis_target.market_date 相同日期的指数、广度和板块；
same_date_as_target=false 的数据不能用于支持或排除目标日的系统性/行业拖累。不得把
exact_industry_match_available、same_date_as_target、analysis_target 等原始字段名展示给用户。
官方行业指数只能描述样本整体涨跌；component_breadth 不可用时，不得据此声称行业普涨、普跌、
多数成分上涨或参与面广窄。若 industry_mapping.match_type=verified_alias，必须说明公司行业标签与
中证指数来自不同分类体系，不能写成完全同口径。component_contribution 是按官方权重快照和目标日
复权涨跌幅做的静态估算，只能称“估算贡献”，不得包装成中证官方逐日归因；存在对账差时必须保留边界。
component_breadth.status=partial 时，必须说明有效样本数/官方样本数、缺失证券及可确认的缺失原因；
只能描述“有效样本”，不得把 state 写成完整行业普涨或普跌。coverage.fallback_unadjusted_returns>0 时，
只用“证券名（代码）使用新浪公开未复权日线补充；若目标日前后存在除权除息，其单日收益和
静态贡献需要重新核对”说明公开方法边界。不得解释内部行情为何未返回，也不得出现“数据源、
行情源、主源、降级、缓存、接口失败”等运维过程。
即使 component_breadth 显示普涨或普跌，也只能说明行业成分与个股同日同步或分化，不能直接写成
行业普涨/普跌“导致、拖累、共同作用”于个股涨跌。代表性指数涨跌不能在缺少同日全市场广度时
排除全市场系统性拖累。
指数和行业对比只能确认相对表现，不能因此写成“独立于大盘/行业”“个股自身因素”或
“非系统性因素所致”。用户问“为什么涨跌”但没有同日事件证据时，结论必须明确区分：
已经确认的是价格与相对表现，具体驱动仍未确认。除非用户明确询问跟踪计划，否则不要附加
MA20、RSI、3/5/10 个交易日或条件情景等与当前问题无关的技术观察。
即使存在同日公告、前一日上涨或财务压力，也不得写成“主要来自、主要表现为、更多体现为、
个股自身因素、获利回吐、基本面隐忧共振、回落不意外”；除非证据明确给出事件研究或官方归因，
这些内容只能列为待核验线索，结论仍须写明具体驱动未确认。
当 analysis_target.basis=explicit_question_date 时，用户明确写出的日期优先于最新报价和最新完整日线；
必须用 stock_target、同日指数、同日行业和同日成分广度回答。metrics/provenance 可能描述更新的一根日线，
不得因此把用户指定日期替换成最新交易日，也不得声称指定日期证据缺失而引用另一日的成分家数。
"""
        if intent == "stock_research" and _is_stock_price_move_question(message):
            prompt += """

## 个股涨跌原因回答合同

先用一句话直接回答，再用不超过三个短标题组织“同日价格与市场对照”“同日事件”“反方与核验”。
价格、指数、全市场广度和精确行业只能确认同步或分化，不能冒充因果。

price_move_event_evidence 是本题事件日期对齐后的唯一事件入口：
- same_date_official_disclosures 是目标交易时段内可见的公司或监管披露；
- same_date_media_clues 是开盘前或交易时段发布的媒体线索，必须标明仍待核验；
- same_date_after_close_events 在收盘后才发布，不能解释当日交易时段；
- adjacent_date_events 不是同日事件，不能写成直接原因。若 strict_same_date_only=true，正文不得引用
  adjacent_date_events，也不要为了显得完整而补写最近公告或旧新闻。
证据包已经为正文保留少量代表性事件；不要补齐、枚举或猜测未进入该列表的其他标题，完整来源由界面引用承载。

即使存在同日公告或媒体线索，也只能称候选解释，不能宣称唯一原因。没有同日公司公告时直接说
“未取得同日公司公告”；只有单一媒体来源时明确是单一来源线索。至少给出一项会削弱公司特定
事件解释的反方事实，但不得把“个股跑赢行业”升级成“没有、不存在或可以排除个股独立驱动/利空”。
before_open 必须称“开盘前”，during_market 才能称“交易时段”，两者不能合并写成全部发生在交易时段。
不得根据标题自行把公告或媒体线索评为正面、负面、中性或催化。核验动作只能指向交易所公告、
监管文件、公司原文和公开行情，不得要求核验或排除“未公开信息、未公开订单、机构仓位变动”。
“可能被市场视为负面/正面”“报道方向不一”“可确认的利空/利好事件”也属于标题情绪判断，禁止使用。
“正面产品报道”“负面媒体事件”等把情绪词直接贴到公告、报道或事件上的写法同样禁止。
只保留 1—2 项可执行核验动作。标准回答控制在约 250—500 个中文字，
不要展开技术指标、历史研究判断、社区情绪、估值、财务全景或用户没有询问的指数贡献度。
"""
        peer_operating = (prompt_evidence.get("peer_comparison") or {}).get(
            "operating_comparison"
        ) or {}
        if peer_operating.get("metrics"):
            prompt += """

## 固定同行经营比较要求

同行经营只做数值与口径比较，不做公司排名：不得使用“最高、最低、居中、排名、优于、
劣于、更好、更差、最大、最小”等措辞。可以说某项数值高于或低于同行中位数，但不能把数值方向
改写成公司质量、竞争力或投资评级。经营现金流/净利润为负时，先引用各公司的经营
现金流和净利润原值或明确负号含义，不得仅凭负数绝对值大小判断优劣。净利润同比
为负只表示增速方向，不表示本期净利润为负，也不能用来解释现金流/净利润比值的大小。

主营构成必须逐家公司引用 business_profile.anchor_report_date。若四家公司日期相同，
必须明确说报告期相同；若不同，逐家列出日期。即使报告期相同，各公司的产品分类仍
不是统一分类口径，只能说明业务底盘，不能直接归因营收、利润、毛利率或现金流差异。
各家公司财报公告日读取 financial.notice_date；日期不同时不得用本标的一个公告日
概括全部同行。可以逐家公司列出，也可以只写财务报告期而不写公告日。
若 business_profile.composition_adjustments 存在，必须同时保留合并抵消等调整项，不能
只列正占比后自行计算合计；不要写“占比超过100%”、应收账款、销售方或其他非分部字段，
也不要把年报/中报分部毛利率说成“三表未披露”。
除非证据包含公司公告或财报原文解释，不得写“天然低毛利、拖低综合毛利、核心盈利
业务真实水平、与某分销业务有关”等因果判断；只可并列展示分部占比和分部毛利率。
不得输出内部英文状态码或方法 ID，也不得用 Markdown 表格。
"""
        if "失效条件" in str(prompt_evidence.get("user_question") or ""):
            prompt += """
用户明确要求失效条件。只能引用证据包“条件展望”中已经计算好的情景条件、
失效说明和观察周期，或复述用户本人已经给出的阈值；不得自行发明毛利率、增速、现金流、
报告期数量等确认门槛。若基本面证据只能说明需要继续核验，应写成待补证项，不得量化成阈值。
失效条件只说明哪些事实会推翻当前判断：跌破下方关键位是下行风险被触发，不是“下行失效”；
价格仍在上下关键位之间是区间情景继续成立，不是“区间失效”。
"""
    if intent == "stock_comparison":
        prompt += """

## 多股统一口径比较要求

这是用户指定的 2—5 只股票比较。先读取 comparison_basis：财务指标只有 report_date 与
period_basis 同时一致时才能横向比较；没有全体共同报告期时，必须逐只列明报告期，只在
groups 中同口径的标的之间比较。不得把不同季度、年度和累计口径混为同一排名。

估值必须逐只保留 valuation.timestamps 的行情时间。mixed_currency 时不得直接比较股价、
市值或绝对金额；可以比较 PE、PB 等无量纲指标，但必须保留跨市场会计、业务和估值环境差异。
优先回答 comparison_focus 和用户当前问题，按“结论、关键差异、反方证据、下一步核验”组织，
不使用 Markdown 表格，不输出综合排名、目标价或买卖建议。某个标的数据缺失时保留其他标的结果，
明确该项不可比，不得用常识补写当前事实。
"""
    if intent == "stock_research" and prompt_evidence.get("deep_stock_coverage"):
        prompt += """

## 六维证据覆盖回答要求

证据包中的 deep_stock_coverage 是系统按确定性规则计算的公司经营、财务质量、行业与相对表现、
估值、技术状态、风险事件六个维度。不得自行改变覆盖状态，也不得把“覆盖充分”改写成公司质量
优秀、投资评级或买卖信号。

当用户明确询问“六维证据、证据覆盖、覆盖状态、覆盖情况或覆盖缺口”时，必须直接围绕六个维度
逐项回答，并使用以下四个标题：“六维证据覆盖”“反方证据”“失效条件”“下一步核验”。
每个维度只说明覆盖状态、已有证据来源、时间口径和缺失项；不得把整份报告重述一遍。
新增证据只允许引用 research_change.latest_change.new_evidence 或其 summary，不能把旧证据冒充新增。
反方证据只允许引用 evidence_debate 中已有内容。失效条件只允许引用 conditional_outlook 中已有的
失效说明、情景条件和观察周期，或明确说明当前尚未形成可量化门槛；不得自行发明阈值。
若引用财务数字，必须逐字沿用证据包中的数值和单位，不得换算成千元、万元或亿元后生成新的数字。
时间口径必须转换成用户可读的绝对日期或本地时间，不得直接输出带 T、Z 或 +00:00 的原始时间串。
"""
    if intent == "stock_research" and prompt_evidence.get("research_claims"):
        prompt += """

## 结构化 Claim 使用要求

research_claims 是本轮回答支持证据、反方证据、未决风险和失效条件的首要索引。
用户询问“反方证据、风险、什么会推翻判断、失效条件、证据来源或下一步核验”时，
必须优先引用其中的 claim、evidence_summary、relation、data_time、limitations 和 next_step；
不得向用户展示 Claim ID、source_key、coverage_status 等内部字段名。

必须区分三类关系：supports 是当前支持证据，weakens 是直接削弱当前研究逻辑的反证，
unresolved 是尚未解决的风险或缺口，不能把 unresolved 写成已经确认的负面事实。
价格、均线、收益、回撤和波动率只能说明价格路径；财报、现金流、公告原文和经营数据
才可作为基本面反证。当前报价即使越过上一完整日线的 MA20，也不得写成趋势反证已经
“消失、反转或正在弱化”；必须等待同日完整日线确认，并保留两个时间锚点。
若 conditional_outlook.current_quote_alignment 表明当前报价已经越过某个关键位，
不得再把同一关键位写成未来“若跌破/若突破”的条件；应先说明报价已经触及，
再说明是否仍待完整日线确认，以及确认后需要重算什么。

回答中优先使用 research_claims 已整理的证据摘要。除非用户明确要求原始字段，
不得从 fundamentals、financial_drivers 等深层结构拼接底层元单位的大整数或十位以上小数；
百分比和比率可在不改变方向与含义的前提下保留最多两位小数。若 Claim 摘要没有用户可读的
金额单位，可改用方向、同比、比率和报告期说明，不自行换算出新的金额。
"""
    if (
        intent == "stock_screen"
        and (prompt_evidence.get("profile") or {}).get("key") == "li_zong"
    ):
        prompt += """

## 李总策略回答要求

这是确定性策略状态查询，不是普通截面筛选。selection_mode=candidate_pool 时，items 只包含
真正进入 qualified 或 triggered 状态的股票；不得把 not_qualified、data_incomplete、invalidated
或尚未处理的股票称为候选。必须先分别说明数据交易日、全市场名单数、可深度核验数、深度处理
进度、上市后量价历史不足数、财务历史待实际核验数和当前候选数。evaluated_symbols/coverage_ratio 只表示已有市值预筛或规则状态
的名单比例，不是深度规则完成率；深度进度只能使用 deep_processed_symbols/deep_check_eligible_count。
若 deep_check_complete=false，只能说“当前已深度处理范围内”的候选情况，不得推断尚待深度处理
的股票，也不得宣称全市场没有候选。没有 items 时要区分“当前已深度处理范围内尚无候选”和
“全市场深度处理完成后无候选”。若 evidence.history.items 存在，必须继续基于这些真实历史
样本即时回答，不得停在“当前0只”：逐只说明信号日期、当时是进入候选还是触发人工复核，
并引用5/10/20个交易日的个股收益、同期沪深300收益和超额表现。某个周期状态不是 available
时只能说该周期尚未形成完整观察，不能补算或猜测。

若 evidence.rule_funnel.steps 存在，用户询问“为什么没有候选、规则是否太严”时，应按固定顺序
引用 remaining_count 解释交集如何收窄。可以说明哪一步在本期截面减少了多少股票，但不得把
单期漏斗升级成该规则的长期预测能力、胜率或永久稀缺性；不得自行改变漏斗顺序重新归因。

历史回放不是预存回答文案。必须围绕用户本轮问题重新组织结论、证据和样本边界；不得照抄
boundary 或把多个样本机械拼接成固定模板。历史规则证据只允许引用 history.items.rule_results，
后续走势只允许引用 performance.horizons/path。不得把历史样本数量包装成胜率、成功率、荐股评价
或未来概率。必须说明回放覆盖率只是近期已完成股票范围，不是多年全市场回测。信号日后的收益
从信号日收盘计算，未计交易成本和实际可成交性。提到区间最大上行或最大下行发生时间时，
必须逐字使用 max_upside_date 或 max_drawdown_date；没有日期字段就只报幅度，不得猜测第几个交易日。

selection_mode=symbol_check 时，必须直接回答该股票是 triggered、qualified、not_qualified、
data_incomplete 还是 invalidated。not_qualified 不是候选，data_incomplete 不能判断通过，invalidated
表示此前状态已被新数据推翻。优先列出明确未通过规则、数据不完整规则、反方证据和下一步核验；
不得因为部分规则通过就把股票写成候选。规则实际值、阈值、证据日期和报告期只能引用证据包。
candidate_qualified 只取决于9条候选规则是否在同一数据日全部通过；3条盘后触发规则只在候选已经
通过后决定是否进入重点关注和人工复核，不是进入候选的附加条件。解释观察池股票的失效条件时，
不得写成“未通过规则转为通过后，还需满足触发规则才能进入候选”；应明确只有9条候选规则共同决定
候选资格，触发规则只决定候选形成后的人工复核层级。
候选规则尚未全部通过时，即使某条触发形态规则的原始条件显示为 passed，也只能写“触发形态条件
匹配，但不形成触发事件”，不得写“当日已触发”“触发规则已触发”或把它列入当前触发；正式触发
只允许引用 candidate_qualified=true 后发布的 triggered_rule_ids。

selection_mode=symbol_comparison 时，必须逐只回答 requested_symbols 中的股票，不能退化为只说明全市场
覆盖率。每只股票至少说明当前中文状态、明确未通过规则或数据不完整规则及其 limitations；若某只股票
尚无快照，必须单独说明尚未形成可用结果。全市场覆盖与深度进度作为共同背景只说明一次。

“介入/触发”只表示进入重点关注和人工复核，不是买入、仓位或交易建议。正文不使用 Markdown 表格，
证券代码使用 internal_symbol，不展示 Tushare 的 .SH 后缀。
面向普通用户时，状态只使用“已触发、已进入候选、未通过、数据不完整、状态已失效”等中文，
不要直接输出 triggered、qualified、not_qualified、data_incomplete、invalidated、selection_mode、
profile key 或策略内部版本标识。默认使用中文规则名称；只有用户明确要求规则编号时才展示 LZ 编号。
全市场名单未形成状态数只允许使用 remaining_symbols；深度待处理数只允许使用 deep_remaining_symbols。
市值门槛达标数量、名单状态覆盖率和深度处理进度不是同一口径，绝不能互相替代。
除非证据明确提供逐规则汇总统计，否则不能猜测哪条规则是主要瓶颈、最严格，或声称满足某几条
规则的股票“极少”。不得为候选池自行增加 T+3、T+5 等复核周期；下一步只写完成剩余评估、
查询具体股票规则证据，或核验证据日期与报告期。
"""
    elif intent == "stock_screen":
        prompt += """

## 研究候选筛选回答要求

筛选结果已经由确定性规则生成。不得新增或重排候选，不得计算综合分、星级、目标价、
上涨概率或买卖信号。候选总数必须读取 candidate_count_total（与 universe.matched 一致），
不得用 items 列表长度自行计数。若 items_in_prompt 小于 candidate_count_total，只能明确写
“本轮共 X 只，下面解释按原顺序提供的前 Y 只”，不得把前 Y 只说成完整结果。第一段必须说明
筛选模板、候选总数、最近完整交易日、股票池覆盖数量
和 data_contract.data_version；数据版本应自然写成“数据版本”，不得输出字段名。覆盖率不足
100% 时只能说“本轮已覆盖范围内”，不得把结果外推为全市场、全部A股或所有股票的结论。
market_snapshot、market_cap、valuation、return_20d 和 financial_candidate_pool 是不同覆盖口径，
不得互相替代；财务候选池覆盖只代表进入财务核验的候选范围，不代表全市场财务覆盖。

随后只解释证据包中的实际规则、逐只命中原因与缺失项。缺失项必须优先使用 missing_reasons.reason
的用户可读原因，不得只输出字段名或 code。行情交易日、5/20 日比较基准日、财务报告期和公告日
必须分开表达；没有报告期或公告日时直接说未取得，不得拿行情日代替。来源口径只按股票基础、
完整日线、估值市值截面和财务指标说明，不展示内部接口名。估值约束不等于低估，相对行业表现
不等于官方行业排名，回撤后近 5 日转正不等于反转确认。最后建议用户选择一只股票进入研究空间
核验财务、公告和反方证据，并保留
“研究候选筛选，不构成推荐、评级或交易建议”的边界。证券代码必须使用 internal_symbol，
不得展示 ts_code 或 Tushare 的 .SH 后缀。正文不使用 Markdown 表格。
"""
    if intent == "market_brief":
        prompt += """

## 大盘标准回答要求

只回答用户当前问题，不复述上一轮回答。正文控制在 300—550 个中文字。
使用短段落或项目符号，不使用 Markdown 表格；最多保留两个小标题。
不得输出原始字段名。区间收益、最大回撤、年化波动率和均线各按 Skill 定义解释，
不能互相替代，也不能据此补写资金行为、历史规律或未来概率。
资讯标题中的简称、绰号或模糊代称只能原样列为标题线索，不得猜测其对应公司、行业或事件。
5日、20日等区间累计收益不能改写成“持续回落数周”或“连续数周下跌”。
5日和20日累计收益也不能分别称作“周线”和“月线”。
代表性指数上涨比例是当前证据集合的统计值，不能归到上证、深证等某一个指数名下。
analysis_target.market_date 是本次综合判断的唯一目标交易日。只能合并该日期的指数、
全市场广度和板块证据；date_alignment 中标记为 cross_date_excluded 的快照不得用于
解释目标日涨跌、计算市场强弱或列为目标日热门板块。若板块榜已切换到下一交易日盘前，
应自然说明“板块榜已切换到新交易日，不能用于解释上一交易日”，不要展示内部字段名。
若 live_alignment 显示分钟行情日期晚于目标交易日，必须在开头主动说明两套时间口径：
回答分析截至哪个完整日线交易日、更新的分钟行情截至哪一天及其涨跌方向。不得把较早的
完整日线称为“最新收盘”，也不得把更新的分钟快照悄悄并入较早交易日的原因分析；若两者
方向相反，应明确提示用户原问题中的涨跌前提可能对应较早交易日，而不是当前最新行情。
当目标交易日没有同日全市场涨跌家数时，只能确认同日指数和板块价格表现；不得把资讯标题
中的“多数个股上涨/下跌”或“超过若干只个股上涨/下跌”改写成已确认的全市场事实。
如需引用，只能明确写成资讯标题线索，并说明尚未由同日全市场快照核验。
用户同时询问“昨天为什么涨跌”和“今天盘前关注什么”时，必须拆成两个时间段回答：
上一交易日只使用同日行情与资讯，盘前部分只列新的可核验事件或观察变量，不能混成一个结论。
"""
        if (prompt_evidence.get("question_focus") or {}).get(
            "key"
        ) == "market_cause":
            prompt += """
涨跌原因回答必须按证据层级组织，而不是罗列新闻：
1. 先给目标交易日的指数涨跌与可用的市场广度，这是已确认价格事实。
2. 再使用 causal_evidence.candidates 说明一至两条同日或相邻交易日候选驱动，逐条写明来源；
   same_date_multi_source 只可表述为“同日多个独立来源共同提及的较强线索”，
   same_date_single_source 只能表述为“单一来源线索”。不得输出这些内部状态名。
3. corroborated_categories 只说明同一类事件被多个来源讨论，不能升级成已经证明的因果。
4. 明确至少一项反方证据或替代解释，例如指数分化、广度与标题方向不一致、
   行业与大盘不同步，或资讯时间未与目标交易日对齐。
5. 最后说明下一步应核验的正式数据、央行/公司原文或下一交易日价格反应。
若 causal_evidence.coverage_status=near_date_only，只能称为邻近日线索；若为 unavailable，
直接说明没有取得可用的同日事件证据，不得用技术指标或旧新闻补成涨跌原因。
"""
        if (prompt_evidence.get("question_focus") or {}).get(
            "key"
        ) == "market_risk" and (prompt_evidence.get("market_drivers") or {}).get(
            "items"
        ):
            prompt += """
当前证据已经包含与该市场直接相关的资讯标题。回答风险、反方证据或失效条件时，
必须引用其中至少一条作为事件线索，并明确标题不能证明唯一因果；不得声称当前没有
市场资讯、事件或驱动线索。
"""
            if "失效条件" in str(prompt_evidence.get("user_question") or ""):
                prompt += """
用户明确要求失效条件。最终回答必须包含标题“失效条件”，并只使用证据包已有的
均线、收益、回撤、波动或事件证据作为可复核条件；不能省略，也不能自造时间窗口。
"""
        if (prompt_evidence.get("question_focus") or {}).get(
            "key"
        ) == "trend_reversal":
            prompt += """
趋势判断只使用当前证据明确给出的区间收益、均线位置和趋势状态。
不得声称这是“首次修复”，也不得把区间累计下跌改写成处于“低价区间”或“低位区间”。
指数区间收益使用“上涨/下跌”，不用“盈利/亏损”。上证与深证的强弱差异不能替代
大小盘或市值风格指数，也不要自行规定“后续几个交易日”之类确认窗口。
"""
        if (prompt_evidence.get("question_focus") or {}).get(
            "key"
        ) == "sector_rotation" and (
            prompt_evidence.get("market_breadth") or {}
        ).get("status") == "available":
            prompt += """
当前证据已经提供沪深京A股完整上涨、下跌、平盘家数和固定广度分类。
回答必须直接给出三项家数并逐字沿用 evidence 中的 state；不得省略固定分类，
也不得只凭涨跌家数推断少数权重股拉动、板块资金集中或多数股票涨幅温和。
当固定分类不是“普涨”或“普跌”时，不得把它重新命名为“结构性行情”；
热门板块只是涨跌幅排序截面，不能据此声称板块集中度较高或已经确认结构性行情。
若缺少个股涨幅分布、全市场成交额或成分贡献度，只能把这些列为尚不能确认的部分。
指数的某项收益缺失时，只能明确写数据缺失，绝不能把其他指数的涨跌幅配到该指数名下。
如果 `market_breadth.turnover.status=available`，应引用当日全市场及分交易所累计成交额；
成交额绝不能写成净流入、机构买入或资金意图。若历史比较状态是 building_history，
只说明正在积累同口径历史，不判断放量或缩量。
成交额是每笔成交价格乘数量后汇总，每笔成交只计一次；买卖双方共同完成交易，
但不能写成同一笔交易向买卖双方各记一次、双重计数或因此翻倍。
如果 `market_breadth.distribution.status=available`，应优先引用涨跌幅中位数、四分位区间和
固定分档家数；不得再声称个股涨幅分布缺失，也不得把固定±3%观察分档写成交易阈值。
分档统一使用“上涨至少3% / 上涨不足3% / 下跌不足3% / 下跌至少3%”这类自然语言，
不得写成“跌幅0~-3%”或“跌幅≥-3%”等符号方向错误的表达。
"""
        if (prompt_evidence.get("question_focus") or {}).get(
            "key"
        ) == "volume_flows" and (
            (prompt_evidence.get("market_breadth") or {}).get("turnover") or {}
        ).get("status") == "available":
            prompt += """
全市场成交额必须使用 `market_breadth.market_date` 作为市场日期，并可同时引用
`coverage.latest_tick_time` 说明快照内最新成交时点；`snapshot_local_time` 只是系统取得快照的时间。
不得用上证、深证、创业板或其他指数的日线日期替代全市场成交额日期，也不得声称
成交额没有单独标注市场日期。回答必须明确说明成交额只是成交金额，不等于资金净流入。
历史比较为 building_history 时，只能说同口径历史仍在积累；不得声称已确认放量或缩量。
"""
    return prompt
