import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  AdvisorApiError,
  confirmAiWriteback,
  getAiWritebacks,
  getConversation,
  getConversations,
  openChatStream,
  postChat,
  rejectAiWriteback,
} from "./api";
import { parseChatResponse } from "./adapters";
import {
  chatResponsePayload,
  parsedConversationDetail,
  parsedConversations,
  parsedWritebacks,
} from "./testFixtures";
import { AdvisorPage } from "./AdvisorPage";

vi.mock("./api", async (importOriginal) => {
  const original = await importOriginal<typeof import("./api")>();
  return {
    ...original,
    getConversations: vi.fn(),
    getConversation: vi.fn(),
    getAiWritebacks: vi.fn(),
    postChat: vi.fn(),
    confirmAiWriteback: vi.fn(),
    rejectAiWriteback: vi.fn(),
    openChatStream: vi.fn(() => () => undefined),
  };
});

const mockGetConversations = vi.mocked(getConversations);
const mockGetConversation = vi.mocked(getConversation);
const mockGetWritebacks = vi.mocked(getAiWritebacks);
const mockPostChat = vi.mocked(postChat);
const mockConfirm = vi.mocked(confirmAiWriteback);
const mockReject = vi.mocked(rejectAiWriteback);

function renderPage(entry = "/advisor", authenticated = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route element={<AdvisorPage authenticated={authenticated} />} path="/advisor/:conversationId?" />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockGetConversations.mockResolvedValue(parsedConversations());
  mockGetConversation.mockResolvedValue(parsedConversationDetail());
  mockGetWritebacks.mockResolvedValue(parsedWritebacks());
  mockPostChat.mockResolvedValue(parseChatResponse(chatResponsePayload()));
  mockConfirm.mockResolvedValue(null);
  mockReject.mockResolvedValue(null);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("AdvisorPage", () => {
  it("gives the question action and evidence drawer distinct landmarks without nesting a page main", async () => {
    renderPage("/advisor/conv-1?symbol=000063.SZ");

    const questionAction = await screen.findByRole("region", { name: "提出研究问题" });
    expect(within(questionAction).getByLabelText("向顾问提问")).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "证据与候选写回" })).toBeInTheDocument();
    expect(screen.queryAllByRole("main")).toHaveLength(0);
  });

  it("groups the conversation, evidence and writeback flow into a named research workspace", async () => {
    renderPage("/advisor/conv-1?symbol=000063.SZ");

    const workspace = await screen.findByRole("region", { name: "顾问研究工作台" });
    expect(within(workspace).getByRole("heading", { name: "提出问题，核对证据，再决定是否写入" })).toBeInTheDocument();
    expect(within(workspace).getByText("会话保留推理过程；证据与候选写回只在有真实记录时出现。")).toBeInTheDocument();
    expect(within(workspace).getByLabelText("会话列表与上下文")).toBeInTheDocument();
  });

  it("locks content when unauthenticated", () => {
    renderPage("/advisor", false);
    expect(screen.getByText(/业务内容已锁定/)).toBeInTheDocument();
    expect(screen.queryByLabelText("向顾问提问")).not.toBeInTheDocument();
  });

  it("renders sidebar, context bar and conversation history with passthrough times", async () => {
    renderPage("/advisor/conv-1?symbol=000063.SZ&source=stock-research&module=financials&asOf=2026-08-06");
    // 侧栏会话列表（异步加载后断言）。
    const sidebar = await screen.findByLabelText("会话列表与上下文");
    expect(await within(sidebar).findByText("中兴通讯研究")).toBeInTheDocument();
    expect(within(sidebar).getByText("开始新对话")).toBeInTheDocument();
    // 0 条消息是有效数值正常显示。
    expect(within(sidebar).getByText(/0 条消息/)).toBeInTheDocument();
    // 上下文条：symbol/sourcePage/module/asOf 四元组。
    expect(within(sidebar).getByText("标的：000063.SZ")).toBeInTheDocument();
    expect(within(sidebar).getByText("来源页：个股研究")).toBeInTheDocument();
    expect(within(sidebar).getByText("模块：financials")).toBeInTheDocument();
    expect(within(sidebar).getByText("数据时间：2026-08-06")).toBeInTheDocument();
    // 消息流：用户/助手消息与 GeneratedAt。
    expect(screen.getByText("中兴通讯三季度现金流怎么样？")).toBeInTheDocument();
    expect(screen.getAllByText(/现金流覆盖需要核验/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/生成时间：/).length).toBeGreaterThan(0);
    // 证据抽屉：五面分析与证据来源。
    const drawer = await screen.findByLabelText("证据与候选写回");
    expect(within(drawer).getByText("已确认事实")).toBeInTheDocument();
    expect(within(drawer).getByText("三季度经营性现金流为正")).toBeInTheDocument();
    expect(within(drawer).getByText("2026 年三季度报告")).toBeInTheDocument();
    expect(within(drawer).getByText("部分数据可用")).toBeInTheDocument();
  });

  it("prefills question from URL but never auto-sends", async () => {
    renderPage("/advisor?symbol=000063.SZ&question=现金流怎么样？");
    const input = await screen.findByLabelText("向顾问提问");
    expect(input).toHaveValue("现金流怎么样？");
    expect(mockPostChat).not.toHaveBeenCalled();
  });

  it("sends chat with symbol, conversation id and request id, then shows the answer", async () => {
    renderPage("/advisor/conv-1?symbol=000063.SZ&source=stock-research");
    const input = await screen.findByLabelText("向顾问提问");
    fireEvent.change(input, { target: { value: "请核验现金流覆盖" } });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    await waitFor(() => expect(mockPostChat).toHaveBeenCalledTimes(1));
    const body = mockPostChat.mock.calls[0][0];
    expect(body.symbol).toBe("000063.SZ");
    expect(body.conversationId).toBe("conv-1");
    expect(typeof body.requestId).toBe("string");
    expect(body.message).toContain("请核验现金流覆盖");
    expect(body.message).toContain("[研究上下文：标的=000063.SZ；来源页=stock-research]");
    // 草稿清空，无整页崩溃。
    await waitFor(() => expect(input).toHaveValue(""));
  });

  it("shows clarification flow when response requires more info", async () => {
    mockPostChat.mockResolvedValue(parseChatResponse({
      status: "clarification",
      answer: "请补充",
      evidence: { type: "advisor_lab_clarification", required_fields: ["投资期限", "风险承受能力"] },
      conversation_id: "conv-1",
    }));
    renderPage("/advisor/conv-1");
    fireEvent.change(await screen.findByLabelText("向顾问提问"), { target: { value: "是否加仓" } });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    expect(await screen.findByText("投资期限")).toBeInTheDocument();
    expect(screen.getByText("风险承受能力")).toBeInTheDocument();
  });

  it("renders pending candidate card with confirm dialog carrying the version", async () => {
    renderPage("/advisor/conv-1");
    const drawer = await screen.findByLabelText("证据与候选写回");
    expect(within(drawer).getByText("研究判断候选")).toBeInTheDocument();
    expect(within(drawer).getByText("待确认草稿")).toBeInTheDocument();
    expect(within(drawer).getByText(/基于版本 2/)).toBeInTheDocument();
    // 无 PATCH：候选只有查看/确认/拒绝/回到对话修改，没有编辑按钮。
    expect(within(drawer).queryByRole("button", { name: /编辑/ })).not.toBeInTheDocument();
    // stale 候选不可再确认。
    expect(within(drawer).getByText("内容已过期")).toBeInTheDocument();
    // 确认需二次对话框。
    fireEvent.click(within(drawer).getByRole("button", { name: "确认写回" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/基于版本 2/)).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "取消" }));
    expect(mockConfirm).not.toHaveBeenCalled();
    fireEvent.click(within(drawer).getByRole("button", { name: "确认写回" }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "确认写回" }));
    await waitFor(() => expect(mockConfirm).toHaveBeenCalledWith("cand-1"));
    expect(await screen.findByText(/候选已确认并写入正式研究记录/)).toBeInTheDocument();
  });

  it("rejects a candidate without a dialog", async () => {
    renderPage("/advisor/conv-1");
    const drawer = await screen.findByLabelText("证据与候选写回");
    fireEvent.click(within(drawer).getByRole("button", { name: "拒绝" }));
    await waitFor(() => expect(mockReject).toHaveBeenCalledWith("cand-1"));
    expect(await screen.findByText(/候选已拒绝/)).toBeInTheDocument();
  });

  it("handles 409 on confirm: conflict notice and refresh, no local overwrite", async () => {
    mockConfirm.mockRejectedValue(new AdvisorApiError(409, "该候选对应的正式对象已更新，候选已失效；已刷新最新状态，请回到对话重新生成候选。"));
    renderPage("/advisor/conv-1");
    const drawer = await screen.findByLabelText("证据与候选写回");
    fireEvent.click(within(drawer).getByRole("button", { name: "确认写回" }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "确认写回" }));
    expect(await screen.findByText(/已刷新最新状态/)).toBeInTheDocument();
    // 冲突后重拉候选列表。
    await waitFor(() => expect(mockGetWritebacks.mock.calls.length).toBeGreaterThanOrEqual(2));
  });

  it("routes revise back to the composer", async () => {
    renderPage("/advisor/conv-1");
    const drawer = await screen.findByLabelText("证据与候选写回");
    fireEvent.click(within(drawer).getByRole("button", { name: "回到对话修改" }));
    const input = await screen.findByLabelText("向顾问提问");
    expect(input).toHaveValue("关于刚才的研究判断候选（000063.SZ），我希望调整为：");
    expect(mockPostChat).not.toHaveBeenCalled();
  });

  it("shows empty state without conversations and no fake data", async () => {
    mockGetConversations.mockResolvedValue({ items: [] });
    mockGetWritebacks.mockResolvedValue({ status: "ready", items: [], summary: { total: 0, pendingConfirmation: 0 } });
    renderPage("/advisor");
    expect(await screen.findByText(/还没有研究对话/)).toBeInTheDocument();
    expect(screen.getByText(/输入第一个问题/)).toBeInTheDocument();
    // 无候选且无证据时不渲染抽屉空壳。
    expect(screen.queryByLabelText("证据与候选写回")).not.toBeInTheDocument();
  });
});
