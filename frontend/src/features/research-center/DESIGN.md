# 研究中心（/research-center）组件设计记录

执行合同：FRONTEND_EXECUTION_CONTRACT_V1（§5.6 研究中心蓝图、§6 数据/时间/金融口径、§7 互动与写入边界、§8 禁止约定）。

本切片的写操作只有「交易复盘中心」的 confirm / archive（真实状态机 `draft → confirmed → archived`，`base_version` + 409）。
「维持判断 / 继续观察 / 已复盘」**没有后端记录接口**（`/me/research-*`、`/me/run-reviews` 全部只有 GET），按 §5.6 只做说明与跳转，页面**不显示已保存**。

## 数据契约总表

| 用途 | 接口 | 关键字段 | 时间类型（§6.2） |
| --- | --- | --- | --- |
| 判断/变化链 | `GET /me/research-changes`（`type="research_tracking"` 直通锁） | `items[*].{symbol,name,thesis,latest_change.{event_type,severity,summary,created_at,data_as_of,changes[*].{label,before,after,detail},new_evidence[*].{category_label,title,published_at},next_review,boundary},current_state,next_review}`、`coverage.{requested,with_report,with_change_archive}`、`boundary` | GeneratedAt = `generated_at`；BarDate = `latest_change.data_as_of`；PublishedAt = `new_evidence.published_at` |
| 历史结果 | `GET /me/research-outcomes`（`type="research_outcome"` 直通锁） | `items[*].{latest_anchor[*],latest_progress,latest_available[*],coverage.{anchors,available,pending}}`；锚点字段 `anchor_timestamp/anchor_close/horizon_sessions/observed_sessions/target_timestamp/close_return_pct/maximum_*_excursion_pct/partial_return_pct/result_status/scenario_label/review_conclusion/calculated_at/data_as_of/protocol.{anchor,horizon,price_series,mfe_mae}` | **OutcomeAnchor** = `anchor_timestamp` + `protocol.anchor`；数据可得时间 = `data_as_of`；计算时间 = `calculated_at` |
| 下一步行动 | `GET /me/research-actions`（`type="research_actions"` 直通锁） | `items[*].{research_status_label,priority_label,headline,data_as_of,actions[*].{title,status,severity,condition,current_evidence,next_step}}` | BarDate = `data_as_of` |
| 判断-变化-处理链 | `GET /v1/stocks/{symbol}/workspace/timeline`（`contract_version="stock_workspace_timeline_v1"` 直通锁） | `thesis_history[*].{version_no,reason_text,status,created_at,confirmed_at}`、`important_changes[*]`（同变化事件）、`observation_tasks.{items,summary}`、`trade_reviews.summary`、`history_summary`、`data_meta.{status,daily_as_of,quote_as_of,report_generated_at,financial_report_period}` | BarDate = `data_meta.daily_as_of`；ReportPeriod = `financial_report_period`；GeneratedAt = `report_generated_at` |
| 报告快照 | `GET /research-reports/{symbol}` | `{title,status,summary,market_timestamp,generated_at}` | GeneratedAt = `generated_at`；MarketAsOf = `market_timestamp` |
| 交易复盘中心 | `GET /v1/trade-reviews`（`contract_version="trade_review_center_v1"` 直通锁） | `items[*].{status,data_status,operation.{operation_type,operated_at,price,reason_text},price_observation.summary,current_version.{version_no,logic_result,created_source},can_confirm,ready_at,confirmed_at,archived_at}`、`summary.{total,actionable,waiting_data,needs_confirmation,confirmed,archived}`、`boundary` | 操作时间 = `operation.operated_at`；确认/归档时间 = `confirmed_at`/`archived_at` |
| 复盘写操作 | `POST /v1/trade-reviews/{review_id}/confirm`、`POST /v1/trade-reviews/{review_id}/archive` | 请求体 `TradeReviewConfirm{base_version}`；`base_version = current_version.version_no`；409 = 草稿/版本已被更新 | — |

