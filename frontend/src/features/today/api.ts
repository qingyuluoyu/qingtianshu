import { api } from "../../api/client";
import {
  parseBreadth,
  parseDataHealth,
  parseGlobalIndices,
  parseIndexHistory,
  parseIndices,
  parseLiveMarkets,
  parseOverview,
  parseResearchActions,
  parseResearchChanges,
  parseSectors,
  parseWatchlistBrief,
  type Breadth,
  type DataHealth,
  type GlobalIndices,
  type IndexHistory,
  type Indices,
  type LiveMarkets,
  type Overview,
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

export async function getGlobalIndices(): Promise<GlobalIndices> {
  const { data, error, response } = await api.GET("/indices", { params: { query: { scope: "all", group: "us" } } });
  return unwrap(response, data, error, parseGlobalIndices);
}

export async function getLiveMarkets(): Promise<LiveMarkets> {
  const { data, error, response } = await api.GET("/markets/live");
  return unwrap(response, data, error, parseLiveMarkets);
}
