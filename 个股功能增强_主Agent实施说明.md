# 清数智算｜个股功能增强主 Agent 实施说明

更新时间：2026-07-22
目标目录：`/Users/chr/Documents/青树金融交易/qingshu-agent-demo`
实施对象：主 Agent / 后续开发 Agent

## 0. 任务结论

请在现有 MVP 基础上，把“个股研究”真正收束成一个可持续、可恢复、可验证的“股票研究空间”。

产品核心不是行情卡片、综合评分或一次性长研报，而是：

```text
用户原判断
  → 公司/行业/财务/估值/事件证据
  → 支持证据与反方证据
  → 当前变化是否影响原逻辑
  → 失效条件与下一条待核验证据
  → 研究行动与后续结果回填
```

主 Agent 必须优先增强已有个股链路，不新建第二套聊天系统，不把多个 Prompt 简单堆成“多 Agent”，不把缺失数据包装成完整结论。

## 1. 必读材料与优先级

开始实施前，先完整阅读以下文件：

1. `/Users/chr/Documents/青树金融交易/AI金融Agent产品方案/HANDOVER.md`
2. `/Users/chr/Documents/青树金融交易/AI金融Agent产品方案/清数智算_超级完整产品与技术PRD_V2.1_审校修订版.docx`
3. `/Users/chr/Documents/青树金融交易/AI金融Agent产品方案/清数智算_技术落地设计与实施规范_V1.0_正式版.docx`
4. `/Users/chr/Documents/青树金融交易/qingshu-agent-demo/PRODUCT_GAP_MATRIX_20260722.md`
5. `/Users/chr/Documents/青树金融交易/qingshu-agent-demo/README.md`
6. `/Users/chr/Documents/青树金融交易/qingshu-agent-demo/后端运行流程与回答上下文.md`
7. 当前个股实现和测试：
   - `app/services/deep_stock.py`
   - `app/services/analysis.py`
   - `app/services/research_actions.py`
   - `app/services/evidence_tasks.py`
   - `app/services/research_tracking.py`
   - `app/services/research_reports.py`
   - `app/providers/tushare.py`
   - `tests/test_deep_stock.py`
   - `tests/test_research_actions.py`
   - `tests/test_evidence_tasks.py`

冲突处理：产品业务口径以 PRD V2.1 为准，工程实施以技术规范 V1.0 为准，当前代码和 `PRODUCT_GAP_MATRIX_20260722.md` 只用于确认“现在真实已经有什么”。旧 HTML 视觉稿不得覆盖最新产品边界。

## 2. 当前实现基线

现有 MVP 已经具备以下能力，主 Agent 不要重复重写：

- `DeepStockResearchService` 已有每名用户、每只股票唯一的研究会话。
- 已有七阶段研究流程：原始研究逻辑、公司与行业、财务与现金流、估值与同行、事件与情绪、反方证据、失效条件与下一证据。
- 已有历史对话、研究报告、证据包、研究行动、证据任务和 T+3/T+5/T+10 结果回填。
- 已有财报质量、利润现金流驱动、主营业务结构、股东结构、券商预期、同行比较、事件时间线、A股信息和市场数据能力。
- 已有用户隔离、会话归属校验、SSE 流式输出、输出守卫和失败降级。
- 已有“我的关注”和股票研究空间入口。
- 已有 `app/providers/tushare.py`，Tushare 已配置，配置从本地 `.env` 加载。

当前主要缺口不是“再增加一个分析模块”，而是：

- 个股各模块尚未统一成一个稳定的研究空间聚合对象；
- 证据、反证、推断、缺口和失效条件还没有统一的可点击结构；
- 研究阶段完成规则仍主要依赖意图和字段存在，缺少更严格的覆盖判定；
- 阶段结果、Claim、来源和下一步动作之间的关联还不够稳定；
- Tushare 数据接入已存在，但需要扩展为可审计的结构化数据层，而不是只调用日线；
- 前端需要进一步突出“当前判断、重要变化、待处理事项”，减少一次性长文本。

