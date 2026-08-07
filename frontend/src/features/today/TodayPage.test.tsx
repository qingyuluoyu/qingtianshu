import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import breadthFixture from "./__fixtures__/breadth-real.json";
import { parseBreadth, parseCapitalFlow, parseDataHealth, parseGlobalIndices, parseIndices, parseLatestResearchReports, parseLiveMarkets, parseMarketAnomalies, parseOverview, parsePositions, parseResearchActions, parseResearchChanges, parseSectors, parseWatchlistBrief } from "./adapters";
import { TodayPage } from "./TodayPage";
import { todayQueryKeys } from "./queries";

function client(history = false) {
  const result = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  result.setQueryData(todayQueryKeys.overview, parseOverview({ contract_version: "today_overview_v1", generated_at: "2026-08-06T07:00:00Z", session: { key: "closed", label: "收盘后", exchange_status: "closed", exchange_label: "已收盘", market_local_time: "2026-08-06T15:00:00+08:00" }, summary: { headline: "真实数据合同", priority_count: 0, related_change_count: 0, market_date: "2026-08-06" }, priority_items: { items: [], total_visible: 0, ranking_method: "后端排序", empty_message: "当前没有需要立即处理的个人研究事项。" }, coverage: { status: "ready" }, themes: [], warnings: [], boundary: "不构成买卖建议。" }));
  result.setQueryData(todayQueryKeys.indices, parseIndices({ indices: ["000001.SS", "399001.SZ", "399006.SZ", "000300.SS", "000688.SS", "000905.SS"].map((symbol) => ({ symbol, status: "available", metrics: { latest_close: 100, change_1d: 1, return_1d_pct: 1 }, market_timestamp: "2026-08-06T07:00:00Z" })) }));
  result.setQueryData(todayQueryKeys.breadth, parseBreadth({ ...breadthFixture, ...(history ? { turnover_history: [{ date: "2026-08-05", amount_100m_cny: 26000 }, { date: "2026-08-06", amount_100m_cny: 25470.71 }] } : {}) }));
  result.setQueryData(todayQueryKeys.sectors, parseSectors({ sectors: [{ code: "BK1", name: "测试行业", pct_change: null, main_net_inflow: null }] }));
  result.setQueryData(todayQueryKeys.watchlistBrief, parseWatchlistBrief({ generated_at: "2026-08-06T07:00:00Z", coverage: { requested: 0, available: 0 }, items: [] }));
  result.setQueryData(todayQueryKeys.researchActions, parseResearchActions({ generated_at: "2026-08-06T07:00:00Z", items: [], boundary: "不构成买卖建议。" }));
  result.setQueryData(todayQueryKeys.researchChanges, parseResearchChanges({ generated_at: "2026-08-06T07:00:00Z", coverage: { requested: 0, with_change_archive: 0 }, items: [], boundary: "不构成买卖建议。" }));
  result.setQueryData(todayQueryKeys.dataHealth, parseDataHealth({ status: "ready", user_label: "正常", created_at: "2026-08-06T07:00:00Z", summary: { total: 1, healthy: 1, attention: 0, critical: 0 }, checks: [] }));
  result.setQueryData(todayQueryKeys.globalIndices, parseGlobalIndices({ indices: [] }));
  result.setQueryData(todayQueryKeys.liveMarkets, parseLiveMarkets({ markets: [] }));
  result.setQueryData(todayQueryKeys.capitalFlow, parseCapitalFlow({ status: "available", market_timestamp: "2026-08-06T07:00:00Z", is_stale: false, summary: { main_net_inflow_100m_cny: -128.45, unit: "CNY_100m_yuan" }, points: [{ time: "09:30", main_net_inflow_100m_cny: -12.5 }, { time: "15:00", main_net_inflow_100m_cny: -128.45 }], method: "主力资金口径；北向资金 2024-08 起港交所停披。", warnings: [] }));
  result.setQueryData(todayQueryKeys.anomalies, parseMarketAnomalies({ status: "available", market_timestamp: "2026-08-06T07:00:00Z", items: [{ symbol: "sh603019", name: "中科曙光", kind: "快速拉升", pct_change: 8.65, amount_100m_cny: 125.62, tick_time: "10:36:00" }] }));
  result.setQueryData(todayQueryKeys.researchReports, parseLatestResearchReports({ status: "ready", items: [{ symbol: "000063.SZ", name: "中兴通讯", title: "中兴通讯：算力基建加速", institution: "中信证券", researchers: "张三", published_at: "2026-08-03", rating: "买入", forecast_eps: 1.85 }] }));
  result.setQueryData(todayQueryKeys.positions, parsePositions({ contract_version: "position_ledger_v1", status: "ready", items: [{ workspace_id: "w-1", symbol: "000063.SZ", name: "中兴通讯", status: "open", current: { quantity: 200, cost_basis: 6400, average_cost: 32 } }] }));
  return result;
}
function page(queryClient: QueryClient) { return render(<QueryClientProvider client={queryClient}><MemoryRouter><TodayPage authenticated /></MemoryRouter></QueryClientProvider>); }
afterEach(cleanup);

