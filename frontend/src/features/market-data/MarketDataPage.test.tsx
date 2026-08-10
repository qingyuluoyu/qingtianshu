import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getBreadth, getCapitalFlow, getIndexHistory, getLiveMarkets } from "../today/api";
import type { Breadth, CapitalFlow, GlobalIndices, IndexHistory, LiveMarkets, Sectors } from "../today/adapters";
import { getIndicesByGroup, getSectors } from "./api";
import { MarketDataPage } from "./MarketDataPage";

vi.mock("./api", async (importOriginal) => {
  const original = await importOriginal<typeof import("./api")>();
  return { ...original, getIndicesByGroup: vi.fn(), getSectors: vi.fn() };
});

vi.mock("../today/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("../today/api")>();
  return {
    ...original,
    getBreadth: vi.fn(),
    getCapitalFlow: vi.fn(),
    getLiveMarkets: vi.fn(),
    getIndexHistory: vi.fn(),
  };
});

const mockGetIndices = vi.mocked(getIndicesByGroup);
const mockGetSectors = vi.mocked(getSectors);
const mockGetBreadth = vi.mocked(getBreadth);
const mockGetCapitalFlow = vi.mocked(getCapitalFlow);
const mockGetLiveMarkets = vi.mocked(getLiveMarkets);
const mockGetIndexHistory = vi.mocked(getIndexHistory);

const chinaIndices: GlobalIndices = {
  items: [
    { symbol: "000001.SS", name: "上证综指", status: "available", latestClose: 3809.66, change1d: 9.31, return1dPct: -0.59, source: null, fetchedAt: null, marketTimestamp: "2026-08-03T01:30:00+00:00", isStale: false },
    { symbol: "399001.SZ", name: "深证成指", status: "available", latestClose: 13448.29, change1d: -33.08, return1dPct: -0.96, source: null, fetchedAt: null, marketTimestamp: "2026-08-03T01:30:00+00:00", isStale: false },
    { symbol: "000300.SS", name: "沪深300", status: "available", latestClose: 4543.18, change1d: 8.61, return1dPct: -0.98, source: null, fetchedAt: null, marketTimestamp: "2026-08-03T01:30:00+00:00", isStale: null },
  ],
};

const usIndices: GlobalIndices = {
  items: [
    { symbol: "^GSPC", name: "标普500", status: "available", latestClose: 6234.6, change1d: 39.1, return1dPct: 0.63, source: null, fetchedAt: null, marketTimestamp: "2026-08-04T20:00:00+00:00", isStale: false },
  ],
};

const sectors: Sectors = {
  source: "东方财富",
  marketTimestamp: "2026-08-03T02:51:27+00:00",
  fetchedAt: "2026-08-03T02:51:31+00:00",
  isStale: false,
  hasWarnings: false,
  items: Array.from({ length: 12 }, (_, index) => ({
    code: `BK${String(index).padStart(4, "0")}`,
    name: `板块${index + 1}`,
    pctChange: 4.56 - index * 0.1,
    advancers: 2,
    decliners: 0,
    mainNetInflow100mCny: 125.62 - index,
  })),
};

const breadth: Breadth = {
  status: "available",
  source: null,
  fetchedAt: null,
  marketDate: "2026-08-04",
  marketTimestamp: null,
  isStale: false,
  state: "上涨家数占优",
  total: 5535,
  advancers: 3549,
  decliners: 1804,
  unchanged: 182,
  advanceRatio: 0.6412,
  declineRatio: 0.3259,
  unchangedRatio: 0.0329,
  coverageRatio: 0.9671,
  turnoverStatus: "available",
  turnover100mCny: 10493.68,
  historyStatus: "available",
  turnoverChangeVsPreviousPct: -5.41,
  medianPctChange: 0.679,
  distributionBins: [
    { key: "le_neg7", label: "≤-7%", count: 68 },
    { key: "unchanged", label: "平盘", count: 182 },
    { key: "ge_7", label: "≥7%", count: 112 },
  ],
  limitUpCount: 42,
  limitDownCount: 7,
  limitMethod: "按板块规则近似判定",
  turnoverHistory: [
    { date: "2026-07-31", amount100mCny: 25590.66 },
    { date: "2026-08-04", amount100mCny: 10493.68 },
  ],
};