## 3. 总体实施目标

### 3.1 用户打开一只股票时，第一屏必须回答

1. 这只股票与用户是什么关系：持仓、重点关注、候选观察或普通关注。
2. 用户当前的原判断是什么，何时更新，是否存在未确认版本。
3. 最近最重要的三条变化是什么，分别来自什么来源，数据时间是什么。
4. 当前最需要处理的三件事是什么：补证、复核、继续观察或结果回填。
5. 当前数据是否新鲜、部分缺失、冲突或失败。

第一屏不能优先展示“87分”“综合评分”“强烈看多”“平台目标价”或模型自信度。

### 3.2 个股研究空间的五个标签

保持现有产品基线的五个标签：

1. 研究概览：原判断、当前变化、研究阶段、关键结论边界。
2. AI研究：绑定现有会话，支持追问、阶段问题和研究报告保存。
3. 数据与证据：行情、财务、现金流、主营、同行、事件、来源和覆盖状态。
4. 任务与操作：补证任务、观察条件、研究行动、手工计划和后续操作入口。
5. 历史与复盘：历史报告、阶段变化、T+3/T+5/T+10 结果和研究质量复盘。

不要创建另一套独立的个股聊天页面；标签中的 AI 研究必须复用已有 `conversation_id` 和 Run。

## 4. 个股能力增强范围

### P0：股票研究空间聚合

新增或增强一个稳定的股票研究空间聚合服务，建议从现有 `DeepStockResearchService` 和 `research_evidence` 组合，而不是在 `main.py` 中继续堆业务逻辑。

聚合结果至少包含：

```json
{
  "symbol": "000063.SZ",
  "name": "中兴通讯",
  "relation": {
    "type": "holding|priority_watch|candidate|normal_watch|ended",
    "tracking_status": "active|paused",
    "reason": "用户关注理由"
  },
  "thesis": {
    "active": "当前正式判断",
    "version": 3,
    "updated_at": "...",
    "status": "active|draft|needs_review"
  },
  "quote_meta": {
    "current_quote_time": "...",
    "historical_bar_time": "...",
    "data_status": "fresh|delayed|stale|missing|conflict"
  },
  "important_changes": [],
  "pending_actions": [],
  "stage_progress": {},
  "evidence_summary": {},
  "counterevidence": [],
  "invalidation_conditions": [],
  "next_evidence": [],
  "latest_report": {},
  "conversation": {}
}
```

所有日期必须区分：当前报价时间、历史日线交易日、财务报告期、公告发布时间、抓取时间。不能把上一根完整日线写成“今日涨跌”。

### P0：证据与覆盖状态

每个证据模块都要返回统一状态：

- `sufficient`：足够支持当前模块的方向性说明；
- `partial`：有部分证据，但存在重要缺口；
- `insufficient`：不足以形成可靠判断；
- `unavailable`：当前没有可用数据。

每个证据项至少包括：

- `claim`：这条证据支持或削弱什么主张；
- `evidence_type`：官方披露、结构化数据、系统计算、媒体、社区或用户记录；
- `source_url` / `source_name`；
- `published_at`、`retrieved_at`、`data_time`；
- `report_period` 或 `trade_date`；
- `supports` / `weakens` / `unresolved`；
- `confidence` 只能表达证据覆盖和来源质量，不得表达未来涨跌概率；
- `limitations`：口径、样本、时效、授权或缺失边界。

不要让 AI 只输出一段 Markdown 后再用正则猜事实。保留结构化中间产物，再渲染自然语言。

### P0：反方证据与失效条件

对每个研究阶段至少记录：

- 当前支持逻辑；
- 最强反方证据；
- 尚未验证的假设；
- 什么事实出现后会改变判断；
- 下一次应该核验什么。

