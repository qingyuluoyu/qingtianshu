import { expect, test, type Page } from "@playwright/test";
import { historyFixture, workspaceFixture } from "../src/features/stock-research/testFixtures";
import { assetsPayload } from "../src/features/watchlist/testFixtures";

const accountSession = {
  id: "33333333-3333-4333-8333-333333333333",
  account: "watchlist-user",
  name: "watchlist-user",
  masked_phone: "+86138****9000",
  auth_type: "account",
  is_registered: true,
  created_at: "2026-08-04T00:00:00+00:00",
  session_expires_at: "2026-08-11T00:00:00+00:00",
};

async function mockWatchlist(page: Page, options: { patchStatus?: number } = {}) {
  const patchBodies: unknown[] = [];
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
    if (path === "/v1/stock-workspaces" && request.method() === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(assetsPayload()) });
      return;
    }
    if (path === "/v1/stocks/000063.SZ/relation" && request.method() === "PATCH") {
      patchBodies.push(request.postDataJSON());
      if (options.patchStatus === 409) {
        await route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ detail: "股票空间已更新，当前版本为 4" }) });
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          contract_version: "stock_domain_v1",
          symbol: "000063.SZ",
          version: 4,
          relation_type: "watching",
          priority: "high",
          tracking_status: "paused",
          workflow_status: "researching",
          attention_tags: ["算力"],
        }),
      });
      return;
    }
    if (path === "/v1/stocks/000063.SZ/workspace") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(workspaceFixture()) });
      return;
    }
    if (path === "/stocks/000063.SZ/history") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(historyFixture()) });
      return;
    }
    await route.continue();
  });
  return { patchBodies };
}

test("renders assets, filters via URL and patches relation with base_version", async ({ page }) => {
  const { patchBodies } = await mockWatchlist(page);
  await page.goto("/watchlist");
  await expect(page.getByRole("heading", { name: "我的关注" })).toBeVisible();
  // 表格与直通数值。
  await expect(page.getByText("000063.SZ")).toBeVisible();
  await expect(page.getByText("-0.14%").first()).toBeVisible();
  await expect(page.getByText("+1.25%").first()).toBeVisible();
  await expect(page.getByText("行情不可用").first()).toBeVisible();
  await expect(page.getByText("尚未保存当前判断").first()).toBeVisible();
  // 概览卡点击只改筛选与 URL。
  await page.getByRole("group", { name: "关注概览筛选" }).getByRole("button", { name: /重点/ }).click();
  await expect(page).toHaveURL(/filter=priority/);
  await expect(page.locator("tbody tr")).toHaveCount(1);
  // 回到全部后触发关系变更：全量载荷 + base_version。
  await page.getByRole("group", { name: "关注概览筛选" }).getByRole("button", { name: /全部/ }).click();
  await page.getByRole("button", { name: "暂停跟踪" }).first().click();
  await expect(page.getByText(/已暂停跟踪（000063\.SZ）/)).toBeVisible();
  expect(patchBodies).toHaveLength(1);
  expect(patchBodies[0]).toMatchObject({
    base_version: 3,
    relation_type: "watching",
    priority: "high",
    tracking_status: "paused",
    workflow_status: "researching",
    attention_tags: ["算力"],
  });
  // 快速预览与小 K 线（仅选中行发起单股请求）。
  await expect(page.getByText(/快速预览/)).toBeVisible();
  await expect(page.getByRole("img", { name: "日 K 蜡烛与成交量图" })).toBeVisible();
  await expect(page.getByRole("link", { name: "进入个股研究" })).toHaveAttribute("href", "/stocks/000063.SZ");
});

test("conflict 409 refreshes the list and asks the user to re-confirm", async ({ page }) => {
  await mockWatchlist(page, { patchStatus: 409 });
  await page.goto("/watchlist");
  await page.getByRole("button", { name: "暂停跟踪" }).first().click();
  await expect(page.getByText(/请确认后重试/)).toBeVisible();
  // 表格仍在（未整页清空），行数据保留。
  await expect(page.getByText("000063.SZ")).toBeVisible();
});

test("ending a relation requires the confirm dialog", async ({ page }) => {
  const { patchBodies } = await mockWatchlist(page);
  await page.goto("/watchlist");
  await page.getByRole("button", { name: "结束关注" }).first().click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("dialog").getByRole("button", { name: "取消", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeHidden();
  expect(patchBodies).toHaveLength(0);
  await page.getByRole("button", { name: "结束关注" }).first().click();
  await page.getByRole("button", { name: "确认结束关注" }).click();
  await expect(page.getByText(/已结束关注（000063\.SZ）/)).toBeVisible();
  expect(patchBodies[0]).toMatchObject({ base_version: 3, relation_type: "ended", priority: null });
});

test("mobile viewport renders without horizontal overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockWatchlist(page);
  await page.goto("/watchlist");
  await expect(page.getByText("000063.SZ")).toBeVisible();
  await expect(page.getByText(/快速预览/)).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});