const capitalFlow: CapitalFlow = {
  status: "available",
  source: null,
  fetchedAt: null,
  marketTimestamp: "2026-08-04T07:00:00+00:00",
  isStale: false,
  mainNetInflow100mCny: -128.45,
  unit: "CNY_100m_yuan",
  points: [
    { time: "09:30", value100mCny: -12.5 },
    { time: "10:30", value100mCny: -60.2 },
    { time: "15:00", value100mCny: -128.45 },
  ],
  method: "主力资金口径；北向资金 2024-08 起港交所停披。",
  warnings: [],
};

const liveMarkets: LiveMarkets = {
  items: [
    { key: "china", name: "中国A股", status: "available", latestPrice: 3809.66, pctChange: 0.24, currency: "CNY", source: null, fetchedAt: null, marketTimestamp: "2026-08-04T07:00:00+00:00", isStale: false },
    { key: "japan", name: "日本股市", status: "available", latestPrice: 40210.5, pctChange: -0.31, currency: "JPY", source: null, fetchedAt: null, marketTimestamp: "2026-08-04T06:00:00+00:00", isStale: false },
    { key: "korea", name: "韩国股市", status: "available", latestPrice: 3120.4, pctChange: 0.12, currency: "KRW", source: null, fetchedAt: null, marketTimestamp: "2026-08-04T06:00:00+00:00", isStale: false },
    { key: "us", name: "美国股市", status: "available", latestPrice: 6234.6, pctChange: 0.63, currency: "USD", source: null, fetchedAt: null, marketTimestamp: "2026-08-04T20:00:00+00:00", isStale: false },
    { key: "london_gold", name: "伦敦金", status: "available", latestPrice: 2358.6, pctChange: 0.78, currency: "USD", source: null, fetchedAt: null, marketTimestamp: "2026-08-04T12:00:00+00:00", isStale: false },
    { key: "dollar_index", name: "美元指数", status: "available", latestPrice: 98.42, pctChange: -0.21, currency: "USD", source: null, fetchedAt: null, marketTimestamp: "2026-08-04T12:00:00+00:00", isStale: false },
    { key: "brent_crude", name: "布伦特原油", status: "available", latestPrice: 69.85, pctChange: 1.12, currency: "USD", source: null, fetchedAt: null, marketTimestamp: "2026-08-04T12:00:00+00:00", isStale: false },
    { key: "us10y_yield", name: "美债十年期", status: "available", latestPrice: 4.25, pctChange: 0.03, currency: "PCT", source: null, fetchedAt: null, marketTimestamp: "2026-08-04T12:00:00+00:00", isStale: false },
  ],
};

const indexHistory: IndexHistory = {
  closes: Array.from({ length: 22 }, (_, index) => 3800 + index * 2),
  marketTimestamp: "2026-08-03T07:00:00+00:00",
};

function LocationProbe() {
  const location = useLocation();
  return <span data-testid="location-search">{location.search}</span>;
}

