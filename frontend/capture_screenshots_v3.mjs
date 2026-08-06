import { chromium } from "playwright";
import fs from "fs";

const FRONTEND = "http://localhost:5173";

async function main() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();

  // Read cookie from file
  const cookieContent = fs.readFileSync("C:/Users/dazhu/AppData/Local/Temp/qingshu_session.txt", "utf8");
  const lines = cookieContent.split("\n").filter((l) => !l.startsWith("# ") && l.trim());
  let sessionCookie = "";
  for (const line of lines) {
    const parts = line.split("\t");
    if (parts.length >= 7 && parts[5] === "qingshu_session") {
      sessionCookie = parts[6];
      break;
    }
  }

  console.log("Session cookie found:", !!sessionCookie, "length:", sessionCookie.length);

  // Set cookie via JavaScript before navigating
  await context.addInitScript(
    (cookie) => {
      document.cookie = `qingshu_session=${cookie}; path=/; domain=localhost`;
    },
    sessionCookie
  );

  // Desktop screenshot
  const page = await context.newPage();
  await page.setViewportSize({ width: 1440, height: 900 });

  console.log("Navigating to TodayPage (desktop)...");
  await page.goto(`${FRONTEND}/today`);
  await page.waitForTimeout(5000);

  await page.screenshot({
    path: "C:/Users/dazhu/AppData/Local/Temp/screenshot-desktop.png",
    fullPage: true,
  });
  console.log("Desktop screenshot saved");

  // Mobile screenshot
  const page2 = await context.newPage();
  await page2.setViewportSize({ width: 375, height: 812 });

  console.log("Navigating to TodayPage (mobile)...");
  await page2.goto(`${FRONTEND}/today`);
  await page2.waitForTimeout(5000);

  await page2.screenshot({
    path: "C:/Users/dazhu/AppData/Local/Temp/screenshot-mobile.png",
    fullPage: true,
  });
  console.log("Mobile screenshot saved");

  // Also capture a screenshot of the network requests (HAR-like)
  console.log("Page title:", await page.title());
  console.log("Page URL:", page.url());

  await browser.close();
}

main().catch(console.error);
