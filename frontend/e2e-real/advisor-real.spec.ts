import { expect, test } from "@playwright/test";

test("real advisor account, private SSE, persisted entry context and refresh recovery", async ({ page }) => {
  const consoleErrors: string[] = [];
  const failedRequests: string[] = [];
  let privateStreamRequests = 0;
  let closedPrivateStreams = 0;
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("requestfailed", (request) => {
    const errorText = request.failure()?.errorText ?? "failed";
    const path = new URL(request.url()).pathname;
    if (path.startsWith("/me/chat/stream/") && errorText === "net::ERR_ABORTED") {
      closedPrivateStreams += 1;
      return;
    }
    failedRequests.push(`${request.method()} ${request.url()} ${errorText}`);
  });
  page.on("request", (request) => {
    if (new URL(request.url()).pathname.startsWith("/me/chat/stream/")) privateStreamRequests += 1;
  });

  await page.goto("/advisor?symbol=000063.SZ&source=stock-research");
  await expect(page.getByRole("dialog", { name: "登录或注册" })).toBeVisible();
  await page.getByLabel("账号").fill("真实顾问用户");
  await page.getByLabel("手机号").fill("13800138001");
  await page.getByLabel("密码").fill("Real-Advisor-Password-2026");
  await page.getByRole("button", { name: "注册并进入" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByText("真实顾问用户", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "金融顾问", exact: true })).toBeVisible();
  await expect(page.getByText("发送后记录来源")).toBeVisible();

  const streamRequest = page.waitForRequest((request) => {
    const url = new URL(request.url());
    return url.pathname.startsWith("/me/chat/stream/") && request.method() === "GET";
  });
  const chatRequest = page.waitForRequest((request) => {
    const url = new URL(request.url());
    return url.pathname === "/me/chat" && request.method() === "POST";
  });
  const chatResponse = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === "/me/chat" && response.request().method() === "POST";
  });

  await page.getByLabel("向金融顾问提问").fill("分析中兴通讯当前最需要优先核验的风险，不要自动修改正式判断。 ");
  await page.getByRole("button", { name: "发送" }).click();
  const stream = await streamRequest;
  const chat = await chatRequest;
  const requestPayload = chat.postDataJSON() as {
    request_id?: unknown;
    conversation_id?: unknown;
    symbol?: unknown;
    entry_context?: Record<string, unknown>;
  };
  expect(stream.url()).toContain(`/me/chat/stream/${String(requestPayload.request_id)}`);
  expect(requestPayload.symbol).toBe("000063.SZ");
  expect(requestPayload.entry_context).toEqual({
    source_page: "stock",
    module: "stock-research",
    symbol: "000063.SZ",
  });

  const response = await chatResponse;
  expect(response.status()).toBe(200);
  expect(response.headers()["content-type"]).toContain("application/json");
  const payload = await response.json() as {
    answer?: unknown;
    run_id?: unknown;
    conversation_id?: unknown;
    status?: unknown;
  };
  expect(typeof payload.answer).toBe("string");
  expect(typeof payload.run_id).toBe("string");
  expect(typeof payload.conversation_id).toBe("string");
  expect(["completed", "preview", "degraded"]).toContain(payload.status);
  expect(privateStreamRequests).toBe(1);

  await expect(page.getByText(String(payload.answer), { exact: true })).toBeVisible();
  await expect(page.getByText("来源已记录")).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`/advisor/${String(payload.conversation_id)}`));

  const runResponse = await page.request.get(`/me/runs/${String(payload.run_id)}`);
  expect(runResponse.status()).toBe(200);
  const run = await runResponse.json() as { input?: { entry_context?: unknown } };
  expect(run.input?.entry_context).toEqual({
    source_page: "stock",
    module: "stock-research",
    as_of: null,
    symbol: "000063.SZ",
  });

  await page.screenshot({ fullPage: true, path: test.info().outputPath("advisor-desktop.png") });
  await page.reload();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByText(String(payload.answer), { exact: true })).toBeVisible();
  await expect(page.getByText("来源已记录")).toBeVisible();

  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
  await expect(page.getByRole("heading", { name: "金融顾问", exact: true })).toBeVisible();
  const rootOverflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(rootOverflow).toBeLessThanOrEqual(0);
  await page.screenshot({ fullPage: true, path: test.info().outputPath("advisor-mobile.png") });

  expect(consoleErrors).toEqual([]);
  expect(closedPrivateStreams).toBeLessThanOrEqual(1);
  expect(failedRequests).toEqual([]);
});
