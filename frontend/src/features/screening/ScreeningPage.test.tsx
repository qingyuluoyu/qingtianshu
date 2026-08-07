import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  getLiZongBacktest,
  getLiZongCandidates,
  getLiZongRunLatest,
  getScreenerProfiles,
  runStockScreen,
} from "./api";
import { parseStockScreen } from "./adapters";
import {
  parsedLiZongBacktest,
  parsedLiZongCandidates,
  parsedLiZongRunLatest,
  parsedProfiles,
  parsedScreen,
  screenPayload,
} from "./testFixtures";
import { ScreeningPage } from "./ScreeningPage";

vi.mock("./api", async (importOriginal) => {
  const original = await importOriginal<typeof import("./api")>();
  return {
    ...original,
    getScreenerProfiles: vi.fn(),
    runStockScreen: vi.fn(),
    getLiZongCandidates: vi.fn(),
    getLiZongRunLatest: vi.fn(),
    getLiZongBacktest: vi.fn(),
  };
});

const mockProfiles = vi.mocked(getScreenerProfiles);
const mockScreen = vi.mocked(runStockScreen);
const mockCandidates = vi.mocked(getLiZongCandidates);
const mockRunLatest = vi.mocked(getLiZongRunLatest);
const mockBacktest = vi.mocked(getLiZongBacktest);

function renderPage(entry = "/screening", authenticated = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route element={<ScreeningPage authenticated={authenticated} />} path="/screening" />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockProfiles.mockResolvedValue(parsedProfiles());
  mockScreen.mockResolvedValue(parsedScreen());
  mockCandidates.mockResolvedValue(parsedLiZongCandidates());
  mockRunLatest.mockResolvedValue(parsedLiZongRunLatest());
  mockBacktest.mockResolvedValue(parsedLiZongBacktest());
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("ScreeningPage 通用筛选模式", () => {
  it("renders mode cards, filter builder, summary and candidate table with passthrough values", async () => {
    renderPage();
    // 三模式互斥卡片。
    const modeGroup = screen.getByRole("group", { name: "选股模式" });
    expect(within(modeGroup).getByRole("button", { name: /通用筛选/ })).toHaveAttribute("aria-pressed", "true");
    expect(within(modeGroup).getByRole("button", { name: /李总指标筛选/ })).toHaveAttribute("aria-pressed", "false");
    expect(within(modeGroup).getByRole("button", { name: /历史复盘 \/ 回测/ })).toHaveAttribute("aria-pressed", "false");
    // 条件面板（档案来自 profiles）。
    expect(await screen.findByLabelText("筛选档案")).toBeInTheDocument();
    expect(screen.getByLabelText("ROE 下限（%）")).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "筛选条件栏" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "筛选结果工作区" })).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "候选详情" })).toBeInTheDocument();
    // 摘要：真实命中总数 + 不代表全市场（§5.2 禁全市场伪装）。
    expect(await screen.findByText("命中候选（真实总数）")).toBeInTheDocument();
    expect(screen.getByText("不代表全市场")).toBeInTheDocument();
    // 候选表：百分数直通（8.789 → +8.79%，0 → +0.00%？不，0 显示 0.00% 不带正号）。
    expect(screen.getByText("600549.SH")).toBeInTheDocument();
    expect(screen.getAllByText("+8.79%").length).toBeGreaterThan(0);
    expect(screen.getAllByText("0.00%").length).toBeGreaterThan(0);
    // 三态区分：完整命中 = 通过；带缺失字段 = 数据不足。
    expect(screen.getAllByText("通过").length).toBeGreaterThan(0);
    expect(screen.getAllByText("数据不足").length).toBeGreaterThan(0);
    // 默认选中首行详情 + 缺失字段展示。
    expect(screen.getByText(/候选详情/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "进入个股研究" })).toHaveAttribute("href", "/stocks/600549.SH");
    // 解释面板：真实规则与漏斗计数，非行业分布编造。
    expect(screen.getByText("规则与漏斗解释")).toBeInTheDocument();
    expect(screen.getByText("筛选漏斗（服务端真实计数）")).toBeInTheDocument();
    // §5.2：无服务端分页，不出现分页控件。
    expect(screen.queryByRole("navigation", { name: /分页/ })).not.toBeInTheDocument();
    expect(screen.getByText(/不提供伪分页/)).toBeInTheDocument();
  });

  it("applies edited filters through the URL and reruns the screen", async () => {
    renderPage();
    await screen.findByText("600549.SH");
    expect(mockScreen).toHaveBeenCalledTimes(1);
    expect(mockScreen.mock.calls[0]![0]).toMatchObject({
      profile: "quality",
      market: "all",
      maxResults: 12,
      filters: { min_market_cap_yi: 50, min_roe: 0 },
    });
    fireEvent.change(screen.getByLabelText("ROE 下限（%）"), { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: "应用筛选" }));
    await waitFor(() => expect(mockScreen).toHaveBeenCalledTimes(2));
    expect(mockScreen.mock.calls[1]![0].filters.min_roe).toBe(5);
    expect(mockScreen.mock.calls[1]![0].filters.min_market_cap_yi).toBe(50);
  });

  it("rejects non-numeric thresholds instead of silently dropping them", async () => {
    renderPage();
    await screen.findByText("600549.SH");
    fireEvent.change(screen.getByLabelText("ROE 下限（%）"), { target: { value: "abc" } });
    fireEvent.click(screen.getByRole("button", { name: "应用筛选" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/需要填写数字/);
    expect(mockScreen).toHaveBeenCalledTimes(1);
  });

  it("shows a real empty state when nothing matches", async () => {
    const payload = screenPayload();
    payload.universe.matched = 0;
    payload.items = [];
    mockScreen.mockResolvedValue(parseStockScreen(payload));
    renderPage();
    expect(await screen.findByText(/当前条件下没有命中候选/)).toBeInTheDocument();
    expect(screen.getByText(/不用示例数据填充/)).toBeInTheDocument();
  });
});

