# 后端 API 参数清单

> 分支：react-04-read | 基于 commit `f4d375a`
> 覆盖范围：`app/main.py` 路由 + `app/api_models.py` 模型
> 注：前端通过 `openapi-fetch` 调用，OpenAPI spec 见 `frontend/src/api/openapi.generated.ts`

---

## 1. 认证与会话

### `POST /users` — 注册
| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `username` | string | 是 | 用户名 |
| `password` | string | 是 | 密码 |
| `phone` | string | 否 | 手机号 |

返回：`201` + `AuthSessionResponse`

### `POST /sessions` — 登录
| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `username` | string | 是 | 用户名 |
| `password` | string | 是 | 密码 |

返回：`200` + `AuthSessionResponse`

### `POST /sessions/claim` — 匿名会话
| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `source` | string | 否 | 来源标识 |

返回：`200` + `AuthSessionResponse`（`is_registered: false`）

### `GET /session/status` — 会话状态
返回：`AuthenticatedSessionStatusResponse` 或 `AnonymousSessionStatusResponse`

| 字段 | 类型 | 说明 |
|---|---|---|
| `authenticated` | boolean | 是否已认证 |
| `is_registered` | boolean | 是否正式账户 |
| `auth_type` | string | "account" / "anonymous" |
| `session` | AuthSessionResponse | 会话详情 |

### `DELETE /session` — 登出
返回：`204`

---

## 2. 今日观察（Today）

### `GET /v1/today/overview` — 今日概览
**认证：正式账户**

返回：`TodayOverviewResponse`

| 字段 | 类型 | 说明 |
|---|---|---|
| `contract_version` | string | 固定 `"today_overview_v1"` |
| `generated_at` | string | ISO时间戳 |
| `session` | object | `{key, label, exchange_status, exchange_label, market_local_time}` |
| `summary` | object | `{headline, market_date, priority_count, related_change_count}` |
| `priority_items` | object | `{items[], total_visible, empty_message, ranking_method}` |
| `coverage` | object | `{status}` |
| `themes` | array | `[{key, title, status, tone, summary, basis}]` |
| `warnings` | string[] | 警告列表 |
| `boundary` | string | 免责声明 |

### `GET /indices` — 指数列表
**认证：公开**

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `scope` | string | 否 | 默认 `"all"` |
| `group` | string | 否 | `"china"` / `"us"` / `"hong_kong"` / `"europe"` / `"asia_pacific"` |

返回：`{indices: [{symbol, name, status, latest_close, change_1d, return_1d_pct, market_timestamp, is_stale}], warnings[]}`

### `GET /indices/{symbol}/history` — 指数历史
**认证：公开**

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `symbol` | path | 是 | 指数代码 |
| `range` | query | 否 | `"1mo"` / `"3mo"` / `"1y"` |

返回：`{closes: number[], market_timestamp}`

### `GET /markets/breadth` — 市场广度
**认证：公开**

返回：`MarketBreadthResponse`

| 字段 | 类型 | 说明 |
|---|---|---|
| `status` | string | `"available"` / `"unavailable"` |
| `market_date` | string | 市场日期 |
| `market_timestamp` | string | 数据时间 |
| `is_stale` | boolean \| null | 是否缓存数据 |
| `state` | string | 市场状态 |
| `total` | number | 全市场股票总数 |
| `advancers` | number | 上涨家数 |
| `decliners` | number | 下跌家数 |
| `unchanged` | number | 平盘家数 |
| `advance_ratio` | number | 上涨占比 |
| `decline_ratio` | number | 下跌占比 |
| `unchanged_ratio` | number | 平盘占比 |
| `coverage_ratio` | number | 数据覆盖率 |
| `limit_up_count` | number | 涨停家数 |
| `limit_down_count` | number | 跌停家数 |
| `limit_method` | string | 口径说明 |
| `turnover` | object | `{status, total_100m_cny, change_vs_previous_pct, history_comparison[]}` |
| `turnover_history` | array | `[{date, amount_100m_cny}]` |
| `distribution` | object | `{bins_7: [{bin, count, ratio}], median_pct_change}` |
| `exchange_status` | object | `{shanghai, shenzhen, beijing}` |

### `GET /markets/capital-flow` — 资金流向
**认证：公开**

返回：`{main_net_inflow_100m_cny, market_timestamp, is_stale, points: [{time, value_100m_cny}], method, warnings[]}`

