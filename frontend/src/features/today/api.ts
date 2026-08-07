import { api } from "../../api/client";
import {
  parseBreadth,
  parseCapitalFlow,
  parseDataHealth,
  parseGlobalIndices,
  parseIndexHistory,
  parseIndices,
  parseLatestResearchReports,
  parseLiveMarkets,
  parseMarketAnomalies,
  parseOverview,
  parsePositions,
  parseResearchActions,
  parseResearchChanges,
  parseSectors,
  parseWatchlistBrief,
  type Breadth,
  type CapitalFlow,
  type DataHealth,
  type GlobalIndices,
  type IndexHistory,
  type Indices,
  type LatestResearchReports,
  type LiveMarkets,
  type MarketAnomalies,
  type Overview,
  type Positions,
  type ResearchActions,
  type ResearchChanges,
  type Sectors,
  type WatchlistBrief,
} from "./adapters";

export class TodayApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
    this.name = "TodayApiError";
  }
}

function unwrap<T>(
  response: Response,
  data: unknown,
  error: unknown,
  parse: (value: unknown) => T,
): T {
  if (!response.ok || error || data === undefined) {
    throw new TodayApiError(response.status, response.status === 401 ? "会话已失效" : "数据暂时不可用");
  }
  return parse(data);
}

export async function getTodayOverview(signal?: AbortSignal): Promise<Overview> {
  const { data, error, response } = await api.GET("/v1/today/overview", { signal });
  return unwrap(response, data, error, parseOverview);
}

export async function getIndices(signal?: AbortSignal): Promise<Indices> {
  const { data, error, response } = await api.GET("/indices", { params: { query: { scope: "all", group: "china" } }, signal });
  return unwrap(response, data, error, parseIndices);
}

export async function getBreadth(signal?: AbortSignal): Promise<Breadth> {
  const { data, error, response } = await api.GET("/markets/breadth", { signal });
  return unwrap(response, data, error, parseBreadth);
}

export async function getSectors(signal?: AbortSignal): Promise<Sectors> {
  const { data, error, response } = await api.GET("/sectors/hot", { params: { query: { limit: 10 } }, signal });
  return unwrap(response, data, error, parseSectors);
}

export async function getWatchlistBrief(signal?: AbortSignal): Promise<WatchlistBrief> {
  const { data, error, response } = await api.GET("/me/watchlist/brief", { signal });
  return unwrap(response, data, error, parseWatchlistBrief);
}

export async function getResearchActions(signal?: AbortSignal): Promise<ResearchActions> {
  const { data, error, response } = await api.GET("/me/research-actions", { signal });
  return unwrap(response, data, error, parseResearchActions);
}

export async function getResearchChanges(signal?: AbortSignal): Promise<ResearchChanges> {
  const { data, error, response } = await api.GET("/me/research-changes", { params: { query: { limit: 20 } }, signal });
  return unwrap(response, data, error, parseResearchChanges);
}

export async function getDataHealth(signal?: AbortSignal): Promise<DataHealth> {
  const { data, error, response } = await api.GET("/system/data-health", { signal });
  return unwrap(response, data, error, parseDataHealth);
}

export async function getIndexHistory(symbol: string, signal?: AbortSignal): Promise<IndexHistory> {
  const { data, error, response } = await api.GET("/indices/{symbol}/history", {
    params: { path: { symbol }, query: { range: "1mo" } }, signal,
  });
  return unwrap(response, data, error, parseIndexHistory);
}

export async function getLatestResearchReports(signal?: AbortSignal): Promise<LatestResearchReports> {
  const { data, error, response } = await api.GET("/research-reports/latest", { params: { query: { limit: 20 } }, signal });
  return unwrap(response, data, error, parseLatestResearchReports);
}

export async function getCapitalFlow(signal?: AbortSignal): Promise<CapitalFlow> {
  const { data, error, response } = await api.GET("/markets/capital-flow", { signal });
  return unwrap(response, data, error, parseCapitalFlow);
}

export async function getPositions(signal?: AbortSignal): Promise<Positions> {
  const { data, error, response } = await api.GET("/v1/positions", { signal });
  return unwrap(response, data, error, parsePositions);
}

export async function getMarketAnomalies(signal?: AbortSignal): Promise<MarketAnomalies> {
  const { data, error, response } = await api.GET("/markets/anomalies", { params: { query: { limit: 10 } }, signal });
  return unwrap(response, data, error, parseMarketAnomalies);
}

export async function getGlobalIndices(signal?: AbortSignal): Promise<GlobalIndices> {
  const { data, error, response } = await api.GET("/indices", { params: { query: { scope: "all", group: "us" } }, signal });
  return unwrap(response, data, error, parseGlobalIndices);
}

export async function getLiveMarkets(signal?: AbortSignal): Promise<LiveMarkets> {
  const { data, error, response } = await api.GET("/markets/live", { signal });
  return unwrap(response, data, error, parseLiveMarkets);
}
