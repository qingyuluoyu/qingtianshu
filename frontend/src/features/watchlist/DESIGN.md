# 我的关注（/watchlist）组件设计记录

执行合同：FRONTEND_EXECUTION_CONTRACT_V1（§5.3 我的关注蓝图、§6 数据/时间/金融口径、§7 互动与写入边界、§8 禁止约定）。
本切片含写操作：关系变更（重点/暂停/恢复/结束）经 `PATCH /v1/stocks/{symbol}/relation`（base_version 乐观锁）；
其余能力（创建任务、深度研究等）本页只给路由入口，不出现无后端能力的写按钮。

## 数据契约总表

| 用途 | 接口 | 关键字段 | 时间类型（§6.2） |
| --- | --- | --- | --- |
| 资产列表聚合 | `GET /v1/stock-workspaces`（contract `stock_asset_list_v1`） | `items[*].{symbol,name,version,relation_type,priority,tracking_status,workflow_status,active_thesis,latest_change,next_action,open_task_count,quote,report_meta,data_times,data_status}`、`summary.{total,watching,holding,ended,paused,waiting_data}`、`status`、`boundary` | MarketAsOf = `data_times.quote_as_of` / `quote.market_timestamp`；GeneratedAt = `report_meta.generated_at` |
| 单股快速预览 | `GET /v1/stocks/{symbol}/workspace`（仅选中行） | `thesis`、`relation`、`boundary` | — |
| 预览小 K 线 | `GET /stocks/{symbol}/history?range=3mo`（仅选中行） | `points`、`coverage.last_timestamp`、`data_granularity`、`source`、`is_stale` | BarDate = `coverage.last_timestamp` |
| 关系变更（写） | `PATCH /v1/stocks/{symbol}/relation` | 请求 `base_version,relation_type,priority,tracking_status,workflow_status,attention_tags`；409 = `StockDomainVersionConflict` | — |

金融口径（adapters 直通锁覆盖）：
- `quote.pct_change` 后端已是百分数，UI 直通加 `%`，不缩放；`quote.price` 为价格原值直通。
- `open_task_count` 缺字段按 0；`0` 是有效数值正常显示。
- PATCH 为**全量替换**语义（未传字段回落 schema 默认值），`buildRelationPatch` 从行当前状态构造完整载荷只改目标字段；`relation_type != "watching"` 时 `priority` 置空（与后端口径一致）。

四态区分（§6.3）：`0` 正常显示；空字符串/缺字段 → `--` 或「待确认」；空列表 → 「暂无…」/ 页面空态；接口失败 → 模块级错误卡 + 重试；`quote.status="unavailable"`（行情不可用）与价格为 0 严格分开。

### §5.3 N+1 禁令的落点

- 列表所有列（价格/涨跌/判断/变化/任务/研究状态/报告时间）全部来自**一次** `GET /v1/stock-workspaces` 聚合，前端**不**对列表行逐只请求 workspace 或行情。
- 概览筛选卡与排序为 URL 状态 + 浏览器侧筛选（服务端暂无筛选/分页参数），切换不新增单股请求；query key 按合同 §2.3 预留 `['stock-workspaces', filters]` 结构，并用 `placeholderData` 避免换键闪烁，后端支持服务端筛选后无需改组件。
- 单股请求只有选中行的预览（workspace + 3mo K 线，共 2 个），由用户行选择触发，不是列表补全。
- 后端暂不支持分页：列表为服务端轻量摘要（每行已含 quote/thesis/任务计数/报告元数据），规模上限由后端聚合控制；DESIGN 记录此缺口，不以并发补全掩盖。

### 关系变更写边界（§7.2）

- 动作集：设为重点/取消重点（仅 watching）、暂停跟踪/恢复跟踪、结束关注（二次确认）、恢复关注（仅 ended 行）。持仓关系的建立走持仓账本流程，本页不提供「设为持仓」按钮（无对应前端事实链）。
- 每次 PATCH 携带行版本 `base_version`；409 时不做任何本地覆盖，失效并重拉列表取回最新版本，提示用户确认后重试；写操作四态：写入中（行内按钮禁用）/ success（提示 + 失效重取）/ failed（提示，可重试）/ conflict（409 分支）。
- 「结束关注」用 ConfirmDialog 明确影响对象与版本号；后端 ended 语义即从关注列表移除并保留历史（`stock_domain.update_relation` 同时清理 watchlist 表）。`DELETE /me/watchlist/{symbol}` 只作用于旧自选股表、不影响研究空间，本页不使用。

