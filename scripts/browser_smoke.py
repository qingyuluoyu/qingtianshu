from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sys
import time
from typing import Any
from urllib.parse import urljoin, urlparse

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright


@dataclass(frozen=True)
class Viewport:
    name: str
    width: int
    height: int


@dataclass(frozen=True)
class Check:
    name: str
    path: str
    ready_selector: str
    content_selector: str


VIEWPORTS = (
    Viewport("desktop", 1280, 720),
    Viewport("mobile-390", 390, 844),
)

CHECKS = (
    Check("today", "/today", "#liveSection:not([hidden])", "#liveMarkets"),
    Check(
        "screening",
        "/research?mode=screening",
        "#stockScreenerPanel:not([hidden])",
        "#generalScreenerPanel:not([hidden])",
    ),
    Check(
        "stock-overview",
        "/stocks/000063.SZ?tab=overview",
        "#deepStockPanel:not([hidden])",
        ".stock-workspace-card.primary",
    ),
    Check(
        "stock-history",
        "/stocks/000063.SZ?tab=history",
        "#stockSpaceHistoryPane:not([hidden])",
        "#deepStockHistory",
    ),
    Check(
        "reviews",
        "/reviews?tab=trades",
        "#methodSection:not([hidden])",
        "#tradeReviewList",
    ),
    Check(
        "agent",
        "/research/new",
        "#agentSection:not([hidden])",
        "#messages",
    ),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the repository-owned browser smoke gate for the core QingShu "
            "desktop and 390px mobile journeys."
        )
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8773",
        help="Running QingShu server origin.",
    )
    parser.add_argument(
        "--artifacts",
        type=Path,
        default=Path("artifacts/browser-smoke"),
        help="Directory for screenshots and the JSON result.",
    )
    parser.add_argument(
        "--browser",
        choices=("auto", "chrome", "chromium"),
        default="auto",
        help=(
            "Browser executable. auto prefers installed Google Chrome and then "
            "Playwright Chromium."
        ),
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Show the browser window while running.",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=20_000,
        help="Per-navigation and locator timeout.",
    )
    return parser.parse_args()


def launch_browser(
    playwright: Playwright,
    browser_choice: str,
    *,
    headless: bool,
) -> tuple[Browser, str]:
    attempts: list[tuple[str, dict[str, Any]]] = []
    if browser_choice in {"auto", "chrome"}:
        attempts.append(("chrome", {"channel": "chrome"}))
    if browser_choice in {"auto", "chromium"}:
        attempts.append(("chromium", {}))

    errors: list[str] = []
    for label, options in attempts:
        try:
            browser = playwright.chromium.launch(
                headless=headless,
                args=["--disable-background-networking"],
                **options,
            )
            return browser, label
        except Exception as exc:  # pragma: no cover - depends on host browsers
            errors.append(f"{label}: {type(exc).__name__}: {exc}")
    joined = "\n".join(errors)
    raise RuntimeError(
        "没有可用的浏览器。macOS 可安装 Google Chrome；CI 或无 Chrome 环境先运行 "
        "`uv run playwright install chromium`。\n" + joined
    )


def visible_overflow(page: Page) -> dict[str, Any]:
    return page.evaluate(
        """
        () => {
          const viewportWidth = window.innerWidth;
          const rootWidth = document.documentElement.scrollWidth;
          const bodyWidth = document.body.scrollWidth;
          const offenders = [...document.querySelectorAll("body *")]
            .filter(node => {
              const style = getComputedStyle(node);
              if (
                style.display === "none"
                || style.visibility === "hidden"
                || Number(style.opacity) === 0
              ) return false;
              const rect = node.getBoundingClientRect();
              if (rect.width <= 0 || rect.height <= 0) return false;
              return rect.left < -1 || rect.right > viewportWidth + 1;
            })
            .slice(0, 12)
            .map(node => {
              const rect = node.getBoundingClientRect();
              return {
                tag: node.tagName.toLowerCase(),
                id: node.id || null,
                className: String(node.className || "").slice(0, 120),
                left: Math.round(rect.left * 10) / 10,
                right: Math.round(rect.right * 10) / 10,
                width: Math.round(rect.width * 10) / 10,
              };
            });
          return {
            viewportWidth,
            rootWidth,
            bodyWidth,
            hasHorizontalOverflow:
              rootWidth > viewportWidth + 1 || bodyWidth > viewportWidth + 1,
            offenders,
          };
        }
        """
    )


def stock_overview_mobile_widths(page: Page) -> list[dict[str, Any]]:
    return page.evaluate(
        """
        () => [
          ".stock-workspace-card.primary",
          ".stock-research-map",
          ".stock-workspace-card.changes",
          ".stock-workspace-card.tasks",
        ].map(selector => {
          const node = document.querySelector(selector);
          const rect = node?.getBoundingClientRect();
          return {
            selector,
            visible: Boolean(node && rect && rect.width > 0 && rect.height > 0),
            width: rect ? Math.round(rect.width * 10) / 10 : 0,
          };
        })
        """
    )


