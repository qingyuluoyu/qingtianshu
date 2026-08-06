# 个股研究（/stocks/:symbol）组件设计记录

执行合同：FRONTEND_EXECUTION_CONTRACT_V1（§5.4 个股研究蓝图、§6 数据/时间/金融口径、§7 互动与写入边界、§8 禁止约定）。
本切片为只读：所有写操作仅提供路由入口（/advisor），页面不出现无后端能力的写按钮。

## 数据契约总表

| 用途 | 接口 | 关键字段 | 时间类型（§6.2） |
| --- | --- | --- | --- |
| 首屏聚合 | `GET /v1/stocks/{symbol}/page?range=1y` | `modules.*` 九模块 `{status,data}` + `summary` | 各模块自带 |
| K 线 | `GET /stocks/{symbol}/history?range=3mo/6mo/1y` | `points[{timestamp,open,high,low,close,adjusted_close,volume}]`、`metrics`、`coverage.last_timestamp`、`data_granularity`、`source`、`timezone`、`currency`、`is_stale` | BarDate = `coverage.last_timestamp`；MarketAsOf = `regular_market_timestamp` |
| 同行对比 | `GET /peer-comparisons/{symbol}` | `subject/peers[{pe_ttm,pb,total_market_cap,market_timestamp}]`、`operating_comparison.metrics`、`warnings` | MarketAsOf = `as_of`；ReportPeriod = `anchor_report_date_name` |
| 研究空间 | 聚合 `modules.workspace` + `GET /v1/stocks/{symbol}/workspace` | `thesis`、`relation`、`stage_progress`、`important_changes`、`next_evidence`、`observation_tasks.summary`、`history_summary`、`data_meta` | GeneratedAt = `latest_report.generated_at`；ReportPeriod = `data_meta.financial_report_period` |
| 观察任务 | `GET /v1/stocks/{symbol}/observation-tasks` | `items`、`summary`、`boundary` | — |
| 判断版本 | `GET /v1/stocks/{symbol}/theses`（404=研究空间不存在） | `items[{status,summary,version,updated_at}]` | — |
| 持仓 | `GET /v1/stocks/{symbol}/position`（404=无持仓） | `quantity/cost_basis/average_cost` 账本原值 | — |
| 深度研究 | `GET /me/deep-stock/{symbol}`（404=会话未建立） | `status/current_stage` | — |

金融口径（adapters 直通锁覆盖）：
- 所有 `*_pct` 字段后端已是百分数，UI 直通加 `%`，不缩放；`change_pp` 为百分点直通。
- `operating_cashflow_to_net_profit` 为 0-1 比值小数，仅 UI 乘 100 展示为百分比。
- `revenue/profit/cashflow/total_market_cap/holding` 接口单位为元/股，adapter 原值直通；展示层 ÷1e8 标注「亿元/亿股」（与后端结论文本口径一致），不在 adapter 内改写数值。
- `forecast_eps` 元/股直通；`kind=actual` 标注 A（历史实际）、`estimate` 标注 E（券商预测均值），预测不当作已实现业绩。

四态区分（§6.3）：`0` 是有效数值（正常显示）；空字符串/缺字段显示 `--` 或「待确认」；空列表显示「暂无…」；接口失败显示模块级错误卡 + 重试；`thesis.status="empty"` 显示「尚未保存当前判断」，与接口失败严格分开。

---

### StockHeader（页头行情区）
- 页面与用户问题：这只股票现在怎样？数据是什么时间的？
- PPT 视觉锚点：幻灯片 6 顶部股票头部；仅复用标题+报价+时间层级。
- 真实数据：聚合 `modules.history`（`regular_market_price`、`metrics.change_1d/return_1d_pct`、`coverage.last_timestamp`、`regular_market_timestamp`、`source/currency/timezone/is_stale`）；名称取 `modules.workspace.name` 回退 `display_name` 回退 `symbol`。
- 可见条件：登录后；history 模块 `unavailable` 时报价区显示「行情暂不可用」不放假 0。
- 状态：loading=页级骨架；error=页级错误卡（整聚合失败）+ 重试；stale=`is_stale=true` 追加「缓存数据」。
- 互动事件：无（只读展示）。
- 写入边界：无。
- 响应式：1280 双栏；820 报价区折到左对齐；390 单列不裁剪时间信息。
- 可访问性：`h1` 含名称+代码；红绿仅表示涨跌事实方向。
- 测试：Page 测试渲染名称/代码/涨跌直通；e2e 断言报价与「日线截至」。

