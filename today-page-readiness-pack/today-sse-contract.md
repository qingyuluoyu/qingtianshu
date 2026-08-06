# 今日观察 SSE 事件合同

> 基于源码分析（app/services/background.py, app/services/background.py EventBroker）
> 不依赖运行时事件采集（后台任务未启用）

---

## 1. 连接信息

| 属性 | 值 |
|---|---|
| URL | `GET /events` |
| Content-Type | `text/event-stream; charset=utf-8` |
| 是否需要 Cookie | **否**（公开端点，无 `require_session_user`） |
| 认证要求 | 无 |
| CORS | 无 CORS 配置（同域通过 Vite 代理） |

---

## 2. 连接行为

| 行为 | 实现 |
|---|---|
| 初始消息 | `data: {"type": "connected", "time": "<ISO8601>"}` |
| 心跳格式 | `: heartbeat`（注释行，无 data） |
| 心跳间隔 | 15 秒（`subscriber.get(timeout=15)`） |
| 事件格式 | `data: <JSON>`（标准 SSE 格式） |
| 浏览器重连 | **自动**（EventSource 默认行为，指数退避） |
| 多连接 | 技术上可以，但前端只有一个 `EventSource` 实例 |
| 持久化 | 事件写入 operational_db（`publish_event`），新连接从 `latest_event_sequence` 补漏 |

---

## 3. 完整事件类型全集（20 种）

| # | 事件类型 | 数据 | 发布位置 |
|---|---|---|---|
| 1 | `connected` | `{type, time}` | EventBroker.stream() 连接时 |
| 2 | `market_updated` | `{type, time, coverage}` | _refresh_markets |
| 3 | `fund_products_updated` | `{type, time, completed, failed}` | _refresh_fund_products |
| 4 | `stock_strategy_updated` | `{type, strategy_id, time, counts, coverage}` | _refresh_li_zong_strategy |
| 5 | `stock_strategy_backtest_updated` | `{type, time, completed, requested}` | _refresh_li_zong_backtest |
| 6 | `article_published` | `{type, time, article: {id, title, summary}}` | _refresh_market_pulse（条件触发） |
| 7 | `a_share_information_updated` | `{type, time, completed, requested}` | _refresh_a_share_information |
| 8 | `a_share_fundamentals_updated` | `{type, time, completed, requested}` | _refresh_a_share_fundamentals |
| 9 | `business_structure_updated` | `{type, time, completed, requested}` | _refresh_business_structure |
| 10 | `shareholder_structure_updated` | `{type, time, completed, requested}` | _refresh_shareholder_structure |
| 11 | `analyst_expectations_updated` | `{type, time, completed, requested}` | _refresh_analyst_expectations |
| 12 | `a_share_filings_updated` | `{type, time, completed, requested}` | _refresh_a_share_filings |
| 13 | `us_equity_fundamentals_updated` | `{type, time, completed, requested}` | _refresh_us_equity_fundamentals |
| 14 | `peer_valuations_updated` | `{type, time, completed, requested}` | _refresh_peer_valuations |
| 15 | `earnings_quality_updated` | `{type, time, completed, requested}` | _refresh_earnings_quality |
| 16 | `financial_drivers_updated` | `{type, time, completed, requested}` | _refresh_financial_drivers |
| 17 | `research_reports_updated` | `{type, time, completed, requested}` | _refresh_research_reports |
| 18 | `research_outcomes_updated` | `{type, time, completed, requested}` | _refresh_research_outcomes |
| 19 | `outlook_calibrations_updated` | `{type, time, completed, requested}` | _refresh_outlook_calibrations |
| 20 | `market_news_updated` | `{type, time, completed, requested}` | _refresh_market_news |
| 21 | `evidence_tasks_updated` | `{type, time, processed, pending, completed, failed, skipped}` | _process_evidence_tasks |
| 22 | `data_health_updated` | `{type, time, data_health: {status, user_label, checked_at, summary}}` | _refresh_data_health |

---

## 4. 前端事件→查询刷新映射

| 事件类型 | 刷新查询 |
|---|---|
| `market_updated` | overview, indices, breadth, sectors |
| `data_health_updated` | dataHealth |
| `evidence_tasks_updated` | overview, researchActions, researchChanges |
| `research-change:*`（前缀匹配） | overview, researchActions, researchChanges |
| `research_reports_updated` | **无**（前端显式忽略） |
| 其他事件 | 忽略（DEV 模式打印 debug） |

**注意**：前端 `queryKeysForEvent` 使用前缀匹配 `type.startsWith("research-change")`，但后端不发布 `research-change:*` 格式的事件。后端发布的是固定的 22 种类型。

---

## 5. 特定事件确认

| 问题 | 答案 |
|---|---|
| 是否有 `market_updated` | **是**（`_refresh_markets` 发布） |
| 是否有 `data_health_updated` | **是**（`_refresh_data_health` 发布） |
| 是否有 `research_reports_updated` | **是**（`_refresh_research_reports` 发布） |
| 是否有 `evidence_tasks_updated` | **是**（`_process_evidence_tasks` 发布，条件触发） |
| 是否有研究变化相关事件 | **否**（无 `research_change_updated` 或类似事件） |

---

## 6. 今日观察刷新映射建议

| 后端事件 | 应刷新接口 | 当前前端映射 |
|---|---|---|
| market_updated | /v1/today/overview, /indices, /markets/breadth, /sectors/hot | 正确 |
| data_health_updated | /system/data-health | 正确 |
| evidence_tasks_updated | /v1/today/overview, /me/research-actions, /me/research-changes | 正确 |
| research_reports_updated | 无直接刷新目标 | 前端忽略 |
| a_share_information_updated | /me/research-changes | **前端未映射** |
| a_share_fundamentals_updated | /me/research-actions, /me/research-changes | **前端未映射** |
| financial_drivers_updated | /me/research-actions, /me/research-changes | **前端未映射** |
| analyst_expectations_updated | /me/research-actions | **前端未映射** |
| 其他 *_updated | 按需 | **前端未映射** |
