import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TodayPage } from "./TodayPage";
import {
  parseBreadth,
  parseDataHealth,
  parseIndices,
  parseOverview,
  parseResearchActions,
  parseResearchChanges,
  parseSectors,
  parseWatchlistBrief,
} from "./adapters";
import { todayQueryKeys } from "./queries";

function overview(items: unknown[] = []) {
  return parseOverview({
    contract_version: "today_overview_v1",
    generated_at: "2026-08-04T02:35:06+00:00",
    session: { key: "intraday", label: "盘中", exchange_status: "open", exchange_label: "交易中", market_local_time: "2026-08-04T10:35:06+08:00" },
    summary: { headline: "上涨家数占优，优先核验已有研究事项。", priority_count: items.length, related_change_count: 1, market_date: "2026-08-04" },
    priority_items: { items, total_visible: items.length, ranking_method: "后端确定性排序", empty_message: "当前没有需要立即处理的个人研究事项。" },
    coverage: { status: "ready", components: {} },
    warnings: [],
    boundary: "所有事项均不构成买卖、仓位或收益建议。",
  });
}

function hydratedClient() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(todayQueryKeys.overview, overview([
    { id: "a-1", kind: "research_action", title: "核验财报证据", detail: "对照正式披露", symbol: "000063.SZ", status_label: "需要复核", rank_reason: "高风险研究条件已经触发" },
  ]));
  client.setQueryData(todayQueryKeys.indices, parseIndices({ generated_at: "2026-08-04T02:35:07+00:00", indices: [
    ["000001.SS", "上证综指", 3809.66, -0.5897], ["399001.SZ", "深证成指", 13448.29, -0.9621],
    ["399006.SZ", "创业板指", 3302.55, -1.2384], ["000688.SS", "科创50", 1552.89, -5.0778],
    ["000300.SS", "沪深300", 4543.18, -0.9812],
  ].map(([symbol, name, latest_close, return_1d_pct]) => ({ symbol, name, status: "available", metrics: { latest_close, return_1d_pct }, market_timestamp: "2026-08-03T01:30:00+00:00", is_stale: false })) }));
  client.setQueryData(todayQueryKeys.breadth, parseBreadth({ status: "available", market_date: "2026-08-04", market_timestamp: null, is_stale: false, breadth: { total: 5535, advancers: 3549, decliners: 1804, unchanged: 182, advance_ratio: 0.6412, decline_ratio: 0.3259, state: "上涨家数占优" }, turnover: { status: "available", total_amount_100m_cny: 10493.68, history_comparison: { status: "intraday_not_comparable" } }, distribution: { median_pct_change: 0.679 } }));
  client.setQueryData(todayQueryKeys.sectors, parseSectors({ market_timestamp: "2026-08-03T02:51:27+00:00", fetched_at: "2026-08-03T02:51:31+00:00", is_stale: true, warnings: ["upstream"], sectors: [{ code: "BK1318", name: "光伏主材", pct_change: 4.56, advancers: 2, decliners: 0 }] }));
  client.setQueryData(todayQueryKeys.watchlistBrief, parseWatchlistBrief({ generated_at: "2026-08-04T02:35:07+00:00", items: [], coverage: { requested: 0, available: 0 }, warnings: [] }));
  client.setQueryData(todayQueryKeys.researchActions, parseResearchActions({ generated_at: "2026-08-04T02:35:07+00:00", items: [], boundary: "不是交易指令。" }));
  client.setQueryData(todayQueryKeys.researchChanges, parseResearchChanges({ generated_at: "2026-08-04T02:35:08+00:00", items: [], events: [], coverage: { requested: 0, with_report: 0, with_change_archive: 0 }, boundary: "不是交易指令。" }));
  client.setQueryData(todayQueryKeys.dataHealth, parseDataHealth({ status: "degraded", user_label: "部分数据同步中", created_at: "2026-08-04T02:34:35+00:00", summary: { total: 67, healthy: 64, attention: 2, critical: 1 }, checks: [{ key: "filing:1", category: "fundamentals", status: "critical", label: "缺少当前报告期财报全文" }] }));
  return client;
}

function renderPage(client: QueryClient) {
  return render(<QueryClientProvider client={client}><MemoryRouter><TodayPage authenticated /></MemoryRouter></QueryClientProvider>);
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("TodayPage", () => {
  it("renders backend values, five index cards, stale state and research boundary", () => {
    renderPage(hydratedClient());
    expect(screen.getByRole("heading", { name: "今日观察" })).toBeInTheDocument();
    expect(screen.getByText("沪深300")).toBeInTheDocument();
    expect(screen.getByText("10,493.68 亿元")).toBeInTheDocument();
    expect(screen.getByText(/高风险研究条件已经触发/)).toBeInTheDocument();
    expect(screen.getByText("缓存 / 延迟数据")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "核验财报证据" })).toHaveAttribute("href", "/stocks/000063.SZ");
    expect(screen.getByText("部分数据同步中")).toBeInTheDocument();
    expect(screen.getByText(/不构成买卖、仓位或收益建议/)).toBeInTheDocument();
  });

  it("renders truthful empty states without fake market values", () => {
    const client = hydratedClient();
    client.setQueryData(todayQueryKeys.overview, overview());
    renderPage(client);
    expect(screen.getByText("当前没有需要立即处理的个人研究事项。")).toBeInTheDocument();
    expect(screen.getByText("暂无研究变化")).toBeInTheDocument();
    expect(screen.getByText("关注列表为空")).toBeInTheDocument();
  });

  it("shows module skeletons while requests are pending", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => undefined)));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderPage(client);
    expect(screen.getAllByText("正在读取…").length).toBeGreaterThan(2);
  });

});