def screening_section_state(page: Page) -> dict[str, Any]:
    return page.evaluate(
        """
        () => {
          const general = document.querySelector("#generalScreenerPanel");
          const strategy = document.querySelector("#liZongPanel");
          const generalTab = document.querySelector('[data-screening-jump="general"]');
          const strategyTab = document.querySelector('[data-screening-jump="li_zong"]');
          const historyPanel = document.querySelector("#liZongHistoryPanel");
          const historyToggle = document.querySelector("#liZongHistoryToggle");
          const historyResults = document.querySelector("#liZongHistoryResults");
          const visible = node => Boolean(
            node
            && !node.hidden
            && node.getBoundingClientRect().width > 0
            && node.getBoundingClientRect().height > 0
          );
          const toggleVisible = visible(historyToggle);
          return {
            url: location.pathname + location.search,
            generalVisible: visible(general),
            strategyVisible: visible(strategy),
            loadState: strategy?.dataset.loadState ?? null,
            generalSelected: generalTab?.getAttribute("aria-selected") ?? null,
            strategySelected: strategyTab?.getAttribute("aria-selected") ?? null,
            historyPanelVisible: visible(historyPanel),
            historyToggleVisible: toggleVisible,
            historyToggleExpanded:
              toggleVisible ? historyToggle.getAttribute("aria-expanded") : null,
            historyDetailsVisible: visible(historyResults),
          };
        }
        """
    )


def wait_for_content(page: Page, selector: str) -> None:
    page.locator(selector).wait_for(state="visible")
    page.wait_for_timeout(900)


