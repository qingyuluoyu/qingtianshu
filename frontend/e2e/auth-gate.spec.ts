import { expect, test } from "@playwright/test";

const sessionExpired = { code: "session_expired", message: "会话已失效" };
const accountSession = {
  id: "11111111-1111-1111-1111-111111111111",
  account: "frontend-user",
  name: "frontend-user",
  masked_phone: "+86138****8000",
  auth_type: "account",
  is_registered: true,
  created_at: "2026-08-04T00:00:00+00:00",
  session_expires_at: "2026-08-11T00:00:00+00:00",
};

test.beforeEach(async ({ page }) => {
  await page.route("**/session/status", (route) => route.fulfill({ status: 401, contentType: "application/json", body: JSON.stringify(sessionExpired) }));
});

for (const path of ["/today", "/screening", "/watchlist", "/stocks/000063.SZ", "/advisor", "/research-center"]) {
  test(`anonymous direct entry ${path} keeps URL and opens the auth dialog`, async ({ page }) => {
    await page.goto(path);
    await expect(page.getByRole("dialog", { name: "登录或注册" })).toBeVisible();
    await expect(page).toHaveURL(new RegExp(`${path.replace(".", "\\.")}$`));
  });
}

test("closing the first prompt keeps the page locked until explicit reopen or protected navigation", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/watchlist");
  const dialog = page.getByRole("dialog", { name: "登录或注册" });
  await expect(dialog).toBeFocused();
  await page.getByRole("button", { name: "关闭登录或注册弹窗" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByText("业务内容已锁定，请先登录或注册。")).toBeVisible();
  await expect(page.getByRole("button", { name: "登录 / 注册" })).toBeFocused();
  await page.waitForTimeout(100);
  await expect(dialog).toHaveCount(0);

  await page.getByRole("button", { name: "登录 / 注册" }).click();
  await expect(dialog).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);

  await page.setViewportSize({ width: 1280, height: 900 });
  await page.getByRole("link", { name: "透明选股" }).click();
  await expect(page).toHaveURL(/\/screening$/);
  await expect(dialog).toBeVisible();
});

test("registering keeps the current URL and does not persist a password", async ({ page }) => {
  await page.route("**/auth/register", (route) => route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify(accountSession), headers: { "set-cookie": "qingshu_session=opaque; HttpOnly; SameSite=Strict" } }));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/advisor");
  await page.getByLabel("账号").fill("frontend-user");
  await page.getByLabel("手机号").fill("13800138000");
  await page.getByLabel("密码").fill("NoPersist-Password-123");
  await page.getByRole("button", { name: "注册并进入" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "登录 / 注册" })).toHaveCount(0);
  await expect(page).toHaveURL(/\/advisor$/);
  await expect(page.getByRole("heading", { name: "金融顾问" })).toBeVisible();
  await expect(page.evaluate(() => `${localStorage.length}:${sessionStorage.length}`)).resolves.toBe("0:0");
  expect(await page.content()).not.toContain("NoPersist-Password-123");
});

for (const [kind, login] of [["an account", "frontend-user"], ["a phone number", "13800138000"]] as const) {
  test(`login submits ${kind} to the real auth endpoint`, async ({ page }) => {
    let submittedLogin = "";
    await page.route("**/auth/login", async (route) => {
      submittedLogin = String(route.request().postDataJSON()?.login);
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(accountSession) });
    });
    await page.goto("/watchlist");
    await page.getByRole("dialog").getByRole("button", { name: "登录", exact: true }).click();
    await page.getByLabel("账号或手机号").fill(login);
    await page.getByLabel("密码").fill("Login-Password-123");
    await page.getByRole("button", { name: "登录", exact: true }).last().click();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "登录 / 注册" })).toHaveCount(0);
    expect(submittedLogin).toBe(login);
  });
}

test("auth errors are rendered from stable backend codes", async ({ page }) => {
  await page.route("**/auth/login", (route) => route.fulfill({ status: 401, contentType: "application/json", body: JSON.stringify({ code: "invalid_credentials", message: "账号或密码错误" }) }));
  await page.goto("/today");
  await page.getByRole("dialog").getByRole("button", { name: "登录", exact: true }).click();
  await page.getByLabel("账号或手机号").fill("frontend-user");
  await page.getByLabel("密码").fill("wrong-password");
  await page.getByRole("button", { name: "登录", exact: true }).last().click();
  await expect(page.getByRole("alert")).toHaveText("账号或密码错误");
});

test("legacy session stays locked while a refreshed formal session restores access", async ({ page }) => {
  await page.route("**/session/status", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ authenticated: true, session: { ...accountSession, auth_type: "legacy_anonymous", is_registered: false, account: null, masked_phone: null } }) }));
  await page.goto("/research-center");
  await expect(page.getByRole("dialog")).toBeVisible();

  await page.unroute("**/session/status");
  await page.route("**/session/status", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ authenticated: true, session: accountSession }) }));
  await page.reload();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "研究中心" })).toBeVisible();
});

test("logout clears the authenticated view and reopens the dialog on the current URL", async ({ page }) => {
  await page.route("**/session/status", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ authenticated: true, session: accountSession }) }));
  await page.route("**/session", (route) => {
    if (route.request().method() === "DELETE") return route.fulfill({ status: 204 });
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(accountSession) });
  });
  await page.goto("/watchlist");
  await page.getByRole("button", { name: "退出" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page).toHaveURL(/\/watchlist$/);
});