金融口径（adapters 直通锁覆盖）：
- 所有 `*_pct`（`return_1d_pct`、`close_return_pct`、`maximum_*_excursion_pct`、`partial_return_pct`）后端已是百分数，UI 直通加 `%`，不缩放、不取绝对值；`0` 是有效数值，`null` 表示尚未形成，二者严格区分（§6.3）。
- 结果锚点不展示收益评分/胜率/预测；MFE/MAE 仅描述路径（协议原文展示）。
- `0`、空字符串、缺字段与接口失败严格区分：缺字段 `--` /「待确认」；接口失败为模块级错误卡 + 重试，不清空整页（§8.5）。

### §5.6 落库禁令的落点

- 「维持判断 / 继续观察 / 已复盘」：探测确认 `/me/research-changes`、`/me/research-outcomes`、`/me/research-actions`、`/me/run-reviews` 均**只读**（openapi 无 POST/PATCH），后端没有记录这三个动作的接口 → ReviewActions 只渲染说明文字与「进入个股研究 / 问顾问」跳转，**没有任何按钮、不出现「已保存」反馈**。
- 真实落库的写操作只有交易复盘 confirm / archive：成功后提示「已确认并落库为正式复盘（可恢复查看）/ 已归档，历史仍可查看」，并 invalidate 复盘中心与时间线取回服务端最新版本；409 时不覆盖，提示刷新后由用户重新确认（§7.2）。
- `generate-draft`、`PATCH draft`、`followups` 是真实端点但本切片未接入（需 AI 草稿上下文与编辑表单，超出「宁少勿歪」范围，留待后续切片评审）。

### URL 状态与 Query key（§2.3）

- URL：`?symbol=`（选中股票，深链接可分享）、`?focus=`（概览卡分组：reviews / changed / outcomes）。
- Query key：`['research-center', symbol]`（timeline，合同规范键）、`['research-center', symbol, 'report']`（派生）、`['research-center', 'changes' | 'outcomes' | 'actions' | 'trade-reviews']`（页面级聚合，不含 symbol）。

### ResearchReviewSummary
- 页面与用户问题：有多少事等着我复盘？哪些判断有变化？哪些已有结果？
- PPT 视觉锚点：幻灯片 8 顶部三卡；仅复用卡片层级。
- 真实数据：待复盘 = 复盘中心 `summary.actionable`；判断有变化 = changes `coverage.with_change_archive`（附 `requested`/`with_report`）；已有结果 = outcomes `coverage.available` 合计（附 `pending` 合计）。不做任何前端估算。
- 状态：计数缺失 `--`；点击写 URL `?focus=` 过滤左侧列表（aria-pressed，再点取消）。
- 写入边界：无写操作。
- 响应式：≥820px 三列，<820px 单列。
- 测试：Page 测试三卡计数直通、focus 过滤列表。

### ReviewStockList
- 页面与用户问题：我要回看哪只股票的研究链？
- 真实数据：research-changes items 为主，outcomes 补齐只在结果里出现的股票（浏览器侧 union，不发逐股请求，§8.4）；行内显示最近变化时间或已到期结果数。
- 互动事件：点击写 URL `?symbol=` → timeline / report 两个 query 加载；`role=listbox/option` + `aria-selected`。
- 响应式：≥1280px 260px 左列，820–1279px 220px，<820px 单列顶置。
- 测试：Page 测试两股渲染、默认选中、URL 写入与 timeline 加载。

### DecisionChangeTimeline
- 页面与用户问题：这只股票我的判断是什么、后来发生了什么、我怎么处理的？
- 真实数据：timeline `thesis_history`（空 → 「尚未保存当前判断」，不伪造 0/N 进度）、`important_changes`（severity/summary/记录时间/数据时间/下一步观察）、`observation_tasks` + `trade_reviews.summary` + `history_summary` 计数。
- 状态：模块级 loading / error + 重试；单模块失败不影响页面其余部分。
- 测试：Page 测试判断版本、变化、任务渲染与模块失败隔离。

