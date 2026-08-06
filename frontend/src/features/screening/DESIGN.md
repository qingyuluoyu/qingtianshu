# 透明选股（/screening）组件设计记录

执行合同：FRONTEND_EXECUTION_CONTRACT_V1（§5.2 透明选股蓝图、§6 数据/时间/金融口径、§7 互动与写入边界、§8 禁止约定）。
本切片为**只读**：`POST /me/stock-screener` 是契约定义的筛选查询入口（`force_refresh` 固定 `false`，不触发数据重建）；
李总策略与回测全部是 GET 快照读取，不触发新筛选 run / 回测任务，页面上没有任何写操作按钮。

## 数据契约总表

| 用途 | 接口 | 关键字段 | 时间类型（§6.2） |
| --- | --- | --- | --- |
| 筛选档案 | `GET /stock-screener/profiles` | `items[*].{key,label,description,sort_rule,default_filters}`、`boundary` | — |
| 通用筛选结果 | `POST /me/stock-screener`（`type="stock_screen"` 直通锁） | `status`、`profile.sort_rule`、`rules[*].{field,operator,value,unit,reason}`、`effective_filters`、`universe.{listed_input,after_common_rules,after_market_rules,valuation_coverage,financial_candidate_pool,matched,represents_full_market}`、`data_contract.{as_of,representation}`、`items[*].{ts_code,metrics,financials,coverage_status,matched_reasons,missing_fields,limitations,evidence_times}`、`warnings`、`boundary` | BarDate = `data_contract.as_of.market_date`；GeneratedAt = `as_of.generated_at`；ReportPeriod = `financial_report_periods` / `evidence_times.financial_report_period` |
| 李总候选快照 | `GET /v1/stock-strategies/li-zong/candidates?status=&limit=200`（`strategy_id="li_zong"` 直通锁） | `status`、`counts.{qualified,triggered,not_qualified,data_incomplete,invalidated,total}`、`funnel.{starting_count,steps,final_candidate_count}`、`data_meta.{latest_as_of_date,universe_count,coverage_ratio,full_market_coverage}`、`strategy.version.rules`、`items[*].{evaluation_status,rule_results,matched_reasons,limitations,summary,triggered_rule_ids,as_of_date}` | BarDate = `as_of_date` / `data_meta.latest_as_of_date` |
| 最近 run | `GET /v1/stock-strategies/li-zong/runs/latest` | `run.{status,as_of_date,universe_count,coverage_ratio,qualified_count,warnings,error,finished_at}`、`coverage.{full_market_coverage,remaining_symbols}` | BarDate = `run.as_of_date`；GeneratedAt = `run.finished_at` |
| 回测 | `GET /v1/stock-strategies/li-zong/backtest?period=` | `status`、`progress.{status,phase,market_data_ratio}`、`assumptions.{benchmark,weighting,rebalance,price_basis,cash_policy}`、`result.{status,period_return_pct,annualized_return_pct,max_drawdown_pct,benchmark_return_pct,excess_return_pct,data_coverage_ratio,points[*].{trade_date,nav,benchmark_nav},generated_at,boundary}` | GeneratedAt = `result.generated_at`；区间 = `start_date~end_date` |

金融口径（adapters 直通锁覆盖）：
- 所有 `*_pct` / `pct_change` 字段后端已是百分数，UI 直通加 `%`，不缩放、不取绝对值（含 `0` 与负值）。
- `coverage_ratio` / `market_data_ratio` / `data_coverage_ratio` 为 0~1 原始比例，按原值 4 位小数展示，不换算百分数。
- `0`、空字符串、缺字段与接口失败严格区分（§6.3）：`0` 正常显示；缺字段 `--` 或「待确认」；`financials` 整体 null 显示「财务数据不可用」而非 0；接口失败为模块级错误卡 + 重试。

### §5.2 互斥模式与伪分页禁令的落点

- 通用筛选 / 李总指标筛选 / 历史复盘回测为**互斥模式**：模式卡片切换写入 URL `?mode=`，切换时清空其余模式的全部 URL 状态，三个模式各有独立表格与面板，不混在一个表格。
- 通用筛选：服务端请求参数只有 `max_results`（1~30，真实上限），**无分页参数与全市场行业分布数据** → 页面不渲染任何分页控件，只展示「命中总数（universe.matched 真实计数）+ 展示前 N 条（sort_rule 直通）」，并在表格下方明示「不提供伪分页」。
- 李总候选：`status` chip 走服务端 `status` 过滤参数（真实过滤），计数来自快照 `counts`；列表为后端快照（limit 200），不做前端逐股补全（§8.4 N+1 禁令）。
- 回测：**仅当** `status==="ready" && result!==null && result.status==="ready"` 时渲染完整指标卡与净值图；其余状态（computing / result null）显示真实进度（phase、market_data_ratio 原值）与「不展示推算指标」空态。
- `RuleCoverageDistribution`：两个模式都使用服务端真实分布数据——通用模式用 `universe` 漏斗计数 + `rules` 原文，李总模式用 `funnel.steps`；接口没有提供全市场行业分布，故不做该面板。

### URL 状态（§2.3）

- `mode`（screen 默认 / lizong / backtest）；通用模式：`profile`、`m`（市场）、`n`（展示条数）、`f_<field>`（阈值）、`symbol`（选中候选）；李总模式：`status`、`symbol`；回测模式：`period`。
- query key 遵循合同 §2.3：`['screener', profile, params, page]`（page 槽位保留为 null，后端支持分页后无需改缓存结构）、`['li-zong-candidates', status]`、`['li-zong-backtest', period]`。

