import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  archiveTradeReview,
  confirmTradeReview,
  getResearchActions,
  getResearchChanges,
  getResearchOutcomes,
  getResearchReport,
  getTradeReviewCenter,
  getWorkspaceTimeline,
  ResearchCenterApiError,
} from "./api";
import {
  parsedActions,
  parsedChanges,
  parsedEmptyChanges,
  parsedEmptyOutcomes,
  parsedEmptyTimeline,
  parsedEmptyTradeReviewCenter,
  parsedOutcomes,
  parsedReport,
  parsedTimeline,
  parsedTradeReviewCenter,
} from "./testFixtures";
import { ResearchCenterPage } from "./ResearchCenterPage";

vi.mock("./api", async (importOriginal) => {
  const original = await importOriginal<typeof import("./api")>();
  return {
    ...original,
    getResearchChanges: vi.fn(),
    getResearchOutcomes: vi.fn(),
    getResearchActions: vi.fn(),
    getTradeReviewCenter: vi.fn(),
    getWorkspaceTimeline: vi.fn(),
    getResearchReport: vi.fn(),
    confirmTradeReview: vi.fn(),
    archiveTradeReview: vi.fn(),
  };
});

const mockGetChanges = vi.mocked(getResearchChanges);
const mockGetOutcomes = vi.mocked(getResearchOutcomes);
const mockGetActions = vi.mocked(getResearchActions);
const mockGetTradeReviews = vi.mocked(getTradeReviewCenter);
const mockGetTimeline = vi.mocked(getWorkspaceTimeline);
const mockGetReport = vi.mocked(getResearchReport);
const mockConfirm = vi.mocked(confirmTradeReview);
const mockArchive = vi.mocked(archiveTradeReview);

