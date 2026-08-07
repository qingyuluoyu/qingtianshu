# 前端功能清单

> 分支：react-04-read | 基于 commit `f4d375a`
> 覆盖范围：`frontend/src/` | 框架：React 19 + TypeScript + Vite + TanStack React Query v5 + CSS Modules

---

## 1. 页面路由（6个正式页面 + 1个兜底）

| 路径 | 页面组件 | 认证要求 | 功能描述 |
|---|---|---|---|
| `/today` | `TodayPage` | 公开（部分内容需认证） | 今日观察：市场概况、指数、广度、板块、资金流向、个人研究 |
| `/market-data` | `MarketDataPage` | 公开（部分内容需认证） | 行情数据：指数总览、市场广度、板块热度、全球市场、资金流向 |
| `/screening` | `ScreeningPage` | 正式账户 | 透明选股：自定义筛选器 + 李总策略双模式 |
| `/watchlist` | `WatchlistPage` | 正式账户 | 我的关注：关注列表、研究空间、个股走势、关系管理 |
| `/stocks/:symbol` | `StockResearchPage` | 正式账户 | 个股研究：总览、行情技术、公司财务、事件预期、我的研究 |
| `/research-center` | `ResearchCenterPage` | 正式账户 | 研究中心：判断-变化-处理链、交易复盘中心 |
| `/advisor` | `AdvisorPage` | 正式账户 | AI顾问：对话、SSE进度、AI写入候选 |
| `/advisor/:conversationId` | `AdvisorPage` | 正式账户 | AI顾问（指定对话） |
| `*` | `NotFoundPage` | 公开 | 404兜底 |

---

## 2. 今日观察（/today）— 8个查询、10个模块

### 数据查询层（React Query）

| 查询键 | API端点 | 缓存策略 | 认证门控 |
|---|---|---|---|
| `overview` | `GET /v1/today/overview` | staleTime 30s | 正式账户 |
| `indices` | `GET /indices?scope=all&group=china` | staleTime 5min | **公开** |
| `breadth` | `GET /markets/breadth` | staleTime 5min | **公开** |
| `sectors` | `GET /sectors/hot?limit=10` | staleTime 5min | **公开** |
| `watchlist-brief` | `GET /me/watchlist/brief` | staleTime 30s | 正式账户 |
| `research-actions` | `GET /me/research-actions` | staleTime 30s | 正式账户 |
| `research-changes` | `GET /me/research-changes?limit=20` | staleTime 30s | 正式账户 |
| `data-health` | `GET /system/data-health` | staleTime 5min | 正式账户 |
| `index-history` | `GET /indices/{symbol}/history?range=1mo` | staleTime 30min | 按需 |
| `research-reports` | `GET /research-reports/latest?limit=20` | staleTime 5min | 公开 |
| `capital-flow` | `GET /markets/capital-flow` | staleTime 5min | **公开** |
| `positions` | `GET /v1/positions` | staleTime 30s | 正式账户 |
| `market-anomalies` | `GET /markets/anomalies?limit=10` | staleTime 5min | 公开 |
| `global-indices` | `GET /indices?scope=all&group=us` | staleTime 5min | **公开** |
| `markets-live` | `GET /markets/live` | staleTime 5min | **公开** |

### 页面模块

