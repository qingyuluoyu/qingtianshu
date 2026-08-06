# 今日观察页面开发就绪总结

> 采集日期：2026-08-04 ｜ 基于真实接口调用 + 代码检索 ｜ 不修改任何文件

---

## 1. 当前数据是否足够开发今日观察

**YES** — 所有 9 个接口均已真实调用并返回有效数据结构。新用户空数据状态、401/422 边界、SSE 事件合同均已确认。

---

## 2. 每个页面模块应使用哪个接口

| 页面模块 | 主接口 | 辅助接口 |
|---|---|---|
| 页面头部（交易状态/日期/时间） | GET /v1/today/overview | — |
| 五个指数 | GET /v1/today/overview（market.indices） | GET /indices（独立缓存） |
| 市场结构（涨跌/成交额/分布） | GET /v1/today/overview（market.breadth） | GET /markets/breadth（独立缓存） |
| 热门行业 | GET /v1/today/overview（market.industries） | GET /sectors/hot（独立缓存） |
| 今日优先事项 | GET /v1/today/overview（priority_items） | GET /me/research-actions |
| 我的关注变化 | GET /v1/today/overview（personalized.changes） | GET /me/research-changes |
| 数据状态 | GET /system/data-health | — |

**注意**：今日观察聚合接口 `/v1/today/overview` 已内部调用所有子接口（indices, breadth, industries, tasks, actions, changes, writebacks），前端可直接使用聚合结果。独立接口用于 SSE 刷新。

---

## 3. 哪些字段可稳定使用

### 始终存在（不依赖数据可用性）
- session.key, session.label, session.exchange_status
- summary.market_date, summary.headline
- priority_items.total_visible, priority_items.empty_message
- coverage.status, coverage.components
- warnings（空数组或字符串数组）

### 数据可用时存在
- indices[].symbol, .name, .status, .latest_close, .return_1d_pct, .source
- breadth.total, .advancers, .decliners, .unchanged, .state, .advance_ratio
- turnover.total_amount_100m_cny
- distribution.median_pct_change
- sectors[].code, .name, .pct_change, .advancers, .decliners

### 可空（需运行时保护）
- indices[].metrics 下所有技术指标（RSI, MACD, 布林带等）
- breadth.turnover（status=unavailable 时整个 turnover 对象结构不同）
- breadth.distribution（同上）
- sectors[].advancers/decliners（新浪降级时为 null）
- data_health.checks 中各检查的 extra 字段

---

## 4. 哪些字段必须做运行时保护

| 字段 | 风险 | 建议 |
|---|---|---|
| `metrics.return_1d_pct` | 交易日边界可能为 null | `?? "暂无"` |
| `breadth.turnover` | 盘中不可比时整个对象结构不同 | 先检查 `breadth.turnover.status` |
| `breadth.distribution` | 同上 | 先检查 `distribution.status` |
| `sectors[].advancers` | 新浪降级时为 null | `item.advancers ?? "—"` |
| `data_health.checks[]` | 不同 category 有不同 extra 字段 | 用 `in` 检查后再访问 |
| `priority_items.items` | 空数组 | 直接检查 `.length > 0` |
| `session.session_expires_at` | 匿名用户可能为 null | 可选链访问 |

---

## 5. 哪些设计内容当前后端不支持

| 设计需求 | 状态 | 说明 |
|---|---|---|
| 沪深300 指数 | **不支持** | INDEX_ORDER 只包含 5 个指数（无沪深300），scope=all&group=china 返回 6 个但前端只取 5 个 |
| 风格指数结论 | **不支持** | styles.status="not_available"，固定返回 message |
| 涨停数/跌停数 | **不支持** | breadth 无此字段 |
| 行业 advance_ratio | **不支持** | sectors 数组元素无此字段 |
| research-change:* SSE 事件 | **不支持** | 后端不发布 research-change 前缀事件 |
| 用户名显示 | **支持** | session.name 和 public_user.name |
| 红绿色涨跌 | **支持** | return_1d_pct 正负值可判断 |

---

## 6. SSE 实际可用事件

| 事件 | 是否应刷新今日观察 | 前端已映射 |
|---|---|---|
| `market_updated` | 刷新 indices, breadth, sectors, overview | 是 |
| `data_health_updated` | 刷新 dataHealth | 是 |
| `evidence_tasks_updated` | 刷新 overview, actions, changes | 是 |
| `research_reports_updated` | 无直接刷新目标 | 忽略 |
| `a_share_information_updated` | 应刷新 changes | **否** |
| `a_share_fundamentals_updated` | 应刷新 actions, changes | **否** |
| `financial_drivers_updated` | 应刷新 actions, changes | **否** |
| `analyst_expectations_updated` | 应刷新 actions | **否** |
| 其他 *_updated | 按需 | **否** |

**后端共发布 22 种事件类型，前端当前只映射 4 种。**

---

## 7. 是否存在联调阻塞

**NO** — 所有接口已真实调用，数据结构已确认，Vite 代理配置完整覆盖所有路径。

**已知但不阻塞的注意事项**：
1. `/events` SSE 端点公开，无 Cookie 要求（与产品要求一致，因为前端通过 React Query 认证状态控制数据请求）
2. `/system/data-health` 公开（当前测试环境 degraded 状态，生产环境应 healthy）
3. `/indices`, `/markets/breadth`, `/sectors/hot` 公开（市场数据通常公开）
4. 前端 TodayPage 已有 3 个字段映射 bug（coverageStatus, exchangeStatus, marketDate 未在 adapter 中转换），需修复后挂载路由

---

## 8. Codex 下一轮最多需要修改哪 3 个部分

| 优先级 | 修改位置 | 内容 |
|---|---|---|
| P0 | [frontend/src/app/App.tsx:37](frontend/src/app/App.tsx#L37) | 将 `/today` 路由从 `PlaceholderPage` 改为 `TodayPage`，传入 `authenticated={formal}` 和 `onUnauthorized` |
| P0 | [frontend/src/features/today/adapters.ts](frontend/src/features/today/adapters.ts) | 修复 3 个字段映射：`coverageStatus`→`coverage.status`，`session.exchangeStatus`→`session.exchange_status`，`marketDate`→`summary.market_date` |
| P1 | [frontend/src/features/today/events.ts](frontend/src/features/today/events.ts) | 扩展 `queryKeysForEvent` 映射：`a_share_information_updated`→researchKeys，`a_share_fundamentals_updated`→researchKeys，`financial_drivers_updated`→researchKeys，`analyst_expectations_updated`→overview+researchActions |

---

## 产物清单

```
today-page-readiness-pack/
├─ summary.md                          ← 本文件
├─ today-field-contract.md             ← 所有接口字段合同
├─ today-sse-contract.md               ← SSE 事件合同
├─ frontend-today-integration-map.md   ← React 底座集成地图
├─ runtime-results.md                  ← 接口响应汇总
├─ raw/
│  ├─ session.json                     ← GET /session 原始响应
│  ├─ today-overview.json              ← GET /v1/today/overview 原始响应
│  ├─ indices.json                     ← GET /indices 原始响应
│  ├─ market-breadth.json              ← GET /markets/breadth 原始响应
│  ├─ sectors-hot.json                 ← GET /sectors/hot 原始响应
│  ├─ data-health.json                 ← GET /system/data-health 原始响应
│  ├─ watchlist-brief.json             ← GET /me/watchlist/brief 原始响应
│  ├─ research-actions.json            ← GET /me/research-actions 原始响应
│  └─ research-changes.json            ← GET /me/research-changes 原始响应
└─ edge-cases/
   └─ boundary-states.md               ← 边界状态测试证据
```