function renderPage(entry = "/research-center", authenticated = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route element={<ResearchCenterPage authenticated={authenticated} />} path="/research-center" />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockGetChanges.mockResolvedValue(parsedChanges());
  mockGetOutcomes.mockResolvedValue(parsedOutcomes());
  mockGetActions.mockResolvedValue(parsedActions());
  mockGetTradeReviews.mockResolvedValue(parsedTradeReviewCenter());
  mockGetTimeline.mockResolvedValue(parsedTimeline());
  mockGetReport.mockResolvedValue(parsedReport());
  mockConfirm.mockResolvedValue({});
  mockArchive.mockResolvedValue({});
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("ResearchCenterPage", () => {
  it("renders summary cards, stock list and decision-change timeline with passthrough values", async () => {
    renderPage();
    // 等所有聚合查询落定后再断言概览卡计数。
    expect(await screen.findByText("判断版本 2")).toBeInTheDocument();
    // 概览卡：计数来自真实聚合（待复盘 actionable=1、有变化 withChangeArchive=1、已到期结果 available=2）。
    const summary = screen.getByRole("group", { name: "研究复盘概览" });
    await waitFor(() => expect(within(summary).getByRole("button", { name: /待复盘/ })).toHaveTextContent("1"));
    expect(within(summary).getByRole("button", { name: /判断有变化/ })).toHaveTextContent("1");
    expect(within(summary).getByRole("button", { name: /已有结果/ })).toHaveTextContent("2");
    // 左侧股票列表：两只股票，默认选中第一只。
    const listbox = screen.getByRole("listbox", { name: "研究股票列表" });
    expect(within(listbox).getByText("中兴通讯")).toBeInTheDocument();
    expect(within(listbox).getByText("贵州茅台")).toBeInTheDocument();
    expect(within(listbox).getByRole("option", { name: /中兴通讯/ })).toHaveAttribute("aria-selected", "true");
    // 中央判断-变化-处理链：判断版本、变化、处理任务。
    expect(await screen.findByText("判断版本 2")).toBeInTheDocument();
    expect(screen.getByText(/算力订单兑现节奏是核心变量/)).toBeInTheDocument();
    expect(screen.getByText(/中兴通讯最新变化/)).toBeInTheDocument();
    expect(screen.getByText("跟踪 MA20 收复情况")).toBeInTheDocument();
    // 报告变化：before → after 直通（原文含百分号，不缩放）。
    expect(screen.getByText(/-13\.96%/)).toBeInTheDocument();
    // 右侧下一步：触发的复核事项与 §5.6 说明（不显示已保存）。
    expect(screen.getByText("检查波动是否显著放大")).toBeInTheDocument();
    expect(screen.getByText(/不会显示为已保存/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "进入个股研究" })).toHaveAttribute("href", "/stocks/000063.SZ");
    expect(screen.getByRole("link", { name: "问顾问" })).toHaveAttribute("href", expect.stringContaining("source=research-center"));
  });

  it("shows outcome anchors with anchor, trade-day window, protocol and data-availability times", async () => {
    renderPage();
    // 结果进度：已观察 1/3 个交易日，阶段收益直通。
    expect(await screen.findByRole("img", { name: "已观察 1 / 3 个交易日" })).toBeInTheDocument();
    // 历史结果卡：OutcomeAnchor / 交易日窗口 / 基准 / 数据可得时间（§6.2）。
    expect(await screen.findByText("结果锚点（OutcomeAnchor）")).toBeInTheDocument();
    expect(screen.getByText("交易日窗口")).toBeInTheDocument();
    expect(screen.getByText("基准与数据可得时间")).toBeInTheDocument();
    expect(screen.getByText(/优先使用复权收盘价/)).toBeInTheDocument();
    // 百分数直通：-1.8524 → -1.85%，MFE 2.1164 → +2.12%。
    expect(screen.getByText("-1.85%")).toBeInTheDocument();
    expect(screen.getByText(/\+2\.12%/)).toBeInTheDocument();
    // 待形成锚点不伪装成已到期：模块 meta 区分已到期 / 待形成，场景标签与结论原文直通。
    expect(screen.getByText(/待形成 3/)).toBeInTheDocument();
    expect(screen.getAllByText(/区间情景延续/).length).toBeGreaterThan(0);
    // boundary 原文。
    expect(screen.getAllByText(/结果回填只检验研究条件后来是否出现/).length).toBeGreaterThan(0);
  });

  it("filters the stock list from summary cards via URL focus param", async () => {
    renderPage("/research-center?focus=changed");
    const listbox = await screen.findByRole("listbox", { name: "研究股票列表" });
    expect(within(listbox).getByText("中兴通讯")).toBeInTheDocument();
    expect(within(listbox).queryByText("贵州茅台")).not.toBeInTheDocument();
    // 选中股票写入 URL ?symbol= 并加载对应 timeline。
    fireEvent.click(within(listbox).getByRole("option", { name: /中兴通讯/ }));
    await waitFor(() => expect(mockGetTimeline).toHaveBeenCalledWith("000063.SZ"));
  });

  it("confirms a draft review with base_version and shows success notice", async () => {
    renderPage();
    const confirmButton = await screen.findByRole("button", { name: "确认复盘" });
    fireEvent.click(confirmButton);
    await waitFor(() => expect(mockConfirm).toHaveBeenCalledWith("review-1", 2));
    expect(await screen.findByText(/复盘已确认并落库为正式复盘/)).toBeInTheDocument();
    // 已确认的复盘提供归档入口。
    fireEvent.click(screen.getByRole("button", { name: "归档复盘" }));
    await waitFor(() => expect(mockArchive).toHaveBeenCalledWith("review-2", 1));
    expect(await screen.findByText(/复盘已归档/)).toBeInTheDocument();
  });

  it("handles 409 conflict by surfacing a conflict notice without overwriting", async () => {
    mockConfirm.mockRejectedValue(new ResearchCenterApiError(409, "该复盘已被其他操作更新，已刷新最新状态，请确认后重试。"));
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "确认复盘" }));
    expect(await screen.findByText(/已被其他操作更新/)).toBeInTheDocument();
    // 失败后重新拉取复盘中心取回新 base_version。
    await waitFor(() => expect(mockGetTradeReviews.mock.calls.length).toBeGreaterThan(1));
  });

  it("shows real empty states instead of fabricated content", async () => {
    mockGetChanges.mockResolvedValue(parsedEmptyChanges());
    mockGetOutcomes.mockResolvedValue(parsedEmptyOutcomes());
    mockGetTradeReviews.mockResolvedValue(parsedEmptyTradeReviewCenter());
    mockGetTimeline.mockResolvedValue(parsedEmptyTimeline());
    renderPage();
    // 无研究跟踪记录 → 引导入口，不展示示例数据（§8.1）。
    expect(await screen.findByText(/还没有研究跟踪记录/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "前往我的关注" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "前往透明选股" })).toBeInTheDocument();
  });

  it("keeps a failed timeline module isolated from the rest of the page", async () => {
    mockGetTimeline.mockRejectedValue(new ResearchCenterApiError(500, "数据暂时不可用"));
    renderPage();
    // 查询层重试两次后才进入模块错误态。
    expect(await screen.findByText(/本模块暂时不可用/, {}, { timeout: 6000 })).toBeInTheDocument();
    // 其他模块仍然渲染。
    expect(screen.getByText("检查波动是否显著放大")).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "研究复盘概览" })).toBeInTheDocument();
  });

  it("locks the page for anonymous visitors", async () => {
    renderPage("/research-center", false);
    expect(await screen.findByText(/业务内容已锁定/)).toBeInTheDocument();
    expect(mockGetChanges).not.toHaveBeenCalled();
  });
});
