# Production Frontend Visual Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `F:/tools/3.4html展示/` 的高保真视觉与交互语言迁移到现有 React 正式产品，同时保留真实数据契约、认证边界、A 股金融口径和可上线验证能力。

**Architecture:** 参考页只作为视觉和交互基线，不复制其静态 DOM、直接 DOM mutation 或演示数据。先建立全局 token 和正式信息架构，再按 Today、个股研究、个人研究工作区逐个垂直切片迁移；所有页面继续通过现有 React Query、adapters 和类型化 API 取数。

**Tech Stack:** React 19、TypeScript 5.7、React Router 7、TanStack Query 5、CSS Modules、Vitest、Testing Library、Playwright、FastAPI 同源代理。

## Global Constraints

- A 股颜色固定为红涨 `#d92d20`、绿跌 `#039855`，不得套用海外市场绿涨红跌。
- 不展示参考页中的演示数字、虚构会员、虚假盈亏、合成 K 线或过期日期。
- `null`、无数据、数据过期、数据源失败、字段缺失和权限锁定必须保持不同状态。
- 不新增 UI 框架和图表依赖；优先复用现有 React/SVG/CSS 能力，控制包体和供应链风险。
- 桌面端目标视口为 1440×900；移动端目标视口为 390×844；页面根不得横向溢出。
- 当前工作区包含用户的未提交修改，本轮不执行 git stage、commit、reset 或 checkout。

---

### Task 1: 设计 Token 与正式应用壳

**Files:**
- Modify: `frontend/src/styles/global.css`
- Modify: `frontend/src/components/AppShell.tsx`
- Modify: `frontend/src/components/AppShell.module.css`
- Modify: `frontend/src/components/AppShell.test.tsx`

**Interfaces:**
- Consumes: `AuthSession`, `GlobalSearch`, React Router `NavLink` 和当前 route map。
- Produces: 正式主导航、辅助工具导航、桌面固定侧栏、移动端抽屉/底栏，以及全站颜色、间距、阴影、字号和焦点 token。

- [ ] **Step 1: 写应用壳失败测试**

```tsx
it("exposes the formal product workflow in priority order", () => {
  page();
  const navigation = screen.getByRole("navigation", { name: "产品导航" });
  expect(within(navigation).getAllByRole("link").slice(0, 5).map((link) => link.textContent)).toEqual([
    "今日观察", "我的关注", "个股研究", "AI 研究", "复盘中心",
  ]);
  expect(within(navigation).getByText("辅助工具")).toBeInTheDocument();
});
```

- [ ] **Step 2: 运行测试并确认因旧导航分组失败**

Run: `npm test -- src/components/AppShell.test.tsx`

Expected: FAIL，旧导航仍以“市场/研究”分组且顺序不符合正式工作流。

- [ ] **Step 3: 实现新应用壳与 token**

将参考页的 218px 侧栏、66px 顶栏、品牌渐变激活态迁移为 React 结构；用内联 SVG 图标组件表达导航含义，保留 `NavLink` 的可访问状态。移动端保留菜单按钮，并增加只包含核心工作流的底部导航。`global.css` 增加 `--color-*`、`--space-*`、`--radius-*`、`--shadow-*`、`--font-*`，统一正文最小可读字号和 `:focus-visible`。

- [ ] **Step 4: 运行应用壳测试**

Run: `npm test -- src/components/AppShell.test.tsx`

Expected: PASS，路由标签、紧凑布局菜单和正式导航顺序均通过。

---

### Task 2: Today 页面任务优先级与首屏信息架构

**Files:**
- Modify: `frontend/src/features/today/TodayPage.tsx`
- Modify: `frontend/src/features/today/TodayComponents.tsx`
- Modify: `frontend/src/features/today/TodayPage.module.css`
- Modify: `frontend/src/features/today/TodayPage.test.tsx`

**Interfaces:**
- Consumes: `useTodayPrivateDashboard(authenticated)`、`useTodayPublicMarket()` 和现有 `Overview.priorityItems` 后端排序。
- Produces: “今日任务 → 指数快照 → 市场结构 → 研究线索”的正式阅读顺序；匿名用户仍可读公开行情。

- [ ] **Step 1: 写 Today 阅读顺序失败测试**

