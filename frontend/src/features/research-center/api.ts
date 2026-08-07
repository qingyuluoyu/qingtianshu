import { api } from "../../api/client";
import {
  parseEvidenceTasks,
  parseResearchActions,
  parseResearchChanges,
  parseResearchOutcomes,
  parseResearchPriority,
  parseRunReviews,
  ResearchCenterContractError,
  type EvidenceTasksPacket,
  type ResearchActionsPacket,
  type ResearchChangesPacket,
  type ResearchOutcomesPacket,
  type ResearchPriorityPacket,
  type RunReviewsPacket,
} from "./adapters";

export class ResearchCenterApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
    this.name = "ResearchCenterApiError";
  }
}

function responseMessage(status: number, error: unknown): string {
  if (typeof error === "object" && error !== null) {
    const payload = error as Record<string, unknown>;
    if (typeof payload.detail === "string" && payload.detail) return payload.detail;
    if (typeof payload.message === "string" && payload.message) return payload.message;
  }
  if (status === 401) return "会话已失效";
  if (status === 403) return "当前账户没有权限读取这份研究记录";
  if (status === 404) return "对应的研究记录不存在";
  return "研究数据暂时不可用";
}

function unwrap<T>(
  response: Response,
  data: unknown,
  error: unknown,
  parse: (value: unknown) => T,
): T {
  if (!response.ok || error || data === undefined) {
    throw new ResearchCenterApiError(response.status, responseMessage(response.status, error));
  }
  try {
    return parse(data);
  } catch (parseError) {
    if (parseError instanceof ResearchCenterContractError) {
      throw new ResearchCenterApiError(502, "研究中心返回的数据格式不完整");
    }
    throw parseError;
  }
}

export async function getResearchPriority(): Promise<ResearchPriorityPacket> {
  const { data, error, response } = await api.GET("/me/research-priority");
  return unwrap(response, data, error, parseResearchPriority);
}

export async function getResearchChanges(): Promise<ResearchChangesPacket> {
  const { data, error, response } = await api.GET("/me/research-changes", {
    params: { query: { limit: 30 } },
  });
  return unwrap(response, data, error, parseResearchChanges);
}

export async function getResearchActions(): Promise<ResearchActionsPacket> {
  const { data, error, response } = await api.GET("/me/research-actions");
  return unwrap(response, data, error, parseResearchActions);
}

export async function getEvidenceTasks(): Promise<EvidenceTasksPacket> {
  const { data, error, response } = await api.GET("/me/evidence-tasks", {
    params: { query: { limit: 50 } },
  });
  return unwrap(response, data, error, parseEvidenceTasks);
}

export async function getResearchOutcomes(): Promise<ResearchOutcomesPacket> {
  const { data, error, response } = await api.GET("/me/research-outcomes", {
    params: { query: { limit: 120 } },
  });
  return unwrap(response, data, error, parseResearchOutcomes);
}

export async function getRunReviews(): Promise<RunReviewsPacket> {
  const { data, error, response } = await api.GET("/me/run-reviews", {
    params: { query: { days: 30, limit: 30 } },
  });
  return unwrap(response, data, error, parseRunReviews);
}
