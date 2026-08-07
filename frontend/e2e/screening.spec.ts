import { expect, test, type Page } from "@playwright/test";
import {
  liZongBacktestPayload,
  liZongCandidatesPayload,
  liZongRunLatestPayload,
  profilesPayload,
  screenPayload,
} from "../src/features/screening/testFixtures";

const accountSession = {
  id: "44444444-4444-4444-8444-444444444444",
  account: "screening-user",
  name: "screening-user",
  masked_phone: "+86137****8000",
  auth_type: "account",
  is_registered: true,
  created_at: "2026-08-04T00:00:00+00:00",
  session_expires_at: "2026-08-11T00:00:00+00:00",
};

async function mockScreening(page: Page) {
  const screenBodies: unknown[] = [];
  const deepStockBodies: unknown[] = [];
  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (path === "/session/status" && request.method() === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ authenticated: true, session: accountSession }) });
      return;
    }
    if (path === "/events") {
      await route.fulfill({ status: 200, contentType: "text/event-stream", body: `data: ${JSON.stringify({ type: "connected", time: "2026-08-06T02:35:23+00:00" })}\n\n` });
      return;
    }
    if (path === "/stock-screener/profiles") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(profilesPayload()) });
      return;
    }
    if (path === "/me/stock-screener" && request.method() === "POST") {
      screenBodies.push(request.postDataJSON());
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(screenPayload()) });
      return;
    }
    if (path === "/me/deep-stock" && request.method() === "POST") {
      deepStockBodies.push(request.postDataJSON());
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({ symbol: "600549.SS", conversation_id: "conversation-screening-1" }),
      });
      return;
    }
    if (path === "/v1/stock-strategies/li-zong/candidates") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(liZongCandidatesPayload()) });
      return;
    }
    if (path === "/v1/stock-strategies/li-zong/runs/latest") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(liZongRunLatestPayload()) });
      return;
    }
    if (path === "/v1/stock-strategies/li-zong/backtest") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(liZongBacktestPayload()) });
      return;
    }
    await route.continue();
  });
  return { deepStockBodies, screenBodies };
}

test("screen mode: filters, three-state table, URL state and no pseudo pagination", async ({ page }) => {
  const { deepStockBodies, screenBodies } = await mockScreening(page);
  await page.goto("/screening");
  await expect(page.getByRole("heading", { name: "透明选股" })).toBeVisible();
  // 初始 POST 载荷：档案默认 + force_refresh=false（不触发数据重建）。
  await expect(page.getByText("600549.SH").first()).toBeVisible();
  expect(screenBodies.length).toBeGreaterThan(0);
  expect(screenBodies[0]).toMatchObject({ profile: "quality", market: "all", max_results: 12, force_refresh: false });
  // 直通数值与三态。
  await expect(page.getByText("+8.79%").first()).toBeVisible();
  await expect(page.getByText("数据不足").first()).toBeVisible();
  // 修改阈值后经 URL 重新筛选。
  await page.getByLabel("ROE 下限（%）").fill("5");
  await page.getByRole("button", { name: "应用筛选" }).click();
  await expect(page).toHaveURL(/f_min_roe=5/);
  await expect.poll(() => screenBodies.length).toBeGreaterThan(1);
  expect(screenBodies[screenBodies.length - 1]).toMatchObject({ filters: { min_roe: 5, min_market_cap_yi: 50 } });
  // §5.2：无服务端分页，页面不出现分页控件，只标注真实命中数与展示上限。
  await expect(page.getByText("命中候选（真实总数）")).toBeVisible();
  await expect(page.getByText(/不提供伪分页/)).toBeVisible();
  // 用户明确点击后先保存完整候选上下文，再进入个股研究。
  await page.getByRole("button", { name: "保存线索并进入个股研究" }).click();
  await expect.poll(() => deepStockBodies.length).toBe(1);
  expect(deepStockBodies[0]).toMatchObject({
    symbol: "600549.SS",
    quality_scope: "user",
    entry_context: {
      source_kind: "stock_screen",
      profile_key: "quality",
      as_of_date: "2026-08-05",
      research_focus: "营收同比 86.99%、净利润同比 189.14% 同时为正。",
    },
  });
  await expect(page).toHaveURL(/\/stocks\/600549\.SS/);
});

test("mutually exclusive modes switch via URL and li-zong shows three states", async ({ page }) => {
  await mockScreening(page);
  await page.goto("/screening");
  await expect(page.getByText("600549.SH").first()).toBeVisible();
  await page.getByRole("group", { name: "选股模式" }).getByRole("button", { name: /李总指标筛选/ }).click();
  await expect(page).toHaveURL(/mode=lizong/);
  await expect(page.getByText("600519.SH").first()).toBeVisible();
  await expect(page.getByText("300750.SZ").first()).toBeVisible();
  await expect(page.getByText("最近筛选 Run")).toBeVisible();
  await expect(page.getByText("规则漏斗分布")).toBeVisible();
  // 状态 chip 走服务端 status 过滤。
  await page.getByRole("group", { name: "候选状态筛选" }).getByRole("button", { name: /数据不足/ }).click();
  await expect(page).toHaveURL(/status=data_incomplete/);
});

test("backtest mode renders metrics and chart only for a completed run", async ({ page }) => {
  await mockScreening(page);
  await page.goto("/screening?mode=backtest");
  await expect(page.getByText("区间收益", { exact: true })).toBeVisible();
  await expect(page.getByText("+28.10%")).toBeVisible();
  await expect(page.getByText("-32.76%")).toBeVisible();
  await expect(page.getByRole("img", { name: "回测净值与基准净值曲线" })).toBeVisible();
  await page.getByRole("group", { name: "回测区间" }).getByRole("button", { name: "近 3 月" }).click();
  await expect(page).toHaveURL(/period=3m/);
});

test("mobile viewport renders without horizontal overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockScreening(page);
  await page.goto("/screening");
  await expect(page.getByText("600549.SH").first()).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});