### ReviewActions
- 页面与用户问题：下一步我该做什么？
- 真实数据：research-actions 选中股的 `research_status_label`、`headline`、`status="triggered"` 的复核事项（current_evidence / next_step 直通）；`pending_data` 项不算触发。
- 写入边界：见 §5.6 落库禁令——只有说明 + `/stocks/:symbol`、`/advisor?symbol=&source=research-center` 跳转，无写按钮。
- 测试：Page 测试触发事项渲染、§5.6 说明文案、跳转 href。

### ReportDiff
- 页面与用户问题：最新研究快照相比之前变了什么？
- 真实数据：`/research-reports/{symbol}` 报告元信息（标题/生成时间/status）+ 选中股 `latest_change.changes`（before → after 原文，含百分号不缩放）与 `new_evidence`（PublishedAt）。
- 可见条件：无 `latest_change` → 真实空态「最新研究快照没有记录维度变化」。
- 测试：Page 测试 before/after 直通渲染。

### ResearchProgress
- 页面与用户问题：进行中的结果观察走到哪了？
- 真实数据：选中股 `latest_progress`：已观察/窗口交易日（纯 SVG 进度条，零新依赖）、`partial_return_pct` 直通、`progress_timestamp`、结论原文；无进行中 → 真实空态。
- 测试：Page 测试 `role=img` 进度条与直通百分数。

### OutcomeCards
- 页面与用户问题：历史结果的锚点、窗口、基准与数据可得时间是什么？
- 真实数据：`latest_available`（已到期）优先，否则 `latest_anchor`（待形成）；每卡四要素——**OutcomeAnchor**（`anchor_close` + `anchor_timestamp` + `protocol.anchor`）、**交易日窗口**（`horizon_sessions` + `protocol.horizon` + `target_timestamp`）、**基准**（`protocol.price_series` 原文）、**数据可得时间**（`data_as_of` + `calculated_at`）；收益/MFE/MAE 直通；`review_conclusion` 与 `boundary` 原文。
- 状态：待形成锚点的 null 结果显示 `--`，不伪装成 0。
- 测试：Page 测试四要素文案、直通百分数、boundary。

### 交易复盘中心（TradeReviewCenterSection）
- 页面与用户问题：哪些交易复盘待确认/可归档？
- 真实数据：见总表；空列表 → 真实空态「暂无交易复盘记录」+ boundary，不展示示例复盘。
- 写入边界：`status==="draft" && can_confirm===true` → 「确认复盘」；`status==="confirmed"` → 「归档复盘」；`base_version = current_version.version_no`（缺失则不出按钮）；四态：pending（写入中…禁用）/ success（落库提示 + invalidate）/ failed / conflict（409 刷新取回新版本，由用户重新确认）。
- 测试：Page 测试 confirm/archive 调用参数、成功提示、409 冲突提示与重新拉取。

## 验收记录

- `npx vitest run src/features/research-center`：21/21 通过（adapters 13 + Page 8）。
- `npx tsc --noEmit`：通过。
- `npx playwright test e2e/research-center.spec.ts`：见 e2e 验收（主链路 mock、URL 状态、写操作四态、390px 无横向溢出）。
- 真实会话截图（acceptance01，数据全部来自 8010 真实后端）：`today-runtime-trace/screenshots/research-center-desktop.png`（1440×900）、`research-center-mobile.png`（390×844）。
- 联调说明：vite dev 代理已覆盖 `/me`、`/v1`、`/research-reports`（vite.config.ts 未改动）。
- 遗留缺口：`/me/run-reviews`、`/research-reports/latest`（券商研报）、`generate-draft` / `PATCH draft` / `followups` 写链路未接入（蓝图未要求或需单独评审）；「维持判断/继续观察/已复盘」待后端提供记录接口后才能落库。
