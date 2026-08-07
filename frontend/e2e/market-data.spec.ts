import { expect, test, type Page, type Route } from "@playwright/test";

const accountSession = {
  id: "33333333-3333-4333-8333-333333333333",
  account: "market-data-user",
  name: "market-data-user",
  masked_phone: "+86138****8000",
  auth_type: "account",
  is_registered: true,
  created_at: "2026-08-04T00:00:00+00:00",
  session_expires_at: "2026-08-11T00:00:00+00:00",
};

const chinaIndices = {
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

const usIndices = {
  generated_at: "2026-08-04T02:35:07+00:00",
  warnings: [],
  indices: [
    ["^GSPC", "标普500", 6234.6, 39.1, 0.63],
    ["^IXIC", "纳斯达克综合", 19726.0, -102.4, -0.52],
    ["^DJI", "道琼斯工业指数", 44432.0, -80.1, -0.18],
  ].map(([symbol, name, latest_close, change_1d, return_1d_pct]) => ({ symbol, name, status: "available", metrics: { latest_close, change_1d, return_1d_pct }, market_timestamp: "2026-08-04T20:00:00+00:00", is_stale: false })),
};

const breadth = {
  status: "available", market_date: "2026-08-04", market_timestamp: null, is_stale: false,
  breadth: { total: 5535, advancers: 3549, decliners: 1804, unchanged: 182, advance_ratio: .6412, decline_ratio: .3259, unchanged_ratio: .0329, limit_up_count: 42, limit_down_count: 7, limit_method: "按板块规则近似判定", state: "上涨家数占优" },
  turnover: { status: "available", total_amount_100m_cny: 10493.68, history_comparison: { status: "available", change_vs_previous_pct: -5.41 } },
  distribution: { median_pct_change: .679, bins_7: { le_neg7: 68, gt_neg7_le_neg3: 236, gt_neg3_lt_0: 1500, unchanged: 182, gt_0_lt_3: 3037, ge_3_lt_7: 400, ge_7: 112 } },
  coverage: { coverage_ratio: .9671 },
  turnover_history: [{ date: "2026-07-31", amount_100m_cny: 25590.66 }, { date: "2026-08-04", amount_100m_cny: 10493.68 }],
};

const sectors = {
  source: "东方财富",
  market_timestamp: "2026-08-03T02:51:27+00:00",
  fetched_at: "2026-08-03T02:51:31+00:00",
  is_stale: false,
  warnings: [],
  sectors: Array.from({ length: 12 }, (_, index) => ({
    code: `BK${String(index).padStart(4, "0")}`,
    name: `板块${index + 1}`,
    pct_change: 4.56 - index * 0.1,
    advancers: 2,
    decliners: 0,
    main_net_inflow: (125.62 - index) * 1e8,
  })),
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

const liveMarkets = {
  generated_at: "2026-08-04T02:35:09+00:00",
  markets: [
    { key: "china", name: "中国A股", status: "available", latest_price: 3809.66, pct_change: 0.24, currency: "CNY", market_timestamp: "2026-08-04T07:00:00+00:00", is_stale: false },
    { key: "japan", name: "日本股市", status: "available", latest_price: 40210.5, pct_change: -0.31, currency: "JPY", market_timestamp: "2026-08-04T06:00:00+00:00", is_stale: false },
    { key: "korea", name: "韩国股市", status: "available", latest_price: 3120.4, pct_change: 0.12, currency: "KRW", market_timestamp: "2026-08-04T06:00:00+00:00", is_stale: false },
    { key: "us", name: "美国股市", status: "available", latest_price: 6234.6, pct_change: 0.63, currency: "USD", market_timestamp: "2026-08-04T20:00:00+00:00", is_stale: false },
    { key: "london_gold", name: "伦敦金", status: "available", latest_price: 2358.6, pct_change: 0.78, currency: "USD", market_timestamp: "2026-08-04T12:00:00+00:00", is_stale: false },
    { key: "dollar_index", name: "美元指数", status: "available", latest_price: 98.42, pct_change: -0.21, currency: "USD", market_timestamp: "2026-08-04T12:00:00+00:00", is_stale: false },
    { key: "brent_crude", name: "布伦特原油", status: "available", latest_price: 69.85, pct_change: 1.12, currency: "USD", market_timestamp: "2026-08-04T12:00:00+00:00", is_stale: false },
    { key: "us10y_yield", name: "美债十年期", status: "available", latest_price: 4.25, pct_change: 0.03, currency: "PCT", market_timestamp: "2026-08-04T12:00:00+00:00", is_stale: false },
  ],
};

const indexHistory = {
  market_timestamp: "2026-08-03T07:00:00+00:00",
  points: Array.from({ length: 22 }, (_, index) => ({ timestamp: `2026-07-${String(index + 1).padStart(2, "0")}T01:30:00+00:00`, open: 3790 + index * 2, high: 3810 + index * 2, low: 3780 + index * 2, close: 3800 + index * 2, adjusted_close: 3800 + index * 2, volume: 1 })),
};

type Override = unknown | { status: number; body?: unknown } | ((route: Route) => Promise<void>);

const defaults: Record<string, unknown> = {
  "/markets/breadth": breadth,
  "/sectors/hot": sectors,
  "/markets/capital-flow": capitalFlow,
  "/markets/live": liveMarkets,
};

async function mockMarketData(page: Page, overrides: Record<string, Override> = {}) {
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
      ?? (url.pathname === "/indices" ? (url.searchParams.get("group") === "us" ? usIndices : chinaIndices) : undefined)
      ?? (/^\/indices\/[^/]+\/history$/.test(url.pathname) ? indexHistory : undefined)
      ?? defaults[url.pathname];
    if (body !== undefined) {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
      return;
    }
    await route.continue();
  });
}

