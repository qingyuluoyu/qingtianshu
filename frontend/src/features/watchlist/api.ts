import { api } from "../../api/client";
import {
  parseStockHistory,
  parseWorkspace,
  type StockHistory,
  type Workspace,
} from "../stock-research/adapters";
import {
  parseStockRelation,
  parseWatchlistAssets,
  type RelationPatch,
  type StockRelation,
  type WatchlistAssets,
} from "./adapters";

export class WatchlistApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
    this.name = "WatchlistApiError";
  }
}

function unwrap<T>(
  response: Response,
  data: unknown,
  error: unknown,
  parse: (value: unknown) => T,
): T {
  if (!response.ok || error || data === undefined) {
    throw new WatchlistApiError(response.status, response.status === 401 ? "会话已失效" : "数据暂时不可用");
  }
  return parse(data);
}

export async function getStockWorkspaces(): Promise<WatchlistAssets> {
  const { data, error, response } = await api.GET("/v1/stock-workspaces");
  return unwrap(response, data, error, parseWatchlistAssets);
}

export async function getStockWorkspace(symbol: string): Promise<Workspace> {
  const { data, error, response } = await api.GET("/v1/stocks/{symbol}/workspace", {
    params: { path: { symbol } },
  });
  return unwrap(response, data, error, parseWorkspace);
}

export async function getStockHistory(symbol: string): Promise<StockHistory> {
  const { data, error, response } = await api.GET("/stocks/{symbol}/history", {
    params: { path: { symbol }, query: { range: "3mo" } },
  });
  return unwrap(response, data, error, parseStockHistory);
}

export async function patchStockRelation(symbol: string, patch: RelationPatch): Promise<StockRelation> {
  const { data, error, response } = await api.PATCH("/v1/stocks/{symbol}/relation", {
    params: { path: { symbol } },
    body: {
      base_version: patch.baseVersion,
      relation_type: patch.relationType,
      priority: patch.priority,
      tracking_status: patch.trackingStatus,
      workflow_status: patch.workflowStatus,
      attention_tags: patch.attentionTags,
    },
  });
  if (response.status === 409) {
    throw new WatchlistApiError(409, "该股票关系已被其他操作更新，已刷新最新状态，请确认后重试。");
  }
  return unwrap(response, data, error, parseStockRelation);
}
