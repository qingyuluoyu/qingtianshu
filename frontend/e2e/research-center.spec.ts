import { expect, test, type Page } from "@playwright/test";
import {
  actionsPayload,
  changesPayload,
  emptyTimelinePayload,
  outcomesPayload,
  reportPayload,
  timelinePayload,
  tradeReviewCenterPayload,
} from "../src/features/research-center/testFixtures";

const accountSession = {
  id: "55555555-5555-4555-8555-555555555555",
  account: "research-user",
  name: "research-user",
  masked_phone: "+86138****9000",
  auth_type: "account",
  is_registered: true,
  created_at: "2026-08-04T00:00:00+00:00",
  session_expires_at: "2026-08-11T00:00:00+00:00",
};

async function mockResearchCenter(page: Page) {
  const confirmBodies: unknown[] = [];
  const archiveBodies: unknown[] = [];
  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const json = (body: unknown) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
    if (path === "/session/status" && request.method() === "GET") {
      await json({ authenticated: true, session: accountSession });
      return;
    }
    if (path === "/events") {
      await route.fulfill({ status: 200, contentType: "text/event-stream", body: `data: ${JSON.stringify({ type: "connected", time: "2026-08-06T02:35:23+00:00" })}\n\n` });
      return;
    }
    if (path === "/me/research-changes") { await json(changesPayload()); return; }
    if (path === "/me/research-outcomes") { await json(outcomesPayload()); return; }
    if (path === "/me/research-actions") { await json(actionsPayload()); return; }
    if (path === "/v1/trade-reviews" && request.method() === "GET") { await json(tradeReviewCenterPayload()); return; }
    if (path === "/v1/trade-reviews/review-1/confirm" && request.method() === "POST") {
      confirmBodies.push(request.postDataJSON());
      await json(tradeReviewCenterPayload().items[0]);
      return;
    }
    if (path === "/v1/trade-reviews/review-2/archive" && request.method() === "POST") {
      archiveBodies.push(request.postDataJSON());
      await json(tradeReviewCenterPayload().items[1]);
      return;
    }
    if (path === "/v1/stocks/000063.SZ/workspace/timeline") { await json(timelinePayload()); return; }
    if (path === "/v1/stocks/600519.SS/workspace/timeline") {
      await json({ ...emptyTimelinePayload(), symbol: "600519.SS", name: "贵州茅台" });
      return;
    }
    if (path === "/research-reports/000063.SZ") { await json(reportPayload()); return; }
    if (path === "/research-reports/600519.SS") {
      await json({ ...reportPayload(), symbol: "600519.SS", name: "贵州茅台", title: "贵州茅台研究快照｜2026-08-06" });
      return;
    }
    await route.continue();
  });
  return { confirmBodies, archiveBodies };
}

test("research center main flow: summary cards, timeline, outcome anchors and URL state", async ({ page }) => {
  await mockResearchCenter(page);
  await page.goto("/research-center");
  await expect(page.getByRole("heading", { name: "研究中心" })).toBeVisible();
  // 概览卡真实计数。
  const summary = page.getByRole("group", { name: "研究复盘概览" });
  await expect(summary.getByRole("button", { name: /待复盘/ })).toContainText("1");
  await expect(summary.getByRole("button", { name: /已有结果/ })).toContainText("2");
  // 左侧列表与中央判断-变化-处理链。
  await expect(page.getByRole("listbox", { name: "研究股票列表" }).getByText("中兴通讯")).toBeVisible();
  await expect(page.getByText("判断版本 2")).toBeVisible();
  await expect(page.getByText("跟踪 MA20 收复情况")).toBeVisible();
  // 历史结果四要素：OutcomeAnchor / 交易日窗口 / 基准 / 数据可得时间 + 直通百分数。
  await expect(page.getByText("结果锚点（OutcomeAnchor）")).toBeVisible();
  await expect(page.getByText("基准与数据可得时间")).toBeVisible();
  await expect(page.getByText("-1.85%", { exact: true })).toBeVisible();
  // §5.6：无记录接口的三动作只显示说明与跳转，不出现「已保存」。
  await expect(page.getByText(/不会显示为已保存/)).toBeVisible();
  // 选中另一只股票写入 URL 并加载其时间线（空 thesis → 真实空态）。
  await page.getByRole("option", { name: /贵州茅台/ }).click();
  await expect(page).toHaveURL(/symbol=600519\.SS/);
  await expect(page.getByText("尚未保存当前判断")).toBeVisible();
  // 概览卡分组过滤写 URL。
  await summary.getByRole("button", { name: /判断有变化/ }).click();
  await expect(page).toHaveURL(/focus=changed/);
});

test("trade review confirm/archive writes carry base_version and surface success", async ({ page }) => {
  const { confirmBodies, archiveBodies } = await mockResearchCenter(page);
  await page.goto("/research-center");
  await page.getByRole("button", { name: "确认复盘" }).click();
  await expect(page.getByText(/复盘已确认并落库为正式复盘/)).toBeVisible();
  expect(confirmBodies).toHaveLength(1);
  expect(confirmBodies[0]).toMatchObject({ base_version: 2 });
  await page.getByRole("button", { name: "归档复盘" }).click();
  await expect(page.getByText(/复盘已归档/)).toBeVisible();
  expect(archiveBodies).toHaveLength(1);
  expect(archiveBodies[0]).toMatchObject({ base_version: 1 });
});

test("mobile viewport renders without horizontal overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockResearchCenter(page);
  await page.goto("/research-center");
  await expect(page.getByRole("listbox", { name: "研究股票列表" }).getByText("中兴通讯")).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});
