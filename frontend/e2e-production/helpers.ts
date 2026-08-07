import { expect, type APIRequestContext, type BrowserContext, type Page } from "@playwright/test";

export type FormalTestUser = {
  account: string;
  password: string;
  phone: string;
};

export type BrowserRuntimeEvidence = {
  apiResponses: string[];
  consoleErrors: string[];
  missingAssets: string[];
  pageErrors: string[];
  requestFailures: string[];
  sseResponses: number;
};

export function productionIdentity(): Record<string, string> {
  const baseURL = requireEnvironment("QINGSHU_PRODUCTION_E2E_BASE_URL");
  return {
    baseURL,
    image: requireEnvironment("QINGSHU_PRODUCTION_E2E_IMAGE"),
    mode: requireEnvironment("QINGSHU_PRODUCTION_E2E_MODE"),
    runId: requireEnvironment("QINGSHU_PRODUCTION_E2E_RUN_ID"),
  };
}

export function requireEnvironment(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required for Docker production E2E`);
  return value;
}

export function createUser(runId: string, suffix: string): FormalTestUser {
  const normalizedSuffix = suffix.replace(/[^a-z0-9]/gi, "").slice(0, 8).toLowerCase();
  const digits = (runId.replace(/\D/g, "") + "00000000").slice(0, 8);
  return {
    account: `e2e-${normalizedSuffix}-${runId.slice(0, 6)}`.slice(0, 32),
    password: `E2e-Real-${runId}-${normalizedSuffix}-A9`,
    phone: `139${digits}`.slice(0, 11),
  };
}

export async function registerUser(context: BrowserContext, user: FormalTestUser): Promise<void> {
  const response = await context.request.post("/auth/register", {
    data: { account: user.account, phone: user.phone, password: user.password },
  });
  expect(response.status()).toBe(201);
  expect(response.headers()["content-type"]).toContain("application/json");
  expect((await response.json() as { account?: string }).account).toBe(user.account);
  const cookie = (await context.cookies()).find((item) => item.name === "qingshu_session");
  expect(cookie?.httpOnly).toBe(true);
  expect(cookie?.value).toBeTruthy();
}

export function collectBrowserRuntimeEvidence(page: Page): BrowserRuntimeEvidence {
  const evidence: BrowserRuntimeEvidence = {
    apiResponses: [],
    consoleErrors: [],
    missingAssets: [],
    pageErrors: [],
    requestFailures: [],
    sseResponses: 0,
  };
  page.on("console", (message) => {
    if (message.type() !== "error") return;
    const path = message.location().url ? new URL(message.location().url).pathname : "";
    if (path === "/session" && message.text().includes("401")) return;
    evidence.consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => evidence.pageErrors.push(error.message));
  page.on("requestfailed", (request) => {
    const path = new URL(request.url()).pathname;
    const reason = request.failure()?.errorText ?? "unknown";
    if (!reason.includes("ERR_ABORTED")) {
      evidence.requestFailures.push(`${request.method()} ${path}: ${reason}`);
    }
  });
  page.on("response", (response) => {
    const path = new URL(response.url()).pathname;
    if (path === "/events") evidence.sseResponses += 1;
    if (/^\/(?:v1|me|auth|session|stocks|research-reports|markets|indices|sectors|system)(?:\/|$)/.test(path)) {
      evidence.apiResponses.push(`${response.request().method()} ${path} ${response.status()}`);
    }
    if (response.status() === 404 && /\.(?:js|css|png|svg|woff2?)$/i.test(path)) {
      evidence.missingAssets.push(path);
    }
  });
  return evidence;
}

export async function expectJsonOrExpectedProviderFailure(
  request: APIRequestContext,
  path: string,
): Promise<number> {
  const response = await request.get(path, { headers: { accept: "application/json" }, timeout: 60_000 });
  expect(response.headers()["content-type"]).toContain("application/json");
  expect([200, 404, 422, 502, 503, 504]).toContain(response.status());
  expect(response.status()).not.toBe(500);
  return response.status();
}
