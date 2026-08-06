import { chromium } from "playwright";
import fs from "fs";

const BACKEND = "http://localhost:8000";
const FRONTEND = "http://localhost:5173";
const COOKIE_FILE = "C:/Users/dazhu/AppData/Local/Temp/qingshu_session.txt";

function extractCookie(filePath) {
  const content = fs.readFileSync(filePath, "utf8");
  const lines = content.split("\n").filter((l) => !l.startsWith("# ") && l.trim());
  for (const line of lines) {
    const parts = line.split("\t");
    if (parts.length >= 7 && parts[5] === "qingshu_session") {
      return parts[6];
    }
  }
  return "";
}

async function main() {
  const sessionCookie = extractCookie(COOKIE_FILE);
  console.log("Session cookie found:", !!sessionCookie, "length:", sessionCookie.length);

  // Launch browser
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();

  // Set cookie
  if (sessionCookie) {
    await context.addCookies([
      {
        name: "qingshu_session",
        value: sessionCookie,
        domain: "127.0.0.1",
        path: "/",
        sameSite: "Lax",
        secure: false,
      },
    ]);
    console.log("Cookie set in browser context");
  }

  // Desktop screenshot
  const page = await context.newPage();
  await page.setViewportSize({ width: 1440, height: 900 });

  console.log("Navigating to TodayPage...");
  await page.goto(`${FRONTEND}/today`);
  await page.waitForTimeout(5000);

  await page.screenshot({
    path: "C:/Users/dazhu/AppData/Local/Temp/screenshot-desktop.png",
    fullPage: true,
  });
  console.log("Desktop screenshot saved");

  // Mobile screenshot
  await page.setViewportSize({ width: 375, height: 812 });
  await page.reload();
  await page.waitForTimeout(5000);

  await page.screenshot({
    path: "C:/Users/dazhu/AppData/Local/Temp/screenshot-mobile.png",
    fullPage: true,
  });
  console.log("Mobile screenshot saved");

  await browser.close();
}

main().catch(console.error);
