import { expect, test } from "@playwright/test";
import { writeFile } from "node:fs/promises";

const account = process.env.QINGSHU_PRODUCTION_E2E_ACCOUNT ?? "";
const password = process.env.QINGSHU_PRODUCTION_E2E_PASSWORD ?? "";
const phone = process.env.QINGSHU_PRODUCTION_E2E_PHONE ?? "";
const hermesEnabled = process.env.QINGSHU_PRODUCTION_E2E_HERMES === "true";
const expectedModel = process.env.HERMES_ECONOMY_MODEL ?? "";

test.skip(!hermesEnabled, "Explicit --hermes mode is required for a paid model acceptance run.");

if (hermesEnabled && (!account || !password || !phone || !expectedModel)) {
  throw new Error("Hermes production E2E credentials and model route are required");
}

test("production React delivers one fresh evidence-bounded Hermes answer", async ({ page }, testInfo) => {
  test.setTimeout(300_000);
  const consoleErrors: string[] = [];
  const failedRequests: string[] = [];
  let privateStreamRequests = 0;
  let closedPrivateStreams = 0;

  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("request", (request) => {
    if (new URL(request.url()).pathname.startsWith("/me/chat/stream/")) {
      privateStreamRequests += 1;
    }
  });
  page.on("requestfailed", (request) => {
    const path = new URL(request.url()).pathname;
    const reason = request.failure()?.errorText ?? "failed";
    if (path.startsWith("/me/chat/stream/") && reason.includes("ERR_ABORTED")) {
      closedPrivateStreams += 1;
      return;
    }
    failedRequests.push(`${request.method()} ${path}: ${reason}`);
  });

  await page.goto("/advisor?symbol=000063.SZ&source=stock-research");
  await expect(page.getByRole("dialog", { name: "登录或注册" })).toBeVisible();
  await page.getByLabel("账号").fill(account);
  await page.getByLabel("手机号").fill(phone);
  await page.getByLabel("密码").fill(password);
  await page.getByRole("button", { name: "注册并进入" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);

  const conversationResponse = await page.request.post("/me/conversations", {
    data: { title: "真实模型隔离验收", quality_scope: "evaluation" },
  });
  expect(conversationResponse.status()).toBe(201);
  const conversation = await conversationResponse.json() as { id?: unknown };
  expect(typeof conversation.id).toBe("string");
  await page.goto(`/advisor/${String(conversation.id)}?symbol=000063.SZ&source=stock-research`);

  const streamResponse = page.waitForResponse((response) => (
    new URL(response.url()).pathname.startsWith("/me/chat/stream/")
    && response.request().method() === "GET"
  ));
  const chatResponse = page.waitForResponse((response) => (
    new URL(response.url()).pathname === "/me/chat"
    && response.request().method() === "POST"
  ));
  await page.getByLabel("向金融顾问提问").fill(
    "请直接分析中兴通讯当前最需要优先核验的两项经营风险。说明证据时间和缺口，不要自动修改正式判断。",
  );
  await page.getByRole("button", { name: "发送" }).click();

  const stream = await streamResponse;
  expect(stream.status()).toBe(200);
  expect(stream.headers()["content-type"]).toContain("text/event-stream");
  const chat = await chatResponse;
  expect(chat.status()).toBe(200);
  const payload = await chat.json() as {
    answer?: unknown;
    conversation_id?: unknown;
    run_id?: unknown;
    status?: unknown;
  };
  expect(payload.status).toBe("completed");
  expect(payload.conversation_id).toBe(conversation.id);
  expect(typeof payload.run_id).toBe("string");
  expect(typeof payload.answer).toBe("string");
  const answer = String(payload.answer);
  expect(answer.length).toBeGreaterThanOrEqual(180);
  expect(answer).toContain("中兴通讯");
  expect(answer).not.toMatch(/失效条件|output_guard|Hermes|守卫/);
  await expect(page.getByText(answer, { exact: true })).toBeVisible();

  const runResponse = await page.request.get(`/me/runs/${String(payload.run_id)}`);
  expect(runResponse.status()).toBe(200);
  const run = await runResponse.json() as {
    evidence?: unknown;
    status?: unknown;
    usage?: unknown;
  };
  expect(run.status).toBe("completed");
  expect(JSON.stringify(run.usage)).toContain(expectedModel);
  const evidence = run.evidence as {
    evidence_status?: unknown;
    module_statuses?: { fundamentals?: { status?: unknown } };
    fundamentals?: {
      summary?: {
        latest_report?: {
          report_date?: unknown;
          net_profit_yoy_pct?: unknown;
          operating_cashflow?: unknown;
        };
      };
    };
  };
  const latestReport = evidence.fundamentals?.summary?.latest_report;
  expect(evidence.module_statuses?.fundamentals?.status).toBe("fresh");
  expect(typeof latestReport?.report_date).toBe("string");
  expect(typeof latestReport?.net_profit_yoy_pct).toBe("number");
  expect(typeof latestReport?.operating_cashflow).toBe("number");
  expect(answer).toContain(String(latestReport?.report_date).slice(0, 4));
  expect(answer).not.toMatch(
    /实时行情、公司公告、最新财务和事件证据都没有成功取得|无法基于本轮证据确认|结构化财务报告期不可用/,
  );
  const evidenceSentences = answer
    .split(/[。！？\n]/)
    .filter((sentence) => (
      /营收|净利润|毛利率|净利率|经营现金流|资产负债率/.test(sentence)
      && /-?\d+(?:\.\d+)?(?:%|亿|万|元)?/.test(sentence)
    ));
  expect(evidenceSentences.length).toBeGreaterThanOrEqual(2);

  await writeFile(
    testInfo.outputPath("advisor-hermes-acceptance.json"),
    JSON.stringify({
      question: "请直接分析中兴通讯当前最需要优先核验的两项经营风险。说明证据时间和缺口，不要自动修改正式判断。",
      answer,
      conversation_id: payload.conversation_id,
      run_id: payload.run_id,
      status: payload.status,
      expected_model: expectedModel,
      evidence_type: (run.evidence as { type?: unknown } | undefined)?.type,
      evidence_status: evidence.evidence_status,
      fundamentals_status: evidence.module_statuses?.fundamentals?.status,
      latest_report: latestReport,
      usage: run.usage,
    }, null, 2),
    "utf-8",
  );

  await page.screenshot({
    fullPage: true,
    path: testInfo.outputPath("advisor-hermes-desktop.png"),
  });

  await page.reload();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByText(answer, { exact: true })).toBeVisible();

  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
  await expect(page.getByText(answer, { exact: true })).toBeVisible();
  await page.screenshot({
    fullPage: true,
    path: testInfo.outputPath("advisor-hermes-mobile.png"),
  });
  const mobileLayout = await page.evaluate(() => ({
    overflow: document.documentElement.scrollWidth - window.innerWidth,
    offenders: [...document.querySelectorAll<HTMLElement>("body *")]
      .filter((element) => element.getBoundingClientRect().right > window.innerWidth + 1)
      .slice(0, 8)
      .map((element) => ({
        className: element.className,
        right: Math.round(element.getBoundingClientRect().right),
        tagName: element.tagName,
        text: element.innerText.slice(0, 80),
      })),
  }));
  expect(mobileLayout.overflow, JSON.stringify(mobileLayout.offenders)).toBeLessThanOrEqual(1);

  expect(privateStreamRequests).toBe(1);
  expect(closedPrivateStreams).toBeLessThanOrEqual(1);
  expect(consoleErrors).toEqual([]);
  expect(failedRequests).toEqual([]);
});
