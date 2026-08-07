# 行情数据（/market-data）组件设计记录

执行合同：FRONTEND_EXECUTION_CONTRACT_V1（§6 数据/时间/金融口径、§7 互动与写入边界、§8 禁止约定）。
本页为纯只读行情数据中心，无写操作；是合同六页之外的补充页，复用今日页市场组件体系，自此导航零占位页。

## 数据契约总表

| 用途 | 接口 | 关键字段 | 时间类型（§6.2） |
| --- | --- | --- | --- |
| 指数总览（分组 tab） | `GET /indices?scope=all&group={group}` | `indices[*].{symbol,name,status,metrics.{latest_close,change_1d,return_1d_pct},market_timestamp,is_stale}` | MarketAsOf = `market_timestamp` |
| 指数近 1 月走势（展开行） | `GET /indices/{symbol}/history?range=1mo` | `points[*].close`、`market_timestamp` | MarketAsOf = `market_timestamp` |
| 市场广度 / 成交额 / 涨跌分布 | `GET /markets/breadth` | `breadth.*`、`turnover.*`、`distribution.bins_7`、`coverage.coverage_ratio`、`turnover_history` | MarketAsOf = `market_date` / `market_timestamp` |
| 板块热度 | `GET /sectors/hot?limit=20` | `sectors[*].{code,name,pct_change,main_net_inflow}`、`is_stale`、`warnings` | MarketAsOf = `market_timestamp` / `fetched_at` |
| 全球市场（8 品种） | `GET /markets/live` | `markets[*].{key,name,latest_price,pct_change,currency,is_stale}` | MarketAsOf = `market_timestamp` |
| 资金流向 | `GET /markets/capital-flow` | `summary.main_net_inflow_100m_cny`、`points`、`method`、`warnings` | MarketAsOf = `market_timestamp` |

复用边界（import 复用，不复制实现）：
- 组件：`ModuleCard` / `MarketBreadthCard` / `TurnoverCard` / `DistributionCard` / `SectorCard` / `CapitalFlowCard` / `GlobalMarketCard` / `formatDateTime` / `formatNumber`（today/TodayComponents），`Sparkline`（today/charts）。
- 解析器：`parseGlobalIndices` / `parseSectors` / `parseIndexHistory`（today/adapters）。
- 查询：`todayQueries.breadth/capitalFlow/liveMarkets/indexHistory` 直接复用（与今日页共享缓存键）；页面级新增 `marketDataQueries.indices(group)` 与 `marketDataQueries.sectors(limit)`。

today 侧可选参数（默认值保持原行为，今日页不受影响）：
- `parseSectors(value, limit = 10)`：解析上限可放宽；默认 10 与今日页一致。
- `SectorCard maxItems = 8`：渲染行数可放宽；本页传 20。
- `GlobalMarketCard liveOrder = LIVE_MARKET_ORDER`：live 品种白名单可替换；本页传 8 品种目录序（china/japan/korea/us/london_gold/dollar_index/brent_crude/us10y_yield），且不传 `indices`，只渲染 live 部分。

金融口径（直通锁覆盖）：
- `return_1d_pct` / `pct_change` / `change_vs_previous_pct` 后端已是百分数，UI 直通加 `%`，不缩放。
- `main_net_inflow` 东财 f62 原始单位为元，adapter 统一换算亿元（/1e8）后直通；`main_net_inflow_100m_cny`、`total_amount_100m_cny` 后端已是亿元，直通。
- `currency === "PCT"`（美债十年期收益率）渲染为 `值%`，其余品种渲染 `值 币种`，由 GlobalMarketCard 原逻辑直通。

四态区分（§6.3）：`0` 正常显示；`null` → 「暂无」；`status != "available"` 或 `latest_close` 缺失 → 行内「暂不可用」（不是 0）；空列表 → 「该分组暂无可确认指数数据」；接口失败 → 模块级错误卡（「本模块暂时不可用」+ 重试），不影响其他模块。

## 模块设计

### IndexExplorer（指数总览）
- 页面与用户问题：各市场主要指数现在什么水平？近 1 月怎么走？
- 分组 tab：中国 china / 香港 hong_kong / 美国 us / 欧洲 europe / 亚太 asia_pacific（与后端 `catalog.py` group 一致）；tab 进 URL `?group=`（china 为默认，省略参数），刷新/分享直达。
- 真实数据：`GET /indices?scope=all&group=…` 经 `parseGlobalIndices` 通用解析（不同于今日页固定 5 只的 `parseIndices`，本页展示分组全量，含中证500、恒生科技等）。
- 互动事件：点击指数行展开近 1 月走势（`todayQueries.indexHistory(symbol)`，仅展开时取数，Sparkline + 数据时间）；再次点击收起；切换分组自动收起。
- 状态：走势读取中 / 失败（行内「走势数据暂时不可用」+ 重试）/ 点数不足（「暂无足够走势数据」）三分支。
- 响应式：≤760px 表格隐藏涨跌与市场时间两列，保留名称/最新价/涨跌幅。

### 市场广度三卡 / 板块热度 / 资金流向 / 全球市场
- 全部复用 today 卡片组件，挂 ModuleCard 失败隔离；数据源与今日页相同（breadth 一源三卡）。
- 板块热度：limit=20、maxItems=20，比今日页（10/8）展示更全；is_stale/warnings 角标沿用。
- 全球市场：仅 live 8 品种（指数类已在分组 tab 呈现，不重复）；失败隔离只挂 `/markets/live` 一个端点。
- 页级「刷新」：失效 `["market-data"]` 及复用的 `["today","breadth"|"capital-flow"|"markets-live"|"index-history"]` 键。

### 未登录锁定
- 与其他特性页一致：`authenticated=false` 时不发任何查询，渲染「业务内容已锁定，请先登录或注册。」；由 App 层 AuthModal 承接登录。

## 验收记录

- `npx vitest run src/features/market-data`：6/6 通过（直通渲染+八品种、tab 切组+URL、URL 直达、展开行走势、单模块失败隔离+重试、未登录锁定）。
- `npx tsc --noEmit`：通过。
- `npx playwright test e2e/market-data.spec.ts`：3/3 通过（桌面全模块+切组+展开走势、单端点 500 失败隔离、390px 移动视口无横向溢出）。
- 全量 `npx vitest run`：通过，未破坏其他特性；today 侧三处可选参数默认值与原行为一致（adapters/SectorCard/GlobalMarketCard 现有测试全绿）。
- 真实会话截图：`today-runtime-trace/screenshots/market-data-desktop.png`（1440×900）、`market-data-mobile.png`（390×844），两视口横向溢出 0px。
