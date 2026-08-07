import { api } from "../../api/client";
import {
  parseResearchActions,
  parseResearchChanges,
  parseResearchOutcomes,
  parseResearchReport,
  parseTradeReviewCenter,
  parseWorkspaceTimeline,
  type ResearchActions,
  type ResearchChanges,
  type ResearchOutcomes,
  type ResearchReport,
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