“反方证据”不能只生成一句风险提示。必须能关联到具体主张、来源和时间，并能进入研究行动或证据任务。

### P1：Tushare 结构化数据增强

Tushare 已配置，不把“申请 Token”或“配置环境”列为当前任务阻塞项。

按实际权限逐项验证并接入，不能假定所有接口都可用：

- `stock_basic`：股票基础信息；
- `trade_cal`：交易日历；
- `daily`：日线行情；
- `daily_basic`：估值、换手率和基础指标；
- `income`、`balancesheet`、`cashflow`：三张财务报表；
- `fina_indicator`：财务指标；
- `forecast`、`express`：业绩预告和业绩快报；
- `disclosure_date`：披露日程；
- `index_daily` 及可用行业/指数数据：行业和指数对照。

实现要求：

1. 所有 Tushare 调用集中在 `app/providers/tushare.py` 或明确的数据服务中。
2. 不在路由、Agent Prompt 或前端直接调用 Tushare。
3. 每次同步保存数据集、交易日/报告期、抓取时间、来源版本、同步状态和警告。
4. 接口权限不足、限流、字段缺失或返回空值时，返回 `partial` / `unavailable`，不要伪造默认值。
5. Tushare 结构化数据用于事实和计算；公告原文、新闻和用户材料仍走各自来源链路。
6. 当前报价与历史日线必须保留不同时间锚点；Tushare 不可用时继续使用已有 provider 降级链路。
7. 先运行 `scripts/verify_tushare.py`，只报告行数、字段和交易日，不得输出 Token。

建议先做一个最小数据包：股票基础、日线、每日指标、三表、财务指标、业绩预告/快报和披露日程；完成质量门禁后再增加更复杂的行业和事件数据。

### P1：研究阶段完成规则

现有七阶段继续保留，但完成不能只因为“意图匹配 + 字段非空”。至少满足：

- 研究 Run 状态为 `completed`；
- 输出通过最终守卫；
- 证据包不是 `missing` / `failed`；
- 本阶段要求的核心模块覆盖达到门槛；
- 至少有一条可追溯来源或明确标注为用户输入；
- 关键缺口仍存在时，阶段可以是 `partial` 或 `needs_review`，不得标记为完成；
- 宽泛的“完整分析”不得自动完成所有阶段，除非每个阶段都有独立证据覆盖。

守卫回退、模型超时、部分失败和只有确定性摘要时，不能自动把阶段标记为已完成。

### P1：统一研究输出协议

AI 个股研究结果建议统一为以下结构：

```json
{
  "answer_summary": "针对当前问题的简短结论",
  "confirmed_facts": [],
  "evidence_based_inferences": [],
  "counterevidence_and_risks": [],
  "hypotheses_to_verify": [],
  "information_gaps": [],
  "invalidation_conditions": [],
  "next_evidence_tasks": [],
  "stage_updates": [],
  "conclusion_boundary": {
    "time_scope": "",
    "data_scope": "",
    "limitations": []
  },
  "citations": [],
  "candidate_writebacks": []
}
```

`candidate_writebacks` 只能是候选草稿。用户确认后，才能写入正式判断、任务或观察条件；AI 不得直接覆盖正式对象。

### P2：研究结果与行动闭环

把以下对象串起来：

```text
研究 Run
  → 结构化证据/Claim
  → 阶段状态
  → 证据缺口/研究行动
  → 用户确认或补充
  → 新 Run / 新报告
  → T+3/T+5/T+10 结果回填
```

研究行动只回答“下一步核验什么”，例如：

- 核对最新公告；
- 补齐报告期财务指标；
- 检查经营现金流是否兑现；
- 检查 MA20、成交量和回撤结构；
- 核对同行口径；
- 等待下一次业绩披露。

不得生成“买入、卖出、加仓、减仓、目标价、止损价、确定性收益”等交易指令。

## 5. API 与代码组织建议