test("renders all market modules, switches groups and expands index history on desktop", async ({ page }) => {
  await mockMarketData(page);
  await page.goto("/market-data");
  await expect(page.getByRole("heading", { name: "行情数据" })).toBeVisible();
  // 指数总览默认中国分组，数值直通。
  await expect(page.getByText("上证综指")).toBeVisible();
  await expect(page.getByText("3,809.66", { exact: true })).toBeVisible();
  await expect(page.getByText("-0.59%")).toBeVisible();
  // 市场广度三卡。
  await expect(page.getByText("上涨家数占优")).toBeVisible();
  await expect(page.getByText("10,493.68 亿")).toBeVisible();
  // 板块热度超过 8 行（limit=20）。
  await expect(page.getByRole("region", { name: "板块热度" }).getByText("板块12")).toBeVisible();
  // 资金流向：亿元直通 + 北向注记。
  await expect(page.getByText("-128.45 亿")).toBeVisible();
  await expect(page.getByText(/北向资金 2024-08 起港交所停披/)).toBeVisible();
  // 全球市场 8 品种，美债 PCT 直通。
  const globalCard = page.getByRole("region", { name: "全球市场观察" });
  for (const name of ["中国A股", "日本股市", "韩国股市", "美国股市", "伦敦金", "美元指数", "布伦特原油", "美债十年期"]) {
    await expect(globalCard.getByText(name)).toBeVisible();
  }
  await expect(globalCard.getByText("4.25%")).toBeVisible();
  // 分组 tab 进 URL 并换数据。
  await page.getByRole("tab", { name: "美国" }).click();
  await expect(page).toHaveURL(/\/market-data\?group=us$/);
  await expect(page.getByText("标普500")).toBeVisible();
  await expect(page.getByText("纳斯达克综合")).toBeVisible();
  // 展开行加载近 1 月走势。
  await page.getByRole("button", { name: /标普500/ }).click();
  await expect(page.getByText(/近 1 月日线收盘/)).toBeVisible();
  await expect(page.locator("svg").nth(0)).toBeVisible();
  // 页脚边界文案。
  await expect(page.getByText(/不生成买卖、仓位或收益建议/)).toBeVisible();
});

test("a single 500 endpoint stays isolated in its module with retry", async ({ page }) => {
  await mockMarketData(page, { "/sectors/hot": { status: 500 } });
  await page.goto("/market-data");
  const sectorCard = page.getByRole("region", { name: "板块热度" });
  await expect(sectorCard.getByText(/本模块暂时不可用/)).toBeVisible({ timeout: 8_000 });
  await expect(sectorCard.getByRole("button", { name: "重新读取" })).toBeVisible();
  // 其他模块不受影响。
  await expect(page.getByText("上证综指")).toBeVisible();
  await expect(page.getByText("上涨家数占优")).toBeVisible();
  await expect(page.getByText("美元指数")).toBeVisible();
  await expect(page.getByText("-128.45 亿")).toBeVisible();
});

test("mobile viewport renders without horizontal overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockMarketData(page);
  await page.goto("/market-data");
  await expect(page.getByRole("heading", { name: "行情数据" })).toBeVisible();
  await expect(page.getByText("上证综指")).toBeVisible();
  await expect(page.getByText("美元指数")).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBe(0);
});
