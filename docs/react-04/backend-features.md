# 后端功能清单

> 分支：react-04-read | 基于 commit `f4d375a`
> 覆盖范围：`app/main.py` + `app/services/` + `app/providers/`

---

## 1. 数据提供层（Providers）

| 提供者 | 文件 | 功能 | 数据字段 |
|---|---|---|---|
| `SinaMarketBreadthProvider` | `app/providers/market.py` | 全市场广度（涨跌家数、五档分布、成交额、历史对比） | `advancers`/`decliners`/`unchanged`、`turnover`、`distribution.bins_7`、`turnover_history`、`coverage_ratio`、`exchange_status` |
| `SinaIndustrySectorProvider` | `app/providers/market.py` | 行业板块热度 | `sectors[*].{code,name,pct_change,main_net_inflow}` |
| `EastmoneySectorProvider` | `app/providers/market.py` | 东方财富板块热度（备用/补充） | 同上 |
| `EastmoneyCapitalFlowProvider` | `app/providers/market.py` | 主力资金流向 | `main_net_inflow`、`points[]`、`method`、`warnings` |
| `EastmoneyGlobalIndexProvider` | `app/providers/market.py` | 全球指数（美股三大、港股、亚太） | `indices[*].{symbol,name,latest_close,change_1d,return_1d_pct}` |
| `YahooMarketProvider` | `app/providers/market.py` | 美元指数、伦敦金、布伦特原油、美债收益率 | `markets[*].{key,name,latest_price,pct_change,currency}` |
| `SinaGoldProvider` | `app/providers/market.py` | 黄金价格（备用） | `latest_price`、`pct_change` |
| `TencentChinaIndexProvider` | `app/providers/market.py` | 中国指数（上证、深证、创业板、科创50、沪深300） | `indices[*].{symbol,name,latest_close,change_1d,return_1d_pct,market_timestamp}` |
| `CSIIndustryIndexProvider` | `app/providers/market.py` | CSI行业指数 | `indices[*].{symbol,name,latest_close}` |
| `A股信息提供商` | `app/providers/china_info.py` | A股公司基本信息 | `company_name`、`industry`、`description` |
| `A股股东结构` | `app/providers/shareholders.py` | 十大股东/流通股东 | `shareholders[]`、`holder_name`、`hold_ratio` |
| `A股业务结构` | `app/providers/business_structure.py` | 营收/利润结构 | `segments[]`、`revenue`、`profit` |
| `A股分析师预期` | `app/providers/analyst_expectations.py` | EPS/营收预测 | `forecasts[]`、`eps`、`revenue` |
| `A股财务基础` | `app/providers/fundamentals.py` | 财务三表 | `balance_sheet`、`income_statement`、`cash_flow` |
| `A股公告` | `app/providers/filings.py` | 公告检索 | `announcements[]`、`title`、`publish_date` |
| `A股基金产品` | `app/providers/funds.py` | 基金搜索/详情 | `funds[]`、`code`、`name`、`nav` |
| `全球信息` | `app/providers/global_info.py` | 全球公司新闻 | `news[]`、`title`、`source` |
| `市场新闻` | `app/providers/market_news.py` | Google财经新闻 | `articles[]`、`title`、`url` |
| `美股财务` | `app/providers/us_fundamentals.py` | 美股财务数据 | `financials[]`、`revenue`、`net_income` |
| `Tushare` | `app/providers/tushare.py` | Tushare数据源 | 股票快照、日线、财务 |

---

## 2. 服务层（Services）

