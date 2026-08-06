# React 底座与今日观察集成地图

> 基于前端代码只读检查 ｜ 不修改任何文件

---

## 1. 文件清单

| 文件 | 路径 | 说明 |
|---|---|---|
| App 入口 | [frontend/src/app/App.tsx](frontend/src/app/App.tsx) | QueryClient, BrowserRouter, 路由 |
| AppShell | [frontend/src/components/AppShell.tsx](frontend/src/components/AppShell.tsx) | 侧栏导航 + 头部 |
| 路由配置 | [frontend/src/app/App.tsx:11-18](frontend/src/app/App.tsx#L11-L18) | pages 数组定义 6 条路由 |
| 今日页面 | [frontend/src/features/today/TodayPage.tsx](frontend/src/features/today/TodayPage.tsx) | **已完整实现** |
| 登录弹窗 | [frontend/src/features/auth/AuthModal.tsx](frontend/src/features/auth/AuthModal.tsx) | 注册/登录弹窗 |
| 占位页 | [frontend/src/pages/PlaceholderPage.tsx](frontend/src/pages/PlaceholderPage.tsx) | 未登录时显示 |
| 404 页 | [frontend/src/pages/NotFoundPage.tsx](frontend/src/pages/NotFoundPage.tsx) | 路由兜底 |

---

## 2. 路由与页面映射

| 路径 | 组件 | 状态 |
|---|---|---|
| `/` | `<Navigate to="/today" />` | 已配置 |
| `/today` | `PlaceholderPage(title="今日观察")` | **占位，需替换为 TodayPage** |
| `/screening` | `PlaceholderPage` | 占位 |
| `/watchlist` | `PlaceholderPage` | 占位 |
| `/stocks/:symbol` | `PlaceholderPage` | 占位 |
| `/advisor/:conversationId?` | `PlaceholderPage` | 占位 |
| `/research-center` | `PlaceholderPage` | 占位 |
| `*` | `NotFoundPage` | 已配置 |

**注意**：`/today` 当前渲染的是 `PlaceholderPage`，而非 `TodayPage`。`TodayPage` 已完整实现但**未被路由引用**。

---

## 3. API Client 配置

| 配置项 | 值 | 位置 |
|---|---|---|
| 基础 URL | `""`（相对路径） | [client.ts:4](frontend/src/api/client.ts#L4) |
| credentials | `"same-origin"` | [client.ts:6](frontend/src/api/client.ts#L6) |
| 类型生成 | `openapi.generated.ts` | [client.ts:1-2](frontend/src/api/client.ts#L1-L2) |

---

## 4. Vite 代理配置

```js
// vite.config.ts:16-31
proxy: {
  "/auth": apiProxy,
  "/session": apiProxy,
  "/sessions": apiProxy,
  "/users": apiProxy,
  "/v1": apiProxy,
  "/me": apiProxy,
  "/markets": apiProxy,
  "/indices": apiProxy,
  "/sectors": apiProxy,
  "/a-share": apiProxy,
  "/system": apiProxy,
  "/research-reports": apiProxy,
  "/events": apiProxy,
  "^/stocks/[^/]+/(history|intraday)(?:/|$)": apiProxy,
}
```

**目标**：`http://127.0.0.1:8000`

**已代理的今日观察相关路径**：
- `/v1/today/overview` ✓
- `/indices` ✓
- `/markets/breadth` ✓
- `/sectors/hot` ✓
- `/system/data-health` ✓
- `/me/watchlist/brief` ✓
- `/me/research-actions` ✓
- `/me/research-changes` ✓
- `/events` ✓

---

## 5. Session 管理

| 功能 | 实现 | 位置 |
|---|---|---|
| 获取 session | `getSession()` → `GET /session` | [session.ts:11-16](frontend/src/api/session.ts#L11-L16) |
| 登出 | `signOut()` → `DELETE /session` | [session.ts:18-21](frontend/src/api/session.ts#L18-L21) |
| 正式账号判断 | `isFormalAccount(session)` → `is_registered && auth_type === "account"` | [session.ts:7-9](frontend/src/api/session.ts#L7-L9) |
| Session Query key | `["session"]` | [App.tsx:22](frontend/src/app/App.tsx#L22) |
| 401 处理 | `getSession` 返回 null → 触发 `setAuthOpen(true)` | [App.tsx:25](frontend/src/app/App.tsx#L25) |

---

## 6. AuthGate 实现

**不是独立组件，内联在 App.tsx 中**：
- `session` query 加载中 → 等待
- `!formal` → 打开 `AuthModal`
- 401 从私有 API → `onUnauthorized` → 打开 `AuthModal`

```tsx
// App.tsx:25
useEffect(() => { if (!session.isLoading && !formal) setAuthOpen(true); }, [formal, session.isLoading]);
```

---

## 7. QueryClient 配置

```tsx
// App.tsx:45
const client = new QueryClient({ defaultOptions: { queries: { staleTime: 30_000 } } });
```

今日观察页面内额外配置（queries.ts）：
- 市场数据 staleTime: 60,000ms
- 个人数据 staleTime: 30,000ms
- 401/422 不重试，其他错误最多重试 2 次

---

## 8. SSE 客户端

| 功能 | 实现 | 位置 |
|---|---|---|
| SSE Hook | `usePublicEvents(enabled)` | [events.ts:24-55](frontend/src/features/today/events.ts#L24-L55) |
| EventSource | `new EventSource("/events")` | [events.ts:33](frontend/src/features/today/events.ts#L33) |
| 连接状态 | `"idle" \| "connected" \| "reconnecting"` | [events.ts:22](frontend/src/features/today/events.ts#L22) |
| 事件映射 | `queryKeysForEvent(type)` | [events.ts:11-19](frontend/src/features/today/events.ts#L11-L19) |
| 测试 | [events.test.ts](frontend/src/features/today/events.test.ts) | 3 个测试用例 |

**注意**：`/events` 通过 Vite 代理到后端，无需 Cookie。

---

## 9. 今日观察查询定义

| Query Key | API 路径 | 参数 | 位置 |
|---|---|---|---|
| `["today","overview"]` | `GET /v1/today/overview` | 无 | [api.ts:43-45](frontend/src/features/today/api.ts#L43-L45) |
| `["today","indices","all","china"]` | `GET /indices` | scope=all, group=china | [api.ts:48-50](frontend/src/features/today/api.ts#L48-L50) |
| `["today","breadth"]` | `GET /markets/breadth` | 无 | [api.ts:53-55](frontend/src/features/today/api.ts#L53-L55) |
| `["today","sectors",10]` | `GET /sectors/hot` | limit=10 | [api.ts:58-60](frontend/src/features/today/api.ts#L58-L60) |
| `["today","watchlist-brief"]` | `GET /me/watchlist/brief` | 无 | [api.ts:63-65](frontend/src/features/today/api.ts#L63-L65) |
| `["today","research-actions"]` | `GET /me/research-actions` | 无 | [api.ts:68-70](frontend/src/features/today/api.ts#L68-L70) |
| `["today","research-changes",20]` | `GET /me/research-changes` | limit=20 | [api.ts:73-75](frontend/src/features/today/api.ts#L73-L75) |
| `["today","data-health"]` | `GET /system/data-health` | 无 | [api.ts:78-80](frontend/src/features/today/api.ts#L78-L80) |

---

## 10. 数据适配器（Adapters）

| 适配器 | 输入 → 输出 | 位置 |
|---|---|---|
| `parseOverview` | 后端 snake_case → 前端 camelCase | [adapters.ts:175-217](frontend/src/features/today/adapters.ts#L175-L217) |
| `parseIndices` | 取 INDEX_ORDER 中 5 个指数 | [adapters.ts:228-253](frontend/src/features/today/adapters.ts#L228-L253) |
| `parseBreadth` | 合并 breadth + turnover + distribution | [adapters.ts:255-278](frontend/src/features/today/adapters.ts#L255-L278) |
| `parseSectors` | 切片 10 项 | [adapters.ts:280-301](frontend/src/features/today/adapters.ts#L280-L301) |
| `parseWatchlistBrief` | 提取 symbol + name | [adapters.ts:303-316](frontend/src/features/today/adapters.ts#L303-L316) |
| `parseResearchActions` | 展平 stock → actions | [adapters.ts:318-347](frontend/src/features/today/adapters.ts#L318-L347) |
| `parseResearchChanges` | 取 events 或 items | [adapters.ts:349-373](frontend/src/features/today/adapters.ts#L349-L373) |
| `parseDataHealth` | 过滤 critical + attention | [adapters.ts:375-399](frontend/src/features/today/adapters.ts#L375-L399) |

---

## 11. 测试基础设施

| 配置 | 值 | 位置 |
|---|---|---|
| 测试目录 | `frontend/src/**/*.test.ts[x]` | vite.config.ts |
| 测试框架 | Vitest + Testing Library | [package.json](frontend/package.json) |
| E2E 框架 | Playwright | [playwright.config.ts](frontend/playwright.config.ts) |
| E2E 启动命令 | `npm run dev -- --host 127.0.0.1 --port 4173` | [playwright.config.ts:10](frontend/playwright.config.ts#L10) |
| E2E baseURL | `http://127.0.0.1:4173` | [playwright.config.ts:6](frontend/playwright.config.ts#L6) |
| 已有测试 | TodayPage.test.tsx, events.test.ts, adapters.test.ts | `frontend/src/features/today/` |

---

## 12. CSS 变量与可复用组件

| 资源 | 路径 | 说明 |
|---|---|---|
| 全局样式 | [frontend/src/styles/global.css](frontend/src/styles/global.css) | CSS 变量定义 |
| AppShell 样式 | [AppShell.module.css](frontend/src/components/AppShell.module.css) | 侧栏布局 |
| 今日页面样式 | [TodayPage.module.css](frontend/src/features/today/TodayPage.module.css) | 页面布局 |
| 认证弹窗样式 | [AuthModal.module.css](frontend/src/features/auth/AuthModal.module.css) | 弹窗 |
| 占位页样式 | [PlaceholderPage.module.css](frontend/src/pages/PlaceholderPage.module.css) | 占位 |

**可复用组件（TodayPage 内）**：
- `ModuleCard` — 模块卡片（含 pending/error/retry 状态）

**不存在的组件**（需新建或从其他页面提取）：
- Loading 骨架屏（用 ModuleCard 内的 skeleton class 替代）
- Empty 空状态（各模块内联处理）
- Error 错误展示（用 ModuleCard 内的 moduleError class 替代）

---

## 13. Codex 应复用的文件

| 优先级 | 文件 | 复用方式 |
|---|---|---|
| P0 | [features/today/TodayPage.tsx](frontend/src/features/today/TodayPage.tsx) | **直接挂载到路由** |
| P0 | [features/today/queries.ts](frontend/src/features/today/queries.ts) | 直接使用 |
| P0 | [features/today/api.ts](frontend/src/features/today/api.ts) | 直接使用 |
| P0 | [features/today/adapters.ts](frontend/src/features/today/adapters.ts) | 直接使用 |
| P0 | [features/today/events.ts](frontend/src/features/today/events.ts) | 直接使用 |
| P1 | [app/App.tsx](frontend/src/app/App.tsx) | 修改路由映射 |
| P1 | [features/today/TodayPage.test.tsx](frontend/src/features/today/TodayPage.test.tsx) | 补充测试 |

---

## 14. 禁止新建的内容

| 禁止 | 原因 |
|---|---|
| 新建 `/today` 组件 | TodayPage.tsx 已存在 |
| 新建 API client | openapi-fetch 已配置 |
| 新建 QueryClient | 已在 App.tsx 配置 |
| 新建 SSE 客户端 | events.ts 已存在 |
| 新建路由结构 | react-router-dom 已配置 |
| 新建 AuthGate | 内联在 App.tsx 中 |
| 新建 CSS 变量 | global.css 已定义 |

---

## 15. 当前代码 Bug（不影响本轮开发）

| Bug | 位置 | 说明 |
|---|---|---|
| `overview.data?.session.exchangeStatus` | TodayPage.tsx:91 | 应使用 `session.exchange_status`（snake_case），adapter 未转换此字段 |
| `overview.data?.coverageStatus` | TodayPage.tsx:112 | 应使用 `coverage.status`，adapter 未转换此字段 |
| `overview.data?.marketDate` | TodayPage.tsx:106 | 应使用 `summary.market_date`，adapter 未转换 |
