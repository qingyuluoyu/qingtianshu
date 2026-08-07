import { expect, test } from "@playwright/test";

const researchPaths = [
  "/me/research-priority",
  "/me/research-changes",
  "/me/research-actions",
  "/me/evidence-tasks",
  "/me/research-outcomes",
  "/me/run-reviews",
] as const;

test("real account research center restores persisted priority and keeps preview runs out of formal review", async ({ page }) => {
  test.setTimeout(180_000);
  const consoleErrors: string[] = [];
  const failedRequests: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("requestfailed", (request) => {
    const failure = request.failure()?.errorText ?? "failed";
    const path = new URL(request.url()).pathname;
    if (path === "/events" && failure === "net::ERR_ABORTED") return;
    failedRequests.push(`${request.method()} ${request.url()} ${failure}`);
  });

  await page.goto("/research-center");
  await expect(page.getByRole("dialog", { name: "登录或注册" })).toBeVisible();
  await page.getByLabel("账号").fill("真实研究中心用户");
  await page.getByLabel("手机号").fill("13800138003");
  await page.getByLabel("密码").fill("Real-Research-Center-Password-2026");
  await page.getByRole("button", { name: "注册并进入" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByText("还没有需要排序的关注标的")).toBeVisible();

  const watchlistResponse = await page.request.post("/me/watchlist", {
    data: {
      symbol: "000063.SZ",
      name: "中兴通讯",
      market: "A股",
      thesis: "核验利润改善是否得到经营现金流和正式披露支持",
    },
  });
  expect(watchlistResponse.status()).toBe(200);
  expect((await watchlistResponse.json() as { symbol?: unknown }).symbol).toBe("000063.SZ");

  const previewResponse = await page.request.post("/me/chat", {
    data: {
      message: "我的研究行动是什么？只整理核验顺序，不要自动形成正式判断。",
      execute_agent: false,
    },
    timeout: 120_000,
  });
  expect(previewResponse.status()).toBe(200);
  expect((await previewResponse.json() as { status?: unknown }).status).toBe("preview");

  const [priorityResponse, changesResponse, actionsResponse, tasksResponse, outcomesResponse, reviewsResponse] = await Promise.all(
    researchPaths.map((path) => page.request.get(path)),
  );
  for (const response of [priorityResponse, changesResponse, actionsResponse, tasksResponse, outcomesResponse, reviewsResponse]) {
    expect(response.status()).toBe(200);
    expect(response.headers()["content-type"]).toContain("application/json");
  }

  const priority = await priorityResponse.json() as {
    coverage?: { requested?: unknown; missing_baseline?: unknown };
    items?: Array<{ symbol?: unknown; priority_label?: unknown }>;
  };
  expect(priority.coverage?.requested).toBe(1);
  expect(priority.coverage?.missing_baseline).toBe(1);
  expect(priority.items?.[0]).toMatchObject({ symbol: "000063.SZ", priority_label: "优先建立基线" });

  const actions = await actionsResponse.json() as {
    summary?: { triggered?: unknown; priority_research?: unknown };
    items?: Array<{ actions?: Array<{ title?: unknown; status?: unknown }> }>;
  };
  expect(actions.summary?.triggered).toBe(1);
  expect(actions.summary?.priority_research).toBe(1);
  expect(actions.items?.[0]?.actions?.[0]).toMatchObject({ title: "建立首份长期研究基线", status: "triggered" });

  expect((await changesResponse.json() as { events?: unknown[] }).events).toEqual([]);
  expect((await tasksResponse.json() as { items?: unknown[] }).items).toEqual([]);
  const outcomes = await outcomesResponse.json() as {
    items?: Array<{
      symbol?: unknown;
      latest_available?: unknown[];
      latest_progress?: unknown;
      coverage?: { anchors?: unknown };
    }>;
  };
  expect(outcomes.items?.[0]).toMatchObject({
    symbol: "000063.SZ",
    latest_available: [],
    latest_progress: null,
    coverage: { anchors: 0 },
  });
  expect((await reviewsResponse.json() as { summary?: { total?: unknown } }).summary?.total).toBe(0);

  const refreshedResponses = Promise.all(researchPaths.map((path) => page.waitForResponse((response) => (
    new URL(response.url()).pathname === path && response.request().method() === "GET"
  ))));
  await page.getByRole("button", { name: "刷新研究状态" }).click();
  expect((await refreshedResponses).every((response) => response.status() === 200)).toBe(true);

  await expect(page.getByText("优先建立基线").first()).toBeVisible();
  await expect(page.getByText("建立首份长期研究基线")).toBeVisible();
  await expect(page.getByText("已触发", { exact: true })).toBeVisible();
  await expect(page.getByText("暂无可追溯变化")).toBeVisible();
  await expect(page.getByText("暂无补证任务")).toBeVisible();
  await expect(page.getByText("暂无研究结果")).toBeVisible();
  await expect(page.getByText("近 30 日暂无正式 Run")).toBeVisible();
  await expect(page.getByRole("link", { name: "查看个股研究" }).first()).toHaveAttribute("href", "/stocks/000063.SZ");
  await page.screenshot({ fullPage: true, path: test.info().outputPath("research-center-desktop.png") });

  await page.reload();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByText("建立首份长期研究基线")).toBeVisible();
  await expect(page.getByText("近 30 日暂无正式 Run")).toBeVisible();

  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
  await expect(page.getByRole("heading", { name: "研究中心", exact: true })).toBeVisible();
  await expect(page.getByText("建立首份长期研究基线")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);
  await page.screenshot({ fullPage: true, path: test.info().outputPath("research-center-mobile.png") });

  expect(consoleErrors).toEqual([]);
  expect(failedRequests).toEqual([]);
});
