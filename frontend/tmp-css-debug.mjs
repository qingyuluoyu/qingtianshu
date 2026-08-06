import { chromium } from "playwright";
import { readFileSync } from "node:fs";
const cookieLine = readFileSync("C:/Users/dazhu/AppData/Local/Temp/qs_cookies.txt", "utf8").split("\n").find((l) => l.includes("qingshu_session"));
const value = cookieLine.trim().split("\t").pop();
const browser = await chromium.launch();
const context = await browser.newContext();
await context.addCookies([{ name: "qingshu_session", value, domain: "127.0.0.1", path: "/" }]);
const page = await context.newPage();
await page.setViewportSize({ width: 1440, height: 900 });
await page.goto("http://127.0.0.1:5173/stocks/000063", { waitUntil: "domcontentloaded" });
await page.getByText("模块数据状态").waitFor({ timeout: 30_000 });
const info = await page.evaluate(() => {
  const nav = document.querySelector("nav[aria-label='个股研究标签']");
  const root = nav.parentElement;
  const matches = [];
  for (const sheet of document.styleSheets) {
    let rules;
    try { rules = sheet.cssRules; } catch { continue; }
    const walk = (list) => {
      for (const rule of list) {
        if (rule.cssRules) walk(rule.cssRules);
        if (rule.selectorText && rule.style && rule.style.gridTemplateColumns) {
          try { if (root.matches(rule.selectorText)) matches.push({ selector: rule.selectorText, gtc: rule.style.gridTemplateColumns, display: rule.style.display }); } catch { /* noop */ }
        }
      }
    };
    walk(rules);
  }
  return matches;
});
console.log(JSON.stringify(info, null, 1));
await browser.close();
