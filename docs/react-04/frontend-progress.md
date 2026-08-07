# 前端进度清单（已完成 / 未完成）

> 分支：react-04-read | 基于 commit `f4d375a`
> 最后更新：2026-08-07

---

## 1. 页面完成度总览

| 页面 | 路由 | 状态 | 说明 |
|---|---|---|---|
| 今日观察 | `/today` | ✅ 完成 | 8个查询、10个模块、全功能 |
| 行情数据 | `/market-data` | ✅ 完成 | 新增页面，指数分组、广度、板块、全球市场 |
| 透明选股 | `/screening` | ✅ 完成 | 通用筛选 + 李总策略双模式 |
| 我的关注 | `/watchlist` | ✅ 完成 | 关注列表、研究空间、关系管理（可写） |
| 个股研究 | `/stocks/:symbol` | ✅ 完成 | 5个Tab：总览/技术/财务/事件/研究 |
| 研究中心 | `/research-center` | ✅ 完成 | 三栏布局、判断链、变化、结果、复盘中心 |
| AI顾问 | `/advisor` | ✅ 完成 | 对话、SSE进度、AI写入候选 |
| 404兜底 | `*` | ✅ 完成 | NotFoundPage |

---

## 2. 今日观察（/today）完成度

### 模块完成度

| 模块 | 状态 | 说明 |
|---|---|---|
| Header (TodayHeader) | ✅ | 交易状态、市场日期、刷新、SSE状态 |
| 主要指数 (IndexSection) | ✅ | 5个指数（上证/深证/创业板/沪深300/科创50），含Sparkline |
| 市场广度 (MarketBreadthCard) | ✅ | SVG Donut图（adv/dec/unch三段） |
| 两市成交额 (TurnoverCard) | ✅ | 成交额 + 对比 + BarChart历史 |
| 涨跌分布 (DistributionCard) | ✅ | Histogram五档分布图 |
| 资金流向 (CapitalFlowCard) | ✅ | 主力净流入 + Sparkline + 北向说明 |
| 板块热度 (SectorCard) | ✅ | 可配置行数，含涨跌幅+净流入 |
| 我的股票新变化 (ChangesCard) | ✅ | 双Tab：全部/持仓 |
| 今日优先事项 (PersonalResearchSection) | ✅ | 主题卡 + 优先级列表（认证） |
| 全球市场观察 (GlobalMarketCard) | ✅ | 美股三大 + 美元/黄金/原油/美债 |
| 异动机会/风险 (AnomalyCard) | ✅ | 涨跌幅≥7%个股 |
| 今日研究报告 (ResearchReportsCard) | ✅ | 最新研报列表 |
| 数据健康状态 (DataHealthBar) | ✅ | 健康/关注/关键计数（认证） |

### react-04变更

| 变更项 | 状态 | 说明 |
|---|---|---|
| indices查询去auth gate | ✅ | anonymous可见中国指数 |
| breadth查询去auth gate | ✅ | anonymous可见市场广度 |
| sectors查询去auth gate | ✅ | anonymous可见板块热度 |
| capitalFlow查询去auth gate | ✅ | anonymous可见资金流向 |
| globalIndices查询去auth gate | ✅ | anonymous可见全球指数 |
| liveMarkets查询去auth gate | ✅ | anonymous可见全球实时市场 |
| anomalies查询去auth gate | ✅ | anonymous可见异动个股 |
| researchReports查询去auth gate | ✅ | anonymous可见研报列表 |
| PersonalResearchSection条件渲染 | ✅ | 仅认证用户渲染 |
| DataHealthBar条件渲染 | ✅ | 仅认证用户渲染 |

---

## 3. 行情数据（/market-data）完成度

| 功能 | 状态 | 说明 |
|---|---|---|
| 指数总览（分组Tab） | ✅ | 中国/香港/美国/欧洲/亚太 |
| 指数展开行 | ✅ | 点击查看近1月Sparkline走势 |
| 市场广度 | ✅ | 复用MarketBreadthCard |
| 成交额 | ✅ | 复用TurnoverCard |
| 涨跌分布 | ✅ | 复用DistributionCard |
| 板块热度 | ✅ | 复用SectorCard，maxItems=20 |
| 资金流向 | ✅ | 复用CapitalFlowCard |
| 全球市场 | ✅ | 复用GlobalMarketCard，8品种 |
| 匿名视图 | ✅ | 公共模块可见，指数/板块锁定 |
| 刷新功能 | ✅ | 批量invalidate相关queries |
| DESIGN.md | ✅ | 数据契约文档 |

