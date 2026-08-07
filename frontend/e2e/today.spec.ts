import { expect, test, type Page, type Route } from "@playwright/test";

const accountSession = {
  id: "22222222-2222-4222-8222-222222222222",
  account: "today-user",
  name: "today-user",
  masked_phone: "+86138****8000",
  auth_type: "account",
  is_registered: true,
  created_at: "2026-08-04T00:00:00+00:00",
  session_expires_at: "2026-08-11T00:00:00+00:00",
};

const overview = {
  contract_version: "today_overview_v1",
  generated_at: "2026-08-04T02:35:06+00:00",
  session: { key: "intraday", label: "盘中", exchange_status: "open", exchange_label: "交易中", market_local_time: "2026-08-04T10:35:06+08:00" },
  summary: { headline: "上涨家数占优，优先核验已有研究事项。", priority_count: 1, related_change_count: 0, market_date: "2026-08-04" },
  priority_items: {
    items: [{ id: "test-action-1", kind: "research_action", title: "核验正式披露", detail: "对照最新财报原文", symbol: "000063.SZ", status_label: "需要复核", rank_reason: "高风险研究条件已经触发" }],
    total_visible: 1,
    ranking_method: "后端确定性排序",
    empty_message: "当前没有需要立即处理的个人研究事项。",
  },
  coverage: { status: "ready", components: {} },
  themes: [
    { key: "market_sentiment", title: "市场情绪", status: "ready", tone: "positive", summary: "上涨家数占优，情绪偏暖。", basis: "市场广度" },
    { key: "earnings_disclosure", title: "业绩披露", status: "ready", tone: "neutral", summary: "今日进入披露密集期。", basis: "公告日历" },
    { key: "concept_heat", title: "概念热度", status: "ready", tone: "negative", summary: "热门概念回落。", basis: "板块热度" },
    { key: "capital_flow", title: "资金流向", status: "unavailable", tone: "unknown", summary: "资金流数据源暂不可用。", basis: null },
  ],
  warnings: [],
  boundary: "所有事项均不构成买卖、仓位或收益建议。",
};

const indices = {
  generated_at: "2026-08-04T02:35:07+00:00",
  warnings: [],
  indices: [
    ["000001.SS", "上证综指", 3809.66, 9.31, -0.59],
    ["399001.SZ", "深证成指", 13448.29, -33.08, -0.96],
    ["399006.SZ", "创业板指", 3302.55, -14.01, -1.24],
    ["000688.SS", "科创50", 1552.89, -6.55, -5.08],
    ["000300.SS", "沪深300", 4543.18, 8.61, -0.98],
    ["000905.SS", "中证500", 7414.52, -12.4, -1.06],
  ].map(([symbol, name, latest_close, change_1d, return_1d_pct]) => ({ symbol, name, status: "available", metrics: { latest_close, change_1d, return_1d_pct }, market_timestamp: "2026-08-03T01:30:00+00:00", is_stale: false })),
};

const breadth = {
  status: "available", market_date: "2026-08-04", market_timestamp: null, is_stale: false,
  breadth: { total: 5535, advancers: 3549, decliners: 1804, unchanged: 182, advance_ratio: .6412, decline_ratio: .3259, unchanged_ratio: .0329, limit_up_count: 42, limit_down_count: 7, limit_method: "按板块规则近似判定", state: "上涨家数占优" },
  turnover: { status: "available", total_amount_100m_cny: 10493.68, history_comparison: { status: "available", change_vs_previous_pct: -5.41 } },
  distribution: { median_pct_change: .679, bins: { strong_advancers_ge_3: 512, mild_advancers_gt_0_lt_3: 3037, unchanged: 182, mild_decliners_lt_0_gt_neg3: 1500, strong_decliners_le_neg3: 304 }, bins_7: { le_neg7: 68, gt_neg7_le_neg3: 236, gt_neg3_lt_0: 1500, unchanged: 182, gt_0_lt_3: 3037, ge_3_lt_7: 400, ge_7: 112 } },
  coverage: { coverage_ratio: .9671 },
  turnover_history: [{ date: "2026-07-31", amount_100m_cny: 25590.66 }, { date: "2026-08-04", amount_100m_cny: 10493.68 }],
};

