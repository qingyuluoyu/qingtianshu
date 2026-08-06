import { test, expect, type Page, type BrowserContext } from "@playwright/test";
import fs from "fs";

const BACKEND = "http://localhost:8000";
const FRONTEND = "http://localhost:5173";

async function getSessionCookie(): Promise<string> {
  // Register a test user (or use existing)
  const registerResp = await fetch(`${BACKEND}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      account: "screenshot-user",
      phone: "13800138003",
      password: "Password-123",
    }),
  });
  const data = await registerResp.json();
  console.log("Register response code:", registerResp.status);

  // The session cookie is set by the server
  // We need to extract it from the response
  const setCookieHeader = registerResp.headers.get("set-cookie");
  console.log("Has Set-Cookie header:", !!setCookieHeader);

  // Try to use curl to get the cookie and save it to a file
  const { execSync } = require("child_process");
  try {
    execSync(
      `curl -s -c C:/Users/dazhu/AppData/Local/Temp/screenshot_cookies.txt -b C:/Users/dazhu/AppData/Local/Temp/screenshot_cookies.txt -X POST ${BACKEND}/auth/register -H "Content-Type: application/json" -d '{"account":"screenshot-user","phone":"13800138003","password":"Password-123"}'`
    );
    const cookieFile = fs.readFileSync("C:/Users/dazhu/AppData/Local/Temp/screenshot_cookies.txt", "utf8");
    const match = cookieFile.match(/qingshu_session\t([^\t]+)/);
    if (match) {
      return match[1];
    }
  } catch (e) {
    console.log("curl approach failed:", e);
  }

  return "";
}

test.describe("TodayPage screenshots and HAR capture", () => {
  let context: BrowserContext;
  let sessionCookie: string;

  test.beforeAll(async () => {
    // Get session cookie
    sessionCookie = await getSessionCookie();
    console.log("Session cookie:", sessionCookie);
  });

  test.beforeEach(async ({ browser }) => {
    context = await browser.newContext();
  });

  test.afterEach(async () => {
    await context.close();
  });

  test("desktop screenshot of TodayPage", async ({ page }) => {
    // Set the session cookie
    if (sessionCookie) {
      await context.addCookies([
        {
          name: "qingshu_session",
          value: sessionCookie,
          domain: "localhost",
          path: "/",
          httpOnly: true,
          sameSite: "Lax",
        },
      ]);
    }

    // Enable HAR capture
    await context.route("**/*", (route) => {
      route.continue();
    });

    // Navigate to TodayPage
    await page.goto(`${FRONTEND}/today`);

    // Wait for the page to load
    await page.waitForTimeout(5000);

    // Take desktop screenshot
    await page.screenshot({
      path: "C:/Users/dazhu/AppData/Local/Temp/screenshot-desktop.png",
      fullPage: true,
    });

    console.log("Desktop screenshot saved");
  });

  test("mobile screenshot of TodayPage", async ({ page }) => {
    // Set mobile viewport
    await page.setViewportSize({ width: 375, height: 812 });

    // Set the session cookie
    if (sessionCookie) {
      await context.addCookies([
        {
          name: "qingshu_session",
          value: sessionCookie,
          domain: "localhost",
          path: "/",
          httpOnly: true,
          sameSite: "Lax",
        },
      ]);
    }

    // Navigate to TodayPage
    await page.goto(`${FRONTEND}/today`);

    // Wait for the page to load
    await page.waitForTimeout(5000);

    // Take mobile screenshot
    await page.screenshot({
      path: "C:/Users/dazhu/AppData/Local/Temp/screenshot-mobile.png",
      fullPage: true,
    });

    console.log("Mobile screenshot saved");
  });
});