### WatchlistSummary（概览筛选卡）
- 页面与用户问题：我的研究资产总共多少？重点/有变化/有任务/暂停/结束各多少？
- PPT 视觉锚点：幻灯片 5 顶部统计卡；仅复用卡片层级。
- 真实数据：`summary.{total,paused,ended}` 直通；重点/有变化/有任务由聚合行派生（priority=high、latest_change≠null、open_task_count>0），不发额外请求。
- 状态：loading=页级骨架；计数缺字段显示 `--`。
- 互动事件：点击仅改变 URL `?filter=` 与列表筛选，不重建研究空间。
- 响应式：6→3→2 列。
- 测试：Page 测试六卡渲染、点击后 URL 与行数变化、无新单股请求。

### AssetTable（资产表格）
- 页面与用户问题：这些股票现在的价格、判断、变化、任务、研究状态、报告时间分别是什么？
- PPT 视觉锚点：幻灯片 5 资产表；仅复用表格层级。
- 真实数据：见总表；价格/涨跌取 `quote`（失败行 `--` + 「行情不可用」，只影响该行）；判断取 `active_thesis.summary`（无 → 「尚未保存当前判断」）；报告时间取 `report_meta.generated_at`（GeneratedAt）。
- 互动事件：行选择（点击/Enter/Space）只更新右侧预览与 URL `?symbol=`；操作列按钮 `stopPropagation` 不触发行选择。
- 状态：单行情失败仅该行 `--`；单写操作失败仅行级提示 + 页级 notice。
- 响应式：表格容器自身横向滚动（min-width 760px），页面根不溢出。
- 可访问性：`aria-selected` 行、操作按钮语义、写入中禁用。
- 测试：Page 测试直通渲染、四态、行选择、操作不触发行选择（经 symbol URL 断言）。

### StockQuickPreview（右侧快速预览）
- 页面与用户问题：选中的这只股票核心事实是什么？怎么进入深读？
- 真实数据：列表摘要优先（quote/relation/thesis/next_action/open_task_count）；选中后读单股 workspace（判断补充）与 3mo K 线（CandlestickChart 复用）。
- 互动事件：「进入个股研究」Link `/stocks/:symbol`；「问顾问」Link `/advisor?symbol=…&source=watchlist`（带 symbol 与来源）。创建任务无对应创建端点（`/v1/observation-tasks` 仅 GET），不提供按钮。
- 状态：K 线失败仅该模块错误卡 + 重试；workspace 失败仅详情卡报错。
- 响应式：≥1280 右侧 390px；<1280 降到主列下方单列。
- 测试：Page 测试默认选中首行、URL symbol 直达、预览链接 href。

### RelationMenu（行内关系操作）
- 页面与用户问题：如何调整这只股票与我的关系？
- 真实数据：`relation_type/priority/tracking_status/version` 来自聚合行。
- 写入边界：见上文「关系变更写边界」；ended 行只显示「恢复关注」。
- 测试：Page 测试全量载荷（保留 workflow_status/tags）、成功失效重取、409 分支、确认对话框。

### RecentSection（最近变化与任务/报告摘要）
- 真实数据：聚合行 `latest_change`（按 created_at 倒序取 5）、`open_task_count>0` 行、`report_meta`（按 generated_at 倒序取 5）；无额外请求。
- 时间：变化记录时间（created_at）、报告生成时间（generated_at）分列。
- 状态：三组全空显示「暂无变化、任务或报告记录」。

## 验收记录

- `npx vitest run src/features/watchlist`：21/21 通过（adapters 11 + Page 10）；全量 `npx vitest run` 75/75 通过。
- `npx tsc --noEmit`：通过。
- `npx playwright test e2e/watchlist.spec.ts`：4/4 通过（主链路+PATCH 载荷断言、409、二次确认对话框、390px 无横向溢出）。
- 真实会话截图：`today-runtime-trace/screenshots/watchlist-desktop.png`（1440×900）、`watchlist-mobile.png`（390×844），两视口横向溢出 0px；验收账号 acceptance01 关注列表为空，截图覆盖真实空态（含列表 boundary 原文）。运行中的 8010 后端早于 `/session/status` 路由（源码已新增、进程未重启），截图时仅对该探测用真实 `/session` 响应透传，业务数据全部来自真实后端。
- 遗留缺口：后端 `/v1/stock-workspaces` 暂无服务端筛选/分页参数，筛选排序在浏览器侧作用于同一份聚合（query key 已预留 filters 槽位）；列表行数规模由后端聚合控制，未做前端并发补全。
