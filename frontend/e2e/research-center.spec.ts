import { expect, test, type Page } from "@playwright/test";
import {
  actionsPayload,
  changesPayload,
  evidenceTasksPayload,
  outcomesPayload,
  priorityPayload,
  runReviewsPayload,
} from "../src/features/research-center/testFixtures";

const accountSession = {
  id: "66666666-6666-4666-8666-666666666666",
  account: "research-center-user",
  name: "research-center-user",
  masked_phone: "+86138****8000",
  auth_type: "account",
  is_registered: true,
  created_at: "2026-08-04T00:00:00+00:00",
  session_expires_at: "2026-08-11T00:00:00+00:00",
};

type ResearchCenterOverrides = {
  empty?: boolean;
  failedPath?: string;
};

function packets(empty: boolean): Record<string, unknown> {
  if (!empty) {
    return {
      "/me/research-priority": priorityPayload(),
      "/me/research-changes": changesPayload(),
      "/me/research-actions": actionsPayload(),
      "/me/evidence-tasks": evidenceTasksPayload(),
      "/me/research-outcomes": outcomesPayload(),
      "/me/run-reviews": runReviewsPayload(),
    };
  }

  return {
    "/me/research-priority": {
      ...priorityPayload(),
      items: [],
      coverage: { requested: 0, available: 0, missing_baseline: 0 },
    },
    "/me/research-changes": {
      ...changesPayload(),
      events: [],
      coverage: { requested: 0, with_report: 0, with_change_archive: 0 },
    },
    "/me/research-actions": {
      ...actionsPayload(),
      items: [],
      summary: { symbols: 0, triggered: 0, pending_data: 0, watching: 0, priority_research: 0 },
    },
    "/me/evidence-tasks": {
      ...evidenceTasksPayload(),
      items: [],
      summary: { total: 0, pending: 0, pending_external: 0, resolved: 0, failed: 0 },
    },
    "/me/research-outcomes": {
      ...outcomesPayload(),
      items: [],
      coverage: { requested_symbols: 0, with_archives: 0, available_outcomes: 0, pending_outcomes: 0 },
    },
    "/me/run-reviews": {
      items: [],
      summary: { total: 0, filtered: 0, repaired: 0, statuses: {}, days: 30 },
    },
  };
}

async function mockResearchCenter(page: Page, overrides: ResearchCenterOverrides = {}) {
  const responses = packets(overrides.empty ?? false);
  await page.route("**/*", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === "/session/status" && request.method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ authenticated: true, session: accountSession }),
      });
      return;
    }
    if (path === "/events") {
      await route.fulfill({ status: 200, contentType: "text/event-stream", body: "" });
      return;
    }
    if (path === overrides.failedPath) {
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "simulated unavailable" }),
      });
      return;
    }
    if (path in responses) {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(responses[path]) });
      return;
    }
    await route.continue();
  });
}

test("renders six real research contracts and keeps links inside the research workflow", async ({ page }) => {
  await mockResearchCenter(page);
  await page.goto("/research-center");

  await expect(page.getByRole("heading", { name: "研究中心", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "优先处理" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "当前行动" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "研究变化" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "补证任务" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "研究结果复盘" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "回答与证据复盘" })).toBeVisible();

  await expect(page.getByText("复核紧迫度 78")).toBeVisible();
  await expect(page.getByText("已触发", { exact: true })).toBeVisible();
  await expect(page.getByText("待补证", { exact: true })).toBeVisible();
  await expect(page.getByText("-2.35%")).toBeVisible();
  await expect(page.getByText("回答检查通过")).toBeVisible();
  await expect(page.getByText(/优先级不是投资排名/)).toBeVisible();

  await expect(page.getByRole("link", { name: "查看个股研究" }).first()).toHaveAttribute("href", "/stocks/000063.SZ");
  await expect(page.getByRole("link", { name: "问顾问" }).first()).toHaveAttribute("href", /source=research-center/);
  await expect(page.getByRole("link", { name: "打开原对话" })).toHaveAttribute("href", "/advisor/conversation-1");
});

test("renders honest empty states for a new account", async ({ page }) => {
  await mockResearchCenter(page, { empty: true });
  await page.goto("/research-center");

  await expect(page.getByText("还没有需要排序的关注标的")).toBeVisible();
  await expect(page.getByText("暂无可追溯变化")).toBeVisible();
  await expect(page.getByText("暂无研究行动")).toBeVisible();
  await expect(page.getByText("暂无补证任务")).toBeVisible();
  await expect(page.getByText("暂无研究结果")).toBeVisible();
  await expect(page.getByText("近 30 日暂无正式 Run")).toBeVisible();
  await expect(page.getByText("中兴通讯")).toHaveCount(0);
});

test("keeps five modules usable when one contract fails and has no mobile root overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockResearchCenter(page, { failedPath: "/me/research-changes" });
  await page.goto("/research-center");

  await expect(page.getByText("该模块暂时不可用")).toBeVisible();
  await expect(page.getByText("复核最新证据变化")).toBeVisible();
  await expect(page.getByText("补齐公司最新公告")).toBeVisible();
  await expect(page.getByText("利润改善是否得到经营现金流确认？")).toBeVisible();
  await expect(page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).resolves.toBe(true);
});