describe("ScreeningPage 李总模式", () => {
  it("switches mode via URL and renders three-state candidates with reasons and gaps", async () => {
    renderPage();
    await screen.findByText("600549.SH");
    fireEvent.click(screen.getByRole("group", { name: "选股模式" }).querySelectorAll("button")[1]!);
    // 最近 run 摘要（状态 partial → 部分数据可用，警告直通）。
    expect(await screen.findByText("最近筛选 Run")).toBeInTheDocument();
    expect(await screen.findByText("部分数据可用")).toBeInTheDocument();
    expect(screen.getByText(/等待补齐数据/)).toBeInTheDocument();
    // 状态筛选 chips 带真实计数。
    const chipGroup = screen.getByRole("group", { name: "候选状态筛选" });
    expect(within(chipGroup).getByRole("button", { name: /全部 3/ })).toBeInTheDocument();
    expect(within(chipGroup).getByRole("button", { name: /未通过 1/ })).toBeInTheDocument();
    // 候选表三态：通过 / 未通过 / 数据不足 + 命中理由 + 数据缺口。
    expect(screen.getByText("600519.SH")).toBeInTheDocument();
    expect(screen.getByText("300750.SZ")).toBeInTheDocument();
    expect(screen.getAllByText("通过", { exact: true }).length).toBeGreaterThan(0);
    expect(screen.getAllByText("未通过", { exact: true }).length).toBeGreaterThan(0);
    expect(screen.getAllByText("数据不足").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/LZ-F-01 已通过/).length).toBeGreaterThan(0);
    // 数据缺口列：data_incomplete 规则 ID 直通。
    expect(screen.getAllByText("LZ-F-02").length).toBeGreaterThan(0);
    // 规则漏斗（真实分布数据）。
    expect(screen.getByText("规则漏斗分布")).toBeInTheDocument();
    // 规则核验清单（默认选中首行）。
    expect(screen.getAllByText(/规则核验/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/总市值严格大于150亿元/).length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: "进入个股研究" })).toHaveAttribute("href", "/stocks/600519.SH");
  });

  it("filters candidates server-side via status chips", async () => {
    renderPage("/screening?mode=lizong");
    await screen.findByText("600519.SH");
    expect(mockCandidates).toHaveBeenCalledWith(null);
    fireEvent.click(within(screen.getByRole("group", { name: "候选状态筛选" })).getByRole("button", { name: /数据不足/ }));
    await waitFor(() => expect(mockCandidates).toHaveBeenCalledWith("data_incomplete"));
  });
});

