import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  confirmAdvisorWriteback,
  createAdvisorConversation,
  getAdvisorConversation,
  getAdvisorRun,
  listAdvisorConversations,
  listAdvisorWritebacks,
  rejectAdvisorWriteback,
  renameAdvisorConversation,
  archiveAdvisorConversation,
  AdvisorApiError,
  sendAdvisorMessage,
} from "./api";
import { AdvisorPage } from "./AdvisorPage";
import type {
  AdvisorConversationDetail,
  AdvisorConversationSummary,
  AdvisorRun,
  WritebackCandidate,
} from "./adapters";

vi.mock("./api", async (importOriginal) => {
  const original = await importOriginal<typeof import("./api")>();
  return {
    ...original,
    listAdvisorConversations: vi.fn(),
    getAdvisorConversation: vi.fn(),
    createAdvisorConversation: vi.fn(),
    renameAdvisorConversation: vi.fn(),
    archiveAdvisorConversation: vi.fn(),
    sendAdvisorMessage: vi.fn(),
    getAdvisorRun: vi.fn(),
    listAdvisorWritebacks: vi.fn(),
    confirmAdvisorWriteback: vi.fn(),
    rejectAdvisorWriteback: vi.fn(),
  };
});

class MockEventSource {
  static instances: MockEventSource[] = [];
  readonly url: string;
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;

  constructor(url: string | URL) {
    this.url = String(url);
    MockEventSource.instances.push(this);
  }

  close() {
    this.closed = true;
  }

  emit(payload: Record<string, unknown>) {
    this.onmessage?.({ data: JSON.stringify(payload) } as MessageEvent<string>);
  }
}

const conversation: AdvisorConversationSummary = {
  id: "conversation-1",
  title: "中兴通讯风险",
  qualityScope: "user",
  status: "active",
  messageCount: 2,
  lastMessagePreview: "需要优先核验现金流",
  lastIntent: "stock_research",
  conversationScope: "stock",
  researchTargets: [{ symbol: "000063.SZ", name: "中兴通讯" }],
  createdAt: "2026-08-07T01:00:00Z",
  updatedAt: "2026-08-07T01:02:00Z",
};

const candidate: WritebackCandidate = {
  id: "candidate-1",
  symbol: "000063.SZ",
  candidateType: "thesis",
  status: "pending_confirmation",
  payload: {
    current_reason_text: "等待订单兑现",
    reason_text: "优先核验经营现金流与订单质量",
  },
  citationIds: ["citation-1"],
  baseVersion: 2,
  createdAt: "2026-08-07T01:02:00Z",
  resolvedAt: null,
};

const detail: AdvisorConversationDetail = {
  ...conversation,
  messages: [
    {
      id: "message-1",
      role: "user",
      content: "当前最需要核验什么？",
      intent: null,
      runId: null,
      createdAt: "2026-08-07T01:01:00Z",
      structuredAnswer: null,
      evidenceSources: [],
    },
    {
      id: "message-2",
      role: "assistant",
      content: "需要优先核验经营现金流与订单兑现。",
      intent: "stock_research",
      runId: "run-1",
      createdAt: "2026-08-07T01:02:00Z",
      structuredAnswer: {
        status: "complete",
        citations: [{
          id: "citation-1",
          sourceName: "公司公告",
          sourceUrl: null,
          evidenceType: "filing",
          dataTime: "2026-08-06",
          reportPeriod: null,
          excerpt: "经营现金流仍需结合订单兑现继续核验。",
          limitations: ["单一公告不能证明完整因果。"],
        }],
        candidateWritebacks: [candidate],
      },
      evidenceSources: [{ title: "公司公告", kind: "filing", copy: null, meta: "2026-08-06", url: null }],
    },
  ],
};

const run: AdvisorRun = {
  id: "run-1",
  status: "completed",
  answer: "需要优先核验经营现金流与订单兑现。",
  error: null,
  entryContext: {
    sourcePage: "stock",
    module: "stock-research",
    asOf: null,
    symbol: "000063.SZ",
  },
};

const mockListConversations = vi.mocked(listAdvisorConversations);
const mockGetConversation = vi.mocked(getAdvisorConversation);
const mockCreateConversation = vi.mocked(createAdvisorConversation);
const mockRenameConversation = vi.mocked(renameAdvisorConversation);
const mockArchiveConversation = vi.mocked(archiveAdvisorConversation);
const mockSendMessage = vi.mocked(sendAdvisorMessage);
const mockGetRun = vi.mocked(getAdvisorRun);
const mockListWritebacks = vi.mocked(listAdvisorWritebacks);
const mockConfirmWriteback = vi.mocked(confirmAdvisorWriteback);
const mockRejectWriteback = vi.mocked(rejectAdvisorWriteback);