### `GET /markets/anomalies` — 异动个股
**认证：公开**

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `limit` | int | 否 | 默认10 |

返回：`{status, market_timestamp, items: [{symbol, name, kind, pct_change}]}`

### `GET /markets/live` — 全球实时市场
**认证：公开**

返回：`{markets: [{key, name, latest_price, pct_change, currency, is_stale}]}`

### `GET /sectors/hot` — 热门板块
**认证：公开**

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `limit` | int | 否 | 默认10，前端传10或20 |

返回：`{source, market_timestamp, fetched_at, is_stale, sectors: [{code, name, pct_change, main_net_inflow}], warnings[]}`

### `GET /system/data-health` — 数据健康状态
**认证：公开**

返回：`{status, user_label, created_at, summary: {total, healthy, attention, critical}, categories: [{key, label, status, count}], actionable_checks: [{key, category, status, label}]}`

### `GET /research-reports/latest` — 最新研报
**认证：公开**

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `limit` | int | 否 | 默认20 |

返回：`{items: [{symbol, title, name, institution, rating, forecast_eps, published_at}]}`

---

## 3. 个人数据（需认证）

### `GET /me/watchlist/brief` — 关注列表摘要
**认证：正式账户**

返回：`{generated_at, requested, available, items: [{symbol, name}]}`

### `GET /me/research-actions` — 研究行动
**认证：正式账户**

返回：`{generated_at, items: [{id, symbol, name, title, status, status_label, next_step}], empty, boundary}`

### `GET /me/research-changes` — 研究变化
**认证：正式账户**

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `limit` | int | 否 | 默认20 |

返回：`{generated_at, items: [{id, symbol, summary, severity, event_type, data_as_of, latest_change}], requested, with_change_archive, boundary}`

### `GET /me/research-outcomes` — 研究结果
**认证：正式账户**

返回：`{generated_at, items: [{symbol, name, coverage: {available, pending}, latest_progress, latest_available[], latest_anchor[]}]}`

### `GET /v1/trade-reviews` — 交易复盘
**认证：正式账户**

返回：`{summary: {total, confirmed, archived, actionable, waiting_data, needs_confirmation}, items: [{id, name, symbol, status, can_confirm, operation, price_observation, current_version}]}`

### `GET /v1/positions` — 持仓
**认证：正式账户**

返回：`{items: [{workspace_id, symbol, name, quantity, cost_basis, average_cost}]}`

---

## 4. 选股与策略

### `GET /stock-screener/profiles` — 筛选器配置
**认证：公开**

返回：`{profiles: [{id, name, market, filters: [{key, label, type, options}]}]}`

### `POST /me/stock-screener` — 执行选股
**认证：正式账户**

Body：`{profile, market, max_results: 1-30, force_refresh: false, filters: {}}`

返回：`{items: [{symbol, name, ...}]}`

### `GET /v1/stock-strategies/li-zong/candidates` — 李总策略候选
**认证：正式账户**

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `status` | string | 否 | `"qualified"` / `"triggered"` / `"not_qualified"` / `"data_incomplete"` |
| `limit` | int | 否 | 默认200 |

返回：`{candidates: [{symbol, name, status, ...}]}`

### `GET /v1/stock-strategies/li-zong/runs/latest` — 最新策略运行
**认证：正式账户**

返回：`{id, strategy_id, strategy_version, parameter_version, data_version, as_of_date, run_scope, universe_count, prefiltered_count, coverage_ratio, status, ...}`

### `GET /v1/stock-strategies/li-zong/backtest` — 策略回测
**认证：正式账户**

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `period` | string | 是 | `"3m"` / `"1y"` / `"3y"` |

返回：`{period, metrics: {total_return, annualized_return, max_drawdown, sharpe_ratio}, equity_curve[]}`

---

## 5. 个股研究

### `GET /v1/stocks/{symbol}/page` — 个股页面聚合
**认证：正式账户**

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `symbol` | path | 是 | 股票代码 |
| `range` | query | 否 | `"1y"`（默认） |

返回：`{overview, technical, financials, events, research}` 各模块

### `GET /stocks/{symbol}/history` — 个股历史
**认证：公开**

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `symbol` | path | 是 | 股票代码 |
| `range` | query | 否 | `"3mo"` / `"6mo"` / `"1y"` |

