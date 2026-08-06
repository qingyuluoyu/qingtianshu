import type { components } from "../../api/openapi.generated";
import { api } from "../../api/client";
import {
  AdvisorContractError,
  parseAdvisorRun,
  parseChatAccepted,
  parseConversationDetail,
  parseConversationList,
  parseConversationSummary,
  parseWritebackCandidate,
  parseWritebackList,
  type AdvisorChatAccepted,
  type AdvisorConversationDetail,
  type AdvisorConversationSummary,
  type AdvisorRun,
  type WritebackCandidate,
} from "./adapters";

export type AdvisorChatRequest = components["schemas"]["ChatRequest"];

export class AdvisorApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
    this.name = "AdvisorApiError";
  }
}

function responseMessage(status: number, error: unknown): string {
  if (typeof error === "object" && error !== null) {
    const payload = error as Record<string, unknown>;
    if (typeof payload.detail === "string" && payload.detail) return payload.detail;
    if (typeof payload.message === "string" && payload.message) return payload.message;
  }
  if (status === 401) return "会话已失效";
  if (status === 403) return "当前账户没有权限";
  if (status === 404) return "对应的研究记录不存在";
  if (status === 409) return "记录已被其他操作更新，请刷新后重新确认";
  return "金融顾问暂时不可用";
}

function unwrap<T>(
  response: Response,
  data: unknown,
  error: unknown,
  parse: (value: unknown) => T,
): T {
  if (!response.ok || error || data === undefined) {
    throw new AdvisorApiError(response.status, responseMessage(response.status, error));
  }
  try {
    return parse(data);
  } catch (parseError) {
    if (parseError instanceof AdvisorContractError) {
      throw new AdvisorApiError(502, "金融顾问返回的数据格式不完整");
    }
    throw parseError;
  }
}

export async function listAdvisorConversations(): Promise<AdvisorConversationSummary[]> {
  const { data, error, response } = await api.GET("/me/conversations", {
    params: { query: { limit: 100 } },
  });
  return unwrap(response, data, error, parseConversationList);
}

export async function getAdvisorConversation(id: string): Promise<AdvisorConversationDetail> {
  const { data, error, response } = await api.GET("/me/conversations/{conversation_id}", {
    params: { path: { conversation_id: id } },
  });
  return unwrap(response, data, error, parseConversationDetail);
}

export async function createAdvisorConversation(): Promise<AdvisorConversationSummary> {
  const { data, error, response } = await api.POST("/me/conversations", {
    body: { title: "新的研究对话", quality_scope: "user" },
  });
  return unwrap(response, data, error, parseConversationSummary);
}

export async function renameAdvisorConversation(id: string, title: string): Promise<AdvisorConversationSummary> {
  const { data, error, response } = await api.PATCH("/me/conversations/{conversation_id}", {
    params: { path: { conversation_id: id } },
    body: { title },
  });
  return unwrap(response, data, error, parseConversationSummary);
}

export async function archiveAdvisorConversation(id: string): Promise<void> {
  const { error, response } = await api.DELETE("/me/conversations/{conversation_id}", {
    params: { path: { conversation_id: id } },
  });
  if (!response.ok || error) {
    throw new AdvisorApiError(response.status, responseMessage(response.status, error));
  }
}

export async function sendAdvisorMessage(request: AdvisorChatRequest): Promise<AdvisorChatAccepted> {
  const { data, error, response } = await api.POST("/me/chat", { body: request });
  return unwrap(response, data, error, parseChatAccepted);
}

export async function getAdvisorRun(id: string): Promise<AdvisorRun> {
  const { data, error, response } = await api.GET("/me/runs/{run_id}", {
    params: { path: { run_id: id } },
  });
  return unwrap(response, data, error, parseAdvisorRun);
}

export async function listAdvisorWritebacks(): Promise<{ items: WritebackCandidate[]; pendingCount: number | null }> {
  const { data, error, response } = await api.GET("/v1/ai-writebacks", {
    params: { query: { limit: 100 } },
  });
  return unwrap(response, data, error, parseWritebackList);
}

export async function confirmAdvisorWriteback(id: string): Promise<WritebackCandidate> {
  const { data, error, response } = await api.POST("/v1/ai-writebacks/{candidate_id}/confirm", {
    params: { path: { candidate_id: id } },
  });
  return unwrap(response, data, error, parseWritebackCandidate);
}

export async function rejectAdvisorWriteback(id: string): Promise<WritebackCandidate> {
  const { data, error, response } = await api.POST("/v1/ai-writebacks/{candidate_id}/reject", {
    params: { path: { candidate_id: id } },
  });
  return unwrap(response, data, error, parseWritebackCandidate);
}