function renderAdvisor(entry = "/advisor/conversation-1?symbol=000063.SZ&source=stock-research", authenticated = true) {
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
  vi.stubGlobal("EventSource", MockEventSource);
  vi.stubGlobal("crypto", { randomUUID: () => "request-advisor-0001" });
  MockEventSource.instances = [];
  mockListConversations.mockResolvedValue([conversation]);
  mockGetConversation.mockResolvedValue(detail);
  mockCreateConversation.mockResolvedValue(conversation);
  mockRenameConversation.mockResolvedValue(conversation);
  mockArchiveConversation.mockResolvedValue(undefined);
  mockSendMessage.mockResolvedValue({
    runId: "run-1",
    status: "completed",
    intent: "stock_research",
    answer: "需要优先核验经营现金流与订单兑现。",
    conversationId: "conversation-1",
    conversationTitle: "中兴通讯风险",
    assistantMessageId: "message-2",
    structuredAnswer: detail.messages[1]!.structuredAnswer,
    evidenceSources: detail.messages[1]!.evidenceSources,
  });
  mockGetRun.mockResolvedValue(run);
  mockListWritebacks.mockResolvedValue({ items: [candidate], pendingCount: 1 });
  mockConfirmWriteback.mockResolvedValue({ ...candidate, status: "confirmed" });
  mockRejectWriteback.mockResolvedValue({ ...candidate, status: "rejected" });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

describe("AdvisorPage", () => {
  it("renders persisted conversation evidence without inventing a factor score", async () => {
    renderAdvisor();

    expect(await screen.findByText("需要优先核验经营现金流与订单兑现。")).toBeInTheDocument();
    expect(screen.getByText("公司公告")).toBeInTheDocument();
    expect(screen.getByText("来源已记录")).toBeInTheDocument();
    expect(screen.queryByText(/五因素/)).not.toBeInTheDocument();
  });

  it("opens one private stream and submits the same request id with strict entry context", async () => {
    renderAdvisor();
    const input = await screen.findByLabelText("向金融顾问提问");
    fireEvent.change(input, { target: { value: "分析当前最需要核验的风险" } });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    expect(MockEventSource.instances).toHaveLength(1);
    expect(MockEventSource.instances[0]!.url).toContain("/me/chat/stream/request-advisor-0001");
    await waitFor(() => expect(mockSendMessage).toHaveBeenCalledTimes(1));
    expect(mockSendMessage.mock.calls[0]?.[0]).toEqual(expect.objectContaining({
      message: "分析当前最需要核验的风险",
      conversation_id: "conversation-1",
      request_id: "request-advisor-0001",
      symbol: "000063.SZ",
      entry_context: {
        source_page: "stock",
        module: "stock-research",
        symbol: "000063.SZ",
      },
    }));
  });

  it("requires a second explicit confirmation before applying a writeback candidate", async () => {
    renderAdvisor();
    await screen.findByText("AI 提出的判断草稿");

    fireEvent.click(screen.getByRole("button", { name: "确认写回" }));
    expect(mockConfirmWriteback).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "确认写回这份草稿" }));
    await waitFor(() => expect(mockConfirmWriteback).toHaveBeenCalledWith("candidate-1"));
  });

  it("shows only guarded or final stream text and closes the connection after the HTTP answer", async () => {
    let resolveResponse: ((value: Awaited<ReturnType<typeof sendAdvisorMessage>>) => void) | undefined;
    mockSendMessage.mockImplementationOnce(() => new Promise((resolve) => { resolveResponse = resolve; }));
    renderAdvisor();
    fireEvent.change(await screen.findByLabelText("向金融顾问提问"), { target: { value: "继续核验风险" } });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    const source = MockEventSource.instances[0]!;

    act(() => source.emit({ type: "agent_delta", draft: "未经校验的草稿", is_unverified: true }));
    expect(screen.queryByText("未经校验的草稿")).not.toBeInTheDocument();
    act(() => source.emit({ type: "agent_delta", draft: "目前可确认的内容", is_guarded_partial: true }));
    expect(screen.getByText("目前可确认的内容")).toBeInTheDocument();

    await waitFor(() => expect(resolveResponse).toBeDefined());
    await act(async () => {
      resolveResponse!({
        runId: "run-1",
        status: "completed",
        intent: "stock_research",
        answer: "最终回答",
        conversationId: "conversation-1",
        conversationTitle: "中兴通讯风险",
        assistantMessageId: "message-2",
        structuredAnswer: null,
        evidenceSources: [],
      });
    });
    await waitFor(() => expect(source.closed).toBe(true));
  });

  it("keeps a stale candidate visible after a 409 instead of retrying the write", async () => {
    mockConfirmWriteback.mockRejectedValueOnce(new AdvisorApiError(409, "正式判断已更新，请刷新后重新确认"));
    renderAdvisor();
    await screen.findByText("AI 提出的判断草稿");
    fireEvent.click(screen.getByRole("button", { name: "确认写回" }));
    fireEvent.click(screen.getByRole("button", { name: "确认写回这份草稿" }));

    expect(await screen.findByText("正式判断已更新，请刷新后重新确认")).toBeInTheDocument();
    expect(screen.getByText("AI 提出的判断草稿")).toBeInTheDocument();
    expect(mockConfirmWriteback).toHaveBeenCalledTimes(1);
  });

  it("does not request private advisor data before login", () => {
    renderAdvisor("/advisor", false);
    expect(screen.getByText("登录后可使用金融顾问")).toBeInTheDocument();
    expect(mockListConversations).not.toHaveBeenCalled();
    expect(mockListWritebacks).not.toHaveBeenCalled();
  });
});
