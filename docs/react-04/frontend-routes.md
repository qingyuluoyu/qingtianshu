# 前端路由与导航

> 分支：react-04-read | 基于 commit `f4d375a`

---

## 1. 路由定义（App.tsx）

```
/                    → 重定向到 /today
/today               → TodayPage
/stocks/:symbol      → StockResearchPage
/watchlist           → WatchlistPage
/screening           → ScreeningPage
/research-center     → ResearchCenterPage
/advisor             → AdvisorPage（新建对话）
/advisor/:id         → AdvisorPage（指定对话）
/market-data         → MarketDataPage
/*                   → NotFoundPage
```

### 路由组件树

```
App
├── QueryClientProvider
│   └── BrowserRouter
│       └── ErrorBoundary（新增）
│           └── ProductApp
│               ├── Routes
│               │   └── Route (AppShell wrapper)
│               │       ├── Route "/" → Navigate to /today
│               │       ├── Route "/today" → TodayPage
│               │       ├── Route "/stocks/:symbol" → StockResearchPage
│               │       ├── Route "/watchlist" → WatchlistPage
│               │       ├── Route "/screening" → ScreeningPage
│               │       ├── Route "/research-center" → ResearchCenterPage
│               │       ├── Route "/advisor/:conversationId?" → AdvisorPage
│               │       ├── Route "/market-data" → MarketDataPage
│               │       └── Route "*" → NotFoundPage
│               └── AuthModal（条件渲染）
```

---

## 2. 认证门控逻辑

### 受保护路径判定

```typescript
function isProtectedPath(pathname: string): boolean {
  return ["/today", "/screening", "/watchlist", "/market-data", "/research-center"]
    .includes(pathname)
    || /^\/stocks\/[^/]+$/.test(pathname)
    || /^\/advisor(?:\/[^/]+)?$/.test(pathname);
}
```

### 认证流程

1. `useQuery(["session"], getSession)` — 获取会话状态
2. `isFormalAccount(session)` — 判断是否正式账户（`is_registered && auth_type === "account"`）
3. 未认证 + 受保护路径 → 弹出 `AuthModal`
4. 认证成功 → 关闭弹窗 + 刷新页面

### 会话状态查询错误处理（react-04新增）

```typescript
if (session.isError) {
  // 会话查询出错时（端点404/网络异常），清除错误状态并触发登录
  queryClient.setQueryData(["session"], null);
}
```

---

## 3. 导航组件

### AppShell

| 功能 | 实现 |
|---|---|
| Header | Logo + 导航链接 + 登录/登出按钮 |
| 导航链接 | /today、/screening、/watchlist、/market-data、/research-center |
| 动态标题 | 根据当前路由显示页面标题 |
| 认证触发 | 点击登录按钮 → `onOpenAuth` |
| 登出 | `signOut()` → 清除queryClient → 显示登录弹窗 |

### 导航项

| 链接 | 图标 | 路径 | 说明 |
|---|---|---|---|
| 今日观察 | - | /today | 首屏默认页 |
| 透明选股 | - | /screening | 需认证 |
| 我的关注 | - | /watchlist | 需认证 |
| 行情数据 | - | /market-data | 新增，部分内容需认证 |
| 研究中心 | - | /research-center | 需认证 |
| 问顾问 | - | /advisor | 需认证 |

---

## 4. 页面级状态管理

### React Query 配置

```typescript
const [client] = useState(() => new QueryClient({
  defaultOptions: {
    queries: { staleTime: 30_000 }
  }
}));
```

### 错误重试策略（react-04变更）

```typescript
const stableErrorPolicy = {
  retry: (_failureCount, _error) => _failureCount < 1,  // 仅重试一次
  retryOnMount: false,
  refetchOnWindowFocus: false,
};
```

- 404/400/422：终端错误，不重试
- 500/网络错误：重试1次，指数退避

---

## 5. SSE事件系统

### usePublicEvents Hook

| 参数 | 类型 | 说明 |
|---|---|---|
| `formal` | boolean | 是否正式账户 |

| 状态 | 值 | 说明 |
|---|---|---|
| idle | `"idle"` | 未连接 |
| connected | `"connected"` | 已连接 |
| reconnecting | `"reconnecting"` | 重连中 |

### 连接逻辑
- 正式账户：建立 `EventSource /events` 连接
- 匿名用户：不建立SSE连接

---

## 6. 认证流程详细

### 登录弹窗（AuthModal）

1. 用户名 + 密码输入
2. `POST /sessions` 发送登录请求
3. 成功：`queryClient.invalidateQueries(["session"])` 刷新会话（react-04变更）
4. 失败：显示错误信息

### 登出流程

1. `DELETE /session`
2. `queryClient.clear()`
3. `queryClient.setQueryData(["session"], null)`
4. 弹出登录弹窗

### 匿名会话

1. 访问受保护路径时自动创建
2. `POST /sessions/claim` 获取匿名session
3. 匿名session可查看公开数据，无法访问个人数据

---

## 7. 前端特性标志

| 特性 | 标志 | 说明 |
|---|---|---|
| ErrorBoundary | `components/ErrorBoundary.tsx` | 包裹ProductApp，捕获渲染错误 |
| MarketDataPage | `features/market-data/` | 新增行情数据页 |
| Public queries | indices/breadth/sectors等去auth gate | 匿名用户可见市场数据 |
| Conditional rendering | PersonalResearchSection/DataHealthBar | 仅对认证用户渲染 |
| 409冲突处理 | Watchlist/ResearchCenter/Advisor | 写操作冲突时刷新不覆盖 |
| SSE进度 | `openChatStream` | 顾问对话进度实时推送 |
| Vite proxy | `/session/*` | 修正路径匹配 |

---

## 8. 构建与部署

### Vite配置

```typescript
server: {
  proxy: {
    "/auth": apiProxy,
    "/session/*": apiProxy,  // react-04修正：*匹配子路径
    "/sessions": apiProxy,
    "/users": apiProxy,
    "/v1": apiProxy,
  }
}
```

### 多阶段构建

- 前端：`node:22-bookworm-slim` → Vite构建 → `/frontend/dist`
- 后端：`python:3.11-slim-bookworm` → Uvicorn
- `COPY --from=frontend-build` 烘焙dist进镜像

### 静态资源

| 路径 | 缓存策略 | 说明 |
|---|---|---|
| `/today` `/screening` 等HTML | no-cache | SPA入口 |
| `/assets/{path}` | 1年immutable | content-hash文件名 |
| `/static/{asset_name}` | 取决于类型 | 媒体资源 |