const anomalies = {
  status: "available", market_timestamp: "2026-08-04T02:00:00+00:00", is_stale: false,
  items: [{ symbol: "sh603019", name: "中科曙光", kind: "快速拉升", pct_change: 8.65, amount_100m_cny: 125.62, tick_time: "10:36:00" }],
};

const usIndices = {
  generated_at: "2026-08-04T02:35:07+00:00",
  warnings: [],
  indices: [
    ["^GSPC", "标普500", 2348.6, 0.63],
    ["^IXIC", "纳斯达克综合", 7726.0, -0.52],
    ["^DJI", "道琼斯工业指数", 10432.0, -0.18],
  ].map(([symbol, name, latest_close, return_1d_pct]) => ({ symbol, name, status: "available", metrics: { latest_close, return_1d_pct }, market_timestamp: "2026-08-04T20:00:00+00:00", is_stale: false })),
};

const indexHistory = {
  market_timestamp: "2026-08-03T07:00:00+00:00",
  points: Array.from({ length: 22 }, (_, index) => ({ timestamp: `2026-07-${String(index + 1).padStart(2, "0")}T01:30:00+00:00`, open: 3790 + index * 2, high: 3810 + index * 2, low: 3780 + index * 2, close: 3800 + index * 2, adjusted_close: 3800 + index * 2, volume: 1 })),
};

const latestReports = {
  status: "ready",
  items: [{ symbol: "000063.SZ", name: "中兴通讯", title: "中兴通讯：算力基建加速", institution: "中信证券", researchers: "张三", published_at: "2026-08-03", rating: "买入", previous_rating: "增持", forecast_eps: 1.85, report_url: "https://example.com/r1", summary: "摘要" }],
  method: "模拟数据",
  warnings: [],
};

const capitalFlow = {
  status: "available",
  market_timestamp: "2026-08-04T07:00:00+00:00",
  is_stale: false,
  summary: { main_net_inflow_100m_cny: -128.45, unit: "CNY_100m_yuan" },
  points: [
    { time: "09:30", main_net_inflow_100m_cny: -12.5 },
    { time: "10:30", main_net_inflow_100m_cny: -60.2 },
    { time: "15:00", main_net_inflow_100m_cny: -128.45 },
  ],
  method: "主力资金口径；北向资金 2024-08 起港交所停披。",
  warnings: [],
};

const positions = {
  contract_version: "position_ledger_v1",
  status: "ready",
  items: [{ workspace_id: "w-1", symbol: "000063.SZ", name: "中兴通讯", status: "open", current: { quantity: 200, cost_basis: 6400, average_cost: 32 } }],
  method: "模拟账本",
  warnings: [],
};

const liveMarkets = {
  generated_at: "2026-08-04T02:35:09+00:00",
  markets: [
    { key: "dollar_index", name: "美元指数", status: "available", latest_price: 98.42, pct_change: -0.21, currency: "USD", market_timestamp: "2026-08-04T12:00:00+00:00", is_stale: false },
    { key: "london_gold", name: "伦敦金（现货黄金）", status: "available", latest_price: 2358.6, pct_change: 0.78, currency: "USD", market_timestamp: "2026-08-04T12:00:00+00:00", is_stale: false },
    { key: "brent_crude", name: "布伦特原油", status: "available", latest_price: 69.85, pct_change: 1.12, currency: "USD", market_timestamp: "2026-08-04T12:00:00+00:00", is_stale: false },
    { key: "us10y_yield", name: "美债10年收益率", status: "available", latest_price: 4.25, pct_change: 0.03, currency: "PCT", market_timestamp: "2026-08-04T12:00:00+00:00", is_stale: false },
  ],
};