### ScreeningModeCards
- 页面与用户问题：我要用哪种透明口径形成研究候选？
- PPT 视觉锚点：幻灯片 2-4 顶部模式卡；仅复用卡片层级。
- 真实数据：无（静态三选一，三模式均有真实接口支撑）。
- 状态：`aria-pressed` 单选互斥；切换清空其他模式 URL 状态。
- 互动事件：点击写 URL `?mode=`，可分享深链接。
- 写入边界：无写操作。
- 响应式：≥620px 三列，<620px 单列。
- 测试：Page 测试三卡渲染、aria-pressed、切换后 URL 与内容切换。

### FilterBuilder
- 页面与用户问题：筛选条件是什么？我能改哪些阈值？
- 真实数据：可选阈值 = 当前 profile 的 `default_filters` 键（真实可选项，不虚构字段）；生效口径以结果 `effective_filters` 为准并展示 `sort_rule`。
- 状态：非数字输入 → 行内 alert 拒绝提交（空值不是有效阈值）；提交中禁用。
- 互动事件：「应用筛选」写 URL `f_*` → 新 query key → 重新 POST；profile 切换重置为该档案默认阈值。
- 响应式：auto-fill 栅格，390px 两列。
- 测试：Page 测试默认载荷、编辑后重发、非数字拒绝。

### RunSummary + CandidateTable（通用）
- 页面与用户问题：这轮筛选命中了什么？数字的口径与时间是什么？
- 真实数据：`universe.matched` 真实总数、`represents_full_market=false` → 「不代表全市场」徽章、`data_contract.as_of` 时间、warnings 直通。
- 候选表三态：通用筛选只返回命中项——完整命中 =「通过」，带 `missing_fields` =「数据不足」（后端字段直通，不自行推断）；未通过项不进入本表（接口只返回命中）。
- 互动事件：行选择只更新详情与 URL `symbol`；「进入个股研究」链接 `/stocks/:symbol`。
- 响应式：表格容器自身横向滚动，页面根不溢出。
- 测试：Page 测试直通百分数、三态徽章、空态（matched=0 真实空态）、无分页控件。

### CandidateDetailPanel / RuleChecklist / RuleCoverageDistribution
- 真实数据：选中项 `matched_reasons`、`missing_fields`、`limitations`、`coverage_status`、`evidence_times`；李总规则清单用 `strategy.version.rules` 字典翻译 `rule_results`（含 evidence_date / report_period / source）；漏斗用 `funnel.steps` 或 `universe` 计数。
- 状态：规则状态直通翻译（passed/failed/data_incomplete）；缺字典回退 rule_id 原文。
- 测试：Page 测试清单渲染、漏斗计数、缺口列。

### BacktestMetricCards + BacktestChart
- 页面与用户问题：这套规则的历史复盘结果是什么？数据够不够？
- 真实数据：见总表；指标全部后端直通（含最大回撤负值、超额、覆盖率原值）。
- 可见条件：仅完成的回测（ready + result）；未完成显示 progress 真实状态与「不展示推算指标」空态。
- 图表：纯 SVG 双折线（组合净值 / 基准净值），不插值、不补齐交易日；回撤只展示后端 `max_drawdown_pct` 指标，前端不重算金融指标（§8.3）。
- 互动事件：period chip 写 URL `?period=`（3m/1y/3y 均有真实 GET）。
- 响应式：图表 `width:100%` viewBox 缩放，390px 可用。
- 测试：Page 测试指标直通、SVG 渲染、未完成空态、period 切换。

## 验收记录

- `npx vitest run src/features/screening`：24/24 通过（adapters 13 + Page 11）；全量 `npx vitest run` 105/105 通过。
- `npx tsc --noEmit`：通过。
- `npx playwright test e2e/screening.spec.ts`：4/4 通过（通用筛选主链路 + POST 载荷断言、互斥模式 URL 切换 + 李总三态、回测指标/净值图 + period 切换、390px 无横向溢出）。
- 真实会话截图（acceptance01，数据全部来自 8010 真实后端，domcontentloaded + 固定等待 15s，截图 spec 内置横向溢出断言 ≤1px 四张全过）：`today-runtime-trace/screenshots/screening-screen-desktop.png`、`screening-lizong-desktop.png`、`screening-backtest-desktop.png`（1440×900）、`screening-mobile.png`（390×844）。截图覆盖：通用筛选真实档案/条件面板/命中摘要（数据日期 2026-08-06、不代表全市场徽章）、李总最近 run（partial + 未覆盖全市场 + warnings 直通）与三态候选表/规则核验/漏斗、回测 ready 指标卡（+28.10% / -32.76% / 覆盖率 0.8315 原值）与净值曲线。
- 联调修复：vite dev 代理缺少 `/stock-screener` 前缀导致 profiles 请求回落 index.html（ContractError 正确拦截），已在 `vite.config.ts` 补 `"/stock-screener": apiProxy` 一行。
- 遗留缺口：通用筛选无服务端分页参数（页面按 §5.2 不展示伪分页，query key 已预留 page 槽位）；`observation-pool`、`history`、`candidates/{symbol}` 详情、`triggers` 端点本切片未接入（页面蓝图未要求，留待后续切片评审）。