返回：`{points: [{date, open, high, low, close, volume}], market_timestamp}`

### `GET /peer-comparisons/{symbol}` — 同业对比
**认证：正式账户**

返回：`{peers: [{symbol, name, ...}]}`

### `GET /v1/stocks/{symbol}/workspace` — 研究空间
**认证：正式账户**

返回：`{symbol, name, workspace}`

### `GET /v1/stocks/{symbol}/theses` — 研究判断
**认证：正式账户**

返回：`{theses: [{id, version_no, reason_text, status, created_at, confirmed_at}]}`

### `GET /v1/stocks/{symbol}/observation-tasks` — 观察任务
**认证：正式账户**

返回：`{items: [{id, title, description, status, updated_at, version}]}`

### `GET /v1/stocks/{symbol}/position` — 个股持仓
**认证：正式账户**

返回：`{workspace_id, symbol, name, quantity, cost_basis, average_cost}`

### `GET /me/deep-stock/{symbol}` — 深度研究
**认证：正式账户**

返回：`{symbol, session, ...}`

### `GET /v1/stock-workspaces` — 全部研究空间
**认证：正式账户**

返回：`{workspaces: [{symbol, name, ...}]}`

### `GET /v1/stocks/{symbol}/workspace/timeline` — 研究时间线
**认证：正式账户**

返回：`{data_meta, important_changes[], thesis_history[], observation_tasks, trade_review_summary}`

### `GET /research-reports/{symbol}` — 个股研报
**认证：正式账户**

返回：`{generated_at, title, items: [{symbol, title, name, institution, rating, forecast_eps, published_at}]}`

---

## 6. 顾问对话（Advisor）

### `GET /me/conversations` — 对话列表
**认证：正式账户**

返回：`{items: [{id, title, created_at, updated_at, message_count}]}`

### `GET /me/conversations/{conversation_id}` — 对话详情
**认证：正式账户**

返回：`{id, title, messages: [{role, content, created_at}]}`

### `POST /me/chat` — 发送消息
**认证：正式账户**

Body：`{message, symbol?: string, conversation_id?: string, request_id?: string}`

返回：`{request_id, response, conversation_id, ...}`

### `GET /me/chat/stream/{request_id}` — SSE进度
**认证：正式账户**

返回：SSE事件流 `{type, phase, label}`

### `GET /v1/ai-writebacks` — AI写入候选
**认证：正式账户**

返回：`{items: [{id, candidate_type, target_type, target_id, status, ...}]}`

### `POST /v1/ai-writebacks/{candidate_id}/confirm` — 确认写入
**认证：正式账户**

返回：`{...}`

### `POST /v1/ai-writebacks/{candidate_id}/reject` — 拒绝写入
**认证：正式账户**

返回：`{...}`

---

## 7. 搜索

### `GET /v1/search` — 全局搜索
**认证：正式账户**

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `q` | string | 是 | 搜索关键词 |

返回：`{results: [{type, symbol, name, ...}]}`

---

## 8. 基金产品

### `GET /fund-products/search` — 基金搜索
**认证：公开**

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `q` | string | 是 | 搜索关键词 |

返回：`{items: [{code, name, nav, ...}]}`

### `GET /fund-products/{code}` — 基金详情
**认证：公开**

返回：`{code, name, ...}`

### `GET /fund-products` — 基金列表
**认证：公开**

返回：`{items: [{code, name, ...}]}`

---

## 9. 管理/系统接口

| 路径 | 方法 | 功能 | 认证 |
|---|---|---|---|
| `/health` | GET | 健康检查 | 公开 |
| `/ready` | GET | 就绪检查 | 内部 |
| `/events` | GET | SSE事件流 | 无（前端轮询） |
| `/system/background` | GET | 后台任务状态 | 内部 |
| `/system/data-health` | GET | 数据健康 | 公开 |
| `/admin/job-queue` | GET | 任务队列 | 管理 |
| `/admin/job-queue/enqueue` | POST | 入队任务 | 管理 |
| `/admin/job-schedules` | GET | 调度列表 | 管理 |
| `/admin/operations/health` | GET | 运营健康 | 管理 |

---

## 10. 文件上传

### `POST /me/uploads/images` — 上传图片
**认证：正式账户**

Body：`multipart/form-data` + `UploadFile`

返回：`201` + `{url}`

---

## 11. 用户资料

### `GET /me` — 当前用户信息
**认证：正式账户**

