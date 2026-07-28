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
        "watchlist-kline",
        "/watchlist",
        "#watchlistPanel:not([hidden])",
        "#watchlistDetail .qs-kline-canvas:not([hidden])",
    ),
    Check(
        "stock-overview",
        "/stocks/000063.SZ?tab=overview",
        "#deepStockPanel:not([hidden])",
        ".stock-workspace-card.primary",
    ),
    Check(
        "stock-kline",
        "/stocks/000063.SZ?tab=overview",
        "#deepStockPanel:not([hidden])",
        ".stock-space-kline-host .qs-kline-canvas:not([hidden])",
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
        "market-reviews",
        "/reviews?tab=market",
        "#reviewMarketPanel:not([hidden])",
        "#marketReviewList",
    ),
    Check(
        "account",
        "/account",
        "#accountPanel:not([hidden])",
        ".account-risk-profile",
    ),
    Check(
        "agent",
        "/research/new",
        "#agentSection:not([hidden])",
        "#agentEntryHub:not([hidden])",
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
          const sectionTabs = [...document.querySelectorAll("[data-screening-jump]")];
          const strategyTabs = document.querySelector(".li-zong-tabs");
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
            sectionLabels: sectionTabs.map(node => node.textContent.trim()),
            generalHeading: document.querySelector(".screener-section-heading strong")
              ?.textContent?.trim() || "",
            strategyKicker: document.querySelector(".li-zong-kicker")
              ?.textContent?.trim() || "",
            strategyTabsFlexWrap: strategyTabs
              ? getComputedStyle(strategyTabs).flexWrap
              : "",
          };
        }
        """
    )


def screening_candidate_disclosure_state(page: Page) -> dict[str, Any]:
    return page.evaluate(
        """
        () => {
          renderStockScreener({
            type: "stock_screen",
            status: "ready",
            profile: {
              key: "trend",
              label: "相对行业增强候选",
              sort_rule: "按近 20 日相对行业超额收益从高到低排列；不计算综合分。",
            },
            data_meta: {
              latest_completed_trade_date: "2026-07-28",
              return_20d_base_date: "2026-06-30",
              financial_report_periods: ["2026-03-31"],
            },
            data_contract: {coverage: {}, data_version: "browser-fixture-v1"},
            rules: [
              {field: "总市值下限", operator: ">=", value: 30, unit: "亿元"},
              {field: "近 20 日收益下限", operator: ">=", value: 0, unit: "%"},
              {field: "近 20 日行业超额下限", operator: ">=", value: 0, unit: ""},
            ],
            items: [
              {
                name: "锐捷网络",
                internal_symbol: "301165.SZ",
                ts_code: "301165.SZ",
                industry: "通信设备",
                metrics: {
                  return_5d_pct: 4.1,
                  return_20d_pct: 43.44,
                  industry_excess_20d_pct: 65.87,
                  pe_ttm: 204.33,
                  pb: 28.34,
                  total_mv_yi: 1454.85,
                  volume_ratio: 1.15,
                },
                financials: {report_period: "2026-03-31", roe: 2.43},
                matched_reasons: [
                  "近 5 日收益 4.10%",
                  "近 20 日收益 43.44%",
                  "近 20 日相对所属行业样本均值 65.87 个百分点",
                ],
                missing_fields: [],
              },
              {
                name: "紫光股份",
                internal_symbol: "000938.SZ",
                ts_code: "000938.SZ",
                industry: "IT设备",
                metrics: {
                  return_5d_pct: 0.05,
                  return_20d_pct: 43.73,
                  industry_excess_20d_pct: 56.12,
                  pe_ttm: 55.83,
                  pb: 7.64,
                  total_mv_yi: 1186.36,
                  volume_ratio: 1.08,
                },
                financials: {report_period: "2026-03-31", roe: 3.86},
                matched_reasons: [
                  "近 5 日收益 0.05%",
                  "近 20 日收益 43.73%",
                  "近 20 日相对所属行业样本均值 56.12 个百分点",
                ],
                missing_fields: [],
              },
            ],
            boundary: "这是可解释的研究候选筛选，不构成推荐、评级、目标价或交易建议。",
          });
          const cards = [...document.querySelectorAll("#stockScreenResults .screener-card")];
          const first = cards[0];
          const firstRect = first?.getBoundingClientRect();
          return {
            cardCount: cards.length,
            coreMetricCounts: cards.map(card => card.querySelectorAll(".screener-metrics-core .screener-metric").length),
            cardDetailsClosed: cards.every(card => !card.querySelector(".screener-card-details")?.open),
            firstFullMetricCount: first?.querySelectorAll(".screener-metrics-full .screener-metric").length || 0,
            firstReasonCount: first?.querySelectorAll(".screener-reasons li").length || 0,
            firstSummary: first?.querySelector(".screener-card-details summary")?.textContent?.trim() || "",
            firstPrompt: first?.querySelector(".screener-candidate-prompt")?.textContent?.trim() || "",
            ruleDetailsClosed: !document.querySelector("#stockScreenRuleDetails")?.open,
            profileTitle: document.querySelector("#stockScreenTitle")?.textContent?.trim() || "",
            profileHint: document.querySelector("#stockScreenProfileHint")?.textContent?.trim() || "",
            firstCardWidth: firstRect ? Math.round(firstRect.width * 10) / 10 : 0,
            viewportWidth: window.innerWidth,
          };
        }
        """
    )


def review_section_state(page: Page) -> dict[str, Any]:
    return page.evaluate(
        """
        () => {
          const items = [...document.querySelectorAll("#tradeReviewList .review-run-item")];
          const workspace = document.querySelector("#reviewTradesPanel .review-run-workspace");
          const sidebar = workspace?.querySelector(".review-run-sidebar");
          return {
            eyebrow: document.querySelector("#methodSection .method-eyebrow")
              ?.textContent?.trim() || "",
            heading: document.querySelector("#methodSection .method-heading")
              ?.textContent?.trim() || "",
            itemCount: items.length,
            emptyCopy: document.querySelector("#tradeReviewList .review-list-empty")
              ?.textContent?.replace(/\\s+/g, " ")?.trim() || "",
            emptyAction: document.querySelector("#tradeReviewList .review-list-empty button")
              ?.textContent?.trim() || "",
            emptyOnboarding: workspace?.classList.contains("empty-onboarding") || false,
            sidebarVisible: Boolean(sidebar && sidebar.getBoundingClientRect().width > 0),
            onboardingTitle: document.querySelector(".trade-review-onboarding-title")
              ?.textContent?.trim() || "",
            onboardingSteps: [...document.querySelectorAll(".trade-review-onboarding-steps strong")]
              .map(node => node.textContent.trim()),
            onboardingStepWidths: [...document.querySelectorAll(".trade-review-onboarding-steps li")]
              .map(node => Math.round(node.getBoundingClientRect().width * 10) / 10),
            onboardingAction: document.querySelector(".trade-review-onboarding > button")
              ?.textContent?.trim() || "",
          };
        }
        """
    )


def populated_review_detail_state(page: Page) -> dict[str, Any]:
    return page.evaluate(
        """
        () => {
          const detail = document.querySelector("#tradeReviewDetail");
          const priceDetails = detail?.querySelector(".trade-review-data-details");
          const style = node => node ? Number.parseFloat(getComputedStyle(node).fontSize) : 0;
          return {
            sectionTitles: [...(detail?.querySelectorAll(".review-detail-section-title") || [])]
              .map(node => node.childNodes[0]?.textContent?.trim() || ""),
            metricLabels: [...(detail?.querySelectorAll(".review-detail-metric span") || [])]
              .map(node => node.textContent.trim()),
            priceDetailsOpen: Boolean(priceDetails?.open),
            priceDetailsLabel: priceDetails?.querySelector("summary")?.textContent?.trim() || "",
            bodyText: detail?.textContent?.replace(/\\s+/g, " ")?.trim() || "",
            titleFontSize: style(detail?.querySelector(".review-detail-section-title")),
            copyFontSize: style(detail?.querySelector(".trade-center-detail-copy")),
          };
        }
        """
    )


def market_review_section_state(page: Page) -> dict[str, Any]:
    return page.evaluate(
        """
        () => {
          const items = [...document.querySelectorAll("#marketReviewList .market-review-item")];
          return {
            itemCount: items.length,
            titles: items.slice(0, 6).map(node =>
              node.querySelector("strong")?.textContent?.trim() || ""
            ),
            summaries: items.slice(0, 6).map(node =>
              node.querySelector("span")?.textContent?.trim() || ""
            ),
            boundary: document.querySelector(".market-review-boundary")
              ?.textContent?.replace(/\\s+/g, " ")?.trim() || "",
          };
        }
        """
    )


def market_overview_state(page: Page) -> dict[str, Any]:
    return page.evaluate(
        """
        () => {
          const quickGrid = document.querySelector("#marketQuickGrid");
          const quickCards = [...document.querySelectorAll("#marketQuickGrid .market-quick-card")];
          const articleItems = [...document.querySelectorAll("#articleFeed .article-item")];
          const firstSummary = articleItems[0]?.querySelector(".article-item-summary");
          return {
            title: document.querySelector(".market-section-title")
              ?.textContent?.trim() || "",
            quickTitle: document.querySelector("#marketQuickTitle")
              ?.textContent?.trim() || "",
            quickMeta: document.querySelector("#marketQuickMeta")
              ?.textContent?.replace(/\\s+/g, " ")?.trim() || "",
            quickLabels: quickCards.map(node =>
              node.querySelector("span")?.textContent?.trim() || ""
            ),
            quickText: quickCards.map(node =>
              node.textContent?.replace(/\\s+/g, " ")?.trim() || ""
            ),
            quickColumns: quickGrid
              ? getComputedStyle(quickGrid).gridTemplateColumns.split(" ").filter(Boolean).length
              : 0,
            articleCount: articleItems.length,
            articleTypes: articleItems.slice(0, 8).map(node =>
              node.querySelector(".article-item-time")?.textContent?.trim() || ""
            ),
            articleSummaryFontSize: firstSummary
              ? Number.parseFloat(getComputedStyle(firstSummary).fontSize)
              : 0,
            insightTabCount: document.querySelectorAll("[data-insight-filter]").length,
            askTitle: document.querySelector("#insightAsk .panel-title")
              ?.textContent?.trim() || "",
            askPlaceholder: document.querySelector("#insightQuestion")
              ?.getAttribute("placeholder") || "",
            watchlistPulseExists: Boolean(document.querySelector("#watchlistPulse")),
          };
        }
        """
    )


def account_section_state(page: Page) -> dict[str, Any]:
    return page.evaluate(
        """
        () => {
          const details = document.querySelector(".account-service-details");
          const row = details?.querySelector(".account-row");
          const copy = details?.querySelector(".account-card-copy");
          return {
            title: document.querySelector("#accountPanel .panel-title")
              ?.textContent?.trim() || "",
            detailsOpen: Boolean(details?.open),
            summary: details?.querySelector("summary")
              ?.textContent?.replace(/\\s+/g, " ")?.trim() || "",
            rowFontSize: row ? Number.parseFloat(getComputedStyle(row).fontSize) : 0,
            copyFontSize: copy ? Number.parseFloat(getComputedStyle(copy).fontSize) : 0,
          };
        }
        """
    )


def account_risk_profile_states(page: Page) -> dict[str, Any]:
    return page.evaluate(
        """
        async () => {
          const steps = [...document.querySelectorAll(".risk-profile-step")];
          const capture = () => {
            const stepGrid = document.querySelector(".risk-profile-steps");
            const question = document.querySelector(".risk-profile-question");
            const option = document.querySelector(".risk-profile-option span");
            const buttons = [...document.querySelectorAll(".risk-profile-actions .btn")];
            const advisor = document.querySelector("#riskProfileAskAdvisor");
            return {
              progressText: document.querySelector("#riskProfileProgressText")
                ?.textContent?.trim() || "",
              progressNow: Number(
                document.querySelector("#riskProfileProgressBar")
                  ?.getAttribute("aria-valuenow") || 0
              ),
              nextStep: document.querySelector("#riskProfileNextStep")
                ?.textContent?.trim() || "",
              state: document.querySelector("#riskProfileState")
                ?.textContent?.trim() || "",
              status: document.querySelector("#riskProfileStatus")
                ?.textContent?.trim() || "",
              stepClasses: steps.map(node => node.className),
              stepColumns: stepGrid
                ? getComputedStyle(stepGrid).gridTemplateColumns
                    .split(" ").filter(Boolean).length
                : 0,
              questionCount: document.querySelectorAll(
                ".risk-profile-question"
              ).length,
              questionFontSize: question
                ? Number.parseFloat(
                    getComputedStyle(question.querySelector("legend")).fontSize
                  )
                : 0,
              optionFontSize: option
                ? Number.parseFloat(getComputedStyle(option).fontSize)
                : 0,
              buttonMinHeights: buttons.map(node =>
                Number.parseFloat(getComputedStyle(node).minHeight)
              ),
              confirmDisabled: Boolean(
                document.querySelector("#riskProfileConfirm")?.disabled
              ),
              missingQuestionCount: document.querySelectorAll(
                ".risk-profile-question.missing"
              ).length,
              activeRiskKey: document.activeElement?.dataset?.riskKey || "",
              advisorVisible: Boolean(advisor && advisor.offsetParent !== null),
              advisorText: advisor?.textContent?.trim() || "",
            };
          };

          const initial = capture();
          document.querySelector("#riskProfileForm").dispatchEvent(
            new Event("submit", {bubbles: true, cancelable: true})
          );
          await new Promise(resolve => requestAnimationFrame(
            () => requestAnimationFrame(resolve)
          ));
          const incomplete = capture();
          for (const question of document.querySelectorAll(
            ".risk-profile-question"
          )) {
            const firstOption = question.querySelector("input[type=radio]");
            if (!firstOption) continue;
            firstOption.checked = true;
            firstOption.dispatchEvent(new Event("change", {bubbles: true}));
          }
          const modified = capture();

          document.querySelector("#riskProfileState").className =
            "risk-profile-state draft";
          document.querySelector("#riskProfileState").textContent =
            "草稿 v1 · 尚未生效";
          document.querySelector("#riskProfileConfirm").disabled = false;
          document.querySelector("#riskProfileStatus").textContent =
            "草稿已保存，但尚未用于 AI。请核对后再确认。";
          document.querySelector("#riskProfileNextStep").textContent =
            "草稿已保存，请核对后确认是否让 AI 使用";
          document.querySelector("#riskProfileStepSave").className =
            "risk-profile-step complete";
          document.querySelector("#riskProfileStepConfirm").className =
            "risk-profile-step active";
          const draft = capture();

          document.querySelector("#riskProfileState").className =
            "risk-profile-state confirmed";
          document.querySelector("#riskProfileState").textContent = "已确认 v1";
          document.querySelector("#riskProfileConfirm").disabled = true;
          document.querySelector("#riskProfileStatus").textContent =
            "已由你确认。后续适合性回答会引用该版本，并明确说明边界。";
          document.querySelector("#riskProfileNextStep").textContent =
            "画像已确认，可以让金融顾问结合这些事实解释产品条件";
          for (const step of steps) step.className = "risk-profile-step complete";
          const confirmedHost = document.querySelector("#riskProfileConfirmed");
          confirmedHost.hidden = false;
          confirmedHost.innerHTML = `
            <strong>当前需要在流动性、波动和长期目标之间平衡</strong>
            <span>版本 1 · 已由测试状态确认</span>
            <p>需要优先核对：产品结构和费用规则需要用通俗语言解释</p>
            <div class="risk-profile-confirmed-actions">
              <span>下一步：带着这份画像询问具体产品，不会自动发送问题。</span>
              <button id="riskProfileAskAdvisor" class="btn primary" type="button">去问金融顾问</button>
            </div>`;
          const confirmed = capture();
          return {initial, incomplete, modified, draft, confirmed};
        }
        """
    )


def agent_landing_state(page: Page) -> dict[str, Any]:
    return page.evaluate(
        """
        () => {
          const section = document.querySelector("#agentSection");
          const hub = document.querySelector("#agentEntryHub");
          const hubRect = hub.getBoundingClientRect();
          const composer = document.querySelector("#chatForm");
          const cards = [...hub.querySelectorAll(".agent-entry-card")];
          const cardRects = cards.map(node => node.getBoundingClientRect());
          const cardTitles = cards.map(node =>
            node.querySelector("strong")?.textContent?.trim() || ""
          );
          const cardCopies = cards.map(node => node.querySelector("span"))
            .filter(Boolean);
          const context = document.querySelector("#diagnosisContext");
          const messages = document.querySelector("#messages");
          const quick = document.querySelector("#quickActions");
          const researchBar = document.querySelector(".agent-research-bar");
          const mobileTools = document.querySelector("#conversationMobileTools");
          const mobileFilterRow = document.querySelector(
            "#conversationMobileTools .conversation-filter-row"
          );
          return {
            entryActive: section.classList.contains("entry-active"),
            hubVisible: !hub.hidden && getComputedStyle(hub).display !== "none",
            cardTitles,
            cardCount: cards.length,
            allCardsInsideHub: cardRects.every(rect =>
              rect.top >= hubRect.top - 1 && rect.bottom <= hubRect.bottom + 1
            ),
            hubClientHeight: hub.clientHeight,
            hubScrollHeight: hub.scrollHeight,
            hubOverflowY: getComputedStyle(hub).overflowY,
            minCardTitleFontSize: Math.min(...cards.map(node =>
              Number.parseFloat(getComputedStyle(node.querySelector("strong")).fontSize)
            )),
            minCardCopyFontSize: Math.min(...cardCopies.map(node =>
              Number.parseFloat(getComputedStyle(node).fontSize)
            )),
            contextHidden: context.hidden || getComputedStyle(context).display === "none",
            messagesHidden: getComputedStyle(messages).display === "none",
            quickActionsHidden: getComputedStyle(quick).display === "none",
            researchBarHidden: getComputedStyle(researchBar).display === "none",
            mobileFilterHidden: !mobileTools
              || mobileTools.hidden
              || getComputedStyle(mobileTools).display === "none"
              || !mobileFilterRow
              || getComputedStyle(mobileFilterRow).display === "none",
            composerVisible: getComputedStyle(composer).display !== "none",
            composerTop: Math.round(composer.getBoundingClientRect().top),
            composerBottom: Math.round(composer.getBoundingClientRect().bottom),
            viewportHeight: window.innerHeight,
          };
        }
        """
    )


def agent_quick_actions_state(page: Page) -> dict[str, Any]:
    page.evaluate(
        """
        () => {
          if (!document.querySelector("#messages .message.user")) {
            window.addMessage("user", "浏览器只读界面检查");
          }
          window.syncAgentEntryHubVisibility();
        }
        """
    )

    def snapshot() -> dict[str, Any]:
        return page.evaluate(
            """
            () => {
              const root = document.querySelector("#quickActions");
              const buttons = [...root.querySelectorAll("button")];
              const visibleButtons = buttons.filter(node => !node.hidden);
              const labels = [...root.querySelectorAll(".quick-actions-label")];
              return {
                expanded: root.classList.contains("expanded"),
                groupLabels: labels.map(node => node.textContent?.trim() || ""),
                visibleButtonLabels: visibleButtons.map(
                  node => node.textContent?.trim() || ""
                ),
                hiddenSecondaryCount: root.querySelectorAll(
                  "[data-quick-secondary][hidden]"
                ).length,
                minButtonFontSize: Math.min(...visibleButtons.map(
                  node => Number.parseFloat(getComputedStyle(node).fontSize)
                )),
                minLabelFontSize: Math.min(...labels.map(
                  node => Number.parseFloat(getComputedStyle(node).fontSize)
                )),
                clientWidth: root.clientWidth,
                scrollWidth: root.scrollWidth,
                clientHeight: root.clientHeight,
                scrollHeight: root.scrollHeight,
              };
            }
            """
        )

    collapsed = snapshot()
    toggle = page.locator("#toggleQuickActions")
    toggle.click()
    expanded = snapshot()
    toggle.click()
    restored = snapshot()
    return {"collapsed": collapsed, "expanded": expanded, "restored": restored}


def agent_conversation_scope_state(page: Page) -> dict[str, Any]:
    return page.evaluate(
        """
        () => {
          const samples = Array.from({length: 67}, (_, index) => ({
            id: `scope-sample-${index}`,
            title: `普通研究问题 ${index + 1}`,
            quality_scope: "user",
            message_count: 1,
            last_message_preview: `普通研究内容 ${index + 1}`,
            last_intent: "general_research",
            research_targets: [],
            updated_at: new Date(Date.now() - index * 60000).toISOString(),
          }));
          samples[0] = {
            ...samples[0],
            title: "基金和ETF有什么区别",
            last_message_preview: "普通投资者应该根据哪些条件选择",
          };
          samples[1] = {
            ...samples[1],
            title: "我快退休了，有一笔闲钱",
            last_message_preview: "不知道该选股票基金还是债券基金",
          };
          samples[2] = {
            ...samples[2],
            title: "中兴通讯为什么大跌",
            last_message_preview: "分析这家公司当前经营与估值",
            last_intent: "stock_research",
            research_targets: [{symbol: "000063.SZ", name: "中兴通讯"}],
          };
          samples[3] = {
            ...samples[3],
            title: "分析股票还是基金",
            conversation_scope: "funds",
          };
          state.conversationId = samples[66].id;
          state.conversationHistoryExpanded = false;
          state.conversationScope = "all";
          state.conversationQuery = "";
          renderConversationList(samples);
          const historySnapshot = () => ({
            rows: document.querySelectorAll("#conversationList .conversation-row").length,
            topics: document.querySelectorAll("#conversationList .conversation-topic-stack").length,
            activeVisible: [...document.querySelectorAll("#conversationList .conversation-row.active")]
              .some(node => node.textContent.includes("普通研究问题 67")),
            toggleText: document.querySelector("#conversationList .conversation-history-toggle")
              ?.textContent || "",
            toggleExpanded: document.querySelector("#conversationList .conversation-history-toggle")
              ?.getAttribute("aria-expanded") || "",
            filterMeta: document.querySelector("#conversationFilterMeta")?.textContent || "",
            scrollTop: document.querySelector("#conversationList")?.scrollTop || 0,
          });
          const historyInitial = historySnapshot();
          document.querySelector("#conversationList .conversation-history-toggle")
            ?.dispatchEvent(new MouseEvent("click", {bubbles: true}));
          const historyExpanded = historySnapshot();
          document.querySelector("#conversationList .conversation-history-toggle")
            ?.dispatchEvent(new MouseEvent("click", {bubbles: true}));
          const historyRestored = historySnapshot();
          const search = document.querySelector("#conversationSearch");
          search.value = "普通研究问题 60";
          search.dispatchEvent(new Event("input", {bubbles: true}));
          const searchFoundOld = [...document.querySelectorAll("#conversationList .conversation-title")]
            .some(node => node.textContent === "普通研究问题 60");
          search.value = "";
          search.dispatchEvent(new Event("input", {bubbles: true}));
          const desktop = document.querySelector("#conversationScopeFilter");
          desktop.value = "funds";
          desktop.dispatchEvent(new Event("change", {bubbles: true}));
          return {
            total: state.conversations.length,
            inferredFund: conversationScopeKey(samples[0]),
            retirementFund: conversationScopeKey(samples[1]),
            stock: conversationScopeKey(samples[2]),
            explicitFund: conversationScopeKey(samples[3]),
            historyDisclosure: {
              initial: historyInitial,
              expanded: historyExpanded,
              restored: historyRestored,
              searchFoundOld,
              filteringTogglePresent: Boolean(
                document.querySelector("#conversationList .conversation-history-toggle")
              ),
            },
            desktopOptions: [...desktop.options].map(option => ({
              value: option.value,
              label: option.textContent,
            })),
            mobileValue: document.querySelector("#conversationMobileScopeFilter")?.value,
            visibleTitles: [...document.querySelectorAll("#conversationList .conversation-title")]
              .map(node => node.textContent),
            filterMeta: document.querySelector("#conversationFilterMeta")?.textContent,
          };
        }
        """
    )


def agent_stream_reading_state(page: Page) -> dict[str, Any]:
    return page.evaluate(
        """
        async () => {
          const messages = document.querySelector("#messages");
          const requiredFunctions = [
            "addMessage",
            "renderGuardedPartialAnswer",
            "renderStreamingProgress",
            "renderVerifiedAnswerProgressively",
          ];
          const missingFunctions = requiredFunctions.filter(
            name => typeof window[name] !== "function"
          );
          if (!messages || missingFunctions.length) {
            return {
              ready: false,
              missingFunctions,
              reason: messages ? "流式阅读函数未加载" : "消息区未加载",
            };
          }

          messages.innerHTML = "";
          messages.style.height = "240px";
          messages.style.maxHeight = "240px";
          messages.style.overflowY = "auto";
          for (let index = 0; index < 7; index += 1) {
            const history = window.addMessage(
              "agent",
              `历史研究 ${index + 1}：${"这是一段用于验证长对话滚动位置的内容。".repeat(8)}`
            );
            history.style.minHeight = "150px";
          }

          const pending = window.addMessage("agent", "正在生成…", true);
          state.pendingAgentRequests.set("__browser_smoke__", {node: pending});
          const partialText = [
            "先说结论：收入增长，但利润和现金流仍有压力。",
            "毛利率可以理解为每一百元收入扣除直接成本后还剩多少。",
          ].join("\\n\\n");
          window.renderGuardedPartialAnswer(pending, partialText);
          const partialBeforeProgress = pending.querySelector(".message-body")?.innerText || "";
          window.renderStreamingProgress(pending, "正在继续核对证据…");
          const partialAfterProgress = pending.querySelector(".message-body")?.innerText || "";

          messages.scrollTop = messages.scrollHeight;
          const scrollTopBeforeUser = messages.scrollTop;
          messages.dispatchEvent(new WheelEvent("wheel", {
            bubbles: true,
            cancelable: true,
            deltaY: -240,
          }));
          messages.scrollTop = Math.max(0, scrollTopBeforeUser - 180);
          const scrollTopAfterUser = messages.scrollTop;

          window.renderGuardedPartialAnswer(
            pending,
            `${partialText}\\n\\n存货增加意味着资金更多压在尚未销售的产品和原材料上。`
          );
          const scrollTopAfterPartialUpdate = messages.scrollTop;

          let progressiveReplaySeen = false;
          const observer = new MutationObserver(() => {
            if (pending.classList.contains("verified-progressive-answer")) {
              progressiveReplaySeen = true;
            }
          });
          observer.observe(pending, {
            attributes: true,
            childList: true,
            subtree: true,
          });
          const renderStartedAt = performance.now();
          const finalText = `${partialText}\\n\\n存货增加意味着资金更多压在尚未销售的产品和原材料上。\\n\\n下一步重点核对半年报里的经营现金流和存货变化。`;
          await window.renderVerifiedAnswerProgressively(pending, finalText);
          await Promise.resolve();
          const finalRenderMs = performance.now() - renderStartedAt;
          observer.disconnect();
          const scrollTopAfterFinal = messages.scrollTop;
          state.pendingAgentRequests.delete("__browser_smoke__");

          return {
            ready: true,
            guardedPartialVisible: pending.dataset.guardedPartialVisible === "true",
            progressPreservedPartial:
              partialAfterProgress === partialBeforeProgress
              && !pending.querySelector(".agent-progress-card"),
            userNavigated: pending.dataset.userNavigatedDuringRun === "true",
            scrollTopBeforeUser,
            scrollTopAfterUser,
            scrollPreservedAfterPartial:
              Math.abs(scrollTopAfterPartialUpdate - scrollTopAfterUser) <= 1,
            scrollPreservedAfterFinal:
              Math.abs(scrollTopAfterFinal - scrollTopAfterUser) <= 1,
            finalAnswerVisible: pending.dataset.finalAnswerVisible === "true",
            finalAnswerMatches: pending.querySelector(".message-body")?.innerText === finalText,
            progressiveReplaySeen,
            finalRenderMs: Math.round(finalRenderMs * 10) / 10,
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
    screening_candidate_disclosure = {}
    agent_stream_reading = {}
    review_structure = {}
    populated_review_structure = {}
    market_review_structure = {}
    market_overview_structure = {}
    account_structure = {}
    account_risk_profile = {}
    agent_landing = {}
    agent_quick_actions = {}
    agent_conversation_scope = {}
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
        screening_candidate_disclosure = screening_candidate_disclosure_state(page)
        screening_structure = {
            "default": default_state,
            "loading": loading_state,
            "strategy": strategy_state,
            "restored": restored_state,
            "panel_visible_seconds": round(panel_visible_seconds, 3),
            "strategy_ready_seconds": round(strategy_ready_seconds, 3),
        }
    if check.name == "reviews":
        page.wait_for_function(
            "!document.querySelector('#tradeReviewSummary')?.textContent?.includes('正在')"
        )
        review_structure = review_section_state(page)
        page.evaluate(
            """
            () => renderTradeReviewCenterDetail({
              id: "browser-review-detail",
              symbol: "000063.SZ",
              name: "中兴通讯",
              status: "draft",
              horizon_sessions: 3,
              created_at: "2026-07-28T10:00:00+08:00",
              operation: {
                operation_type: "reduce",
                operated_at: "2026-07-23T10:00:00+08:00",
                price: "35.90",
                quantity: "100",
                reason_text: "经营现金流尚未改善，订单兑现仍需核验，所以按计划减少100股。"
              },
              action_plan: {
                id: "browser-plan-detail",
                trigger_text: "经营现金流继续恶化时重新评估，并在操作前核验订单兑现。",
                target_quantity: "100"
              },
              price_observation: {
                operation_price: "35.90",
                required_sessions: 3,
                end_price: "34.03",
                end_date: "2026-07-28",
                price_change_pct: "-5.21",
                summary: "操作价35.90；第3个后续交易日复权收盘34.03，价格变化-5.21%。价格结果不自动代表逻辑对错。"
              },
              current_version: {
                version_no: 1,
                created_source: "ai",
                logic_result: "操作时保存的记录缺少经营现金流和订单核验，当前无法确认原判断是否成立。",
                plan_deviation: "原计划要求经营现金流继续恶化，但实际记录只写尚未改善，触发条件仍需确认。",
                improvement_text: "下次由用户自己写清可核验条件、数据来源，并随操作记录一并保存。",
                bias_tags: ["证据未留档", "触发条件待确认"]
              }
            }, null)
            """
        )
        populated_review_structure = populated_review_detail_state(page)
    if check.name == "market-reviews":
        market_review_structure = market_review_section_state(page)
    if check.name == "today":
        page.wait_for_function(
            "document.querySelectorAll('#marketQuickGrid .market-quick-card').length === 4"
        )
        page.wait_for_function(
            "!document.querySelector('#marketQuickTitle')?.textContent?.includes('一眼看懂')"
        )
        page.wait_for_function(
            "document.querySelectorAll('#articleFeed .article-item').length > 0"
        )
        market_overview_structure = market_overview_state(page)
    if check.name == "account":
        page.wait_for_function(
            "document.querySelectorAll('.risk-profile-question').length === 7 "
            "&& !document.querySelector('#riskProfileStatus')?.textContent?.includes('正在读取')"
        )
        account_structure = account_section_state(page)
        account_risk_profile = account_risk_profile_states(page)
        page.reload(wait_until="domcontentloaded")
        page.locator(check.ready_selector).wait_for(state="visible")
        wait_for_content(page, check.content_selector)
    if check.name == "agent":
        agent_landing = agent_landing_state(page)
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
    if check.name == "agent":
        agent_quick_actions = agent_quick_actions_state(page)
        agent_stream_reading = agent_stream_reading_state(page)
        agent_conversation_scope = agent_conversation_scope_state(page)
    result = {
        "name": check.name,
        "path": check.path,
        "url": page.url,
        "title": page.title(),
        "overflow": overflow,
        "mobile_core_widths": mobile_widths,
        "screening_progressive_disclosure": screening_structure,
        "screening_candidate_disclosure": screening_candidate_disclosure,
        "agent_stream_reading": agent_stream_reading,
        "review_structure": review_structure,
        "populated_review_structure": populated_review_structure,
        "market_review_structure": market_review_structure,
        "market_overview_structure": market_overview_structure,
        "account_structure": account_structure,
        "account_risk_profile": account_risk_profile,
        "agent_landing": agent_landing,
        "agent_quick_actions": agent_quick_actions,
        "agent_conversation_scope": agent_conversation_scope,
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
    if screening_candidate_disclosure:
        if not (
            screening_candidate_disclosure.get("cardCount") == 2
            and screening_candidate_disclosure.get("coreMetricCounts") == [3, 3]
            and screening_candidate_disclosure.get("cardDetailsClosed")
            and screening_candidate_disclosure.get("ruleDetailsClosed")
        ):
            problems.append("条件选股候选没有保持三项核心指标与默认折叠")
        if not (
            screening_candidate_disclosure.get("firstFullMetricCount", 0) >= 6
            and screening_candidate_disclosure.get("firstReasonCount") == 3
            and screening_candidate_disclosure.get("firstSummary") == "查看完整数据与入选依据"
        ):
            problems.append("条件选股完整数据或入选依据没有保留在展开区")
        if not (
            "近期强于行业" in screening_candidate_disclosure.get("profileTitle", "")
            and "先核验" in screening_candidate_disclosure.get("firstPrompt", "")
            and "适合" in screening_candidate_disclosure.get("profileHint", "")
        ):
            problems.append("条件选股模板用途或逐股核验提示不可读")
        if viewport.width <= 390 and float(
            screening_candidate_disclosure.get("firstCardWidth") or 0
        ) < 300:
            problems.append("390px 条件选股候选卡宽度不足")
        if strategy_state.get("sectionLabels") != ["按条件选股", "李总策略"]:
            problems.append("透明选股分区仍使用内部术语或标签顺序异常")
        if strategy_state.get("generalHeading") != "按条件选股":
            problems.append("通用选股标题仍使用内部术语")
        if strategy_state.get("strategyKicker") != "规则公开 · 每项可核验":
            problems.append("李总策略仍显示英文内部标签")
        if viewport.width <= 390 and strategy_state.get("strategyTabsFlexWrap") != "wrap":
            problems.append("390px 李总策略结果分类仍被横向隐藏")
    if agent_stream_reading:
        required_agent_states = {
            "ready": "对话流式阅读测试没有成功初始化",
            "guardedPartialVisible": "通过后端守卫的流式正文没有显示",
            "progressPreservedPartial": "后续进度事件覆盖了已显示的流式正文",
            "userNavigated": "用户滚轮操作没有停止自动跟随",
            "scrollPreservedAfterPartial": "流式正文更新后抢回了用户滚动位置",
            "scrollPreservedAfterFinal": "最终回答到达后抢回了用户滚动位置",
            "finalAnswerVisible": "最终回答没有完成显示",
            "finalAnswerMatches": "最终回答正文与通过校验的内容不一致",
        }
        for key, copy in required_agent_states.items():
            if not agent_stream_reading.get(key):
                problems.append(copy)
        if agent_stream_reading.get("progressiveReplaySeen"):
            problems.append("已有安全流式正文仍被清空后逐段重放")
    if agent_landing:
        if not agent_landing.get("entryActive") or not agent_landing.get("hubVisible"):
            problems.append("新建对话没有进入清晰的开始研究状态")
        if agent_landing.get("cardTitles") != [
            "看今天大盘",
            "研究一只股票",
            "按规则选股",
            "比较基金与 ETF",
        ]:
            problems.append("新建对话入口标题不直白、缺失或顺序异常")
        if not agent_landing.get("allCardsInsideHub"):
            problems.append("新建对话仍有入口藏在内部滚动区域之外")
        if agent_landing.get("hubScrollHeight", 0) > agent_landing.get("hubClientHeight", 0) + 1:
            problems.append("新建对话入口仍需滚动才能发现全部功能")
        if float(agent_landing.get("minCardTitleFontSize") or 0) < 14:
            problems.append("新建对话入口标题字号小于14px")
        if float(agent_landing.get("minCardCopyFontSize") or 0) < 11:
            problems.append("新建对话入口说明字号小于11px")
        if not all(
            agent_landing.get(key)
            for key in (
                "contextHidden",
                "messagesHidden",
                "quickActionsHidden",
                "researchBarHidden",
                "mobileFilterHidden",
                "composerVisible",
            )
        ):
            problems.append("新建对话仍同时展示重复欢迎层、空研究框或历史筛选")
        if agent_landing.get("composerBottom", 0) > agent_landing.get("viewportHeight", 0) + 1:
            problems.append("新建对话输入框和发送区超出当前视口")
    if agent_quick_actions:
        collapsed = agent_quick_actions["collapsed"]
        expanded = agent_quick_actions["expanded"]
        restored = agent_quick_actions["restored"]
        expected_visible = [
            "大盘解读",
            "个股分析",
            "行业板块",
            "自选股变化",
            "基金与 ETF",
            "财报公告",
            "多股比较",
            "反方风险",
            "操作前检查",
            "全部工具",
        ]
        if collapsed.get("groupLabels") != ["常用问题", "专项工具"]:
            problems.append("对话快捷入口没有区分常用问题与专项工具")
        if collapsed.get("visibleButtonLabels") != expected_visible:
            problems.append("对话首屏快捷能力缺失、重复或顺序异常")
        if collapsed.get("scrollWidth", 0) > collapsed.get("clientWidth", 0) + 1:
            problems.append("对话首屏快捷能力仍被横向裁切")
        if collapsed.get("scrollHeight", 0) > collapsed.get("clientHeight", 0) + 1:
            problems.append("对话首屏快捷能力仍被纵向裁切")
        if float(collapsed.get("minButtonFontSize") or 0) < 12:
            problems.append("对话快捷按钮字号小于12px")
        if float(collapsed.get("minLabelFontSize") or 0) < 11:
            problems.append("对话快捷分组字号小于11px")
        if not expanded.get("expanded") or expanded.get("hiddenSecondaryCount"):
            problems.append("全部工具不能展开隐藏的专项能力")
        if "收起工具" not in expanded.get("visibleButtonLabels", []):
            problems.append("全部工具展开后缺少明确收起入口")
        if restored.get("expanded") or restored.get("visibleButtonLabels") != expected_visible:
            problems.append("专项工具收起后没有恢复稳定首屏")
    if agent_conversation_scope:
        if agent_conversation_scope.get("total") != 67:
            problems.append("历史对话分类验收没有覆盖67条列表")
        if agent_conversation_scope.get("inferredFund") != "funds":
            problems.append("基金与ETF旧对话仍被错误归入个股")
        if agent_conversation_scope.get("retirementFund") != "funds":
            problems.append("退休理财旧对话仍被错误归入选股")
        if agent_conversation_scope.get("stock") != "stock":
            problems.append("基金分类修复破坏了真实个股对话分类")
        if agent_conversation_scope.get("explicitFund") != "funds":
            problems.append("后端持久化的基金分类没有优先生效")
        option_values = [
            item.get("value")
            for item in agent_conversation_scope.get("desktopOptions") or []
        ]
        if "funds" not in option_values:
            problems.append("桌面历史筛选缺少基金理财入口")
        if agent_conversation_scope.get("mobileValue") != "funds":
            problems.append("桌面与390px历史筛选没有同步基金理财状态")
        expected_fund_titles = {
            "基金和ETF有什么区别",
            "我快退休了，有一笔闲钱",
            "分析股票还是基金",
        }
        if set(agent_conversation_scope.get("visibleTitles") or []) != expected_fund_titles:
            problems.append("基金理财筛选混入其他研究类型或遗漏旧对话")
        disclosure = agent_conversation_scope.get("historyDisclosure") or {}
        initial_history = disclosure.get("initial") or {}
        expanded_history = disclosure.get("expanded") or {}
        restored_history = disclosure.get("restored") or {}
        if initial_history.get("topics") != 9 or initial_history.get("rows") != 9:
            problems.append("最近对话默认视图没有限制为8个主题并固定当前旧会话")
        if not initial_history.get("activeVisible"):
            problems.append("当前打开的旧会话在最近对话视图中被隐藏")
        if initial_history.get("toggleText") != "查看全部历史（67）":
            problems.append("最近对话缺少清晰的全部历史入口")
        if expanded_history.get("topics") != 67 or expanded_history.get("rows") != 67:
            problems.append("查看全部历史没有恢复67条完整对话")
        if expanded_history.get("toggleText") != "只看最近对话":
            problems.append("全部历史展开后缺少明确的收起入口")
        if restored_history.get("topics") != 9 or restored_history.get("rows") != 9:
            problems.append("全部历史收起后没有恢复最近对话视图")
        if restored_history.get("scrollTop") != 0:
            problems.append("全部历史收起后没有回到最新对话顶部")
        if not disclosure.get("searchFoundOld"):
            problems.append("历史搜索被最近对话限制截断，无法找到旧会话")
        if disclosure.get("filteringTogglePresent"):
            problems.append("分类筛选结果仍混入无关的全部历史开关")
    if review_structure:
        if review_structure.get("eyebrow") != "研究复盘":
            problems.append("研究复盘标题仍使用英文或内部标签")
        if not review_structure.get("itemCount"):
            if not review_structure.get("emptyOnboarding"):
                problems.append("空交易复盘仍展示无效搜索筛选或双栏空状态")
            if review_structure.get("sidebarVisible"):
                problems.append("没有交易记录时仍展示搜索和状态筛选")
            if review_structure.get("onboardingAction") != "去记录一次真实操作":
                problems.append("空交易复盘没有提供唯一且直白的下一步")
            expected_steps = ["选择一只关注股票", "记录减仓或卖出", "等待后续交易日"]
            if review_structure.get("onboardingSteps") != expected_steps:
                problems.append("空交易复盘没有解释真实的三步形成流程")
            if viewport.width <= 390 and any(
                width < 280 for width in review_structure.get("onboardingStepWidths") or []
            ):
                problems.append("移动端复盘步骤仍被横向挤压，标题和说明无法正常阅读")
    if populated_review_structure:
        expected_sections = [
            "后续价格事实",
            "当时为什么操作",
            "判断依据复盘",
            "与原计划的差异",
            "下次怎么做得更好",
            "待你确认的记录问题",
        ]
        if populated_review_structure.get("sectionTitles") != expected_sections:
            problems.append("有记录复盘详情仍存在重复分区或内部式标题")
        if populated_review_structure.get("metricLabels") != [
            "操作价",
            "第 3 日收盘",
            "价格变化",
            "数据截至",
        ]:
            problems.append("复盘价格事实没有合并成单一可读区域")
        if populated_review_structure.get("priceDetailsOpen"):
            problems.append("复盘价格计算口径没有默认折叠")
        if populated_review_structure.get("priceDetailsLabel") != "查看价格计算口径":
            problems.append("复盘价格口径入口标题不清楚")
        body_text = str(populated_review_structure.get("bodyText") or "")
        if any(term in body_text for term in ("thesis", "watch_items", "确认偏差")):
            problems.append("复盘详情仍展示内部字段名或未经证实的心理诊断")
        if populated_review_structure.get("titleFontSize", 0) < 13:
            problems.append("复盘详情分区标题字号过小")
        if populated_review_structure.get("copyFontSize", 0) < 12:
            problems.append("复盘详情正文字号过小")
    if market_review_structure:
        boundary = str(market_review_structure.get("boundary") or "")
        summaries = market_review_structure.get("summaries") or []
        if "MVP" in boundary or "后续将" in boundary:
            problems.append("市场复盘仍向普通用户展示内部版本规划")
        if any("跨市场分时" in str(summary) for summary in summaries):
            problems.append("市场复盘摘要仍未使用已保存的A股结构事实")
    if market_overview_structure:
        if market_overview_structure.get("title") != "A 股今天怎么样":
            problems.append("市场总览仍使用抽象标题，没有直接回答A股今天怎么样")
        if market_overview_structure.get("quickLabels") != [
            "市场状态",
            "全市场涨跌中位数",
            "当日累计成交额",
            "领涨方向",
        ]:
            problems.append("A股一眼看懂缺少涨跌、成交或领涨方向")
        quick_text = " ".join(market_overview_structure.get("quickText") or [])
        if "上涨" not in quick_text or "下跌" not in quick_text or "成交" not in quick_text:
            problems.append("A股首屏摘要没有直接展示市场广度和成交事实")
        if market_overview_structure.get("articleCount", 0) < 1 or any(
            not str(item).startswith("大盘洞察")
            for item in market_overview_structure.get("articleTypes") or []
        ):
            problems.append("市场总览仍把个股报告或机会混入市场文章")
        if market_overview_structure.get("insightTabCount"):
            problems.append("市场总览仍要求用户在大盘、个股和机会之间筛选")
        if market_overview_structure.get("watchlistPulseExists"):
            problems.append("A股市场明细仍混入重复的个人关注模块")
        if market_overview_structure.get("askTitle") != "问 Agent：今天市场发生了什么？":
            problems.append("市场Agent入口标题不够直接")
        expected_columns = 2 if viewport.width <= 390 else 4
        if market_overview_structure.get("quickColumns") != expected_columns:
            problems.append("A股一眼看懂在当前视口没有保持清晰分组")
        if float(market_overview_structure.get("articleSummaryFontSize") or 0) < 13:
            problems.append("市场文章摘要字号小于13px")
    if account_structure:
        if account_structure.get("title") != "我的研究空间":
            problems.append("个人中心重复标题没有改成任务语言")
        if account_structure.get("detailsOpen"):
            problems.append("服务、隐私与版本说明默认展开")
        if "需要排查账户或数据状态时再展开" not in str(
            account_structure.get("summary") or ""
        ):
            problems.append("服务说明缺少渐进披露提示")
        if float(account_structure.get("rowFontSize") or 0) < 12:
            problems.append("个人中心技术字段字号小于12px")
        if float(account_structure.get("copyFontSize") or 0) < 11:
            problems.append("个人中心说明文字字号小于11px")
    if account_risk_profile:
        initial = account_risk_profile.get("initial") or {}
        incomplete = account_risk_profile.get("incomplete") or {}
        modified = account_risk_profile.get("modified") or {}
        draft = account_risk_profile.get("draft") or {}
        confirmed = account_risk_profile.get("confirmed") or {}
        if initial.get("questionCount") != 7:
            problems.append("风险画像没有完整展示7个通俗问题")
        if initial.get("progressText") != "已回答 0/7" or initial.get(
            "progressNow"
        ) != 0:
            problems.append("风险画像初始回答进度不正确")
        if not initial.get("confirmDisabled"):
            problems.append("风险画像未保存时仍可直接确认")
        if incomplete.get("missingQuestionCount") != 1 or not incomplete.get(
            "activeRiskKey"
        ):
            problems.append("风险画像缺失答案没有定位并聚焦第一道问题")
        if "还有 7 题未回答" not in str(incomplete.get("status") or ""):
            problems.append("风险画像缺失答案没有给出明确数量提示")
        if modified.get("progressText") != "已回答 7/7" or "保存并核对" not in str(
            modified.get("nextStep") or ""
        ):
            problems.append("风险画像填写完成后没有明确引导保存核对")
        if "有修改" not in str(modified.get("state") or ""):
            problems.append("风险画像答案修改后没有显示待保存状态")
        if draft.get("confirmDisabled") or "尚未用于 AI" not in str(
            draft.get("status") or ""
        ):
            problems.append("风险画像草稿状态没有明确等待用户确认")
        if not confirmed.get("advisorVisible") or confirmed.get(
            "advisorText"
        ) != "去问金融顾问":
            problems.append("风险画像确认后缺少直达金融顾问入口")
        if "金融顾问" not in str(confirmed.get("nextStep") or ""):
            problems.append("风险画像确认后没有说明下一步用途")
        if not all(
            "complete" in str(item)
            for item in confirmed.get("stepClasses") or []
        ):
            problems.append("风险画像确认后流程状态没有完整结束")
        expected_step_columns = 1 if viewport.width <= 390 else 3
        if initial.get("stepColumns") != expected_step_columns:
            problems.append("风险画像三步流程在当前视口排版异常")
        if float(initial.get("questionFontSize") or 0) < 13 or float(
            initial.get("optionFontSize") or 0
        ) < 12:
            problems.append("风险画像问题或选项字号过小")
        if any(
            float(value or 0) < 40
            for value in initial.get("buttonMinHeights") or []
        ):
            problems.append("风险画像操作按钮高度小于40px")
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
