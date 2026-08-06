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
await page.waitForTimeout(1500);
const info = await page.evaluate(() => {
  const nav = document.querySelector("nav[aria-label='个股研究标签']");
  const pageRoot = nav?.parentElement;
  const chain = [];
  let el = nav;
  while (el && chain.length < 6) {
    const cs = getComputedStyle(el);
    chain.push({ tag: el.tagName, cls: el.className, display: cs.display, gridTemplateColumns: cs.gridTemplateColumns, width: el.offsetWidth, height: el.offsetHeight });
    el = el.parentElement;
  }
  const firstTab = nav?.querySelector("a");
  const tabCs = firstTab ? getComputedStyle(firstTab) : null;
  return { chain, tab: tabCs ? { display: tabCs.display, padding: tabCs.padding, fontSize: tabCs.fontSize, height: firstTab.offsetHeight, alignSelf: tabCs.alignSelf } : null, pageChildren: pageRoot ? [...pageRoot.children].map((c) => ({ tag: c.tagName, cls: typeof c.className === "string" ? c.className.slice(0, 40) : "", top: Math.round(c.getBoundingClientRect().top), left: Math.round(c.getBoundingClientRect().left), w: c.offsetWidth })) : null };
});
console.log(JSON.stringify(info, null, 1));
await browser.close();