describe("TodayPage runtime closure", () => {
  it("keeps the five required index cards in order and removes CSI 500", () => { page(client()); expect(screen.getAllByRole("article").slice(0, 5).map((node) => node.textContent)).toEqual(expect.arrayContaining([expect.stringContaining("上证综指"), expect.stringContaining("深证成指"), expect.stringContaining("创业板指"), expect.stringContaining("沪深300"), expect.stringContaining("科创50")])); expect(screen.queryByText("中证500")).not.toBeInTheDocument(); });
  it("keeps turnover headline and precise comparison but no chart when real history is absent", () => { page(client()); expect(screen.getByTestId("turnover-card")).toHaveTextContent("25,470.71 亿"); expect(screen.getByTestId("turnover-card")).toHaveTextContent("-4.94%"); expect(screen.queryByText("近日成交额（亿元）")).not.toBeInTheDocument(); });
  it("renders a turnover chart only with at least two actual history points", () => { page(client(true)); expect(screen.getByText("近日成交额（亿元）")).toBeInTheDocument(); });
  it("restores capital flow, anomalies, research reports and the positions tab with passthrough values", () => {
    page(client());
    expect(screen.getByRole("region", { name: "资金流向" })).toHaveTextContent("-128.45 亿");
    expect(screen.getByRole("region", { name: "资金流向" })).toHaveTextContent(/北向资金 2024-08 起港交所停披/);
    expect(screen.getByRole("region", { name: "异动机会 / 风险提示" })).toHaveTextContent("中科曙光");
    expect(screen.getByRole("region", { name: "异动机会 / 风险提示" })).toHaveTextContent("+8.65%");
    expect(screen.getByRole("region", { name: "今日研究报告" })).toHaveTextContent("中兴通讯：算力基建加速");
    expect(screen.getByRole("region", { name: "今日研究报告" })).toHaveTextContent(/中信证券/);
    expect(screen.getByRole("region", { name: "今日研究报告" })).toHaveTextContent(/1\.85 元\/股/);
    const changesRegion = screen.getByRole("region", { name: "我的股票新变化" });
    expect(changesRegion).toHaveTextContent("暂无研究变化");
    expect(screen.queryByText("6,400.00")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "持仓" }));
    expect(changesRegion).toHaveTextContent("6,400.00");
    expect(changesRegion).toHaveTextContent("32.00");
  });
  it("keeps a failed restored module isolated inside its own ModuleCard", () => {
    const queryClient = client();
    const fail = (key: readonly unknown[]) => queryClient.getQueryCache().find({ queryKey: key, exact: true })?.setState({ status: "error", error: new Error("simulated 500"), fetchStatus: "idle", data: undefined });
    fail(todayQueryKeys.capitalFlow);
    fail(todayQueryKeys.anomalies);
    page(queryClient);
    expect(screen.getByRole("region", { name: "异动机会 / 风险提示" })).toHaveTextContent(/本模块暂时不可用/);
    expect(within(screen.getByRole("region", { name: "异动机会 / 风险提示" })).queryByText("中科曙光")).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: "板块热度" })).toHaveTextContent("测试行业");
    expect(screen.getByRole("region", { name: "资金流向" })).toHaveTextContent(/本模块暂时不可用/);
    expect(screen.getByRole("region", { name: "今日研究报告" })).toHaveTextContent("中兴通讯：算力基建加速");
  });
  it("uses truthful personal empty state and never renders null industry inflow as zero", () => { page(client()); expect(screen.getByText("当前没有需要立即处理的个人研究事项。")).toBeInTheDocument(); expect(screen.getByText("暂无研究变化")).toBeInTheDocument(); expect(screen.getByText("测试行业")).toBeInTheDocument(); expect(screen.queryByText("0.00亿")).not.toBeInTheDocument(); });
});
