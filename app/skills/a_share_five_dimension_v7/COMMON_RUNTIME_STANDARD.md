# A股任意股票研究 Skill — 通用运行规范

版本：7.0.0

## 1. 适用范围

本 Skill 面向沪深北交易所全部 A 股上市公司，不以某一家制造业、科技股或成长股为默认样本。执行前必须先识别公司的会计模型、经营模式、生命周期、业务结构和当前事件，再选择研究模块。

允许覆盖：

- 主板、创业板、科创板、北交所；
- 正常上市、ST/*ST、重组、困境反转、持续亏损、新上市公司；
- 制造、消费、软件、医药、资源、公共事业、交通、建筑、房地产、银行、保险、券商、控股平台等公司；
- 单一主业和多元化集团。

## 2. 核心目标

报告面向交易员和研究员，必须形成完整研究闭环：

1. 识别研究对象和当前最重要的问题；
2. 选择与公司类型匹配的数据、指标和研究方法；
3. 解释最新事实、历史趋势和边际变化；
4. 建立变量之间的传导关系；
5. 区分已披露事实、系统计算、管理层表述、外部预测和系统推断；
6. 给出支持证据、反向证据、未验证事项、下一验证节点和失效条件。

禁止把搜索结果、F10资料、指标清单或统一模板直接拼成报告。

## 3. 输入契约

```json
{
  "execution_context": {
    "ts_code": "600000.SH",
    "stock_name": "示例公司",
    "dimension": "DIMENSION",
    "analysis_date": "YYYY-MM-DD",
    "latest_complete_trade_date": "YYYY-MM-DD",
    "report_mode": "auto",
    "user_focus": [],
    "previous_view": null
  },
  "research_packet": {
    "stock_identity": {},
    "structured_data": {},
    "derived_metrics": {},
    "documents": [],
    "sources": [],
    "data_quality": {},
    "capabilities": {}
  }
}
```

股票简称存在歧义时，必须通过代码、交易所和公司全称唯一确认。无法唯一确认时停止研究并返回候选列表。

## 4. 通用路由：先分类，再研究

执行报告前生成 `company_routing`，至少包括以下字段。

### 4.1 会计与经营模型 `business_archetype`

从下列类型中选择一项主类型，可附加一项次类型：

- `general_industrial_service`：制造、消费品、一般服务、硬件；
- `bank`：商业银行；
- `insurance`：寿险、财险、保险集团；
- `securities`：证券公司、期货及综合金融服务；
- `real_estate`：房地产开发、商业地产；
- `construction_project`：建筑、工程、系统集成、项目制业务；
- `utility_transport`：电力、燃气、水务、公路、港口、机场、铁路、航运；
- `resource_cyclical`：煤炭、油气、金属、化工、建材、农产品等强周期；
- `pharma_biotech`：成熟制药、创新药、生物科技、医疗器械；
- `software_platform`：软件、互联网平台、订阅及数字服务；
- `holding_asset`：投资控股、资产运营、主要价值来自参控股公司；
- `special_situation`：ST、重整、资产注入、重大重组、壳价值或经营模式正在重构。

不能仅使用证监会行业名称完成分类。需要结合收入、利润、资产和现金流来源判断。

### 4.2 生命周期 `life_cycle`

- `early_loss_making`：早期或持续亏损；
- `high_growth`：高速扩张；
- `mature_stable`：成熟稳定；
- `cyclical_up` / `cyclical_down`：周期上行或下行；
- `turnaround`：经营修复；
- `distressed`：流动性、净资产或持续经营压力；
- `post_merger`：重大并购后的整合期。

### 4.3 业务结构 `segment_structure`

- `single_core`：单一核心业务；
- `multi_segment_related`：相关多元化；
- `conglomerate`：跨行业集团；
- `asset_heavy_platform`：资产运营平台。

### 4.4 事件重要性 `event_materiality`

对分析截止日前的最新事件评分：

- `material`：财报、业绩预告、重大订单、资产重组、监管处罚、重大技术/政策/价格变化，足以改变核心假设；
- `relevant`：提供增量证据，但不足以重建主要模型；
- `immaterial`：普通会议、产品宣传、小额事项或与盈利无直接关系的新闻。

`report_mode=auto` 时：

- 仅 `material` 事件触发更新报告；
- `relevant` 事件融入深度报告；
- `immaterial` 事件不得主导报告标题和结构；
- 近期无重大事件时输出公司/维度深度研究，不强行写“点评”。

## 5. 数据与证据等级

### 5.1 Claim type

- `reported_fact`：正式公告、财报或监管披露；
- `structured_fact`：Tushare 等结构化数据；
- `management_statement`：管理层、业绩说明会、投资者关系记录；
- `external_estimate`：券商、行业机构、一致预期或第三方预测；
- `system_calculation`：公式及输入可追溯的计算；
- `system_inference`：多项证据形成的推断；
- `unverified_information`：尚未可靠确认的信息。

### 5.2 Evidence grade

- `A1`：交易所、监管机构、公司正式公告和定期报告；
- `A2`：政府、统计机构、客户或供应商正式披露；
- `B1`：公司官网、投资者关系活动记录、正式演示材料；
- `B2`：行业协会、权威数据库和一手产业资料；
- `C1`：券商研报和机构预测；
- `C2`：高质量财经媒体；
- `D`：普通媒体、转载、搜索摘要；
- `U`：来源不明。

核心结论不得只依赖 D/U。搜索摘要只能用于定位原文。

## 6. 数据质量与降级机制

每项数据标记：`available`、`missing`、`conflicted`、`stale`、`not_applicable`。

报告状态分为：

- `full`：核心数据完整，可建立主要模型；
- `constrained`：存在缺口，仍可输出受限结论；
- `blocked`：缺少本维度必要数据，禁止继续生成伪分析。

必须说明缺口对哪些结论造成限制。不得通过网页传闻、行业均值或其他公司数据补造目标公司的缺失数字。

通用校验：

- 公告和数据不得晚于分析截止日；
- 年报、半年报、累计季度、单季度和预测口径不得混用；
- 修订公告优先于原公告；
- 元、万元、亿元、股、手等单位先统一再计算；
- 合并口径、母公司口径、归母和少数股东权益必须区分；
- 并购、增发、转股、除权和会计政策变化需要做可比性调整；
- 结论使用的数据必须可追溯到 `source_id` 或 `calculation_id`。

## 7. 写作和组织方式

报告以连贯研究论证为主，不要求机械填满固定章节。根据公司类型和研究问题动态选择模块。

每个重要段落遵循：

> 事实与数据 → 形成机制 → 对本维度的影响 → 证据限制或反向条件

表格用于比较、趋势、预测、敏感性和风险映射。每张表必须有标题、单位、口径、来源和正文解读。不得用大量状态标签表替代研究论证。

禁止：

- “不是……而是……”等口号式二元对立；
- “一句话看懂”“真正的问题只有一个”“全面爆发”等营销表达；
- 概念堆砌和重复结论；
- 无证据的主力行为、财务造假或违法定性；
- 买入、卖出、保证收益和确定性目标价；
- 因数据不足而输出看似精确的数字。

## 8. 图文输出

模型输出 `dimension_report.json`，渲染层生成 HTML、PDF、DOCX。

推荐结构：

```json
{
  "meta": {},
  "company_routing": {},
  "data_quality": {},
  "research_thesis": {},
  "blocks": [],
  "tables": [],
  "charts": [],
  "conclusion": {},
  "sources": [],
  "limitations": []
}
```

`blocks` 使用灵活的叙事块，不要求固定章节数量。图表只引用已有数据：

- `chart_id`
- `chart_type`
- `title`
- `research_question`
- `data_ref`
- `series`
- `unit`
- `time_range`
- `source_ids`
- `notes`

无可靠数据时不绘图。

## 9. 结论要求

结论需要包含：

- 当前判断及适用范围；
- 最重要的支持证据；
- 最重要的反向证据；
- 未验证信息；
- 下一验证节点；
- 上调条件；
- 下调或失效条件；
- 数据限制。
