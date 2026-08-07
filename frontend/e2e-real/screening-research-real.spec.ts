import { expect, test, type Page } from "@playwright/test";

type Profile = {
  key?: unknown;
  default_filters?: unknown;
};

type ScreenCandidate = {
  ts_code?: unknown;
  internal_symbol?: unknown;
  name?: unknown;
};

type ScreenResult = {
  profileKey: string;
  candidate: ScreenCandidate;
};

async function findRealCandidate(page: Page): Promise<ScreenResult> {
  const profilesResponse = await page.request.get("/stock-screener/profiles");
  expect(profilesResponse.status()).toBe(200);
  const profilesPayload = await profilesResponse.json() as { items?: Profile[] };
  const profiles = Array.isArray(profilesPayload.items) ? profilesPayload.items : [];
  const preferred = ["trend", "quality", "value", "pullback"];
  const priority = (profile: Profile) => {
    const index = preferred.indexOf(String(profile.key));
    return index === -1 ? preferred.length : index;
  };
  const ordered = [...profiles].sort((left, right) => priority(left) - priority(right));
  const attempts: string[] = [];
  for (const profile of ordered) {
    if (typeof profile.key !== "string") continue;
    const response = await page.request.post("/me/stock-screener", {
      data: {
        profile: profile.key,
        market: "all",
        max_results: 5,
        force_refresh: false,
        filters: typeof profile.default_filters === "object" && profile.default_filters !== null
          ? profile.default_filters
          : {},
      },
      timeout: 120_000,
    });
    attempts.push(`${profile.key}:${response.status()}`);
    if (response.status() !== 200) continue;
    const payload = await response.json() as { items?: ScreenCandidate[] };
    const candidate = Array.isArray(payload.items) ? payload.items[0] : undefined;
    if (candidate && (typeof candidate.internal_symbol === "string" || typeof candidate.ts_code === "string")) {
      return { profileKey: profile.key, candidate };
    }
  }
  throw new Error(`真实筛选未返回研究候选（${attempts.join(", ")}）`);
}

test("real screening candidate persists into stock research and continues to advisor", async ({ page }) => {
  test.setTimeout(240_000);
  const consoleErrors: string[] = [];
  const failedRequests: string[] = [];
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

  await page.goto("/screening");
  await expect(page.getByRole("dialog", { name: "登录或注册" })).toBeVisible();
  await page.getByLabel("账号").fill("真实研究链用户");
  await page.getByLabel("手机号").fill("13800138002");
  await page.getByLabel("密码").fill("Real-Research-Chain-Password-2026");
  await page.getByRole("button", { name: "注册并进入" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);

  const selected = await findRealCandidate(page);
  await page.goto(`/screening?profile=${encodeURIComponent(selected.profileKey)}`);
  const displayedSymbol = typeof selected.candidate.ts_code === "string"
    ? selected.candidate.ts_code
    : String(selected.candidate.internal_symbol);
  await expect(page.getByText(displayedSymbol).first()).toBeVisible({ timeout: 120_000 });

  const startRequest = page.waitForRequest((request) => (
    new URL(request.url()).pathname === "/me/deep-stock" && request.method() === "POST"
  ));
  const startResponse = page.waitForResponse((response) => (
    new URL(response.url()).pathname === "/me/deep-stock" && response.request().method() === "POST"
  ));
  await page.getByRole("button", { name: "保存线索并进入个股研究" }).click();
  const request = await startRequest;
  const response = await startResponse;
  expect(response.status()).toBe(201);
  const requestBody = request.postDataJSON() as {
    symbol?: unknown;
    entry_context?: Record<string, unknown>;
  };
  expect(requestBody.entry_context?.source_kind).toBe("stock_screen");
  expect(requestBody.entry_context?.profile_key).toBe(selected.profileKey);
  expect(Array.isArray(requestBody.entry_context?.matched_reasons)).toBe(true);
  expect(typeof requestBody.entry_context?.research_focus).toBe("string");

  const session = await response.json() as { symbol?: unknown; conversation_id?: unknown };
  expect(typeof session.symbol).toBe("string");
  expect(typeof session.conversation_id).toBe("string");
  const symbol = String(session.symbol);
  await expect(page).toHaveURL(new RegExp(`/stocks/${symbol.replace(".", "\\.")}`));

  const sessionResponse = await page.request.get(`/me/deep-stock/${encodeURIComponent(symbol)}`);
  expect(sessionResponse.status()).toBe(200);
  const persistedSession = await sessionResponse.json() as { research_entry?: Record<string, unknown> };
  expect(persistedSession.research_entry?.source_kind).toBe("stock_screen");
  expect(persistedSession.research_entry?.profile_key).toBe(selected.profileKey);
  expect(persistedSession.research_entry?.status).toBe("user_selected_context");

  await expect(page.getByText("本次研究入口")).toBeVisible({ timeout: 120_000 });
  await expect(page.getByText(String(requestBody.entry_context?.research_focus), { exact: true })).toBeVisible();
  await page.screenshot({ fullPage: true, path: test.info().outputPath("screening-to-stock-desktop.png") });

  await page.getByRole("link", { name: "问顾问" }).first().click();
  await expect(page.getByRole("heading", { name: "金融顾问", exact: true })).toBeVisible();
  const chatResponse = page.waitForResponse((chat) => (
    new URL(chat.url()).pathname === "/me/chat" && chat.request().method() === "POST"
  ));
  await page.getByLabel("向金融顾问提问").fill("先核验从选股页带来的研究重点，不要自动形成正式判断。");
  await page.getByRole("button", { name: "发送" }).click();
  const chat = await chatResponse;
  expect(chat.status()).toBe(200);
  const chatPayload = await chat.json() as { answer?: unknown; run_id?: unknown };
  expect(typeof chatPayload.answer).toBe("string");
  expect(typeof chatPayload.run_id).toBe("string");
  await expect(page.getByText(String(chatPayload.answer), { exact: true })).toBeVisible();

  const runResponse = await page.request.get(`/me/runs/${String(chatPayload.run_id)}`);
  expect(runResponse.status()).toBe(200);
  const run = await runResponse.json() as { input?: { entry_context?: Record<string, unknown> } };
  expect(run.input?.entry_context).toEqual({
    source_page: "stock",
    module: "stock-research",
    as_of: null,
    symbol,
  });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
  await expect(page.getByRole("heading", { name: "金融顾问", exact: true })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  await page.screenshot({ fullPage: true, path: test.info().outputPath("screening-to-advisor-mobile.png") });

  expect(consoleErrors).toEqual([]);
  expect(closedPrivateStreams).toBeLessThanOrEqual(1);
  expect(failedRequests).toEqual([]);
});
