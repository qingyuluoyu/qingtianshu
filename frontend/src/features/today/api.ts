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

export async function getTodayOverview(): Promise<Overview> {
  const { data, error, response } = await api.GET("/v1/today/overview");
  return unwrap(response, data, error, parseOverview);
}

export async function getIndices(): Promise<Indices> {
  const { data, error, response } = await api.GET("/indices", { params: { query: { scope: "all", group: "china" } } });
  return unwrap(response, data, error, parseIndices);
}

export async function getBreadth(): Promise<Breadth> {
  const { data, error, response } = await api.GET("/markets/breadth");
  return unwrap(response, data, error, parseBreadth);
}

export async function getSectors(): Promise<Sectors> {
  const { data, error, response } = await api.GET("/sectors/hot", { params: { query: { limit: 10 } } });
  return unwrap(response, data, error, parseSectors);
}

export async function getWatchlistBrief(): Promise<WatchlistBrief> {
  const { data, error, response } = await api.GET("/me/watchlist/brief");
  return unwrap(response, data, error, parseWatchlistBrief);
}

export async function getResearchActions(): Promise<ResearchActions> {
  const { data, error, response } = await api.GET("/me/research-actions");
  return unwrap(response, data, error, parseResearchActions);
}

export async function getResearchChanges(): Promise<ResearchChanges> {
  const { data, error, response } = await api.GET("/me/research-changes", { params: { query: { limit: 20 } } });
  return unwrap(response, data, error, parseResearchChanges);
}

export async function getDataHealth(): Promise<DataHealth> {
  const { data, error, response } = await api.GET("/system/data-health");
  return unwrap(response, data, error, parseDataHealth);
}

export async function getIndexHistory(symbol: string): Promise<IndexHistory> {
  const { data, error, response } = await api.GET("/indices/{symbol}/history", {
    params: { path: { symbol }, query: { range: "1mo" } },
  });
  return unwrap(response, data, error, parseIndexHistory);
}

export async function getLatestResearchReports(): Promise<LatestResearchReports> {
  const { data, error, response } = await api.GET("/research-reports/latest", { params: { query: { limit: 20 } } });
  return unwrap(response, data, error, parseLatestResearchReports);
}

export async function getCapitalFlow(): Promise<CapitalFlow> {
  const { data, error, response } = await api.GET("/markets/capital-flow");
  return unwrap(response, data, error, parseCapitalFlow);
}

export async function getPositions(): Promise<Positions> {
  const { data, error, response } = await api.GET("/v1/positions");
  return unwrap(response, data, error, parsePositions);
}

export async function getMarketAnomalies(): Promise<MarketAnomalies> {
  const { data, error, response } = await api.GET("/markets/anomalies", { params: { query: { limit: 10 } } });
  return unwrap(response, data, error, parseMarketAnomalies);
}

export async function getGlobalIndices(): Promise<GlobalIndices> {
  const { data, error, response } = await api.GET("/indices", { params: { query: { scope: "all", group: "us" } } });
  return unwrap(response, data, error, parseGlobalIndices);
}

export async function getLiveMarkets(): Promise<LiveMarkets> {
  const { data, error, response } = await api.GET("/markets/live");
  return unwrap(response, data, error, parseLiveMarkets);
}
