import { chromium } from "playwright";
import {
  createScreenshotCredentials,
  ensureAuthenticatedScreenshotSession,
} from "./scripts/authenticated-screenshot-session.mjs";

const FRONTEND = process.env.QINGSHU_SCREENSHOT_FRONTEND ?? "http://localhost:5173";

async function main() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  try {
    await ensureAuthenticatedScreenshotSession(context, {
      frontend: FRONTEND,
      ...createScreenshotCredentials(),
    });
    console.log("Authenticated screenshot session established through frontend origin.");

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

  } finally {
    await browser.close();
  }
}

main().catch(console.error);
