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
  warnings: [],
  boundary: "所有事项均不构成买卖、仓位或收益建议。",
};

const indices = {
  generated_at: "2026-08-04T02:35:07+00:00",
  warnings: [],
  indices: [
    ["000001.SS", "上证综指", 3809.66, -0.59],
    ["399001.SZ", "深证成指", 13448.29, -0.96],
    ["399006.SZ", "创业板指", 3302.55, -1.24],
    ["000688.SS", "科创50", 1552.89, -5.08],
    ["000300.SS", "沪深300", 4543.18, -0.98],
  ].map(([symbol, name, latest_close, return_1d_pct]) => ({ symbol, name, status: "available", metrics: { latest_close, return_1d_pct }, market_timestamp: "2026-08-03T01:30:00+00:00", is_stale: false })),
};

const breadth = {
  status: "available", market_date: "2026-08-04", market_timestamp: null, is_stale: false,
  breadth: { total: 5535, advancers: 3549, decliners: 1804, unchanged: 182, advance_ratio: .6412, decline_ratio: .3259, state: "上涨家数占优" },
  turnover: { status: "available", total_amount_100m_cny: 10493.68, history_comparison: { status: "intraday_not_comparable" } },
  distribution: { median_pct_change: .679 },
};

const defaults: Record<string, unknown> = {
  "/v1/today/overview": overview,
  "/indices": indices,
  "/markets/breadth": breadth,
  "/sectors/hot": { market_timestamp: "2026-08-03T02:51:27+00:00", fetched_at: "2026-08-03T02:51:31+00:00", is_stale: true, warnings: ["simulated stale cache"], sectors: [{ code: "BK1318", name: "光伏主材", pct_change: 4.56, advancers: 2, decliners: 0 }] },
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
    if (url.pathname === "/session" && request.method() === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(accountSession) });
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
    const body = override ?? defaults[url.pathname];
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
  await expect(page.getByText("沪深300")).toBeVisible();
  await expect(page.getByText("10,493.68 亿元")).toBeVisible();
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
  await expect(page.getByRole("region", { name: "热门板块" }).getByText(/本模块暂时不可用/)).toBeVisible({ timeout: 8_000 });
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

test("simulated private 401 returns control to the existing authentication gate", async ({ page }) => {
  let sessionCalls = 0;
  let overviewCalls = 0;
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/session") {
      sessionCalls += 1;
      await route.fulfill({ status: sessionCalls === 1 ? 200 : 401, contentType: "application/json", body: JSON.stringify(sessionCalls === 1 ? accountSession : { code: "session_expired", message: "会话已失效" }) });
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