function renderPage(entry = "/market-data", authenticated = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route element={<><MarketDataPage authenticated={authenticated} /><LocationProbe /></>} path="/market-data" />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockGetIndices.mockImplementation((group) => Promise.resolve(group === "us" ? usIndices : chinaIndices));
  mockGetSectors.mockResolvedValue(sectors);
  mockGetBreadth.mockResolvedValue(breadth);
  mockGetCapitalFlow.mockResolvedValue(capitalFlow);
  mockGetLiveMarkets.mockResolvedValue(liveMarkets);
  mockGetIndexHistory.mockResolvedValue(indexHistory);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("MarketDataPage", () => {
  it("renders all modules with passthrough values and eight live markets", async () => {
    renderPage();
    expect(await screen.findByText("上证综指")).toBeInTheDocument();
    // 指数：点位/涨跌/涨跌幅直通（-0.59 → -0.59%，不缩放）。
    expect(screen.getByText("3,809.66")).toBeInTheDocument();
    expect(screen.getByText("+9.31")).toBeInTheDocument();
    expect(screen.getByText("-0.59%")).toBeInTheDocument();
    expect(mockGetIndices).toHaveBeenCalledWith("china");
    // 市场广度三卡复用。
    expect(screen.getByText("上涨家数占优")).toBeInTheDocument();
    expect(screen.getByText("10,493.68 亿")).toBeInTheDocument();
    expect(screen.getByText(/涨跌中位数/)).toBeInTheDocument();
    // 板块热度 limit=20，超过 today 页 8 行上限。
    expect(mockGetSectors).toHaveBeenCalledWith(20);
    expect(screen.getByText("板块12")).toBeInTheDocument();
    // 资金流向：亿元直通 + 北向注记。
    expect(screen.getByText("-128.45 亿")).toBeInTheDocument();
    expect(screen.getByText(/北向资金 2024-08 起港交所停披/)).toBeInTheDocument();
    // 全球市场八品种；美债 PCT 直通带 %，其余带币种。
    const globalCard = screen.getByRole("region", { name: "全球市场观察" });
    for (const name of ["中国A股", "日本股市", "韩国股市", "美国股市", "伦敦金", "美元指数", "布伦特原油", "美债十年期"]) {
      expect(within(globalCard).getByText(name)).toBeInTheDocument();
    }
    expect(within(globalCard).getByText("4.25%")).toBeInTheDocument();
    expect(within(globalCard).getByText("98.42 USD")).toBeInTheDocument();
  });

  it("switches index group via tabs and reflects it in the URL", async () => {
    renderPage();
    expect(await screen.findByText("上证综指")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "美国" }));
    expect(await screen.findByText("标普500")).toBeInTheDocument();
    expect(mockGetIndices).toHaveBeenCalledWith("us");
    expect(screen.getByTestId("location-search").textContent).toContain("group=us");
  });

  it("reads the initial group from the URL", async () => {
    renderPage("/market-data?group=us");
    expect(await screen.findByText("标普500")).toBeInTheDocument();
    expect(mockGetIndices).toHaveBeenCalledWith("us");
    expect(screen.getByRole("tab", { name: "美国" })).toHaveAttribute("aria-selected", "true");
  });

  it("expands an index row to load the 1mo history sparkline", async () => {
    renderPage();
    const row = await screen.findByRole("button", { name: /上证综指/ });
    expect(mockGetIndexHistory).not.toHaveBeenCalled();
    fireEvent.click(row);
    await waitFor(() => expect(mockGetIndexHistory).toHaveBeenCalledWith("000001.SS"));
    expect(await screen.findByText(/近 1 月日线收盘/)).toBeInTheDocument();
    // 再次点击收起。
    fireEvent.click(row);
    await waitFor(() => expect(screen.queryByText(/近 1 月日线收盘/)).not.toBeInTheDocument());
  });

  it("isolates a single-module failure with retry while other modules stay readable", async () => {
    // Use mockImplementation returning a rejected promise rather than
    // mockRejectedValue, which has microtask-flush timing issues in jsdom.
    mockGetSectors.mockImplementation(() => Promise.reject(new Error("数据暂时不可用")));
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter initialEntries={["/market-data"]}>
          <Routes>
            <Route element={<MarketDataPage authenticated />} path="/market-data" />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    // Allow the rejected-promise microtask to propagate through TanStack Query.
    await act(async () => { await Promise.resolve(); });
    await waitFor(() => expect(screen.getByText("本模块暂时不可用，其他内容仍可继续查看。")).toBeInTheDocument(), { timeout: 3000 });
    expect(screen.getByRole("button", { name: "重新读取" })).toBeInTheDocument();
    expect(await screen.findByText("上证综指")).toBeInTheDocument();
    // 重试成功后恢复。
    mockGetSectors.mockResolvedValue(sectors);
    fireEvent.click(screen.getByRole("button", { name: "重新读取" }));
    expect(await screen.findByText("板块1")).toBeInTheDocument();
  });

  it("shows public market data for anonymous visitors and locks the index explorer", async () => {
    renderPage("/market-data", false);
    // Public queries fire regardless of auth.
    expect(mockGetIndices).toHaveBeenCalledWith("china");
    expect(mockGetBreadth).toHaveBeenCalled();
    expect(mockGetCapitalFlow).toHaveBeenCalled();
    expect(mockGetLiveMarkets).toHaveBeenCalled();
    // Public cards render.
    expect(await screen.findByText("上涨家数占优")).toBeInTheDocument();
    expect(screen.getByText("-128.45 亿")).toBeInTheDocument();
    // Private queries do NOT fire.
    expect(mockGetSectors).not.toHaveBeenCalled();
    // Index explorer shows locked message.
    expect(screen.getByText("指数分组与板块热度已锁定，请先登录或注册。")).toBeInTheDocument();
  });
});