### ResearchStatus（研究状态卡）
- 页面与用户问题：我在这只股票上的判断和研究进行到哪了？
- PPT 视觉锚点：幻灯片 6 右侧研究判断区；仅复用层级。
- 真实数据：`workspace.thesis/relation/stage_progress/observation_tasks.summary/completeness.missing_items/history_summary.latest_report`。
- 可见条件：workspace 模块可用；`thesis.status="empty"` 显示「尚未保存当前判断」+ 创建/问顾问入口（Link 到 `/advisor?symbol=…&source=stock-research`）；`stage_progress.status="not_started"` 显示「尚未开启」，不伪造 0/7 进度（仅后端返回非 not_started 进度时才显示真实 completed/total）。
- 状态：模块 error=错误卡；空态=「尚未保存当前判断」。
- 互动事件：入口 Link 仅改变路由，携带 symbol 与 sourcePage 上下文。
- 写入边界：本切片只读，创建判断在顾问页完成；本页不出现写按钮。
- 响应式：指标栅格 4→3→2 列。
- 可访问性：入口为语义链接。
- 测试：Page 测试空态文案与入口链接；thesis empty 不显示假进度。

### KeyChanges / NextActions（关键变化 / 下一步研究动作）
- 页面与用户问题：发生了什么变化？下一步该核验什么？
- 真实数据：`workspace.important_changes[{summary,severity,next_review.focus,data_as_of,created_at}]`、`workspace.next_evidence[{status,description,source}]`、`pending_actions` 计数。
- 状态：空列表=「暂无已记录的关键变化」「暂无待核验事项」；模块失败=错误卡。
- 互动事件：无。
- 时间：data_as_of（BarDate 类）与 created_at（GeneratedAt）分列。
- 响应式：两列→单列。
- 测试：Page 测试变化摘要与空态。

### ModuleStatusPanel（模块数据状态面板）
- 页面与用户问题：这个股票页哪些数据是完整的、哪些不可用？
- 真实数据：聚合九模块 `status` + `summary.{available,failed,total,required_failed}`。
- 状态翻译（§6.3）：available/ready/sufficient→数据完整（绿）、partial/insufficient→部分数据可用/数据不足（橙）、unavailable→当前不可用（灰）、pending_confirmation/waiting_data→待确认草稿/等待数据（紫）、stale→内容已过期（红）、ended/paused→已结束/已暂停（灰）。
- 互动事件：无；单模块失败不清空整页（失败模块仅在对应卡片显示错误）。
- 测试：Page 测试九模块状态翻译与 summary 计数。

### KLineExplorer（K 线主区 + CandlestickChart）
- 页面与用户问题：价格路径是什么样？频率、复权、截止时间是什么口径？
- PPT 视觉锚点：幻灯片 6 K 线主区；仅复用主图+副图结构。
- 真实数据：`/stocks/{symbol}/history` `points`（真实 OHLC，不补齐缺失交易日、不合成固定长度 K 线）+ `coverage/data_granularity/source/is_stale/warnings`。
- 状态：loading=骨架；error=错误卡+重试；points<2=「K 线数据暂不可用」。
- 互动事件：range 切换（3mo/6mo/1y）写入 URL `?range=`，可分享；切换后 BarDate/频率/复权说明随之更新（§7.1）。
- 复权口径：接口无独立复权字段，OHLC 为原始价格并附 `adjusted_close` 复权收盘参考列——页面如实标注，不自称前/后复权。
- 响应式：SVG viewBox 自适应容器宽度，无硬编码画布依赖。
- 可访问性：`role="img"` + aria-label，单 bar title 含 OHLC。
- 测试：adapters 解析锁；e2e range 切换断言 URL 与新数据。