### react-04变更

| 变更项 | 状态 | 说明 |
|---|---|---|
| 新增MarketDataPage组件 | ✅ | 144行TSX + 38行CSS |
| 新增market-data/api.ts | ✅ | 复用today解析器 |
| 新增market-data/queries.ts | ✅ | 独立queryKey命名空间 |
| 新增market-data/MarketDataPage.test.tsx | ✅ | 256行测试 |
| 新增market-data/e2e测试 | ✅ | market-data.spec.ts |
| 路由注册 | ✅ | App.tsx中注册/market-data |
| 移除PlaceholderPage | ✅ | 不再有占位页 |

---

## 4. 透明选股（/screening）完成度

| 功能 | 状态 | 说明 |
|---|---|---|
| 筛选器配置加载 | ✅ | GET /stock-screener/profiles |
| 通用筛选执行 | ✅ | POST /me/stock-screener |
| 筛选结果展示 | ✅ | 股票列表 + 详情 |
| 李总策略候选 | ✅ | GET /v1/stock-strategies/li-zong/candidates |
| 策略运行状态 | ✅ | GET /v1/stock-strategies/li-zong/runs/latest |
| 策略回测 | ✅ | GET /v1/stock-strategies/li-zong/backtest |
| 状态过滤 | ✅ | qualified/triggered/not_qualified/data_incomplete |
| 409冲突处理 | ✅ | 写操作冲突时刷新 |

---

## 5. 我的关注（/watchlist）完成度

| 功能 | 状态 | 说明 |
|---|---|---|
| 关注列表 | ✅ | GET /v1/stock-workspaces |
| 个股研究空间 | ✅ | GET /v1/stocks/{symbol}/workspace |
| 个股走势 | ✅ | CandlestickChart + 3mo历史 |
| 关系管理（可写） | ✅ | PATCH /v1/stocks/{symbol}/relation |
| 409冲突处理 | ✅ | 关系更新冲突时刷新 |

---

## 6. 个股研究（/stocks/:symbol）完成度

| 功能 | 状态 | 说明 |
|---|---|---|
| 研究总览Tab | ✅ | 公司概况 + 关键指标 |
| 行情技术Tab | ✅ | K线图 + 历史切换（3mo/6mo/1y） |
| 公司财务Tab | ✅ | 财务数据 + 同业对比 |
| 事件预期Tab | ✅ | 事件时间线 + 分析师预期 |
| 我的研究Tab | ✅ | 研究空间、判断、观察任务、持仓、深度研究 |
| 个股页面聚合 | ✅ | GET /v1/stocks/{symbol}/page |
| 个股历史 | ✅ | GET /stocks/{symbol}/history |
| 同业对比 | ✅ | GET /peer-comparisons/{symbol} |
| 研究判断 | ✅ | GET /v1/stocks/{symbol}/theses |
| 观察任务 | ✅ | GET /v1/stocks/{symbol}/observation-tasks |
| 个股持仓 | ✅ | GET /v1/stocks/{symbol}/position |
| 深度研究 | ✅ | GET /me/deep-stock/{symbol} |

---

## 7. 研究中心（/research-center）完成度

| 功能 | 状态 | 说明 |
|---|---|---|
| 研究股票列表 | ✅ | 变化 + 结果 + 复盘聚合 |
| 概览卡片 | ✅ | 待复盘/判断有变化/已有结果 |
| 判断链 | ✅ | Thesis版本历史 |
| 变化时间线 | ✅ | 变化记录 + 新增证据 |
| 处理链 | ✅ | 观察任务 + 交易复盘 |
| 报告变化 | ✅ | ReportDiff：维度变化对比 |
| 结果进度 | ✅ | OutcomeAnchor：交易日窗口 + 进度条 |
| 历史结果 | ✅ | OutcomeCard：锚点 + 基准 |
| 下一步行动 | ✅ | ReviewActions：触发事项 + 跳转 |
| 交易复盘中心 | ✅ | 状态机 + confirm/archive + 409 |
| 聚焦过滤 | ✅ | 全部/待复盘/判断有变化/已有结果 |
| 写操作 | ✅ | confirm + archive（含409处理） |

---

## 8. AI顾问（/advisor）完成度

