import { queryOptions } from "@tanstack/react-query";
import {
  getBreadth,
  getCapitalFlow,
  getDataHealth,
  getGlobalIndices,
  getIndexHistory,
  getIndices,
  getLatestResearchReports,
  getLiveMarkets,
  getMarketAnomalies,
  getPositions,
  getResearchActions,
  getResearchChanges,
  getSectors,
  getTodayOverview,
  getWatchlistBrief,
  TodayApiError,
} from "./api";

export const todayQueryKeys = {
  overview: ["today", "overview"] as const,
  indices: ["today", "indices", "all", "china"] as const,
  breadth: ["today", "breadth"] as const,
  sectors: ["today", "sectors", 10] as const,
  watchlistBrief: ["today", "watchlist-brief"] as const,
  researchActions: ["today", "research-actions"] as const,
  researchChanges: ["today", "research-changes", 20] as const,
  dataHealth: ["today", "data-health"] as const,
  indexHistory: (symbol: string) => ["today", "index-history", symbol] as const,
  researchReports: ["today", "research-reports", "latest", 20] as const,
  capitalFlow: ["today", "capital-flow"] as const,
  positions: ["today", "positions"] as const,
  globalIndices: ["today", "indices", "all", "us"] as const,
  liveMarkets: ["today", "markets-live"] as const,
  anomalies: ["today", "market-anomalies", 10] as const,
};

function retry(failureCount: number, error: Error): boolean {
  if (error instanceof TodayApiError && (error.status === 401 || error.status === 422)) return false;
  return failureCount < 2;
}

const marketStaleTime = 60_000;
const personalStaleTime = 30_000;
const stableErrorPolicy = { retry, retryOnMount: false } as const;

export const todayQueries = {
  overview: () => queryOptions({ queryKey: todayQueryKeys.overview, queryFn: getTodayOverview, ...stableErrorPolicy, staleTime: personalStaleTime }),
  indices: () => queryOptions({ queryKey: todayQueryKeys.indices, queryFn: getIndices, ...stableErrorPolicy, staleTime: marketStaleTime }),
  breadth: () => queryOptions({ queryKey: todayQueryKeys.breadth, queryFn: getBreadth, ...stableErrorPolicy, staleTime: marketStaleTime }),
  sectors: () => queryOptions({ queryKey: todayQueryKeys.sectors, queryFn: getSectors, ...stableErrorPolicy, staleTime: marketStaleTime }),
  watchlistBrief: () => queryOptions({ queryKey: todayQueryKeys.watchlistBrief, queryFn: getWatchlistBrief, ...stableErrorPolicy, staleTime: personalStaleTime }),
  researchActions: () => queryOptions({ queryKey: todayQueryKeys.researchActions, queryFn: getResearchActions, ...stableErrorPolicy, staleTime: personalStaleTime }),
  researchChanges: () => queryOptions({ queryKey: todayQueryKeys.researchChanges, queryFn: getResearchChanges, ...stableErrorPolicy, staleTime: personalStaleTime }),
  dataHealth: () => queryOptions({ queryKey: todayQueryKeys.dataHealth, queryFn: getDataHealth, ...stableErrorPolicy, staleTime: marketStaleTime }),
  indexHistory: (symbol: string) => queryOptions({ queryKey: todayQueryKeys.indexHistory(symbol), queryFn: () => getIndexHistory(symbol), ...stableErrorPolicy, staleTime: marketStaleTime }),
  researchReports: () => queryOptions({ queryKey: todayQueryKeys.researchReports, queryFn: getLatestResearchReports, ...stableErrorPolicy, staleTime: marketStaleTime }),
  capitalFlow: () => queryOptions({ queryKey: todayQueryKeys.capitalFlow, queryFn: getCapitalFlow, ...stableErrorPolicy, staleTime: marketStaleTime }),
  positions: () => queryOptions({ queryKey: todayQueryKeys.positions, queryFn: getPositions, ...stableErrorPolicy, staleTime: personalStaleTime }),
  globalIndices: () => queryOptions({ queryKey: todayQueryKeys.globalIndices, queryFn: getGlobalIndices, ...stableErrorPolicy, staleTime: marketStaleTime }),
  liveMarkets: () => queryOptions({ queryKey: todayQueryKeys.liveMarkets, queryFn: getLiveMarkets, ...stableErrorPolicy, staleTime: marketStaleTime }),
  anomalies: () => queryOptions({ queryKey: todayQueryKeys.anomalies, queryFn: getMarketAnomalies, ...stableErrorPolicy, staleTime: marketStaleTime }),
};
