import { api } from "../../api/client";
import {
  parseResearchActions,
  parseResearchChanges,
  parseResearchOutcomes,
  parseResearchReport,
  parsePendingWritebacks,
  parseTradeReviewCenter,
  parseWorkspaceTimeline,
  type ResearchActions,
  type ResearchChanges,
  type ResearchOutcomes,
  type ResearchReport,
  type PendingWritebacks,
  type TradeReviewCenter,
  type WorkspaceTimeline,
} from "./adapters";

export class ResearchCenterApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
    this.name = "ResearchCenterApiError";
  }
}

function unwrap<T>(
  response: Response,
  data: unknown,
  error: unknown,
  parse: (value: unknown) => T,
): T {
  if (!response.ok || error || data === undefined) {
    throw new ResearchCenterApiError(response.status, response.status === 401 ? "会话已失效" : "数据暂时不可用");
  }
  return parse(data);
}

export async function getResearchChanges(): Promise<ResearchChanges> {
  const { data, error, response } = await api.GET("/me/research-changes");
  return unwrap(response, data, error, parseResearchChanges);
}

export async function getResearchOutcomes(): Promise<ResearchOutcomes> {
  const { data, error, response } = await api.GET("/me/research-outcomes");
  return unwrap(response, data, error, parseResearchOutcomes);
}

export async function getResearchActions(): Promise<ResearchActions> {
  const { data, error, response } = await api.GET("/me/research-actions");
  return unwrap(response, data, error, parseResearchActions);
}

export async function getTradeReviewCenter(): Promise<TradeReviewCenter> {
  const { data, error, response } = await api.GET("/v1/trade-reviews");
  return unwrap(response, data, error, parseTradeReviewCenter);
}

export async function getWorkspaceTimeline(symbol: string): Promise<WorkspaceTimeline> {
  const { data, error, response } = await api.GET("/v1/stocks/{symbol}/workspace/timeline", {
    params: { path: { symbol } },
  });
  return unwrap(response, data, error, parseWorkspaceTimeline);
}

export async function getResearchReport(symbol: string): Promise<ResearchReport> {
  const { data, error, response } = await api.GET("/research-reports/{symbol}", {
    params: { path: { symbol } },
  });
  return unwrap(response, data, error, parseResearchReport);
}

export type TradeReviewDraftInput = {
  baseVersion: number;
  priceResult: string;
  logicResult: string;
  planDeviation: string | null;
  biasTags: string[];
  improvementText: string | null;
};

export type TradeReviewFollowupInput = {
  target: "observation_task" | "thesis_draft";
  title: string | null;
  priority: "high" | "normal" | "low";
};

function unwrapMutation(response: Response, data: unknown, error: unknown): unknown {
  if (response.status === 409) {
    throw new ResearchCenterApiError(409, "该记录已被其他操作更新，已刷新最新状态，请确认后重试。");
  }
  return unwrap(response, data, error, (value) => value);
}

export async function getPendingWritebacks(): Promise<PendingWritebacks> {
  const { data, error, response } = await api.GET("/v1/ai-writebacks", {
    params: { query: { status: "pending_confirmation", limit: 100 } },
  });
  return unwrap(response, data, error, parsePendingWritebacks);
}

export async function generateTradeReviewDraft(
  reviewId: string,
  baseVersion: number,
  modelTier: "economy" | "deep",
): Promise<unknown> {
  const { data, error, response } = await api.POST("/v1/trade-reviews/{review_id}/generate-draft", {
    params: { path: { review_id: reviewId } },
    body: { base_version: baseVersion, model_tier: modelTier },
  });
  return unwrapMutation(response, data, error);
}

export async function confirmWriteback(candidateId: string): Promise<unknown> {
  const { data, error, response } = await api.POST("/v1/ai-writebacks/{candidate_id}/confirm", {
    params: { path: { candidate_id: candidateId } },
  });
  return unwrapMutation(response, data, error);
}

export async function rejectWriteback(candidateId: string): Promise<unknown> {
  const { data, error, response } = await api.POST("/v1/ai-writebacks/{candidate_id}/reject", {
    params: { path: { candidate_id: candidateId } },
  });
  return unwrapMutation(response, data, error);
}

export async function updateTradeReviewDraft(reviewId: string, draft: TradeReviewDraftInput): Promise<unknown> {
  const { data, error, response } = await api.PATCH("/v1/trade-reviews/{review_id}/draft", {
    params: { path: { review_id: reviewId } },
    body: {
      base_version: draft.baseVersion,
      price_result: draft.priceResult,
      logic_result: draft.logicResult,
      plan_deviation: draft.planDeviation,
      bias_tags: draft.biasTags,
      improvement_text: draft.improvementText,
    },
  });
  return unwrapMutation(response, data, error);
}

export async function createTradeReviewFollowup(reviewId: string, followup: TradeReviewFollowupInput): Promise<unknown> {
  const { data, error, response } = await api.POST("/v1/trade-reviews/{review_id}/followups", {
    params: { path: { review_id: reviewId } },
    body: followup,
  });
  return unwrapMutation(response, data, error);
}

async function postTradeReviewTransition(
  path: "/v1/trade-reviews/{review_id}/confirm" | "/v1/trade-reviews/{review_id}/archive",
  reviewId: string,
  baseVersion: number,
): Promise<unknown> {
  const { data, error, response } = await api.POST(path, {
    params: { path: { review_id: reviewId } },
    body: { base_version: baseVersion },
  });
  if (response.status === 409) {
    throw new ResearchCenterApiError(409, "该复盘已被其他操作更新，已刷新最新状态，请确认后重试。");
  }
  return unwrap(response, data, error, (value) => value);
}

/** 确认复盘草稿（draft → confirmed）：base_version 为 current_version.version_no，409 刷新后由用户重新确认。 */
export function confirmTradeReview(reviewId: string, baseVersion: number): Promise<unknown> {
  return postTradeReviewTransition("/v1/trade-reviews/{review_id}/confirm", reviewId, baseVersion);
}

/** 归档已确认复盘（confirmed → archived）：base_version 同上。 */
export function archiveTradeReview(reviewId: string, baseVersion: number): Promise<unknown> {
  return postTradeReviewTransition("/v1/trade-reviews/{review_id}/archive", reviewId, baseVersion);
}
