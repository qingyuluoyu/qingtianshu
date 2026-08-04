import { expect, test } from "@playwright/test";

const account = process.env.QINGSHU_PRODUCTION_E2E_ACCOUNT ?? `visual-${Date.now().toString(36)}`;
const password = process.env.QINGSHU_PRODUCTION_E2E_PASSWORD ?? "Test123456!";
const phone = process.env.QINGSHU_PRODUCTION_E2E_PHONE ?? "13800138000";
const baseURL = process.env.QINGSHU_PRODUCTION_E2E_BASE_URL;

if (!account || !password || !phone || !baseURL) {
  throw new Error("Production E2E credentials and base URL are required");
}

test("Capture today UI evidence at multiple viewports", async ({ browser }) => {
  const context = await browser.newContext();
  const page = await context.newPage();

  // Navigate to /today (unauthenticated)
  await page.goto("/today");
  await page.waitForTimeout(500);

  // Screenshot 1: 1440×900 desktop - auth modal
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.screenshot({ path: "today-ui-readiness/current-desktop-1440-top.png", fullPage: false });

  // Register a new account
  await page.getByLabel("账号").fill(account);
  await page.getByLabel("手机号").fill(phone);
  await page.getByLabel("密码").fill(password);
  await page.getByRole("button", { name: "注册并进入" }).click();

  // Wait for registration and data load
  await page.waitForTimeout(5000);

  // Screenshot 2: 1440×900 desktop - authenticated full page
  await page.screenshot({ path: "today-ui-readiness/current-desktop-1440-full.png", fullPage: true });

  // Screenshot 3: 1920×1080 desktop - authenticated top
  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.waitForTimeout(500);
  await page.screenshot({ path: "today-ui-readiness/current-desktop-1920-top.png", fullPage: false });

  // Screenshot 4: 390×844 mobile - authenticated top
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(500);
  await page.screenshot({ path: "today-ui-readiness/current-mobile-390-top.png", fullPage: false });

  // Screenshot 5: 390×844 mobile - authenticated full page
  await page.screenshot({ path: "today-ui-readiness/current-mobile-390-full.png", fullPage: true });

  await context.close();
});