def safe_name(value: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")


def expected_boot_response(item: dict[str, Any]) -> bool:
    path = urlparse(str(item.get("url") or "")).path
    status = int(item.get("status") or 0)
    return (path == "/session" and status == 401) or (
        path == "/favicon.ico" and status == 404
    )


def run_check(
    context: BrowserContext,
    *,
    base_url: str,
    viewport: Viewport,
    check: Check,
    artifacts: Path,
    timeout_ms: int,
) -> dict[str, Any]:
    page = context.new_page()
    page.set_default_timeout(timeout_ms)
    console_errors: list[str] = []
    page_errors: list[str] = []
    error_responses: list[dict[str, Any]] = []
    page.on(
        "console",
        lambda message: console_errors.append(message.text)
        if message.type == "error"
        else None,
    )
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.on(
        "response",
        lambda response: error_responses.append(
            {"status": response.status, "url": response.url}
        )
        if response.url.startswith(base_url) and response.status >= 400
        else None,
    )

    url = urljoin(base_url.rstrip("/") + "/", check.path.lstrip("/"))
    response = page.goto(url, wait_until="domcontentloaded")
    if response is None or response.status >= 400:
        raise AssertionError(
            f"{check.name} 页面响应异常：{response.status if response else '无响应'}"
        )
    page.locator(check.ready_selector).wait_for(state="visible")
    wait_for_content(page, check.content_selector)
    overflow = visible_overflow(page)
    mobile_widths = []
    screening_structure = {}
    if viewport.width <= 390 and check.name == "stock-overview":
        mobile_widths = stock_overview_mobile_widths(page)
    if check.name == "screening":
        default_state = screening_section_state(page)
        switch_started = time.perf_counter()
        page.locator('[data-screening-jump="li_zong"]').click()
        page.locator("#liZongPanel:not([hidden])").wait_for(state="visible")
        panel_visible_seconds = time.perf_counter() - switch_started
        loading_state = screening_section_state(page)
        page.locator('#liZongPanel[data-load-state="ready"]').wait_for(
            state="visible",
            timeout=max(timeout_ms, 30_000),
        )
        strategy_ready_seconds = time.perf_counter() - switch_started
        page.wait_for_timeout(200)
        strategy_state = screening_section_state(page)
        page.locator('[data-screening-jump="general"]').click()
        page.locator("#generalScreenerPanel:not([hidden])").wait_for(state="visible")
        page.locator("#liZongPanel").wait_for(state="hidden")
        page.wait_for_timeout(100)
        restored_state = screening_section_state(page)
        screening_structure = {
            "default": default_state,
            "loading": loading_state,
            "strategy": strategy_state,
            "restored": restored_state,
            "panel_visible_seconds": round(panel_visible_seconds, 3),
            "strategy_ready_seconds": round(strategy_ready_seconds, 3),
        }
    unexpected_responses = [
        item for item in error_responses if not expected_boot_response(item)
    ]
    ignored_responses = [
        item for item in error_responses if expected_boot_response(item)
    ]
    if ignored_responses and not unexpected_responses:
        console_errors = [
            message
            for message in console_errors
            if not message.startswith("Failed to load resource:")
        ]
    screenshot = artifacts / f"{viewport.name}-{safe_name(check.name)}.png"
    page.screenshot(path=str(screenshot), full_page=True)
    result = {
        "name": check.name,
        "path": check.path,
        "url": page.url,
        "title": page.title(),
        "overflow": overflow,
        "mobile_core_widths": mobile_widths,
        "screening_progressive_disclosure": screening_structure,
        "console_errors": console_errors,
        "page_errors": page_errors,
        "failed_responses": unexpected_responses,
        "ignored_boot_responses": ignored_responses,
        "screenshot": str(screenshot),
    }
    page.close()

    problems = []
    if overflow["hasHorizontalOverflow"]:
        problems.append(
            f"页面宽度 {overflow['rootWidth']} 超过视口 {overflow['viewportWidth']}"
        )
    too_narrow = [
        item
        for item in mobile_widths
        if not item["visible"] or float(item["width"]) < 280
    ]
    if too_narrow:
        problems.append(
            "390px 核心卡片不可读："
            + " | ".join(
                f"{item['selector']}={item['width']}px" for item in too_narrow
            )
        )
    if screening_structure:
        default_state = screening_structure["default"]
        strategy_state = screening_structure["strategy"]
        restored_state = screening_structure["restored"]
        panel_visible_seconds = float(
            screening_structure.get("panel_visible_seconds") or 0
        )
        if not (
            default_state.get("generalVisible")
            and not default_state.get("strategyVisible")
            and default_state.get("generalSelected") == "true"
            and default_state.get("strategySelected") == "false"
            and "section=li_zong" not in str(default_state.get("url") or "")
        ):
            problems.append("透明选股默认分区异常：通用筛选没有独占显示")
        if not (
            not strategy_state.get("generalVisible")
            and strategy_state.get("strategyVisible")
            and strategy_state.get("loadState") == "ready"
            and strategy_state.get("generalSelected") == "false"
            and strategy_state.get("strategySelected") == "true"
            and "section=li_zong" in str(strategy_state.get("url") or "")
        ):
            problems.append("透明选股切换异常：李总策略没有独占显示或 URL 未恢复")
        if panel_visible_seconds > 1.5:
            problems.append(
                f"透明选股切换反馈过慢：策略面板 {panel_visible_seconds:.3f}s 后可见"
            )
        if not (
            restored_state.get("generalVisible")
            and not restored_state.get("strategyVisible")
            and restored_state.get("generalSelected") == "true"
            and restored_state.get("strategySelected") == "false"
            and "section=li_zong" not in str(restored_state.get("url") or "")
        ):
            problems.append("透明选股返回异常：通用筛选状态没有恢复")
        if strategy_state.get("historyToggleVisible") and (
            strategy_state.get("historyToggleExpanded") != "false"
            or strategy_state.get("historyDetailsVisible")
        ):
            problems.append("李总策略历史详情没有保持默认折叠")
    if console_errors:
        problems.append("console error: " + " | ".join(console_errors[:3]))
    if page_errors:
        problems.append("page error: " + " | ".join(page_errors[:3]))
    if unexpected_responses:
        problems.append(
            "unexpected response: "
            + " | ".join(
                f"{item['status']} {item['url']}"
                for item in unexpected_responses[:3]
            )
        )
    if problems:
        result["status"] = "failed"
        result["problems"] = problems
    else:
        result["status"] = "passed"
        result["problems"] = []
    return result


def main() -> int:
    args = parse_args()
    artifacts = args.artifacts.expanduser().resolve()
    artifacts.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []

    with sync_playwright() as playwright:
        browser, browser_label = launch_browser(
            playwright,
            args.browser,
            headless=not args.headed,
        )
        try:
            for viewport in VIEWPORTS:
                context = browser.new_context(
                    viewport={"width": viewport.width, "height": viewport.height},
                    device_scale_factor=1,
                    locale="zh-CN",
                    timezone_id="Asia/Shanghai",
                )
                try:
                    for check in CHECKS:
                        try:
                            result = run_check(
                                context,
                                base_url=args.base_url.rstrip("/"),
                                viewport=viewport,
                                check=check,
                                artifacts=artifacts,
                                timeout_ms=args.timeout_ms,
                            )
                        except Exception as exc:
                            result = {
                                "name": check.name,
                                "path": check.path,
                                "status": "failed",
                                "problems": [f"{type(exc).__name__}: {exc}"],
                            }
                        result["viewport"] = {
                            "name": viewport.name,
                            "width": viewport.width,
                            "height": viewport.height,
                        }
                        results.append(result)
                        marker = "PASS" if result["status"] == "passed" else "FAIL"
                        print(f"[{marker}] {viewport.name} {check.path}")
                        for problem in result.get("problems") or []:
                            print(f"       {problem}")
                finally:
                    context.close()
        finally:
            browser.close()

    report = {
        "base_url": args.base_url.rstrip("/"),
        "browser": browser_label,
        "viewports": [viewport.__dict__ for viewport in VIEWPORTS],
        "checks": results,
        "passed": sum(item["status"] == "passed" for item in results),
        "failed": sum(item["status"] != "passed" for item in results),
    }
    report_path = artifacts / "result.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"结果：{report['passed']} 通过，{report['failed']} 失败")
    print(f"报告：{report_path}")
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