### Indicators / PeriodPerformance（关键指标 / 区间表现）
- 真实数据：`metrics.{rsi_14,macd_12_26,macd_signal_9,macd_histogram,ma20,ma60,bollinger_*,atr_14_pct,volume_ratio_5_20,max_drawdown_60d_pct,volatility_20d_annualized_pct,trend_state,technical_state,technical_method}`、`return_{1,5,20,60}d_pct` + 各自 base/end 日期。
- 口径：百分数直通；`technical_method` 原文展示「只描述已发生的技术结构，不生成买卖信号」。
- 测试：adapters 直通锁（rsi/macd/回撤/波动率不缩放）。

### FinancialPeriodsTable / EarningsQuality / FinancialDrivers（公司财务标签）
- 页面与用户问题：最新财报说了什么？盈利质量和利润变化落在哪些科目？
- 真实数据：聚合 `fundamentals.financial_periods`（报告期/营收/净利/同比/三率/EPS，累计口径警示直通）、`earnings_quality`（overall_label/factors/contradictions/boundary）、`financial_drivers`（confirmed_mechanical_drivers/plausible_clues/company_explanations/unresolved_causes/boundary）。
- 加载策略：标签激活后渲染（聚合数据已在首屏），同行对比单独懒请求。
- 时间：ReportPeriod=report_date/report_date_name；PublishedAt=notice_date。
- 分层：机械桥接（已确认）/可疑线索（未证实）/公司原文解释（管理层披露）三层不混淆；unresolved_causes 如实列出。
- 响应式：表格容器自身横向滚动，页面根不溢出。
- 测试：adapters 直通锁（元金额不缩放、百分数不缩放）；Page 测试累计口径提示。

### PeerCompare（同行估值对比）
- 真实数据：`/peer-comparisons/{symbol}` `subject/peers/operating_comparison.metrics/warnings/selection_basis`。
- 口径：PE/PB 倍数直通；市值元→亿元展示标注；`operating_cashflow_to_net_profit` 比值 UI×100；warnings（样本非完整行业指数、不得改写为高估/低估）原文展示。
- 互动：同行名称 Link 到对应 `/stocks/:symbol`。
- 状态：独立 query，失败只影响本卡。
- 测试：e2e 断言同行表与本股行。

### EventTimeline / Information / Shareholders / Expectations（事件预期标签）
- 页面与用户问题：最近发生了什么官方/媒体事件？股东和预期有什么变化？
- 真实数据：聚合 `event_timeline`（themes/recent_official_events/supportive_events/risk_events/coverage/boundary）、`information`（announcements/news/social_posts/sentiment.caveat）、`shareholders`（户数/信号/top10/boundary）、`analyst_expectations`（rating_statement/forecast_eps/revision/latest_reports/coverage/boundary）。
- 分层：官方披露 / 媒体线索 / 社区低可信样本分块展示；媒体报道标注「只是定位线索」；评级分布标注「只描述研报样本，不构成交易建议」；目标价字段不进入页面。
- 时间：PublishedAt=published_at；股东户数截至=holder_count_as_of；预期数据截至=as_of_date。
- 状态：各模块独立错误卡+重试（触发聚合重取）。
- 测试：adapters 直通锁（EPS 不缩放、百分数不缩放）；Page 测试事件分层与边界文案。

### ResearchTab（我的研究标签）
- 页面与用户问题：我的判断、任务、持仓、深度研究分别是什么状态？
- 真实数据：见数据契约总表；404（theses/position/deep-stock）按业务空态处理：「尚未保存当前判断」「暂无该股票的持仓记录」「深度研究会话尚未建立」，均不当作接口失败。
- 可见条件：未登录显示登录引导，不发请求（enabled=authenticated）。
- 互动事件：创建判断/问顾问/开启深度研究均为路由入口（/advisor 带 symbol 与 intent 参数）；本切片不做写操作。
- 状态：每卡独立 loading/error/空态；判断版本、任务、持仓、深度研究互不影响。
- 测试：Page 测试未登录引导、空态三件套、404 空态；e2e 覆盖。

## 验收记录

- `npx vitest run` / `npx tsc --noEmit` / `npx playwright test`：结果见交付汇报（本文随后更新）。
- 真实会话截图：`today-runtime-trace/screenshots/stock-research-desktop.png`（1440×900）、`stock-research-mobile.png`（390×844），两视口无横向溢出。