保持现有接口兼容，优先新增服务层和聚合响应，不要一次性破坏旧 `/me/*` 接口。

当前入口：

- `GET/POST /me/deep-stock`
- `GET /me/deep-stock/{symbol}`
- `GET /me/watchlist/brief`
- `GET /me/research-actions`
- `GET /me/evidence-tasks`
- `GET /stocks/{symbol}/history`
- `GET /stocks/{symbol}/event-timeline`
- `GET /stocks/{symbol}/earnings-quality`
- `GET /stocks/{symbol}/financial-drivers`

目标上可以逐步提供兼容聚合接口：

- `GET /v1/stocks/{ts_code}/workspace`
- `GET /v1/stocks/{ts_code}/workspace/evidence`
- `GET /v1/stocks/{ts_code}/workspace/timeline`
- `GET /v1/stocks/{ts_code}/workspace/actions`
- `POST /v1/ai/writebacks/{id}/confirm`

如果暂时不迁移旧路径，至少让旧路径返回同一份聚合对象，避免网页和 Agent 各自维护一套字段。

推荐代码边界：

- `app/services/stock_workspace.py`：股票研究空间聚合；
- `app/services/research_claims.py`：Claim、支持/反证和引用；
- `app/services/tushare_sync.py`：Tushare 数据同步和质量门禁；
- `app/services/deep_stock.py`：继续负责阶段生命周期，不承担所有数据采集；
- `app/providers/tushare.py`：只负责协议适配和安全错误包装；
- `app/main.py`：只保留请求解析、鉴权、调用服务和响应转换。

如果当前 SQLite JSON 结构足够支持 MVP，可先在既有对象中追加版本化字段；只有在需要跨股票检索、Claim 查询或高并发更新时，再拆出规范化表。任何迁移都必须可回滚，并保留旧数据。

## 6. 页面要求

个股页面必须有以下可见内容：

- 股票名称、代码、关系状态、研究状态；
- 当前报价、历史日线、数据日期和数据状态分开显示；
- 当前判断及版本时间；
- 最多三条重要变化；
- 最多三项待处理事项；
- 研究阶段进度，明确“覆盖进度”而不是“投资质量评分”；
- 证据来源、时间和覆盖状态；
- 反方证据、信息缺口、失效条件；
- 进入绑定 AI 对话的入口；
- 研究报告和历史回填入口。

前端禁止展示：

- 87 分、综合雷达评分、市场温度等无透明算法指标；
- 平台自产目标价；
- “强烈看多”“必涨”“确定性机会”；
- 把研究阶段完成度写成投资质量；
- 把供应商错误、内部 Prompt、密钥、Agent 内部角色名称直接展示给普通用户。

## 7. 分阶段实施顺序

### Phase A：基线和数据验证

- 阅读并确认本说明、HANDOVER、PRD、技术规范和当前代码。
- 运行现有测试和 `ruff check .`。
- 运行 `scripts/verify_tushare.py`，确认已配置账号实际能返回哪些接口字段。
- 使用 `000063.SZ`、`300308.SZ` 和 `NVDA` 各做一次只读数据包检查。
- 不修改 `/Users/chr/Documents/tradingagents`。

### Phase B：股票研究空间聚合

- 新建或完善 `StockWorkspaceService`。
- 让“我的关注”和“个股研究”返回同一套关系、判断、变化、证据、任务和报告字段。
- 首屏只展示关键摘要，完整证据放入标签或详情抽屉。
- 保留当前会话绑定和用户隔离。

### Phase C：证据、反证和阶段协议

- 统一证据状态和来源字段。
- 完善 Claim/反方证据/失效条件/下一证据结构。
- 收紧阶段完成条件。
- 所有候选写回必须经过用户确认。

### Phase D：Tushare 数据增强