```tsx
it("puts deterministic personal actions before the market dashboard for signed-in users", () => {
  page(client(), true);
  const actions = screen.getByRole("region", { name: "今日优先事项" });
  const indices = screen.getByRole("region", { name: "主要指数" });
  expect(actions.compareDocumentPosition(indices) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `npm test -- src/features/today/TodayPage.test.tsx`

Expected: FAIL，当前优先事项位于第三个“研究跟进”区块。

- [ ] **Step 3: 调整组件编排**

登录用户在页头后立即看到后端确定性排序的 3–5 个研究事项；未登录用户看到公开市场首屏和明确登录入口，不显示伪骨架。指数卡使用参考页紧凑四/五列布局，成交额、广度、分布作为一个三列市场结构组；研究报告、异动和全球市场下沉为线索区。

- [ ] **Step 4: 运行 Today 单元测试**

Run: `npm test -- src/features/today/TodayPage.test.tsx`

Expected: PASS；公开数据来源、真实空态、个人权限、成交额历史阈值和模块隔离断言保持通过。

---

### Task 3: Today 视觉密度、状态表达与响应式

**Files:**
- Modify: `frontend/src/features/today/TodayPage.module.css`
- Modify: `frontend/src/features/today/charts.tsx`
- Modify: `frontend/src/features/today/TodayComponents.tsx`

**Interfaces:**
- Consumes: Task 1 的全局 token 和 Task 2 的 DOM 分区。
- Produces: 1440px 首屏可见任务与核心行情、1280px 容器自适应、390px 单列无溢出；卡片各自拥有 loading/error/empty/locked 状态。

- [ ] **Step 1: 增加状态可访问性断言**

在 `TodayPage.test.tsx` 中断言 locked 状态不包含“正在读取”，模块失败有重试按钮，数据来源文本不小于可读状态类所使用的 token。

- [ ] **Step 2: 运行失败测试**

Run: `npm test -- src/features/today/TodayPage.test.tsx`

Expected: FAIL 于新状态标识或 class 约束。

- [ ] **Step 3: 实现视觉层**

卡片半径使用 12px，正文 13–14px，辅助信息不低于 11px；删除 40px 夸张页标题和重复 route 标题，提升数字对齐；断点基于主内容可用宽度，使 1280px 加侧栏时不误降为两列长页。图表颜色和 aria 标签保持金融口径。

- [ ] **Step 4: 再运行 Today 测试**

Run: `npm test -- src/features/today/TodayPage.test.tsx`

Expected: PASS。

---

### Task 4: 个股研究与个人研究工作区迁移

**Files:**
- Modify: `frontend/src/features/stock-research/charts.tsx`
- Modify: `frontend/src/features/stock-research/StockResearchPage.tsx`
- Modify: `frontend/src/features/stock-research/StockResearchPage.module.css`
- Modify: `frontend/src/features/stock-research/StockResearchPage.test.tsx`
- Modify: `frontend/src/features/watchlist/WatchlistPage.module.css`
- Modify: `frontend/src/features/research-center/ResearchCenterPage.module.css`
- Modify: `frontend/src/features/advisor/AdvisorPage.module.css`

**Interfaces:**
- Consumes: 真实 OHLC、财务、工作区、复盘和顾问 API；Task 1 的 token。
- Produces: 参考页的报价头、K 线主副图、指标卡、关注表格、复盘双栏和 AI 研究工作台视觉，但不引入参考页的合成数据。

- [ ] **Step 1: 写 K 线交互失败测试**

新增对 `CandlestickChart` 的时间范围、MA5/MA10/MA20、键盘可聚焦和空数据降级测试；缩放/平移状态只改变可见真实点集，不生成插值点。

- [ ] **Step 2: 运行个股研究测试并确认失败**

Run: `npm test -- src/features/stock-research/StockResearchPage.test.tsx`

Expected: FAIL，当前纯 SVG K 线没有移动平均线、十字光标、缩放和平移接口。

- [ ] **Step 3: 实现交互图表和页面视觉**

用 React state 管理可见窗口和 hover candle；鼠标拖动平移、滚轮缩放、双击重置、方向键移动十字光标。所有指标从真实 points 确定性计算，少于 20 个交易日时不显示 MA20。其他工作区只迁移 CSS 层级和布局，不改变写回状态机与 API。

- [ ] **Step 4: 运行受影响页面测试**

Run: `npm test -- src/features/stock-research/StockResearchPage.test.tsx src/features/watchlist/WatchlistPage.test.tsx src/features/research-center/ResearchCenterPage.test.tsx src/features/advisor/AdvisorPage.test.tsx`

Expected: PASS，数据口径、写回状态机、权限和 URL 状态断言不回退。

---

### Task 5: 上线前视觉与链路发布门禁

**Files:**
- Replace: `frontend/src/tests/screenshots.spec.ts`
- Modify: `frontend/playwright.config.ts`
- Create: `frontend/e2e/production-visual.spec.ts`
- Update: `frontend/src/features/*/DESIGN.md`

**Interfaces:**
- Consumes: 8020 后端、5174 前端、host-only 会话 cookie 和 Tasks 1–4 的页面。
- Produces: 可重复的桌面/移动端视觉回归、控制台错误检查、根节点溢出检查和关键交互冒烟。

- [ ] **Step 1: 将旧截图脚本改成环境参数**

使用 `BACKEND_URL ?? http://127.0.0.1:8020`、`FRONTEND_URL ?? http://127.0.0.1:5174`，禁止硬编码 `localhost:8000/5173`、本机 Temp 路径和 `domain=localhost` cookie；让浏览器通过真实注册响应接收 host-only cookie。

- [ ] **Step 2: 添加桌面与移动端验收**

对 `/today`、`/watchlist`、`/stocks/000063.SZ`、`/advisor`、`/research-center` 在 1440×900 与 390×844 检查：页面主标题可见、根节点无横向溢出、无 uncaught console error、loading 最终收敛为 data/empty/error/locked 之一。

- [ ] **Step 3: 运行完整前端验证**

Run: `npm test`

Expected: 全部 Vitest 测试通过。

Run: `npm run build`

Expected: TypeScript 与 Vite build 退出码 0。

Run: `npm run test:e2e -- e2e/production-visual.spec.ts`

Expected: 桌面/移动关键路径通过，无页面根横向溢出和控制台错误。

- [ ] **Step 4: 人工浏览器验收**

在 `http://127.0.0.1:5174/today` 验收 1440×900、1280×720、390×844；检查首屏信息优先级、卡片对齐、文本可读性、加载收敛、导航、搜索、登录和图表交互，并保存验收截图。

---

## Self-Review

- 参考源码的六页信息架构、桌面密度、移动底栏、K 线交互和视觉回归均有对应任务。
- 正式产品约束覆盖真实数据、权限、空态、金融颜色、无横向溢出和无新增依赖。
- 计划不包含参考页的假数据、合成行情、假会员或直接 DOM mutation。
- 本轮按用户授权直接使用 inline execution，不等待逐任务确认。