describe("ScreeningPage 回测模式", () => {
  it("renders metric cards and the nav chart only for a completed backtest", async () => {
    renderPage("/screening?mode=backtest");
    expect(await screen.findByText("区间收益")).toBeInTheDocument();
    // 百分数直通：28.1046 → +28.10%，-32.7614 → -32.76%。
    expect(screen.getByText("+28.10%")).toBeInTheDocument();
    expect(screen.getByText("-32.76%")).toBeInTheDocument();
    expect(screen.getByText("+16.91%")).toBeInTheDocument();
    // 覆盖率原值直通（0.8315，不换算百分数）。
    expect(screen.getByText("0.8315")).toBeInTheDocument();
    // 纯 SVG 净值图 + 口径说明。
    expect(screen.getByRole("img", { name: "回测净值与基准净值曲线" })).toBeInTheDocument();
    expect(screen.getAllByText(/沪深300/).length).toBeGreaterThan(0);
    expect(mockBacktest).toHaveBeenCalledWith("1y");
  });

  it("honors the period URL param and switches periods via chips", async () => {
    renderPage("/screening?mode=backtest&period=3y");
    await screen.findByText("区间收益");
    expect(mockBacktest).toHaveBeenCalledWith("3y");
    fireEvent.click(within(screen.getByRole("group", { name: "回测区间" })).getByRole("button", { name: "近 3 月" }));
    await waitFor(() => expect(mockBacktest).toHaveBeenCalledWith("3m"));
  });

  it("shows a real progress/empty state for an unfinished backtest without inventing metrics", async () => {
    const parsed = parsedLiZongBacktest();
    mockBacktest.mockResolvedValue({
      ...parsed,
      status: "computing",
      result: null,
      progress: { ...parsed.progress!, status: "computing", phase: "evaluating" },
    });
    renderPage("/screening?mode=backtest");
    expect(await screen.findByText(/尚未完成或结果不可用/)).toBeInTheDocument();
    expect(screen.getByText(/不展示推算指标/)).toBeInTheDocument();
    expect(screen.queryByText("区间收益")).not.toBeInTheDocument();
    expect(screen.queryByRole("img", { name: "回测净值与基准净值曲线" })).not.toBeInTheDocument();
  });
});

describe("ScreeningPage 通用行为", () => {
  it("prompts login without issuing requests when unauthenticated", () => {
    renderPage("/screening", false);
    expect(screen.getByText(/登录后可查看筛选条件/)).toBeInTheDocument();
    expect(mockProfiles).not.toHaveBeenCalled();
    expect(mockScreen).not.toHaveBeenCalled();
    expect(mockCandidates).not.toHaveBeenCalled();
  });

  it("shows a module-level error with retry when the screen request fails", async () => {
    mockScreen.mockRejectedValue(new Error("数据暂时不可用"));
    renderPage();
    // 按查询策略最多重试 2 次后才进入错误态（默认退避约 3s），等待放宽到 8s。
    expect(await screen.findByText("筛选结果暂时不可用。", undefined, { timeout: 8000 })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重新读取" })).toBeInTheDocument();
  });
});
