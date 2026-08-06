import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import breadthFixture from "./__fixtures__/breadth-real.json";
import { parseBreadth, parseDataHealth, parseGlobalIndices, parseIndices, parseLiveMarkets, parseOverview, parseResearchActions, parseResearchChanges, parseSectors, parseWatchlistBrief } from "./adapters";
import { shouldLoadDataHealth, TodayPage } from "./TodayPage";
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
  return result;
}
function page(queryClient: QueryClient) { return render(<QueryClientProvider client={queryClient}><MemoryRouter><TodayPage authenticated /></MemoryRouter></QueryClientProvider>); }
afterEach(cleanup);

describe("TodayPage runtime closure", () => {
  it("loads independent data health as soon as an authenticated session exists", () => {
    expect(shouldLoadDataHealth(true)).toBe(true);
    expect(shouldLoadDataHealth(false)).toBe(false);
  });

  it("keeps the five required index cards in order and removes CSI 500", () => { page(client()); expect(screen.getAllByRole("article").slice(0, 5).map((node) => node.textContent)).toEqual(expect.arrayContaining([expect.stringContaining("上证综指"), expect.stringContaining("深证成指"), expect.stringContaining("创业板指"), expect.stringContaining("沪深300"), expect.stringContaining("科创50")])); expect(screen.queryByText("中证500")).not.toBeInTheDocument(); });
  it("keeps turnover headline and precise comparison but no chart when real history is absent", () => { page(client()); expect(screen.getByTestId("turnover-card")).toHaveTextContent("25,470.71 亿"); expect(screen.getByTestId("turnover-card")).toHaveTextContent("-4.94%"); expect(screen.queryByText("近日成交额（亿元）")).not.toBeInTheDocument(); });
  it("renders a turnover chart only with at least two actual history points", () => { page(client(true)); expect(screen.getByText("近日成交额（亿元）")).toBeInTheDocument(); });
  it("keeps core content while candidate 404 and 500 modules are absent", () => { page(client()); expect(screen.getByText("市场广度")).toBeInTheDocument(); expect(screen.getByText("板块热度")).toBeInTheDocument(); expect(screen.queryByText("资金流向")).not.toBeInTheDocument(); expect(screen.queryByText("异动机会 / 风险提示")).not.toBeInTheDocument(); expect(screen.queryByText("今日研究报告")).not.toBeInTheDocument(); expect(screen.queryByText("我的持仓")).not.toBeInTheDocument(); });
  it("uses truthful personal empty state and never renders null industry inflow as zero", () => { page(client()); expect(screen.getByText("当前没有需要立即处理的个人研究事项。")).toBeInTheDocument(); expect(screen.getByText("暂无研究变化")).toBeInTheDocument(); expect(screen.getByText("测试行业")).toBeInTheDocument(); expect(screen.queryByText("0.00亿")).not.toBeInTheDocument(); });
});
