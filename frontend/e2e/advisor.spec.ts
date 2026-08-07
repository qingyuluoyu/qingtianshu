import { expect, test, type Page } from "@playwright/test";
import {
  chatResponsePayload,
  conversationDetailPayload,
  conversationsPayload,
  writebacksPayload,
} from "../src/features/advisor/testFixtures";

const accountSession = {
  id: "33333333-3333-4333-8333-333333333333",
  account: "advisor-user",
  name: "advisor-user",
  masked_phone: "+86138****9000",
  auth_type: "account",
  is_registered: true,
  created_at: "2026-08-04T00:00:00+00:00",
  session_expires_at: "2026-08-11T00:00:00+00:00",
};

async function mockAdvisor(page: Page, options: { confirmStatus?: number } = {}) {
  const chatBodies: unknown[] = [];
  const confirmed: string[] = [];
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
    if (path === "/me/conversations" && request.method() === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(conversationsPayload()) });
      return;
    }
    if (path === "/me/conversations/conv-1" && request.method() === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(conversationDetailPayload()) });
      return;
    }
    if (path === "/me/chat" && request.method() === "POST") {
      chatBodies.push(request.postDataJSON());
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(chatResponsePayload()) });
      return;
    }
    if (path.startsWith("/me/chat/stream/")) {
      // mock 模式退化为无进度通道：EventSource 404 后前端静默降级，回答以 POST 同步响应为准。
      await route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: "实时回答不存在" }) });
      return;
    }
    if (path === "/v1/ai-writebacks" && request.method() === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(writebacksPayload()) });
      return;
    }
    if (path === "/v1/ai-writebacks/cand-1/confirm" && request.method() === "POST") {
      confirmed.push("cand-1");
      if (options.confirmStatus === 409) {
        await route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ detail: "正式判断已更新，当前版本为 3" }) });
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ...writebacksPayload().items[0],
          status: "confirmed",
          resolved_at: "2026-08-06T03:00:00+00:00",
          thesis: { id: "thesis-1", version_no: 3 },
        }),
      });
      return;
    }
    if (path === "/v1/ai-writebacks/cand-1/reject" && request.method() === "POST") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ...writebacksPayload().items[0], status: "rejected", resolved_at: "2026-08-06T03:00:00+00:00" }),
      });
      return;
    }
    await route.continue();
  });
  return { chatBodies, confirmed };
}

test("advisor main flow: history, context, send question and confirm candidate", async ({ page }) => {
  const { chatBodies, confirmed } = await mockAdvisor(page);
  await page.goto("/advisor/conv-1?symbol=000063.SZ&source=stock-research&module=financials&asOf=2026-08-06");
  await expect(page.getByRole("heading", { name: "金融顾问" })).toBeVisible();
  // 侧栏会话与上下文四元组。
  const sidebar = page.getByLabel("会话列表与上下文");
  await expect(sidebar.getByText("中兴通讯研究")).toBeVisible();
  await expect(sidebar.getByText("标的：000063.SZ")).toBeVisible();
  await expect(sidebar.getByText("来源页：个股研究")).toBeVisible();
  await expect(sidebar.getByText("模块：financials")).toBeVisible();
  await expect(sidebar.getByText("数据时间：2026-08-06")).toBeVisible();
  // 历史消息与证据抽屉（五面分析 + 证据来源）。
  await expect(page.getByText("中兴通讯三季度现金流怎么样？")).toBeVisible();
  const drawer = page.getByLabel("证据与候选写回");
  await expect(drawer.getByText("已确认事实")).toBeVisible();
  await expect(drawer.getByText("2026 年三季度报告")).toBeVisible();
  // 发送问题：携带 symbol/conversation_id/request_id 与上下文行。
  await page.getByLabel("向顾问提问").fill("请核验现金流覆盖");
  await page.getByRole("button", { name: "发送" }).click();
  await expect.poll(() => chatBodies.length).toBe(1);
  const body = chatBodies[0] as Record<string, unknown>;
  expect(body.symbol).toBe("000063.SZ");
  expect(body.conversation_id).toBe("conv-1");
  expect(typeof body.request_id).toBe("string");
  expect(String(body.message)).toContain("请核验现金流覆盖");
  expect(String(body.message)).toContain("来源页=stock-research");
  // 候选确认：二次对话框 → POST confirm。
  await drawer.getByRole("button", { name: "确认写回" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("dialog").getByRole("button", { name: "确认写回" }).click();
  await expect(page.getByText(/候选已确认并写入正式研究记录/)).toBeVisible();
  expect(confirmed).toEqual(["cand-1"]);
});

test("candidate confirm 409 shows conflict notice and keeps the page intact", async ({ page }) => {
  await mockAdvisor(page, { confirmStatus: 409 });
  await page.goto("/advisor/conv-1");
  const drawer = page.getByLabel("证据与候选写回");
  await drawer.getByRole("button", { name: "确认写回" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "确认写回" }).click();
  await expect(page.getByText(/已刷新最新状态/)).toBeVisible();
  // 页面不清空：消息与候选卡仍在。
  await expect(page.getByText("中兴通讯三季度现金流怎么样？")).toBeVisible();
  await expect(drawer.getByText("研究判断候选")).toBeVisible();
});

test("mobile 390px has no horizontal overflow and composer stays usable", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockAdvisor(page);
  await page.goto("/advisor/conv-1?symbol=000063.SZ");
  await expect(page.getByRole("heading", { name: "金融顾问" })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBe(0);
  await page.getByLabel("向顾问提问").fill("现金流怎么样");
  await expect(page.getByRole("button", { name: "发送" })).toBeEnabled();
});
