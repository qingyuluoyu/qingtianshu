import { expect, test } from "@playwright/test";
import {
  createScreenshotCredentials,
  ensureAuthenticatedScreenshotSession,
} from "../scripts/authenticated-screenshot-session.mjs";

test("screenshot preflight authenticates through the same frontend origin", async ({ page }) => {
  const frontend = new URL(test.info().project.use.baseURL as string).origin;
  await ensureAuthenticatedScreenshotSession(page.context(), {
    frontend,
    ...createScreenshotCredentials(),
  });

  await page.goto("/today");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  const status = await page.request.get("/session/status");
  expect(status.status()).toBe(200);
  expect((await status.json() as { authenticated?: unknown }).authenticated).toBe(true);
});

test("real FastAPI, PostgreSQL, cookie and Today read chain", async ({ page }) => {
  await page.goto("/today");
  await page.getByRole("button", { name: "登录 / 注册" }).click();
  await expect(page.getByRole("dialog", { name: "登录或注册" })).toBeVisible();

  await page.getByLabel("账号").fill("真实链路用户");
  await page.getByLabel("手机号").fill("13800138000");
  await page.getByLabel("密码").fill("Real-E2E-Password-2026");

  const registerResponse = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === "/auth/register" && response.request().method() === "POST";
  });
  const overviewResponse = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === "/v1/today/overview" && response.request().method() === "GET";
  });
  const breadthResponse = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === "/markets/breadth" && response.request().method() === "GET";
  });
  await page.getByRole("button", { name: "注册并进入" }).click();
  const registration = await registerResponse;
  expect(registration.status()).toBe(201);
  expect(registration.headers()["content-type"]).toContain("application/json");
  const registeredAccount = await registration.json() as { account?: unknown; auth_type?: unknown; is_registered?: unknown };
  expect(registeredAccount.account).toBe("真实链路用户");
  expect(registeredAccount.auth_type).toBe("account");
  expect(registeredAccount.is_registered).toBe(true);
  const registrationCookie = (await page.context().cookies()).find((cookie) => cookie.name === "qingshu_session");
  expect(registrationCookie?.httpOnly).toBe(true);
  expect(registrationCookie?.secure).toBe(false);
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByText("真实链路用户", { exact: true })).toBeVisible();

  const response = await overviewResponse;
  expect(response.status()).toBe(200);
  const packet = await response.json() as { generated_at?: unknown; summary?: { headline?: unknown; market_date?: unknown } };
  expect(typeof packet.generated_at).toBe("string");
  expect(typeof packet.summary?.headline).toBe("string");
  expect(packet.summary?.market_date === null || typeof packet.summary?.market_date === "string").toBe(true);

  const breadth = await breadthResponse;
  expect(breadth.status()).toBe(200);
  const breadthPacket = await breadth.json() as { turnover_history?: unknown };
  expect(Array.isArray(breadthPacket.turnover_history)).toBe(true);
  expect((breadthPacket.turnover_history as unknown[]).every((point) => {
    const item = point as { date?: unknown; amount_100m_cny?: unknown };
    return typeof item.date === "string" && typeof item.amount_100m_cny === "number";
  })).toBe(true);

  const marker = page.getByTestId("today-generated-at");
  await expect(marker).toHaveAttribute("data-generated-at", String(packet.generated_at));
  await expect(page.getByText(String(packet.summary?.headline), { exact: true })).toBeVisible();
  await expect(page.getByTestId("today-market-date")).toHaveText(
    typeof packet.summary?.market_date === "string" ? packet.summary.market_date : "市场日期读取中",
  );
  await expect(page.getByRole("region", { name: "主要指数" })).toBeVisible();
  await expect(page.getByRole("region", { name: "数据健康状态" })).toBeVisible();

  const sessionResponse = await page.request.get("/session");
  expect(sessionResponse.status()).toBe(200);
  const sessionStatusResponse = await page.request.get("/session/status");
  expect(sessionStatusResponse.status()).toBe(200);
  expect((await sessionStatusResponse.json() as { authenticated?: unknown }).authenticated).toBe(true);
  const session = await sessionResponse.json() as { account?: unknown; is_registered?: unknown };
  expect(session.account).toBe("真实链路用户");
  expect(session.is_registered).toBe(true);

  await page.reload();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByText("真实链路用户", { exact: true })).toBeVisible();
  await expect(page.getByTestId("today-generated-at")).toHaveAttribute("data-generated-at", /.+/);

  await page.getByRole("button", { name: "退出" }).click();
  await expect(page.getByRole("dialog", { name: "登录或注册" })).toBeVisible();

  await page.getByRole("dialog").getByRole("button", { name: "登录", exact: true }).click();
  await page.getByLabel("账号或手机号").fill("真实链路用户");
  await page.getByLabel("密码").fill("Real-E2E-Password-2026");
  const loginResponse = page.waitForResponse((candidate) => {
    const url = new URL(candidate.url());
    return url.pathname === "/auth/login" && candidate.request().method() === "POST";
  });
  await page.getByRole("button", { name: "登录", exact: true }).last().click();
  const login = await loginResponse;
  expect(login.status()).toBe(200);
  expect(login.headers()["content-type"]).toContain("application/json");
  const loggedInAccount = await login.json() as { account?: unknown; auth_type?: unknown; is_registered?: unknown };
  expect(loggedInAccount.account).toBe("真实链路用户");
  expect(loggedInAccount.auth_type).toBe("account");
  expect(loggedInAccount.is_registered).toBe(true);
  const loginCookie = (await page.context().cookies()).find((cookie) => cookie.name === "qingshu_session");
  expect(loginCookie?.httpOnly).toBe(true);
  expect(loginCookie?.secure).toBe(false);
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByText("真实链路用户", { exact: true })).toBeVisible();
  const restoredSession = await page.request.get("/session");
  expect(restoredSession.status()).toBe(200);
  expect((await restoredSession.json() as { account?: unknown }).account).toBe("真实链路用户");
});
