import { queryOptions } from "@tanstack/react-query";
import {
  getDeepStockSession,
  getObservationTasks,
  getPeerComparisons,
  getStockHistory,
  getStockPage,
  getStockPosition,
  getStockWorkspace,
  getTheses,
  StockResearchApiError,
  type HistoryRange,
} from "./api";

export const stockResearchQueryKeys = {
  page: (symbol: string, range: HistoryRange) => ["stock-page", symbol, range] as const,
  history: (symbol: string, range: HistoryRange) => ["stock-history", symbol, range] as const,
  peers: (symbol: string) => ["stock-peers", symbol] as const,
  workspace: (symbol: string) => ["stock-workspace", symbol] as const,
  theses: (symbol: string) => ["stock-theses", symbol] as const,
  observationTasks: (symbol: string) => ["stock-observation-tasks", symbol] as const,
  position: (symbol: string) => ["stock-position", symbol] as const,
  deepStock: (symbol: string) => ["stock-deep-research", symbol] as const,
};

function retry(failureCount: number, error: Error): boolean {
  if (error instanceof StockResearchApiError && (error.status === 401 || error.status === 422)) return false;
  return failureCount < 2;
}

const marketStaleTime = 60_000;
const personalStaleTime = 30_000;
const stableErrorPolicy = { retry, retryOnMount: false } as const;

export const stockResearchQueries = {
  page: (symbol: string, range: HistoryRange) => queryOptions({
    queryKey: stockResearchQueryKeys.page(symbol, range),
    queryFn: () => getStockPage(symbol),
    ...stableErrorPolicy,
    staleTime: marketStaleTime,
  }),
  history: (symbol: string, range: HistoryRange) => queryOptions({
    queryKey: stockResearchQueryKeys.history(symbol, range),
    queryFn: () => getStockHistory(symbol, range),
    ...stableErrorPolicy,
    staleTime: marketStaleTime,
  }),
  peers: (symbol: string) => queryOptions({
    queryKey: stockResearchQueryKeys.peers(symbol),
    queryFn: () => getPeerComparisons(symbol),
    ...stableErrorPolicy,
    staleTime: marketStaleTime,
  }),
  workspace: (symbol: string) => queryOptions({
    queryKey: stockResearchQueryKeys.workspace(symbol),
    queryFn: () => getStockWorkspace(symbol),
    ...stableErrorPolicy,
    staleTime: personalStaleTime,
  }),
  theses: (symbol: string) => queryOptions({
    queryKey: stockResearchQueryKeys.theses(symbol),
    queryFn: () => getTheses(symbol),
    ...stableErrorPolicy,
    staleTime: personalStaleTime,
  }),
  observationTasks: (symbol: string) => queryOptions({
    queryKey: stockResearchQueryKeys.observationTasks(symbol),
    queryFn: () => getObservationTasks(symbol),
    ...stableErrorPolicy,
    staleTime: personalStaleTime,
  }),
  position: (symbol: string) => queryOptions({
    queryKey: stockResearchQueryKeys.position(symbol),
    queryFn: () => getStockPosition(symbol),
    ...stableErrorPolicy,
    staleTime: personalStaleTime,
  }),
  deepStock: (symbol: string) => queryOptions({
    queryKey: stockResearchQueryKeys.deepStock(symbol),
    queryFn: () => getDeepStockSession(symbol),
    ...stableErrorPolicy,
    staleTime: personalStaleTime,
  }),
};