const defaults: Record<string, unknown> = {
  "/v1/today/overview": overview,
  "/indices": indices,
  "/markets/breadth": breadth,
  "/sectors/hot": { market_timestamp: "2026-08-03T02:51:27+00:00", fetched_at: "2026-08-03T02:51:31+00:00", is_stale: true, warnings: ["simulated stale cache"], sectors: [{ code: "BK1318", name: "光伏主材", pct_change: 4.56, advancers: 2, decliners: 0, main_net_inflow: 12_562_000_000 }] },
  "/research-reports/latest": latestReports,
  "/markets/capital-flow": capitalFlow,
  "/v1/positions": positions,
  "/markets/live": liveMarkets,
  "/markets/anomalies": anomalies,
  "/me/watchlist/brief": { generated_at: "2026-08-04T02:35:07+00:00", items: [], coverage: { requested: 0, available: 0 }, warnings: [] },
  "/me/research-actions": { generated_at: "2026-08-04T02:35:07+00:00", items: [], boundary: "不是交易指令。" },
  "/me/research-changes": { generated_at: "2026-08-04T02:35:08+00:00", items: [], events: [], coverage: { requested: 0, with_report: 0, with_change_archive: 0 }, boundary: "不是交易指令。" },
  "/system/data-health": { status: "degraded", user_label: "部分数据同步中", created_at: "2026-08-04T02:34:35+00:00", summary: { total: 67, healthy: 64, attention: 2, critical: 1 }, checks: [{ key: "filing:1", category: "fundamentals", status: "critical", label: "缺少当前报告期财报全文" }] },
};

type Override = unknown | { status: number; body?: unknown } | ((route: Route) => Promise<void>);

async function mockToday(page: Page, overrides: Record<string, Override> = {}) {
  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === "/session/status" && request.method() === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ authenticated: true, session: accountSession }) });
      return;
    }
    if (url.pathname === "/events") {
      await route.fulfill({ status: 200, contentType: "text/event-stream", body: `data: ${JSON.stringify({ type: "connected", time: "2026-08-04T02:35:23+00:00" })}\n\n` });
      return;
    }
    const override = overrides[url.pathname];
    if (typeof override === "function") {
      await override(route);
      return;
    }
    if (override && typeof override === "object" && "status" in override && typeof override.status === "number") {
      await route.fulfill({ status: override.status, contentType: "application/json", body: JSON.stringify(override.body ?? { detail: "simulated unavailable" }) });
      return;
    }
    const body = override
      ?? (url.pathname === "/indices" && url.searchParams.get("group") === "us" ? usIndices : undefined)
      ?? (/^\/indices\/[^/]+\/history$/.test(url.pathname) ? indexHistory : undefined)
      ?? defaults[url.pathname];
    if (body !== undefined) {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
      return;
    }
    await route.continue();
  });
}

