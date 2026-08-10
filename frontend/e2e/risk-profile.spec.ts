import { expect, test, type Page } from "@playwright/test";

const accountSession = {
  id: "33333333-3333-4333-8333-333333333333",
  account: "risk-user@example.com",
  name: "风险测试用户",
  masked_phone: "+86138****9000",
  auth_type: "account",
  is_registered: true,
  created_at: "2026-08-04T00:00:00+00:00",
  session_expires_at: "2026-08-11T00:00:00+00:00",
};

async function mockRiskProfile(page: Page, authenticated = true) {
  let profileRequests = 0;
  await page.route("**/*", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === "/session/status" && request.method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(authenticated ? { authenticated: true, session: accountSession } : { authenticated: false }),
      });
      return;
    }
    if (path === "/events") {
      await route.fulfill({ status: 200, contentType: "text/event-stream", body: "" });
      return;
    }
    if (path === "/me/risk-profile" && request.method() === "GET") {
      profileRequests += 1;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          profile: {
            id: "risk-1",
            status: "confirmed",
            risk_level: "balanced",
            risk_label: "稳健型",
            score: 42,
            answers: {},
            confirmed_at: "2026-08-06T08:00:00+08:00",
            boundary: "风险档案只反映已确认的个人偏好。",
          },
        }),
      });
      return;
    }
    await route.continue();
  });
  return { profileRequests: () => profileRequests };
}

test("personal center presents only session account fields and real risk-profile fields", async ({ page }) => {
  await mockRiskProfile(page);
  await page.goto("/risk-profile");

  await expect(page.getByRole("heading", { name: "个人中心" })).toBeVisible();
  const account = page.getByRole("region", { name: "账户信息" });
  await expect(account.getByText("风险测试用户")).toBeVisible();
  await expect(account.getByText("risk-user@example.com")).toBeVisible();
  await expect(account.getByText("+86138****9000")).toBeVisible();
  await expect(page.getByRole("region", { name: "风险档案" }).getByText("当前风险等级：稳健型")).toBeVisible();
  await expect(page.getByText("风险档案只反映已确认的个人偏好。")).toBeVisible();
  await expect(page.locator("main")).toHaveCount(1);
});

test("anonymous visitor receives the access gate without any risk-profile request", async ({ page }) => {
  const mocked = await mockRiskProfile(page, false);
  await page.goto("/risk-profile");

  await expect(page.getByText(/业务内容已锁定/)).toBeVisible();
  await expect(page.getByRole("region", { name: "个人中心访问限制" })).toBeVisible();
  expect(mocked.profileRequests()).toBe(0);
});

test("personal center remains readable without mobile horizontal overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockRiskProfile(page);
  await page.goto("/risk-profile");

  await expect(page.getByRole("region", { name: "账户信息" })).toBeVisible();
  await expect(page.getByRole("region", { name: "风险档案" })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});