返回：`{user: {id, username, phone, ...}}`

### `GET /me/risk-profile` — 风险档案
**认证：正式账户**

返回：`{profile: {...}}`

### `PUT /me/risk-profile/draft` — 风险草稿
**认证：正式账户**

Body：`RiskProfileDraft`

返回：`{draft}`

### `POST /me/risk-profile/confirm` — 确认风险档案
**认证：正式账户**

Body：`RiskProfileConfirm`

返回：`{profile}`

---

## 12. 金融数据（Tushare）

### `GET /v1/data/tushare/stocks/{symbol}/snapshot` — 股票快照
**认证：正式账户**

返回：`{snapshot: {...}}`

### `POST /v1/data/tushare/stocks/{symbol}/refresh` — 刷新快照
**认证：正式账户**

返回：`{snapshot}`

---

## 13. 策略与复盘

### `GET /v1/stock-strategies/li-zong` — 策略列表
**认证：正式账户**

返回：`{strategies: []}`

### `POST /v1/stock-strategies/li-zong/runs` — 启动策略运行
**认证：正式账户**

Body：`LiZongRunRequest`

返回：`202` + `{run_id}`

### `POST /v1/stock-strategies/li-zong/universe-runs` — 启动全市场运行
**认证：正式账户**

Body：`LiZongUniverseRunRequest`

返回：`202`

### `GET /v1/stock-strategies/li-zong/candidates/{symbol}` — 个股策略候选
**认证：正式账户**

返回：`{candidates: []}`

### `GET /v1/stock-strategies/li-zong/observation-pool` — 观察池
**认证：正式账户**

返回：`{items: []}`

### `GET /v1/stock-strategies/li-zong/history` — 策略历史
**认证：正式账户**

返回：`{runs: []}`

### `POST /v1/stock-strategies/li-zong/history/runs` — 启动历史回测
**认证：正式账户**

Body：`LiZongHistoryRunRequest`

返回：`202`

### `GET /v1/stock-strategies/li-zong/backtest` — 回测结果
**认证：正式账户**

返回：`{backtest}`

### `POST /v1/stock-strategies/li-zong/backtest/runs` — 启动组合回测
**认证：正式账户**

Body：`LiZongBacktestRunRequest`

返回：`202`

### `GET /v1/stock-strategies/li-zong/triggers` — 策略触发
**认证：正式账户**

返回：`{triggers: []}`

---

## 14. 研究与工作流

### `POST /v1/stocks/{symbol}/workspace` — 创建研究空间
**认证：正式账户**

Body：`{symbol}`

返回：`{workspace}`

### `PATCH /v1/stocks/{symbol}/relation` — 更新股票关系
**认证：正式账户**

Body：`{base_version, relation_type, priority, tracking_status, workflow_status, attention_tags}`

返回：`{relation}`（409冲突时需刷新）

### `POST /me/deep-stock` — 创建深度研究
**认证：正式账户**

Body：`{symbol}`

返回：`201` + `{session}`

### `GET /me/deep-stock/{symbol}` — 深度研究详情
**认证：正式账户**

返回：`{session}`

### `POST /v1/trade-reviews/{review_id}/confirm` — 确认复盘
**认证：正式账户**

Body：`{base_version}`

返回：`{review}`

### `POST /v1/trade-reviews/{review_id}/archive` — 归档复盘
**认证：正式账户**

Body：`{base_version}`

返回：`{review}`

### `GET /me/conversations` — 对话列表
**认证：正式账户**

返回：`{items: [{id, title, created_at, updated_at}]}`

### `POST /me/conversations` — 创建对话
**认证：正式账户**

Body：`{title?}`

返回：`201` + `{id, title}`

### `PATCH /me/conversations/{conversation_id}` — 更新对话
**认证：正式账户**

Body：`{title?}`

返回：`{conversation}`

### `DELETE /me/conversations/{conversation_id}` — 删除对话
**认证：正式账户**

返回：`204`

---

## 15. 顾问实验室（Legacy）

| 路径 | 方法 | 功能 | 认证 |
|---|---|---|---|
| `/advisor-lab` | GET | 顾问实验室页面 | 无（HTML） |
| `/legacy/advisor-lab` | GET | Legacy顾问实验室 | 无（HTML） |
| `/legacy/{legacy_path:path}` | GET | Legacy路径回退 | 无 |