test("simulated normal state renders real-contract modules on desktop and mobile", async ({ page }) => {
  await mockToday(page);
  await page.goto("/today");
  await expect(page.getByRole("heading", { name: "今日观察" })).toBeVisible();
  await expect(page.getByText("今天市场发生了什么？你应该关注哪些重点信号？")).toBeVisible();
  await expect(page.getByText("沪深300")).toBeVisible();
  await expect(page.getByText("+9.31")).toBeVisible();
  await expect(page.getByText("中科曙光")).toBeVisible();
  await expect(page.getByText("10,493.68 亿")).toBeVisible();
  await expect(page.getByText("125.62亿")).toBeVisible();
  await expect(page.getByText("中兴通讯：算力基建加速")).toBeVisible();
  await expect(page.getByText(/中信证券/)).toBeVisible();
  await expect(page.getByText("标普500")).toBeVisible();
  await expect(page.getByText("伦敦金（现货黄金）")).toBeVisible();
  await expect(page.getByText("美元指数")).toBeVisible();
  await expect(page.getByText("布伦特原油")).toBeVisible();
  await expect(page.getByText("美债10年收益率")).toBeVisible();
  await expect(page.getByText("4.25%")).toBeVisible();
  await expect(page.getByText("主力净流入", { exact: true })).toBeVisible();
  await expect(page.getByText("-128.45 亿")).toBeVisible();
  await expect(page.getByText(/北向资金 2024-08 起港交所停披/)).toBeVisible();
  await expect(page.getByText("市场情绪")).toBeVisible();
  await expect(page.getByText("资金流数据源暂不可用。")).toBeVisible();
  await page.getByRole("tab", { name: "持仓" }).click();
  await expect(page.getByText("6,400.00")).toBeVisible();
  await expect(page.getByText("32.00", { exact: true })).toBeVisible();
  await page.getByRole("tab", { name: "全部" }).click();
  await expect(page.getByText("暂无研究变化")).toBeVisible();
  await expect(page.getByText("缓存 / 延迟数据")).toBeVisible();
  await expect(page.getByRole("button", { name: "刷新" })).toBeVisible();
  await expect(page.getByRole("link", { name: "核验正式披露" })).toHaveAttribute("href", "/stocks/000063.SZ");
  await expect(page.getByText(/不构成买卖、仓位或收益建议/)).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("region", { name: "主要指数" })).toBeVisible();
  await page.getByRole("link", { name: "核验正式披露" }).click();
  await expect(page).toHaveURL(/\/stocks\/000063\.SZ$/);
});

test("simulated loading state is per-module and resolves without a page-wide blocker", async ({ page }) => {
  let release: (() => void) | undefined;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  const delayed = async (route: Route) => { await gate; const path = new URL(route.request().url()).pathname; await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(defaults[path]) }); };
  await mockToday(page, Object.fromEntries(Object.keys(defaults).map((path) => [path, delayed])));
  await page.goto("/today");
  await expect(page.getByText("正在读取…").first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "今日观察" })).toBeVisible();
  release?.();
  await expect(page.getByText("沪深300")).toBeVisible();
});

test("simulated empty state does not invent priorities, changes or watchlist data", async ({ page }) => {
  await mockToday(page, {
    "/v1/today/overview": { ...overview, summary: { ...overview.summary, priority_count: 0 }, priority_items: { ...overview.priority_items, items: [], total_visible: 0 } },
  });
  await page.goto("/today");
  await expect(page.getByText("当前没有需要立即处理的个人研究事项。")).toBeVisible();
  await expect(page.getByText("暂无研究变化")).toBeVisible();
  await expect(page.getByText("关注列表为空")).toBeVisible();
});

test("simulated partial and one-module failure keep verified personal content visible", async ({ page }) => {
  await mockToday(page, {
    "/v1/today/overview": { ...overview, coverage: { status: "partial", components: { sectors: "unavailable" } } },
    "/sectors/hot": { status: 503 },
  });
  await page.goto("/today");
  await expect(page.getByText("部分数据暂不可用；已返回模块仍保持可读。")).toBeVisible();
  await expect(page.getByText("核验正式披露")).toBeVisible();
  await expect(page.getByRole("region", { name: "板块热度" }).getByText(/本模块暂时不可用/)).toBeVisible({ timeout: 8_000 });
});

test("simulated market unavailable leaves research modules readable", async ({ page }) => {
  await mockToday(page, {
    "/indices": { status: 503 },
    "/markets/breadth": { status: 503 },
    "/sectors/hot": { status: 503 },
  });
  await page.goto("/today");
  await expect(page.getByText("核验正式披露")).toBeVisible();
  await expect(page.getByRole("region", { name: "主要指数" }).getByText(/本模块暂时不可用/)).toBeVisible({ timeout: 8_000 });
  await expect(page.getByRole("region", { name: "市场广度" }).getByText(/本模块暂时不可用/)).toBeVisible({ timeout: 8_000 });
});

