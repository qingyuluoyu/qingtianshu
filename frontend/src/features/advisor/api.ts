import { api } from "../../api/client";
import {
  parseChatResponse,
  parseConversationDetail,
  parseConversationList,
  parseWritebackCandidate,
  parseWritebackList,
  type ChatRequestBody,
  type ChatResponse,
  type ConversationDetail,
  type ConversationList,
  type WritebackCandidate,
  type WritebackList,
} from "./adapters";

export class AdvisorApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
    this.name = "AdvisorApiError";
  }
}

function unwrap<T>(
  response: Response,
  data: unknown,
  error: unknown,
  parse: (value: unknown) => T,
): T {
  if (!response.ok || error || data === undefined) {
    throw new AdvisorApiError(
      response.status,
      response.status === 401 ? "会话已失效" : response.status === 404 ? "研究对话不存在" : "数据暂时不可用",
    );
  }
  return parse(data);
}

export async function getConversations(): Promise<ConversationList> {
  const { data, error, response } = await api.GET("/me/conversations");
  return unwrap(response, data, error, parseConversationList);
}

export async function getConversation(conversationId: string): Promise<ConversationDetail> {
  const { data, error, response } = await api.GET("/me/conversations/{conversation_id}", {
    params: { path: { conversation_id: conversationId } },
  });
  return unwrap(response, data, error, parseConversationDetail);
}

export async function postChat(body: ChatRequestBody): Promise<ChatResponse> {
  const { data, error, response } = await api.POST("/me/chat", {
    body: {
      message: body.message,
      symbol: body.symbol ?? null,
      model_tier: "economy",
      execute_agent: true,
      prefer_precomputed: false,
      conversation_id: body.conversationId ?? null,
      request_id: body.requestId ?? null,
      quality_scope: "user",
    },
  });
  return unwrap(response, data, error, parseChatResponse);
}

export async function getAiWritebacks(): Promise<WritebackList> {
  const { data, error, response } = await api.GET("/v1/ai-writebacks");
  return unwrap(response, data, error, parseWritebackList);
}

export async function confirmAiWriteback(candidateId: string): Promise<WritebackCandidate | null> {
  const { data, error, response } = await api.POST("/v1/ai-writebacks/{candidate_id}/confirm", {
    params: { path: { candidate_id: candidateId } },
  });
  if (response.status === 409) {
    throw new AdvisorApiError(409, "该候选对应的正式对象已更新，候选已失效；已刷新最新状态，请回到对话重新生成候选。");
  }
  // 响应 = public_writeback + 目标对象（thesis/observation_task/...），列表状态由失效重拉保证。
  return unwrap(response, data, error, parseWritebackCandidate);
}

export async function rejectAiWriteback(candidateId: string): Promise<WritebackCandidate | null> {
  const { data, error, response } = await api.POST("/v1/ai-writebacks/{candidate_id}/reject", {
    params: { path: { candidate_id: candidateId } },
  });
  return unwrap(response, data, error, parseWritebackCandidate);
}

// ---------- SSE 进度（GET /me/chat/stream/{request_id}，不在 openapi 中，include_in_schema=False） ----------

export type ChatStreamEvent = {
  type: string | null;
  phase: string | null;
  label: string | null;
};

/**
 * 订阅一次提问的生成进度。失败（404/网络断开）静默降级为「无进度」，
 * 完整回答始终以 POST /me/chat 的同步响应为准。返回取消函数。
 */
export function openChatStream(
  requestId: string,
  onEvent: (event: ChatStreamEvent) => void,
): () => void {
  if (typeof EventSource === "undefined") return () => undefined;
  const source = new EventSource(`/me/chat/stream/${encodeURIComponent(requestId)}`);
  source.onmessage = (message) => {
    try {
      const raw = JSON.parse(String(message.data)) as Record<string, unknown>;
      onEvent({
        type: typeof raw.type === "string" ? raw.type : null,
        phase: typeof raw.phase === "string" ? raw.phase : null,
        label: typeof raw.label === "string" ? raw.label : null,
      });
    } catch {
      // 心跳（": heartbeat"）与异常帧不进入 UI。
    }
  };
  source.onerror = () => {
    // 静默降级：进度不可用时主链路不受影响。
  };
  return () => source.close();
}
