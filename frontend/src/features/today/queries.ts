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
// A server contract failure is informative; retrying a 404/500 only adds load and noise.
const stableErrorPolicy = { retry: false, retryOnMount: false, refetchOnWindowFocus: false } as const;

export const todayQueries = {
  overview: () => queryOptions({ queryKey: todayQueryKeys.overview, queryFn: ({ signal }) => getTodayOverview(signal), ...stableErrorPolicy, staleTime: personalStaleTime }),
  indices: () => queryOptions({ queryKey: todayQueryKeys.indices, queryFn: ({ signal }) => getIndices(signal), ...stableErrorPolicy, staleTime: marketStaleTime }),
  breadth: () => queryOptions({ queryKey: todayQueryKeys.breadth, queryFn: ({ signal }) => getBreadth(signal), ...stableErrorPolicy, staleTime: marketStaleTime }),
  sectors: () => queryOptions({ queryKey: todayQueryKeys.sectors, queryFn: ({ signal }) => getSectors(signal), ...stableErrorPolicy, staleTime: marketStaleTime }),
  watchlistBrief: () => queryOptions({ queryKey: todayQueryKeys.watchlistBrief, queryFn: ({ signal }) => getWatchlistBrief(signal), ...stableErrorPolicy, staleTime: personalStaleTime }),
  researchActions: () => queryOptions({ queryKey: todayQueryKeys.researchActions, queryFn: ({ signal }) => getResearchActions(signal), ...stableErrorPolicy, staleTime: personalStaleTime }),
  researchChanges: () => queryOptions({ queryKey: todayQueryKeys.researchChanges, queryFn: ({ signal }) => getResearchChanges(signal), ...stableErrorPolicy, staleTime: personalStaleTime }),
  dataHealth: () => queryOptions({ queryKey: todayQueryKeys.dataHealth, queryFn: ({ signal }) => getDataHealth(signal), ...stableErrorPolicy, staleTime: marketStaleTime }),
  indexHistory: (symbol: string) => queryOptions({ queryKey: todayQueryKeys.indexHistory(symbol), queryFn: ({ signal }) => getIndexHistory(symbol, signal), ...stableErrorPolicy, staleTime: historyStaleTime }),
  researchReports: () => queryOptions({ queryKey: todayQueryKeys.researchReports, queryFn: ({ signal }) => getLatestResearchReports(signal), ...stableErrorPolicy, staleTime: marketStaleTime }),
  capitalFlow: () => queryOptions({ queryKey: todayQueryKeys.capitalFlow, queryFn: ({ signal }) => getCapitalFlow(signal), ...stableErrorPolicy, staleTime: marketStaleTime }),
  positions: () => queryOptions({ queryKey: todayQueryKeys.positions, queryFn: ({ signal }) => getPositions(signal), ...stableErrorPolicy, staleTime: personalStaleTime }),
  anomalies: () => queryOptions({ queryKey: todayQueryKeys.anomalies, queryFn: ({ signal }) => getMarketAnomalies(signal), ...stableErrorPolicy, staleTime: marketStaleTime }),
  globalIndices: () => queryOptions({ queryKey: todayQueryKeys.globalIndices, queryFn: ({ signal }) => getGlobalIndices(signal), ...stableErrorPolicy, staleTime: marketStaleTime }),
  liveMarkets: () => queryOptions({ queryKey: todayQueryKeys.liveMarkets, queryFn: ({ signal }) => getLiveMarkets(signal), ...stableErrorPolicy, staleTime: marketStaleTime }),
};