test("simulated 500 on restored modules stays isolated per module with retry", async ({ page }) => {
  await mockToday(page, {
    "/markets/capital-flow": { status: 500 },
    "/markets/anomalies": { status: 500 },
    "/research-reports/latest": { status: 500 },
    "/v1/positions": { status: 500 },
  });
  await page.goto("/today");
  await expect(page.getByRole("region", { name: "资金流向" }).getByText(/本模块暂时不可用/)).toBeVisible({ timeout: 8_000 });
  await expect(page.getByRole("region", { name: "资金流向" }).getByRole("button", { name: "重新读取" })).toBeVisible();
  await expect(page.getByRole("region", { name: "异动机会 / 风险提示" }).getByText(/本模块暂时不可用/)).toBeVisible();
  await expect(page.getByRole("region", { name: "今日研究报告" }).getByText(/本模块暂时不可用/)).toBeVisible();
  // Other modules are not affected by the restored-module failures.
  await expect(page.getByText("沪深300")).toBeVisible();
  await expect(page.getByText("核验正式披露")).toBeVisible();
  await expect(page.getByRole("region", { name: "板块热度" }).getByText("光伏主材")).toBeVisible();
  // The positions tab isolates its own failure inside the changes card.
  await page.getByRole("tab", { name: "持仓" }).click();
  await expect(page.getByRole("region", { name: "我的股票新变化" }).getByText(/本模块暂时不可用/)).toBeVisible();
  await expect(page.getByRole("region", { name: "我的股票新变化" }).getByRole("button", { name: "重新读取" })).toBeVisible();
  await expect(page.getByRole("region", { name: "今日研究报告" }).getByText(/本模块暂时不可用/)).toBeVisible();
});

test("simulated empty research reports show the truthful empty state", async ({ page }) => {
  await mockToday(page, {
    "/research-reports/latest": { status: "empty", items: [] },
  });
  await page.goto("/today");
  await expect(page.getByRole("region", { name: "今日研究报告" }).getByText("暂无最新研究报告")).toBeVisible();
});

test("simulated private 401 returns control to the existing authentication gate", async ({ page }) => {
  let sessionCalls = 0;
  let overviewCalls = 0;
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/session/status") {
      sessionCalls += 1;
      await route.fulfill({ status: sessionCalls === 1 ? 200 : 401, contentType: "application/json", body: JSON.stringify(sessionCalls === 1 ? { authenticated: true, session: accountSession } : { code: "session_expired", message: "会话已失效" }) });
      return;
    }
    if (url.pathname === "/v1/today/overview") {
      overviewCalls += 1;
      await route.fulfill({ status: 401, contentType: "application/json", body: JSON.stringify({ code: "session_expired", message: "会话已失效" }) });
      return;
    }
    if (url.pathname === "/events") {
      await route.fulfill({ status: 200, contentType: "text/event-stream", body: "" });
      return;
    }
    if (defaults[url.pathname] !== undefined) {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(defaults[url.pathname]) });
      return;
    }
    await route.continue();
  });
  await page.goto("/today");
  await expect.poll(() => overviewCalls, { message: `session calls: ${sessionCalls}` }).toBeGreaterThan(0);
  await expect(page.getByRole("dialog", { name: "登录或注册" })).toBeVisible();
  await expect(page).toHaveURL(/\/today$/);
});

test("simulated non-trading day labels last confirmed market data", async ({ page }) => {
  await mockToday(page, {
    "/v1/today/overview": { ...overview, session: { ...overview.session, key: "closed", label: "休市", exchange_status: "closed", exchange_label: "已休市" } },
    "/indices": { ...indices, indices: indices.indices.map((item) => ({ ...item, is_stale: true })) },
    "/markets/breadth": { ...breadth, is_stale: true },
  });
  await page.goto("/today");
  await expect(page.getByText("已休市")).toBeVisible();
  await expect(page.getByText(/当前为休市，行情展示最近已确认数据/)).toBeVisible();
  await expect(page.getByText("缓存数据").first()).toBeVisible();
});
