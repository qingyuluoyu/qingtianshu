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
  anomalies: ["today", "market-anomalies", 10] as const,
  globalIndices: ["today", "indices", "all", "us"] as const,
  liveMarkets: ["today", "markets-live"] as const,
};

const marketStaleTime = 5 * 60_000;
const historyStaleTime = 30 * 60_000;
const personalStaleTime = 30_000;
// Retry once with exponential backoff for transient failures (network blips, 502/503).
// 404 / 400 / 422 are terminal — no retry. 500 / network errors get one retry.
const stableErrorPolicy = {
  retry: (_failureCount: number, _error: unknown) => _failureCount < 1,
  retryOnMount: false,
  refetchOnWindowFocus: false,
} as const;

export const todayQueries = {
  overview: () => queryOptions({ queryKey: todayQueryKeys.overview, queryFn: getTodayOverview, ...stableErrorPolicy, staleTime: personalStaleTime }),
  indices: () => queryOptions({ queryKey: todayQueryKeys.indices, queryFn: getIndices, ...stableErrorPolicy, staleTime: marketStaleTime }),
  breadth: () => queryOptions({ queryKey: todayQueryKeys.breadth, queryFn: getBreadth, ...stableErrorPolicy, staleTime: marketStaleTime }),
  sectors: () => queryOptions({ queryKey: todayQueryKeys.sectors, queryFn: getSectors, ...stableErrorPolicy, staleTime: marketStaleTime }),
  watchlistBrief: () => queryOptions({ queryKey: todayQueryKeys.watchlistBrief, queryFn: getWatchlistBrief, ...stableErrorPolicy, staleTime: personalStaleTime }),
  researchActions: () => queryOptions({ queryKey: todayQueryKeys.researchActions, queryFn: getResearchActions, ...stableErrorPolicy, staleTime: personalStaleTime }),
  researchChanges: () => queryOptions({ queryKey: todayQueryKeys.researchChanges, queryFn: getResearchChanges, ...stableErrorPolicy, staleTime: personalStaleTime }),
  dataHealth: () => queryOptions({ queryKey: todayQueryKeys.dataHealth, queryFn: getDataHealth, ...stableErrorPolicy, staleTime: marketStaleTime }),
  indexHistory: (symbol: string) => queryOptions({ queryKey: todayQueryKeys.indexHistory(symbol), queryFn: () => getIndexHistory(symbol), ...stableErrorPolicy, staleTime: historyStaleTime }),
  researchReports: () => queryOptions({ queryKey: todayQueryKeys.researchReports, queryFn: getLatestResearchReports, ...stableErrorPolicy, staleTime: marketStaleTime }),
  capitalFlow: () => queryOptions({ queryKey: todayQueryKeys.capitalFlow, queryFn: getCapitalFlow, ...stableErrorPolicy, staleTime: marketStaleTime }),
  positions: () => queryOptions({ queryKey: todayQueryKeys.positions, queryFn: getPositions, ...stableErrorPolicy, staleTime: personalStaleTime }),
  anomalies: () => queryOptions({ queryKey: todayQueryKeys.anomalies, queryFn: getMarketAnomalies, ...stableErrorPolicy, staleTime: marketStaleTime }),
  globalIndices: () => queryOptions({ queryKey: todayQueryKeys.globalIndices, queryFn: getGlobalIndices, ...stableErrorPolicy, staleTime: marketStaleTime }),
  liveMarkets: () => queryOptions({ queryKey: todayQueryKeys.liveMarkets, queryFn: getLiveMarkets, ...stableErrorPolicy, staleTime: marketStaleTime }),
};