| 服务 | 文件 | 功能 | 返回结构 |
|---|---|---|---|
| `TodayOverviewService` | `app/services/today_overview.py` | 今日观察聚合：市场概况、优先事项、主题卡、研究变化 | `contract_version: "today_overview_v1"`、`session`、`summary`、`priority_items`、`coverage`、`themes[]`、`warnings`、`boundary` |
| `MarketAnalysisService` | `app/services/analysis.py` | 市场分析：指数历史、行业快照、市场广度、成交额、板块热度 | 指数K线、技术指标（MA/RSI/MACD/布林带）、市场广度、成交额趋势 |
| `DataHealthService` | `app/services/data_health.py` | 数据健康状态监控 | `status`、`userLabel`、`summary.{total,healthy,attention,critical}`、`categories[]`、`actionableChecks[]` |
| `LiveMarketService` | `app/services/live_market.py` | 实时市场数据 | `markets[*].{key,name,latest_price,pct_change,currency,is_stale}` |
| `MarketNewsService` | `app/services/market_news.py` | 市场新闻聚合 | `articles[]` |
| `GlobalInformationService` | `app/services/global_info.py` | 全球公司信息 | `company_info` |
| `ChinaInformationService` | `app/services/china_info.py` | A股公司信息 | `company_profile` |
| `BusinessStructureAnalysisService` | `app/services/business_structure.py` | 业务结构分析 | `segments[]` |
| `ShareholderStructureAnalysisService` | `app/services/shareholders.py` | 股东结构分析 | `holders[]` |
| `AnalystExpectationsService` | `app/services/analyst_expectations.py` | 分析师预期 | `forecasts[]` |
| `A股财务服务` | `app/services/fundamentals.py` | 财务数据分析 | `metrics[]` |
| `基金产品服务` | `app/services/fund_products.py` | 基金搜索/详情 | `funds[]` |
| `事件时间线` | `app/services/event_timeline.py` | 个股事件时间线 | `events[]` |
| `财务驱动因素` | `app/services/financial_drivers.py` | 财务驱动分析 | `drivers[]` |
| `盈利质量` | `app/services/earnings_quality.py` | 盈利质量评估 | `quality_score`、`components[]` |
| `Filings服务` | `app/services/filings.py` | 公告分析 | `filings[]` |
| `KnowledgeService` | `app/services/knowledge.py` | 知识库检索 | `results[]` |
| `StockPageService` | `app/services/stock_page.py` | 个股页面聚合 | `overview`、`technical`、`financials`、`events`、`research` |
| `StockWorkspaceService` | `app/services/stock_workspace.py` | 个股研究空间 | `workspace`、`timeline` |
| `StockComparisonService` | `app/services/stock_comparison.py` | 股票对比 | `comparison[]` |
| `PeerComparisonService` | `app/services/peer_comparison.py` | 同业对比 | `peers[]` |
| `ResearchPriorityService` | `app/services/research_priority.py` | 研究优先级 | `priorities[]` |
| `ResearchActionService` | `app/services/research_actions.py` | 研究行动 | `actions[]` |
| `ResearchOutcomeService` | `app/services/research_outcomes.py` | 研究结果 | `outcomes[]`、`anchors[]` |
| `ResearchReportService` | `app/services/research_reports.py` | 研究报告 | `reports[]` |
| `ResearchPlanService` | `app/services/research_plan.py` | 研究计划 | `plans[]` |
| `RiskProfileService` | `app/services/risk_profile.py` | 风险档案 | `risk_profile` |
| `PositionLedgerService` | `app/services/position_ledger.py` | 持仓账本 | `positions[]` |
| `TradeWorkflowService` | `app/services/trade_workflow.py` | 交易工作流（状态机：draft→confirmed→archived） | `workflow`、`reviews[]` |
| `ChangeEventService` | `app/services/change_events.py` | 变化事件 | `events[]` |
| `ObservationTaskService` | `app/services/observation_tasks.py` | 观察任务 | `tasks[]` |
| `EvidenceTaskService` | `app/services/evidence_tasks.py` | 证据任务 | `tasks[]` |
| `StockDomainService` | `app/services/stock_domain.py` | 股票领域模型 | `domain` |
| `StructuredAIService` | `app/services/structured_ai.py` | 结构化AI（研究草稿/候选） | `candidates[]` |
| `DeepStockResearchService` | `app/services/deep_stock.py` | 深度个股研究 | `session` |
| `StockScreenerService` | `app/services/stock_screener.py` | 选股筛选器 | `profiles[]`、`results[]` |
| `AgentService` | `app/services/agent.py` | 顾问Agent对话 | `response` |
| `AgentStreamBroker` | `app/services/agent_stream.py` | 顾问SSE进度推送 | SSE事件流 |
| `ChatOrchestrationService` | `app/services/chat_orchestration.py` | 对话编排 | `conversation` |
| `ChatExecutionService` | `app/services/chat_execution.py` | 对话执行 | `response` |
| `ChatRefinementService` | `app/services/chat_refinement.py` | 对话精炼 | `refined` |
| `ChatMarketEvidenceService` | `app/services/chat_market_evidence.py` | 市场证据检索 | `evidence[]` |
| `ChatScreeningEvidenceService` | `app/services/chat_screening_evidence.py` | 选股证据检索 | `evidence[]` |
| `ChatCompanyEvidenceService` | `app/services/chat_company_evidence.py` | 公司证据检索 | `evidence[]` |
| `ChatStockResearchEvidenceService` | `app/services/chat_stock_research_evidence.py` | 个股研究证据检索 | `evidence[]` |
| `ChatPersistence` | `app/services/chat_persistence.py` | 对话持久化 | `conversation` |
| `ChatRequestContextService` | `app/services/chat_context.py` | 请求上下文构建 | `context` |
| `ChatStockContextService` | `app/services/chat_stock_context.py` | 股票上下文 | `context` |
| `ChatRoutingService` | `app/services/chat_routing.py` | 意图路由 | `intent` |
| `ConversationQualityService` | `app/services/conversation_quality.py` | 对话质量评估 | `quality` |
| `CalibrationService` | `app/services/calibration.py` | 预期校准 | `calibration` |
| `MarketPulseArticleService` | `app/services/article.py` | 市场脉搏文章生成 | `article` |
| `BackgroundScheduler` | `app/services/background.py` | 后台任务调度 | `jobs[]` |
| `TushareSnapshotService` | `app/services/tushare_snapshots.py` | Tushare快照 | `snapshot` |
| `LiZongStrategyService` | `app/services/li_zong_strategy_service.py` | 李总策略 | `strategy` |
| `LiZongHistoryService` | `app/services/li_zong_history.py` | 策略历史 | `history[]` |
| `LiZongPortfolioBacktestService` | `app/services/li_zong_portfolio_backtest.py` | 组合回测 | `backtest` |
| `GlobalSearchService` | `app/services/global_search.py` | 全局搜索 | `results[]` |
| `StockAssetListService` | `app/services/stock_assets.py` | 股票资产列表 | `assets[]` |
| `SecurityMasterService` | `app/services/security_master.py` | 证券主数据 | `securities[]` |