- 先接入有权限且稳定的结构化数据集。
- 增加数据质量门禁、时间口径和失败降级。
- 将三表、财务指标、业绩预告和披露日程接入对应研究阶段。
- 不因为 Tushare 已配置就宣称“所有金融数据已覆盖”。

### Phase E：验收和交接

- 增加单元测试、API 测试、跨用户访问测试、数据时间测试和缺失数据测试。
- 本地启动服务，打开网页，实际验证页面切换、股票切换、证据详情、阶段更新和返回对话。
- 用真实 Tushare 配置做最小 smoke；不得把 Token 写入日志。
- 更新 `PRODUCT_GAP_MATRIX_20260722.md` 和新的交接文件，记录完成项、未完成项、失败原因和下一步。

## 8. 必须通过的验收标准

### 功能

- [ ] `000063.SZ` 能创建或恢复唯一股票研究空间，并绑定已有会话。
- [ ] 第一屏同时显示关系、原判断、重要变化、待处理事项和数据状态。
- [ ] 公司业务、财务现金流、估值同行、事件情绪、反方证据、失效条件均可进入对应阶段。
- [ ] 每条关键证据都有来源、时间和覆盖状态。
- [ ] 当前报价和历史日线不混淆，跨日期比较会明确降级。
- [ ] Tushare 接入失败、权限不足或空数据时，页面仍可用并明确显示缺口。
- [ ] 研究行动只产生核验证据的下一步，不产生交易指令。
- [ ] AI 回退或守卫失败不会错误推进研究阶段。
- [ ] 阶段状态、报告、研究行动和证据任务在刷新后仍能恢复。

### 质量

- [ ] 用户 A 不能读取用户 B 的股票空间、研究报告、证据任务或会话。
- [ ] 不输出 Token、完整 API Key、`.env` 内容或敏感请求体。
- [ ] 不使用固定演示数字冒充实时数据。
- [ ] 不把来源缺失的 AI 推断写成事实。
- [ ] 不新增目标价、综合评分、胜率或买卖评级。
- [ ] 现有测试全部通过，新增测试覆盖新逻辑。
- [ ] `ruff check .` 通过。
- [ ] 实际打开网页并完成一次视觉验收，检查中文、数据日期、空状态、错误状态和窄屏可读性。

## 9. 主 Agent 最终交付内容

完成后必须交付：

1. 修改过的文件清单和每个文件的作用；
2. 新增/变更 API、数据结构和迁移说明；
3. Tushare 实际验证过的接口和未获得权限的接口；
4. 测试命令及真实结果；
5. 仍然存在的数据缺口和产品边界；
6. 更新后的 `PRODUCT_GAP_MATRIX_20260722.md` 或专门的增量交接文件；
7. 不得只说“功能已完成”，必须说明哪些是实际可用、哪些仍是降级或规划。

## 10. 明确不做

- 不重写 `/Users/chr/Documents/tradingagents`。
- 不读取、打印或复制任何密钥。
- 不把 `tushare使用方法.docx` 中的临时代理/凭证写入代码或文档。
- 不重建一个新的聊天系统。
- 不先做复杂微服务、复杂回测或自动交易。
- 不用多个角色的长文本代替证据协议。
- 不把“数据字段存在”当作“研究结论成立”。
- 不把研究覆盖进度、模型自信度或历史涨跌占比包装成未来收益概率。

## 11. 实施起点

从以下顺序开始：

```text
1. 运行现有测试与 Tushare verify
2. 审计 /me/deep-stock 的真实响应
3. 建立 StockWorkspaceService 聚合层
4. 为 000063.SZ 补齐证据/反证/失效条件结构
5. 接入一个 Tushare 财务数据最小闭环
6. 增加测试并完成网页验收
7. 更新交接文件，等待下一轮确认
```

本说明的完成标准不是“增加了多少模块”，而是用户能否对一只股票持续回答：

> 我当时为什么关注它？现在发生了什么？哪些事实支持或削弱原逻辑？下一步要核验什么？后来结果如何？
