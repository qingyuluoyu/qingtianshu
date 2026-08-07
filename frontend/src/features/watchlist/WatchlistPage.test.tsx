import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { parsedHistory, parsedStockPage } from "../stock-research/testFixtures";
import {
  getStockHistory,
  getStockWorkspace,
  getStockWorkspaces,
  patchStockRelation,
  WatchlistApiError,
} from "./api";
import { parsedAssets } from "./testFixtures";
import { WatchlistPage } from "./WatchlistPage";

vi.mock("./api", async (importOriginal) => {
  const original = await importOriginal<typeof import("./api")>();
  return {
    ...original,
    getStockWorkspaces: vi.fn(),
    getStockWorkspace: vi.fn(),
    getStockHistory: vi.fn(),
    patchStockRelation: vi.fn(),
  };
});

const mockGetAssets = vi.mocked(getStockWorkspaces);
const mockGetWorkspace = vi.mocked(getStockWorkspace);
const mockGetHistory = vi.mocked(getStockHistory);
const mockPatchRelation = vi.mocked(patchStockRelation);

function renderPage(entry = "/watchlist", authenticated = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route element={<WatchlistPage authenticated={authenticated} />} path="/watchlist" />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockGetAssets.mockResolvedValue(parsedAssets());
  mockGetWorkspace.mockResolvedValue(parsedStockPage().modules.workspace.data!);
  mockGetHistory.mockResolvedValue(parsedHistory());
  mockPatchRelation.mockResolvedValue({
    contractVersion: "stock_domain_v1",
    symbol: "000063.SZ",
    version: 4,
    relationType: "watching",
    priority: "high",
    trackingStatus: "active",
    workflowStatus: "researching",
    attentionTags: ["算力"],
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("WatchlistPage", () => {
  it("renders summary cards, asset table and quick preview with passthrough values", async () => {
    renderPage();
    // 概览筛选卡（总数直通 summary.total=3）。
    const summaryGroup = await screen.findByRole("group", { name: "关注概览筛选" });
    expect(within(summaryGroup).getByRole("button", { name: /全部/ })).toBeInTheDocument();
    expect(within(summaryGroup).getByRole("button", { name: /重点/ })).toBeInTheDocument();
    // 资产表三行：代码、名称、涨跌百分数直通（-0.14 → -0.14%，1.25 → +1.25%）。
    expect(screen.getByText("000063.SZ")).toBeInTheDocument();
    expect(screen.getAllByText("中兴通讯").length).toBeGreaterThan(0);
    expect(screen.getAllByText("-0.14%").length).toBeGreaterThan(0);
    expect(screen.getAllByText("+1.25%").length).toBeGreaterThan(0);
    // 行情不可用行：价格 -- + 状态，不是 0。
    expect(screen.getAllByText("--").length).toBeGreaterThan(0);
    expect(screen.getAllByText("行情不可用").length).toBeGreaterThan(0);
    // 任务数为 0 是有效数值，正常显示 0。
    expect(screen.getAllByText("0").length).toBeGreaterThan(0);
    // 无判断行显示真实空态文案，与接口失败区分。
    expect(screen.getAllByText("尚未保存当前判断").length).toBeGreaterThan(0);
    // 研究状态翻译（§6.3）：暂停 / 等待数据 / 已结束。
    expect(screen.getAllByText("已暂停").length).toBeGreaterThan(0);
    expect(screen.getAllByText("已结束").length).toBeGreaterThan(0);
    // 默认选中首行并渲染快速预览（aria-selected）。
    const selectedRow = document.querySelector("tbody tr[aria-selected='true']");
    expect(selectedRow?.textContent).toContain("000063.SZ");
    expect(await screen.findByText(/快速预览/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "进入个股研究" })).toHaveAttribute("href", "/stocks/000063.SZ");
    expect(screen.getByRole("link", { name: "问顾问" })).toHaveAttribute("href", expect.stringContaining("source=watchlist"));
    // 最近变化与任务/报告摘要模块。
    expect(screen.getByText("最近变化与任务/报告摘要")).toBeInTheDocument();
    expect(screen.getAllByText(/中兴通讯披露半年报/).length).toBeGreaterThan(0);
    // 列表 boundary 原文展示。
    expect(screen.getAllByText(/已结束空间仍保留判断、任务和历史/).length).toBeGreaterThan(0);
  });

  it("selects the row from the URL symbol param", async () => {
    renderPage("/watchlist?symbol=AAPL");
    expect(await screen.findByText("Apple Inc. 快速预览")).toBeInTheDocument();
    const selectedRow = document.querySelector("tbody tr[aria-selected='true']");
    expect(selectedRow?.textContent).toContain("AAPL");
    // 已结束行只提供恢复关注，不出现暂停/结束按钮。
    expect(selectedRow?.textContent).toContain("恢复关注");
  });

  it("applies summary-card filters via URL without extra requests", async () => {
    renderPage();
    await screen.findByText("000063.SZ");
    const summaryGroup = screen.getByRole("group", { name: "关注概览筛选" });
    fireEvent.click(within(summaryGroup).getByRole("button", { name: /重点/ }));
    await waitFor(() => {
      expect(document.querySelectorAll("tbody tr")).toHaveLength(1);
    });
    expect(document.querySelector("tbody tr")?.textContent).toContain("000063.SZ");
    // 筛选在浏览器侧完成：列表只命中同一个聚合端点（无逐股 workspace 请求），
    // 预览的 workspace 请求只来自当前选中行。
    expect(mockGetAssets).toHaveBeenCalledTimes(1);
    expect(mockGetWorkspace).toHaveBeenCalledTimes(1);
    expect(mockGetWorkspace).toHaveBeenCalledWith("000063.SZ");
  });

  it("sends a full-state relation patch and refreshes the list on success", async () => {
    renderPage();
    await screen.findByText("000063.SZ");
    fireEvent.click(screen.getAllByRole("button", { name: "暂停跟踪" })[0]!);
    await waitFor(() => expect(mockPatchRelation).toHaveBeenCalledTimes(1));
    // 全量替换语义：保留 priority=high / workflow_status=researching / attention_tags，只改 tracking_status。
    expect(mockPatchRelation).toHaveBeenCalledWith("000063.SZ", {
      baseVersion: 3,
      relationType: "watching",
      priority: "high",
      trackingStatus: "paused",
      workflowStatus: "researching",
      attentionTags: ["算力"],
    });
    expect(await screen.findByText(/已暂停跟踪（000063\.SZ）/)).toBeInTheDocument();
    // 成功后失效并重新拉取列表，取回新 base_version。
    await waitFor(() => expect(mockGetAssets.mock.calls.length).toBeGreaterThan(1));
  });

  it("ends a relation only after explicit confirmation", async () => {
    renderPage();
    await screen.findByText("000063.SZ");
    fireEvent.click(screen.getAllByRole("button", { name: "结束关注" })[0]!);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText(/结束对 中兴通讯 的关注/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "确认结束关注" }));
    await waitFor(() => expect(mockPatchRelation).toHaveBeenCalledTimes(1));
    // 结束后 priority 置空（与后端口径一致），base_version 来自行版本。
    expect(mockPatchRelation).toHaveBeenCalledWith("000063.SZ", expect.objectContaining({
      baseVersion: 3,
      relationType: "ended",
      priority: null,
    }));
    expect(await screen.findByText(/已结束关注（000063\.SZ）/)).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("handles 409 by refreshing the row and asking the user to re-confirm", async () => {
    mockPatchRelation.mockRejectedValue(new WatchlistApiError(409, "该股票关系已被其他操作更新，已刷新最新状态，请确认后重试。"));
    renderPage();
    await screen.findByText("000063.SZ");
    fireEvent.click(screen.getAllByRole("button", { name: "暂停跟踪" })[0]!);
    expect(await screen.findByText(/请确认后重试/)).toBeInTheDocument();
    // 409 后刷新列表取回最新版本，不做本地覆盖。
    await waitFor(() => expect(mockGetAssets.mock.calls.length).toBeGreaterThan(1));
  });

  it("surfaces failed writes without changing local data", async () => {
    mockPatchRelation.mockRejectedValue(new WatchlistApiError(500, "数据暂时不可用"));
    renderPage();
    await screen.findByText("000063.SZ");
    fireEvent.click(screen.getAllByRole("button", { name: "暂停跟踪" })[0]!);
    expect(await screen.findByText(/写入失败（000063\.SZ）/)).toBeInTheDocument();
  });

  it("renders the empty state with real search and screening entries", async () => {
    mockGetAssets.mockResolvedValue(parsedAssets());
    mockGetAssets.mockResolvedValueOnce((await import("./adapters")).parseWatchlistAssets({
      contract_version: "stock_asset_list_v1",
      status: "empty",
      items: [],
      summary: { total: 0, watching: 0, holding: 0, ended: 0, paused: 0, waiting_data: 0 },
      boundary: "该列表组织用户的长期股票研究资产。",
    }));
    renderPage();
    expect(await screen.findByText(/还没有关注任何股票/)).toBeInTheDocument();
    expect(screen.getByText(/全局搜索/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "前往透明选股" })).toHaveAttribute("href", "/screening");
  });

  it("keeps the asset list and preview scaffold when the watchlist is empty", async () => {
    mockGetAssets.mockResolvedValueOnce((await import("./adapters")).parseWatchlistAssets({
      contract_version: "stock_asset_list_v1",
      status: "empty",
      items: [],
      summary: { total: 0, watching: 0, holding: 0, ended: 0, paused: 0, waiting_data: 0 },
      boundary: "该列表组织用户的长期股票研究资产。",
    }));
    renderPage();

    const listRegion = await screen.findByRole("region", { name: "研究资产列表" });
    expect(within(listRegion).getByRole("table", { name: "关注资产表" })).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "股票快速预览" })).toBeInTheDocument();
  });

  it("shows a page-level error with retry when the list request fails", async () => {
    mockGetAssets.mockRejectedValue(new WatchlistApiError(503, "数据暂时不可用"));
    renderPage();
    // 503 按查询策略最多重试 2 次后才进入错误态，等待放宽到 8s。
    expect(await screen.findByText("关注列表暂时不可用。", undefined, { timeout: 8000 })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重新读取" })).toBeInTheDocument();
  });

  it("prompts login without issuing requests when unauthenticated", () => {
    renderPage("/watchlist", false);
    expect(screen.getByText(/登录后可管理你的关注标的/)).toBeInTheDocument();
    expect(mockGetAssets).not.toHaveBeenCalled();
  });
});
