import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  getEvidenceTasks,
  getResearchActions,
  getResearchChanges,
  getResearchOutcomes,
  getResearchPriority,
  getRunReviews,
  ResearchCenterApiError,
} from "./api";
import { ResearchCenterPage } from "./ResearchCenterPage";
import { parsedResearchCenter } from "./testFixtures";

vi.mock("./api", async (importOriginal) => {
  const original = await importOriginal<typeof import("./api")>();
  return {
    ...original,
    getResearchPriority: vi.fn(),
    getResearchChanges: vi.fn(),
    getResearchActions: vi.fn(),
    getEvidenceTasks: vi.fn(),
    getResearchOutcomes: vi.fn(),
    getRunReviews: vi.fn(),
  };
});

const mockPriority = vi.mocked(getResearchPriority);
const mockChanges = vi.mocked(getResearchChanges);
const mockActions = vi.mocked(getResearchActions);
const mockTasks = vi.mocked(getEvidenceTasks);
const mockOutcomes = vi.mocked(getResearchOutcomes);
const mockReviews = vi.mocked(getRunReviews);

function renderPage(authenticated = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, retryDelay: 0 } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/research-center"]}>
        <Routes>
          <Route element={<ResearchCenterPage authenticated={authenticated} />} path="/research-center" />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockPriority.mockResolvedValue(parsedResearchCenter.priority());
  mockChanges.mockResolvedValue(parsedResearchCenter.changes());
  mockActions.mockResolvedValue(parsedResearchCenter.actions());
  mockTasks.mockResolvedValue(parsedResearchCenter.evidenceTasks());
  mockOutcomes.mockResolvedValue(parsedResearchCenter.outcomes());
  mockReviews.mockResolvedValue(parsedResearchCenter.runReviews());
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("ResearchCenterPage", () => {
  it("renders the real research workflow without turning urgency or outcomes into advice", async () => {
    const priority = parsedResearchCenter.priority();
    priority.items[1] = { ...priority.items[1], priorityLabel: null };
    mockPriority.mockResolvedValue(priority);
    renderPage();
    expect(await screen.findByRole("heading", { name: "研究中心" })).toBeInTheDocument();
    expect(await screen.findByText("复核紧迫度 78")).toBeInTheDocument();

    const summary = screen.getByRole("region", { name: "研究中心概览" });
    expect(within(summary).getAllByText("2")).toHaveLength(2);
    expect(within(summary).getAllByText("1").length).toBeGreaterThanOrEqual(3);

    expect(screen.getByRole("heading", { name: "优先处理" })).toBeInTheDocument();
    expect(screen.getByText(/按研究复核紧迫度排序，不按预期收益/)).toBeInTheDocument();
    expect(screen.getByText("复核最新证据变化")).toBeInTheDocument();
    expect(screen.getByText("待建立基线")).toBeInTheDocument();
    expect(screen.getByText("已触发")).toBeInTheDocument();
    expect(screen.getByText("待补证")).toBeInTheDocument();
    expect(screen.queryByText("triggered")).not.toBeInTheDocument();
    expect(screen.queryByText("pending_data")).not.toBeInTheDocument();
    expect(screen.queryByText("baseline_missing")).not.toBeInTheDocument();
    expect(screen.getByText("利润、现金流与价格结构出现新的反方证据。")).toBeInTheDocument();
    expect(screen.getByText("补齐公司最新公告")).toBeInTheDocument();
    expect(screen.getByText("-2.35%")).toBeInTheDocument();
    expect(screen.getByText(/不评价买卖收益、策略胜率或荐股准确率/)).toBeInTheDocument();
    expect(screen.getByText("利润改善是否得到经营现金流确认？")).toBeInTheDocument();
    expect(screen.getByText("回答检查通过")).toBeInTheDocument();

    expect(screen.getAllByRole("link", { name: "查看个股研究" })[0]).toHaveAttribute("href", "/stocks/000063.SZ");
    expect(screen.getAllByRole("link", { name: "问顾问" })[0]).toHaveAttribute("href", expect.stringContaining("source=research-center"));
    expect(screen.getByRole("link", { name: "打开原对话" })).toHaveAttribute("href", "/advisor/conversation-1");
  });

  it("keeps other modules readable when one endpoint fails", async () => {
    mockChanges.mockRejectedValue(new ResearchCenterApiError(403, "当前账户没有权限读取这份研究记录"));
    renderPage();

    expect(await screen.findByText("该模块暂时不可用")).toBeInTheDocument();
    expect(screen.getByText("复核最新证据变化")).toBeInTheDocument();
    expect(screen.getByText("补齐公司最新公告")).toBeInTheDocument();
    expect(screen.getByText("利润改善是否得到经营现金流确认？")).toBeInTheDocument();
  });

  it("renders honest empty states instead of sample research records", async () => {
    mockPriority.mockResolvedValue({ ...parsedResearchCenter.priority(), items: [], coverage: { requested: 0, available: 0, missingBaseline: 0 } });
    mockChanges.mockResolvedValue({ ...parsedResearchCenter.changes(), events: [], coverage: { requested: 0, withReport: 0, withChangeArchive: 0 } });
    mockActions.mockResolvedValue({ ...parsedResearchCenter.actions(), items: [], summary: { symbols: 0, triggered: 0, pendingData: 0, watching: 0, priorityResearch: 0 } });
    mockTasks.mockResolvedValue({ ...parsedResearchCenter.evidenceTasks(), items: [], summary: { total: 0 } });
    mockOutcomes.mockResolvedValue({ ...parsedResearchCenter.outcomes(), items: [], coverage: { requestedSymbols: 0, withArchives: 0, availableOutcomes: 0, pendingOutcomes: 0 } });
    mockReviews.mockResolvedValue({ ...parsedResearchCenter.runReviews(), items: [], summary: { total: 0, filtered: 0, repaired: 0, days: 30 } });
    renderPage();

    expect(await screen.findByText("还没有需要排序的关注标的")).toBeInTheDocument();
    expect(screen.getByText("暂无可追溯变化")).toBeInTheDocument();
    expect(screen.getByText("暂无研究行动")).toBeInTheDocument();
    expect(screen.getByText("暂无补证任务")).toBeInTheDocument();
    expect(screen.getByText("暂无研究结果")).toBeInTheDocument();
    expect(screen.getByText("近 30 日暂无正式 Run")).toBeInTheDocument();
    expect(screen.queryByText("中兴通讯")).not.toBeInTheDocument();
  });

  it("refreshes all six independent modules explicitly", async () => {
    renderPage();
    await screen.findByText("复核最新证据变化");
    fireEvent.click(screen.getByRole("button", { name: "刷新研究状态" }));
    await waitFor(() => {
      expect(mockPriority).toHaveBeenCalledTimes(2);
      expect(mockChanges).toHaveBeenCalledTimes(2);
      expect(mockActions).toHaveBeenCalledTimes(2);
      expect(mockTasks).toHaveBeenCalledTimes(2);
      expect(mockOutcomes).toHaveBeenCalledTimes(2);
      expect(mockReviews).toHaveBeenCalledTimes(2);
    });
  });

  it("does not request personal research data before authentication", () => {
    renderPage(false);
    expect(screen.getByText("登录后可使用研究中心")).toBeInTheDocument();
    expect(mockPriority).not.toHaveBeenCalled();
    expect(mockChanges).not.toHaveBeenCalled();
    expect(mockActions).not.toHaveBeenCalled();
    expect(mockTasks).not.toHaveBeenCalled();
    expect(mockOutcomes).not.toHaveBeenCalled();
    expect(mockReviews).not.toHaveBeenCalled();
  });
});
