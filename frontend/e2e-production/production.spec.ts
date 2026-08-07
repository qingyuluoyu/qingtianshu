import { expect, request as playwrightRequest, test } from "@playwright/test";

const account = process.env.QINGSHU_PRODUCTION_E2E_ACCOUNT;
const password = process.env.QINGSHU_PRODUCTION_E2E_PASSWORD;
const phone = process.env.QINGSHU_PRODUCTION_E2E_PHONE;
const baseURL = process.env.QINGSHU_PRODUCTION_E2E_BASE_URL;

if (!account || !password || !phone || !baseURL) {
  throw new Error("Docker production E2E credentials and base URL are required");
}

test("Docker production authentication, Today, routing, SSE and legacy chain", async ({ browser }) => {
  const context = await browser.newContext();
  const page = await context.newPage();
  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];
  const failedRequests: string[] = [];
  const missingAssets: string[] = [];
  const businessRequests: string[] = [];
  let eventsResponses = 0;

  page.on("console", (message) => {
    if (message.type() !== "error") return;
    const sourceUrl = message.location().url;
    const sourcePath = sourceUrl ? new URL(sourceUrl).pathname : "";
    if (sourcePath === "/session" && message.text().includes("401")) return;
    consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("requestfailed", (request) => {
    const path = new URL(request.url()).pathname;
    const reason = request.failure()?.errorText ?? "unknown";
    // React Router cancels in-flight feature requests when a user leaves a page.
    // That is lifecycle behaviour, not a failed network operation; real HTTP
    // failures and every non-abort transport failure remain test failures.
    if (!reason.includes("ERR_ABORTED")) failedRequests.push(`${request.method()} ${path}: ${reason}`);
  });
  page.on("request", (request) => {
    const path = new URL(request.url()).pathname;
    if (/^\/(?:v1|me|indices|markets|sectors|system)(?:\/|$)/.test(path)) {
      businessRequests.push(`${request.method()} ${path}`);
    }
  });
  page.on("response", (response) => {
    const path = new URL(response.url()).pathname;
    if (path === "/events") eventsResponses += 1;
    if (response.status() === 404 && /\.(?:js|css|png|svg|woff2?)$/i.test(path)) {
      missingAssets.push(path);
    }
  });

  const indexResponse = await page.goto("/today");
  expect(indexResponse?.status()).toBe(200);
  expect(indexResponse?.headers()["content-type"]).toContain("text/html");
  expect(indexResponse?.headers()["x-content-type-options"]).toBe("nosniff");
  expect(indexResponse?.headers()["referrer-policy"]).toBe("strict-origin-when-cross-origin");
  expect(await indexResponse?.text()).not.toContain("demo-boot.js");

  const dialog = page.getByRole("dialog", { name: "登录或注册" });
  await expect(dialog).toBeVisible();
  await page.getByRole("button", { name: "关闭登录或注册弹窗" }).click();
  await expect(dialog).toHaveCount(0);
  const authTrigger = page.getByRole("button", { name: "登录 / 注册" });
  await expect(authTrigger).toBeVisible();
  await page.waitForTimeout(300);
  expect(businessRequests).toEqual([]);
  await authTrigger.click();
  await expect(dialog).toBeVisible();

  await page.getByLabel("账号").fill(account);
  await page.getByLabel("手机号").fill(phone);
  await page.getByLabel("密码").fill(password);
  const registrationResponse = page.waitForResponse(
    (response) => new URL(response.url()).pathname === "/auth/register"
      && response.request().method() === "POST",
  );
  const firstEventsResponse = page.waitForResponse(
    (response) => new URL(response.url()).pathname === "/events",
  );
  await page.getByRole("button", { name: "注册并进入" }).click();

  const registration = await registrationResponse;
  expect(registration.status()).toBe(201);
  expect(registration.headers()["content-type"]).toContain("application/json");
  expect((await registration.json() as { account: string }).account).toBe(account);
  const registeredCookie = (await context.cookies()).find((cookie) => cookie.name === "qingshu_session");
  expect(registeredCookie?.httpOnly).toBe(true);
  expect(registeredCookie?.value).toBeTruthy();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByText(account, { exact: true })).toBeVisible();

  await expect.poll(() => businessRequests.includes("GET /v1/today/overview")).toBe(true);
  const overview = await context.request.get("/v1/today/overview");
  expect(overview.status()).toBe(200);
  expect(overview.headers()["content-type"]).toContain("application/json");
  const overviewBody = await overview.json() as {
    generated_at: string;
    summary: { market_date: string | null; headline: string };
  };
  await expect(page.getByTestId("today-generated-at")).toHaveAttribute(
    "data-generated-at",
    overviewBody.generated_at,
  );
  await expect(page.getByTestId("today-market-date")).toHaveText(
    overviewBody.summary.market_date ?? "数据日期待确认",
  );
  await expect(page.getByText(overviewBody.summary.headline, { exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "主要指数" })).toBeVisible();
  await expect(page.getByRole("region", { name: "数据健康状态" })).toBeVisible();

  const events = await firstEventsResponse;
  expect(events.status()).toBe(200);
  expect(events.headers()["content-type"]).toContain("text/event-stream");
  expect(eventsResponses).toBe(1);

  const reloadEventsResponse = page.waitForResponse(
    (response) => new URL(response.url()).pathname === "/events",
  );
  await page.reload();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByText(account, { exact: true })).toBeVisible();
  expect((await reloadEventsResponse).headers()["content-type"]).toContain("text/event-stream");
  expect(eventsResponses).toBe(2);

  const secondPage = await context.newPage();
  await secondPage.goto("/today");
  await expect(secondPage.getByRole("dialog")).toHaveCount(0);
  await expect(secondPage.getByText(account, { exact: true })).toBeVisible();
  await secondPage.close();

  const stockPage = await page.goto("/stocks/600519.SS");
  expect(stockPage?.status()).toBe(200);
  expect(stockPage?.headers()["content-type"]).toContain("text/html");
  await expect(page.getByRole("heading", { name: "个股研究" })).toBeVisible();

  for (const endpoint of ["/stocks/600519.SS/history", "/stocks/600519.SS/intraday"]) {
    const response = await context.request.get(endpoint, {
      headers: { accept: "application/json" },
      timeout: 60_000,
    });
    expect(response.headers()["content-type"], endpoint).toContain("application/json");
    expect([200, 404, 422, 502, 503, 504], endpoint).toContain(response.status());
    expect(response.status(), endpoint).not.toBe(500);
  }

  const legacy = await context.request.get("/legacy");
  expect(legacy.status()).toBe(200);
  expect(legacy.headers()["content-type"]).toContain("text/html");
  expect(await legacy.text()).toContain("demo-boot.js");
  const demo = await context.request.get("/demo", { maxRedirects: 0 });
  expect([302, 307]).toContain(demo.status());
  expect(demo.headers().location).toBe("/legacy");

  const unknownApi = await context.request.get("/api-future/missing", {
    headers: { accept: "text/html" },
  });
  expect(unknownApi.status()).toBe(404);
  expect(unknownApi.headers()["content-type"]).toContain("application/json");
  const missingScript = await context.request.get("/missing-production.js", {
    headers: { accept: "text/html" },
  });
  expect(missingScript.status()).toBe(404);
  expect(missingScript.headers()["content-type"]).toContain("application/json");

  const oldCookieHeader = `qingshu_session=${registeredCookie?.value}`;
  const logoutResponse = page.waitForResponse(
    (response) => new URL(response.url()).pathname === "/session"
      && response.request().method() === "DELETE",
  );
  await page.getByRole("button", { name: "退出" }).click();
  expect((await logoutResponse).status()).toBe(204);
  await expect(page.getByRole("dialog", { name: "登录或注册" })).toBeVisible();
  expect((await context.request.get("/session")).status()).toBe(401);

  const oldSessionClient = await playwrightRequest.newContext({
    baseURL,
    extraHTTPHeaders: { cookie: oldCookieHeader },
  });
  expect((await oldSessionClient.get("/session")).status()).toBe(401);
  await oldSessionClient.dispose();

  await page.getByRole("dialog").getByRole("button", { name: "登录", exact: true }).click();
  await page.getByLabel("账号或手机号").fill(account);
  await page.getByLabel("密码").fill(password);
  const loginResponse = page.waitForResponse(
    (response) => new URL(response.url()).pathname === "/auth/login"
      && response.request().method() === "POST",
  );
  const secondEventsResponse = page.waitForResponse(
    (response) => new URL(response.url()).pathname === "/events",
  );
  const eventsBeforeLogin = eventsResponses;
  await page.getByRole("button", { name: "登录", exact: true }).last().click();
  expect((await loginResponse).status()).toBe(200);
  expect((await secondEventsResponse).headers()["content-type"]).toContain("text/event-stream");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByText(account, { exact: true })).toBeVisible();
  expect(eventsResponses).toBe(eventsBeforeLogin + 1);

  await page.getByRole("button", { name: "退出" }).click();
  await expect(page.getByRole("dialog", { name: "登录或注册" })).toBeVisible();
  expect((await context.request.get("/session")).status()).toBe(401);

  const assetUrls = await page.evaluate(() => performance.getEntriesByType("resource")
    .map((entry) => entry.name)
    .filter((url) => /\.(?:js|css)(?:\?|$)/.test(url)));
  expect(assetUrls.length).toBeGreaterThan(0);
  for (const url of assetUrls) {
    const response = await context.request.get(url);
    expect(response.status(), url).toBe(200);
    expect(response.headers()["x-content-type-options"], url).toBe("nosniff");
  }

  expect(consoleErrors).toEqual([]);
  expect(pageErrors).toEqual([]);
  expect(failedRequests).toEqual([]);
  expect(missingAssets).toEqual([]);
  await context.close();
});