| 模块 | 组件 | 数据源 | 说明 |
|---|---|---|---|
| Header | `TodayHeader` | overview | 交易状态、市场日期、刷新按钮、SSE状态 |
| 主要指数 | `IndexSection` | indices | 5个指数卡片（上证/深证/创业板/沪深300/科创50），含Sparkline走势 |
| 市场广度 | `MarketBreadthCard` | breadth | SVG Donut图（上涨/下跌/平盘）+ 覆盖率 |
| 两市成交额 | `TurnoverCard` | breadth | 今日成交额 + 较前一交易日对比 + BarChart历史走势 |
| 涨跌分布 | `DistributionCard` | breadth | Histogram五档分布图（≥3%/0~3%/平盘/-3%~0/≤-3%） |
| 资金流向 | `CapitalFlowCard` | capitalFlow | 主力净流入 + Sparkline当日累计 + 北向资金说明 |
| 板块热度 | `SectorCard` | sectors | 可配置行数（默认8），含涨跌幅+净流入 |
| 我的股票新变化 | `ChangesCard` | changes + positions | 双Tab：全部/持仓，含变化时间线 + 持仓表格 |
| 今日优先事项 | `PersonalResearchSection` | overview + actions + watchlist | 主题卡 + 优先级列表 + 关注状态 |
| 全球市场观察 | `GlobalMarketCard` | globalIndices + liveMarkets | 美股三大指数 + 美元/黄金/原油/美债收益率 |
| 异动机会/风险 | `AnomalyCard` | anomalies | 涨跌幅≥7%个股 |
| 今日研究报告 | `ResearchReportsCard` | researchReports | 最新研报列表 |
| 数据健康状态 | `DataHealthBar` | dataHealth | 健康/关注/关键计数 |

### 关键设计决策
- **react-04变更**：indices/breadth/sectors/capitalFlow/globalIndices/liveMarkets/anomalies/researchReports 从认证门控改为公开（anonymous用户可见）
- `PersonalResearchSection` 和 `DataHealthBar` 对anonymous用户返回null
- `indexHistory` 按需加载：authenticated && publicSettled
- SSE连接：`usePublicEvents(formal)` — 仅正式账户建立SSE

---

## 3. 行情数据（/market-data）— 新增页面

### 数据查询

| 查询键 | API端点 | 说明 |
|---|---|---|
| `market-data` indices | `GET /indices?scope=all&group={group}` | 分组切换：中国/香港/美国/欧洲/亚太 |
| `today` breadth | `GET /markets/breadth` | 复用今日查询键 |
| `market-data` sectors | `GET /sectors/hot?limit={limit}` | 复用今日解析器，limit可配置 |
| `today` capitalFlow | `GET /markets/capital-flow` | 复用今日查询键 |
| `today` liveMarkets | `GET /markets/live` | 复用今日查询键 |
| `today` indexHistory | `GET /indices/{symbol}/history` | 展开行查看近1月走势 |

### 页面模块

| 模块 | 说明 |
|---|---|
| IndexExplorer | 分组Tab（中国/香港/美国/欧洲/亚太），点击展开查看近1月Sparkline |
| MarketBreadthCard | 复用今日组件 |
| TurnoverCard | 复用今日组件 |
| DistributionCard | 复用今日组件 |
| SectorCard | 复用今日组件，maxItems=SECTOR_LIMIT(20) |
| CapitalFlowCard | 复用今日组件 |
| GlobalMarketCard | 复用今日组件，自定义liveOrder（含china/japan/korea/us/...） |

### 认证行为
- anonymous：显示市场广度、成交额、分布、资金流向、全球市场；指数分组和板块热度锁定
- authenticated：全部模块可见

---

## 4. 透明选股（/screening）— 双模式

### 数据查询

| 查询键 | API端点 | 说明 |
|---|---|---|
| screener-profiles | `GET /stock-screener/profiles` | 获取筛选器配置 |
| 筛选结果 | `POST /me/stock-screener` | 执行筛选（force_refresh: false） |
| li-zong-candidates | `GET /v1/stock-strategies/li-zong/candidates` | 李总策略候选 |
| li-zong-runs/latest | `GET /v1/stock-strategies/li-zong/runs/latest` | 最新策略运行 |
| li-zong-backtest | `GET /v1/stock-strategies/li-zong/backtest?period={period}` | 策略回测（3m/1y/3y） |

### 页面功能
- 通用筛选：选择profile → 选择市场 → 调整maxResults(1-30) → 查看结果
- 李总策略：查看候选股票、最新运行状态、回测曲线
- 状态过滤：qualified / triggered / not_qualified / data_incomplete

