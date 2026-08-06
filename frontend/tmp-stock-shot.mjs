import { chromium } from "playwright";
import { readFileSync } from "node:fs";

const cookieLine = readFileSync("C:/Users/dazhu/AppData/Local/Temp/qs_cookies.txt", "utf8")
  .split("\n")
  .find((line) => line.includes("qingshu_session"));
if (!cookieLine) throw new Error("qingshu_session cookie not found");
const value = cookieLine.trim().split("\t").pop();

const browser = await chromium.launch();
const context = await browser.newContext();
await context.addCookies([{ name: "qingshu_session", value, domain: "127.0.0.1", path: "/" }]);

async function capture(width, height, path) {
  const page = await context.newPage();
  await page.setViewportSize({ width, height });
  await page.goto("http://127.0.0.1:5173/stocks/000063", { waitUntil: "domcontentloaded" });
  await page.getByText("模块数据状态").waitFor({ timeout: 30_000 });
  await page.waitForTimeout(2500);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  await page.screenshot({ path, fullPage: true });
  console.log(`${path} viewport=${width}x${height} horizontalOverflow=${overflow}px`);
  await page.close();
  return overflow;
}

const desktop = await capture(1440, 900, "F:/tools/3.9haorzn-03/today-runtime-trace/screenshots/stock-research-desktop.png");
const mobile = await capture(390, 844, "F:/tools/3.9haorzn-03/today-runtime-trace/screenshots/stock-research-mobile.png");
await browser.close();
if (desktop > 1 || mobile > 1) {
  console.error("HORIZONTAL OVERFLOW DETECTED");
  process.exit(1);
}
console.log("OK: no horizontal overflow on either viewport");
