import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TodayPage } from "./TodayPage";
import {
  parseBreadth,
  parseCapitalFlow,
  parseDataHealth,
  parseGlobalIndices,
  parseIndexHistory,
  parseIndices,
  parseLatestResearchReports,
  parseLiveMarkets,
  parseMarketAnomalies,
  parseOverview,
  parsePositions,
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
    themes: [
      { key: "market_sentiment", title: "市场情绪", status: "ready", tone: "positive", summary: "上涨家数占优，情绪偏暖。", basis: "市场广度" },
      { key: "earnings_disclosure", title: "业绩披露", status: "ready", tone: "neutral", summary: "今日进入披露密集期。", basis: "公告日历" },
      { key: "concept_heat", title: "概念热度", status: "ready", tone: "negative", summary: "热门概念回落。", basis: "板块热度" },
      { key: "capital_flow", title: "资金流向", status: "unavailable", tone: "unknown", summary: "资金流数据源暂不可用。", basis: null },
    ],
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
    ["000001.SS", "上证综指", 3809.66, 9.31, -0.5897], ["399001.SZ", "深证成指", 13448.29, -33.08, -0.9621],
    ["399006.SZ", "创业板指", 3302.55, -14.01, -1.2384], ["000688.SS", "科创50", 1552.89, -6.55, -5.0778],
    ["000300.SS", "沪深300", 4543.18, 8.61, -0.9812], ["000905.SS", "中证500", 7414.52, -12.4, -1.0604],
  ].map(([symbol, name, latest_close, change_1d, return_1d_pct]) => ({ symbol, name, status: "available", metrics: { latest_close, change_1d, return_1d_pct }, market_timestamp: "2026-08-03T01:30:00+00:00", is_stale: false })) }));
  client.setQueryData(todayQueryKeys.breadth, parseBreadth({ status: "available", market_date: "2026-08-04", market_timestamp: null, is_stale: false, breadth: { total: 5535, advancers: 3549, decliners: 1804, unchanged: 182, advance_ratio: 0.6412, decline_ratio: 0.3259, unchanged_ratio: 0.0329, limit_up_count: 42, limit_down_count: 7, limit_method: "按板块规则近似判定", state: "上涨家数占优" }, turnover: { status: "available", total_amount_100m_cny: 10493.68, history_comparison: { status: "available", change_vs_previous_pct: -5.41 } }, distribution: { median_pct_change: 0.679, bins: { strong_advancers_ge_3: 512, mild_advancers_gt_0_lt_3: 3037, unchanged: 182, mild_decliners_lt_0_gt_neg3: 1500, strong_decliners_le_neg3: 304 }, bins_7: { le_neg7: 68, gt_neg7_le_neg3: 236, gt_neg3_lt_0: 1500, unchanged: 182, gt_0_lt_3: 3037, ge_3_lt_7: 400, ge_7: 112 } }, coverage: { coverage_ratio: 0.9671 }, turnover_history: [{ date: "2026-07-31", amount_100m_cny: 25590.66 }, { date: "2026-08-04", amount_100m_cny: 10493.68 }] }));
  client.setQueryData(todayQueryKeys.sectors, parseSectors({ market_timestamp: "2026-08-03T02:51:27+00:00", fetched_at: "2026-08-03T02:51:31+00:00", is_stale: true, warnings: ["upstream"], sectors: [{ code: "BK1318", name: "光伏主材", pct_change: 4.56, advancers: 2, decliners: 0, main_net_inflow: 12_562_000_000 }] }));
  client.setQueryData(todayQueryKeys.watchlistBrief, parseWatchlistBrief({ generated_at: "2026-08-04T02:35:07+00:00", items: [], coverage: { requested: 0, available: 0 }, warnings: [] }));
  client.setQueryData(todayQueryKeys.researchActions, parseResearchActions({ generated_at: "2026-08-04T02:35:07+00:00", items: [], boundary: "不是交易指令。" }));
  client.setQueryData(todayQueryKeys.researchChanges, parseResearchChanges({ generated_at: "2026-08-04T02:35:08+00:00", items: [], events: [], coverage: { requested: 0, with_report: 0, with_change_archive: 0 }, boundary: "不是交易指令。" }));
  client.setQueryData(todayQueryKeys.dataHealth, parseDataHealth({ status: "degraded", user_label: "部分数据同步中", created_at: "2026-08-04T02:34:35+00:00", summary: { total: 67, healthy: 64, attention: 2, critical: 1 }, checks: [{ key: "filing:1", category: "fundamentals", status: "critical", label: "缺少当前报告期财报全文" }] }));
  for (const symbol of ["000001.SS", "399001.SZ", "399006.SZ", "000688.SS", "000300.SS", "000905.SS"]) {
    client.setQueryData(todayQueryKeys.indexHistory(symbol), parseIndexHistory({ market_timestamp: "2026-08-03T07:00:00+00:00", points: Array.from({ length: 22 }, (_, index) => ({ timestamp: `2026-07-${String(index + 1).padStart(2, "0")}T01:30:00+00:00`, close: 3800 + index * 2 })) }));
  }
  client.setQueryData(todayQueryKeys.researchReports, parseLatestResearchReports({ status: "ready", items: [{ symbol: "000063.SZ", name: "中兴通讯", title: "中兴通讯：算力基建加速", institution: "中信证券", researchers: "张三", published_at: "2026-08-03", rating: "买入", forecast_eps: 1.85, summary: "摘要" }] }));
  client.setQueryData(todayQueryKeys.capitalFlow, parseCapitalFlow({
    status: "available",
    market_timestamp: "2026-08-04T07:00:00+00:00",
    is_stale: false,
    summary: { main_net_inflow_100m_cny: -128.45, unit: "CNY_100m_yuan" },
    points: [
      { time: "09:30", main_net_inflow_100m_cny: -12.5 },
      { time: "10:30", main_net_inflow_100m_cny: -60.2 },
      { time: "15:00", main_net_inflow_100m_cny: -128.45 },
    ],
    method: "主力资金口径；北向资金 2024-08 起港交所停披。",
    warnings: [],
  }));
  client.setQueryData(todayQueryKeys.positions, parsePositions({
    contract_version: "position_ledger_v1",
    status: "ready",
    items: [{ workspace_id: "w-1", symbol: "000063.SZ", name: "中兴通讯", status: "open", current: { quantity: 200, cost_basis: 6400, average_cost: 32 } }],
    warnings: [],
  }));
  client.setQueryData(todayQueryKeys.globalIndices, parseGlobalIndices({ indices: [
    { symbol: "^GSPC", name: "标普500", status: "available", metrics: { latest_close: 2348.6, return_1d_pct: 0.63 }, market_timestamp: "2026-08-04T20:00:00+00:00", is_stale: false },
    { symbol: "^IXIC", name: "纳斯达克综合", status: "available", metrics: { latest_close: 7726.0, return_1d_pct: -0.52 }, market_timestamp: "2026-08-04T20:00:00+00:00", is_stale: false },
    { symbol: "^DJI", name: "道琼斯工业指数", status: "available", metrics: { latest_close: 10432.0, return_1d_pct: -0.18 }, market_timestamp: "2026-08-04T20:00:00+00:00", is_stale: false },
  ] }));
  client.setQueryData(todayQueryKeys.liveMarkets, parseLiveMarkets({ markets: [
    { key: "dollar_index", name: "美元指数", status: "available", latest_price: 98.42, pct_change: -0.21, currency: "USD", market_timestamp: "2026-08-04T12:00:00+00:00", is_stale: false },
    { key: "london_gold", name: "伦敦金（现货黄金）", status: "available", latest_price: 2358.6, pct_change: 0.78, currency: "USD", market_timestamp: "2026-08-04T12:00:00+00:00", is_stale: false },
    { key: "brent_crude", name: "布伦特原油", status: "available", latest_price: 69.85, pct_change: 1.12, currency: "USD", market_timestamp: "2026-08-04T12:00:00+00:00", is_stale: false },
    { key: "us10y_yield", name: "美债10年收益率", status: "available", latest_price: 4.25, pct_change: 0.03, currency: "PCT", market_timestamp: "2026-08-04T12:00:00+00:00", is_stale: false },
  ] }));
  client.setQueryData(todayQueryKeys.anomalies, parseMarketAnomalies({ status: "available", market_timestamp: "2026-08-04T02:00:00+00:00", items: [{ symbol: "sh603019", name: "中科曙光", kind: "快速拉升", pct_change: 8.65, amount_100m_cny: 125.62, tick_time: "10:36:00" }] }));
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
  it("renders backend values, six index cards, stale state and research boundary", () => {
    renderPage(hydratedClient());
    expect(screen.getByRole("heading", { name: "今日观察" })).toBeInTheDocument();
    expect(screen.getByText("今天市场发生了什么？你应该关注哪些重点信号？")).toBeInTheDocument();
    expect(screen.getByText("沪深300")).toBeInTheDocument();
    expect(screen.getByText("中证500")).toBeInTheDocument();
    expect(screen.getByText("+9.31")).toBeInTheDocument();
    expect(screen.getByText("涨停家数")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();
    expect(screen.getByText("中科曙光")).toBeInTheDocument();
    expect(screen.getByText("快速拉升")).toBeInTheDocument();
    expect(screen.getByText(/近日成交额/)).toBeInTheDocument();
    expect(screen.getByText("10,493.68 亿")).toBeInTheDocument();
    expect(screen.getByText("-5.41%")).toBeInTheDocument();
    expect(screen.getByText("125.62亿")).toBeInTheDocument();
    expect(screen.getByText("中兴通讯：算力基建加速")).toBeInTheDocument();
    expect(screen.getByText(/中信证券/)).toBeInTheDocument();
    expect(screen.getByText("标普500")).toBeInTheDocument();
    expect(screen.getByText("伦敦金（现货黄金）")).toBeInTheDocument();
    expect(screen.getByText("美元指数")).toBeInTheDocument();
    expect(screen.getByText("布伦特原油")).toBeInTheDocument();
    expect(screen.getByText("美债10年收益率")).toBeInTheDocument();
    expect(screen.getByText("4.25%")).toBeInTheDocument();
    expect(screen.getByText("主力净流入")).toBeInTheDocument();
    expect(screen.getByText("-128.45 亿")).toBeInTheDocument();
    expect(screen.getByText(/北向资金 2024-08 起港交所停披/)).toBeInTheDocument();
    expect(screen.getByText("市场情绪")).toBeInTheDocument();
    expect(screen.getByText("上涨家数占优，情绪偏暖。")).toBeInTheDocument();
    expect(screen.getByText("资金流数据源暂不可用。")).toBeInTheDocument();
    expect(screen.getByText("我的持仓")).toBeInTheDocument();
    expect(screen.getByText("6,400.00")).toBeInTheDocument();
    expect(screen.getByText("32.00")).toBeInTheDocument();
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