---

## 3. 认证与会话

| 功能 | 实现 | 说明 |
|---|---|---|
| HttpOnly Cookie | `qingshu_session` | SameSite=Strict |
| 注册 | `POST /users` | 用户名+密码注册 |
| 登录 | `POST /sessions` | 密码登录，返回session |
| 匿名会话 | `POST /sessions/claim` | 匿名会话（游客模式） |
| 会话状态 | `GET /session/status` | 匿名+正式双模式 |
| 登出 | `DELETE /session` | 清除session |
| 速率限制 | `AuthRateLimiter` | 每IP 120次/分钟，每用户10次/分钟 |

---

## 4. 缓存策略

| 数据 | 缓存方式 | TTL |
|---|---|---|
| 市场广度 | Provider级缓存 + DB持久化 | 5分钟 |
| 指数数据 | Provider级缓存 | 5分钟 |
| 板块热度 | Provider级缓存 | 5分钟 |
| 个人数据 | 无缓存（staleTime: 30s） | 30秒 |
| 指数历史 | Provider级缓存 | 30分钟 |
| 市场快照 | `upsert_market_breadth_snapshot` | 21天滚动 |

---

## 5. 后台任务

| 任务 | 调度 | 功能 |
|---|---|---|
| 市场数据刷新 | 可配置秒数 | 自动刷新广度/板块/指数 |
| 基金产品刷新 | 1800秒 | 基金净值更新 |
| 数据质量检查 | 60秒 | 监控数据源健康状态 |

---

## 6. 数据库模型（核心）

| 表/集合 | 用途 |
|---|---|
| `users` | 用户账户 |
| `sessions` | 会话（匿名+正式） |
| `watchlist_assets` | 关注列表 |
| `stock_relations` | 股票关系（关联/优先级/跟踪状态） |
| `research_actions` | 研究行动 |
| `research_changes` | 研究变化 |
| `research_outcomes` | 研究结果 |
| `trade_reviews` | 交易复盘（状态机） |
| `theses` | 研究判断 |
| `observation_tasks` | 观察任务 |
| `positions` | 持仓 |
| `deep_stock_sessions` | 深度研究会话 |
| `conversations` | 顾问对话 |
| `ai_writeback_candidates` | AI写入候选 |
| `market_breadth_snapshots` | 市场广度快照（21天） |
| `fund_products` | 基金产品 |