| 功能 | 状态 | 说明 |
|---|---|---|
| 对话列表 | ✅ | GET /me/conversations |
| 新建对话 | ✅ | POST /me/conversations |
| 对话详情 | ✅ | GET /me/conversations/{id} |
| 发送消息 | ✅ | POST /me/chat |
| SSE进度 | ✅ | EventSource /me/chat/stream/{id} |
| AI写入候选列表 | ✅ | GET /v1/ai-writebacks |
| 确认写入 | ✅ | POST /v1/ai-writebacks/{id}/confirm |
| 拒绝写入 | ✅ | POST /v1/ai-writebacks/{id}/reject |
| 409冲突处理 | ✅ | 写操作冲突时刷新 |
| 上下文携带 | ✅ | symbol + source参数 |

---

## 9. 全局功能完成度

| 功能 | 状态 | 说明 |
|---|---|---|
| 路由 | ✅ | 7个路由 + 404兜底 |
| 认证门控 | ✅ | AuthModal + 会话管理 |
| 错误边界 | ✅ | ErrorBoundary包裹ProductApp |
| 数据缓存 | ✅ | TanStack React Query v5 |
| 错误重试 | ✅ | 1次重试（react-04变更） |
| SSE事件 | ✅ | usePublicEvents hook |
| 类型安全 | ✅ | openapi-typescript生成类型 |
| 适配器层 | ✅ | 所有API响应的类型安全解析 |
| 单元测试 | ✅ | 每个feature有.test.tsx |
| E2E测试 | ✅ | Playwright specs |
| 响应式布局 | ✅ | CSS Modules + 媒体查询 |

---

## 10. 未完成 / 待实现功能

| 功能 | 状态 | 说明 |
|---|---|---|
| 股票搜索页面 | ❌ 未实现 | `/search` 路由存在，前端无对应页面组件 |
| 基金产品页面 | ❌ 未实现 | API已实现，前端无页面 |
| 风险档案页面 | ❌ 未实现 | API已实现，前端无页面 |
| 深度研究独立页 | ❌ 未实现 | 仅作为个股研究Tab的一部分 |
| 个人资料/设置 | ❌ 未实现 | 仅API端点 |
| 文件上传UI | ❌ 未实现 | API已实现 |
| 李总历史回测独立页 | ❌ 未实现 | 仅作为选股页的一部分 |
| 策略运行监控页 | ❌ 未实现 | API已实现，前端无页面 |
| 观察任务管理 | ❌ 仅展示 | 观察任务仅展示，无创建/编辑 |
| 研究计划管理 | ❌ 仅展示 | 研究计划API存在，前端未接入 |
| 盈利质量页 | ❌ 未实现 | API已实现，前端未接入 |
| 财务驱动因素 | ❌ 未实现 | API已实现，前端未接入 |
| 公告分析页 | ❌ 未实现 | API已实现，前端未接入 |
| 股东结构页 | ❌ 未实现 | API已实现，前端未接入 |
| 业务结构页 | ❌ 未实现 | API已实现，前端未接入 |
| 分析师预期页 | ❌ 未实现 | API已实现，前端未接入 |
| 知识库页面 | ❌ 未实现 | API已实现，前端无页面 |
| 文章生成页 | ❌ 未实现 | API已实现，前端无页面 |
| 后台管理 | ❌ 未实现 | Admin路由存在，前端无页面 |
| 全局搜索页面 | ❌ 未实现 | API已实现，前端无独立搜索页 |

---

## 11. 测试覆盖度

| 测试类型 | 状态 | 文件 |
|---|---|---|
| 单元测试 | ✅ | 每个feature模块有.test.tsx |
| 适配器测试 | ✅ | adapters.test.ts（含distribution/exchangeBreakdown） |
| 事件测试 | ✅ | events.test.ts（SSE） |
| 会话测试 | ✅ | session.test.ts |
| 截图测试 | ✅ | screenshots.spec.ts |
| E2E - 今日 | ✅ | today.spec.ts |
| E2E - 选股 | ✅ | screening.spec.ts |
| E2E - 关注 | ✅ | watchlist.spec.ts |
| E2E - 研究中心 | ✅ | research-center.spec.ts |
| E2E - 顾问 | ✅ | advisor.spec.ts |
| E2E - 个股 | ✅ | stock-research.spec.ts |
| E2E - 行情 | ✅ | market-data.spec.ts（新增） |
| E2E - 认证 | ✅ | auth-gate.spec.ts |

---

## 12. 已知限制

| 限制 | 说明 |
|---|---|
| 无离线支持 | 无Service Worker/PWA |
| 无暗色模式 | 仅亮色主题 |
| 无国际化 | 仅中文界面 |
| 无移动端独立布局 | 响应式但非独立移动端设计 |
| 数据不持久化 | 无localStorage缓存（除React Query） |
| 无消息推送 | 仅SSE（需页面打开） |