---

## 5. 我的关注（/watchlist）— 可写页面

### 数据查询

| 查询键 | API端点 | 方法 |
|---|---|---|
| stock-workspaces | `GET /v1/stock-workspaces` | 获取全部研究空间 |
| stock-workspace | `GET /v1/stocks/{symbol}/workspace` | 个股研究空间 |
| stock-history | `GET /stocks/{symbol}/history?range=3mo` | 近3月历史 |
| stock-relation | `PATCH /v1/stocks/{symbol}/relation` | 更新关系（409冲突处理） |

### 页面功能
- 关注列表：关注股票 + 研究状态
- 研究空间：个股研究总览
- 走势图：CandlestickChart + 关系管理
- 可写操作：更新股票关系（relation_type, priority, tracking_status, workflow_status）

---

## 6. 个股研究（/stocks/:symbol）— 5个Tab

### 数据查询

| 查询键 | API端点 | Tab |
|---|---|---|
| stock-page | `GET /v1/stocks/{symbol}/page?range=1y` | 研究总览 |
| stock-history | `GET /stocks/{symbol}/history?range={3mo\|6mo\|1y}` | 行情技术 |
| peer-comparisons | `GET /peer-comparisons/{symbol}` | 公司财务 |
| stock-workspace | `GET /v1/stocks/{symbol}/workspace` | 我的研究 |
| theses | `GET /v1/stocks/{symbol}/theses` | 我的研究 |
| observation-tasks | `GET /v1/stocks/{symbol}/observation-tasks` | 我的研究 |
| stock-position | `GET /v1/stocks/{symbol}/position` | 我的研究 |
| deep-stock | `GET /me/deep-stock/{symbol}` | 我的研究 |

### 页面功能
- **研究总览**：公司概况 + 关键指标
- **行情技术**：K线图（CandlestickChart）+ 历史走势切换（3月/6月/1年）
- **公司财务**：财务数据 + 同业对比
- **事件预期**：事件时间线 + 分析师预期
- **我的研究**：研究空间、判断、观察任务、持仓、深度研究

---

## 7. 研究中心（/research-center）— 三栏布局

### 数据查询

| 查询键 | API端点 | 说明 |
|---|---|---|
| research-changes | `GET /me/research-changes` | 研究变化 |
| research-outcomes | `GET /me/research-outcomes` | 研究结果 |
| research-actions | `GET /me/research-actions` | 研究行动 |
| trade-reviews | `GET /v1/trade-reviews` | 交易复盘 |
| workspace-timeline | `GET /v1/stocks/{symbol}/workspace/timeline` | 股票时间线 |
| research-report | `GET /research-reports/{symbol}` | 个股研报 |

### 页面功能
- **左侧**：研究股票列表（变化 + 结果 + 复盘聚合）
- **中上**：判断-变化-处理链（Thesis版本历史 + 变化记录 + 观察任务）
- **中下**：报告变化（ReportDiff：维度变化 + 新增证据）
- **中下**：结果进度（OutcomeAnchor：交易日窗口 + 窗口收益 + 进度条）
- **中下**：历史结果（OutcomeCard：锚点价格 + 基准 + 数据可得时间）
- **右侧**：下一步行动（ReviewActions：触发事项 + 跳转链接）
- **右侧**：交易复盘中心（状态机：draft → confirmed → archived，含409冲突处理）

### 可写操作
- 确认复盘草稿（`POST /v1/trade-reviews/{id}/confirm`）
- 归档复盘（`POST /v1/trade-reviews/{id}/archive`）

---

## 8. AI顾问（/advisor）— 对话 + SSE

### 数据查询

| 查询键 | API端点 | 方法 |
|---|---|---|
| conversations | `GET /me/conversations` | 对话列表 |
| conversation | `GET /me/conversations/{id}` | 对话详情 |
| chat | `POST /me/chat` | 发送消息 |
| ai-writebacks | `GET /v1/ai-writebacks` | AI写入候选 |
| confirm-writeback | `POST /v1/ai-writebacks/{id}/confirm` | 确认写入 |
| reject-writeback | `POST /v1/ai-writebacks/{id}/reject` | 拒绝写入 |

### 页面功能
- 对话列表 + 新建对话
- 消息流（用户/AI交替）
- SSE进度条（`EventSource /me/chat/stream/{request_id}`）
- AI写入候选：确认/拒绝（409冲突处理）
- 上下文携带：symbol + source 参数

---

## 9. 共享组件库

| 组件 | 文件 | 用途 |
|---|---|---|
| `AppShell` | `components/AppShell.tsx` | 全局布局：Header + 导航 + Footer |
| `ErrorBoundary` | `components/ErrorBoundary.tsx` | React错误边界（新增） |
| `ModuleCard` | `features/today/TodayComponents.tsx` | 统一卡片容器：title + meta + skeleton + error + retry |
| `DonutChart` | `features/today/charts.tsx` | SVG环图（adv/dec/unch三段） |
| `BarChart` | `features/today/charts.tsx` | HTML/CSS柱状图（成交额历史） |
| `Histogram` | `features/today/charts.tsx` | 涨跌分布直方图 |
| `Sparkline` | `features/today/charts.tsx` | SVG迷你走势线 |
| `CandlestickChart` | `features/stock-research/charts.tsx` | K线图 |

---

## 10. 工具函数与适配器

| 模块 | 文件 | 功能 |
|---|---|---|
| `parseOverview` | `adapters.ts` | 解析今日概览（contract_version: today_overview_v1） |
| `parseIndices` | `adapters.ts` | 解析指数列表（固定5个中国指数） |
| `parseBreadth` | `adapters.ts` | 解析市场广度（含distribution回退、turnover_history回退） |
| `parseSectors` | `adapters.ts` | 解析板块热度（可配置limit） |
| `parseCapitalFlow` | `adapters.ts` | 解析资金流向 |
| `parseDataHealth` | `adapters.ts` | 解析数据健康状态 |
| `parseGlobalIndices` | `adapters.ts` | 解析全球指数（美股三大 + 全球8品种） |
| `parseLiveMarkets` | `adapters.ts` | 解析全球实时市场 |
| `parseIndexHistory` | `adapters.ts` | 解析指数历史 |
| `parseMarketAnomalies` | `adapters.ts` | 解析异动个股 |
| `parseWatchlistBrief` | `adapters.ts` | 解析关注列表摘要 |
| `parseResearchActions` | `adapters.ts` | 解析研究行动 |
| `parseResearchChanges` | `adapters.ts` | 解析研究变化 |
| `parseLatestResearchReports` | `adapters.ts` | 解析最新研报 |
| `parsePositions` | `adapters.ts` | 解析持仓 |

---

## 11. 错误处理策略

| 场景 | 处理方式 |
|---|---|
| HTTP 401 | 显示"会话已失效"，触发登录 |
| HTTP 404 | 某些端点（如theses/position/deep-stock）404视为合法空态，返回null |
| HTTP 409 | 冲突时刷新数据，不覆盖 |
| 网络错误 | 静默降级，显示"数据暂时不可用" |
| SSE断开 | 静默降级，主链路不受影响 |
| 解析失败 | `ContractError`，显示模块级错误 |

---

## 12. 数据直通原则

- 所有百分数字段后端已是百分数，前端直接加`%`不缩放
- 红涨绿跌灰平：`#d92d20`（涨）、`#039855`（跌）、`#98a2b3`（平）
- 时间格式化：`Intl.DateTimeFormat` + `Asia/Shanghai`时区
- 状态翻译：只翻译后端状态码，不自行推断
- null处理：`"暂无"` / `"--"` / 空数组，不显示虚假数据
