import { queryOptions } from "@tanstack/react-query";
import {
  getResearchActions,
  getResearchChanges,
  getResearchOutcomes,
  getResearchReport,
  getTradeReviewCenter,
  getWorkspaceTimeline,
  ResearchCenterApiError,
} from "./api";

/**
 * Query key 遵循合同 §2.3：`['research-center', selectedSymbol]`。
 * 页面级聚合（changes/outcomes/actions/trade-reviews）不带 symbol；
 * 选中股相关的 timeline 用 `['research-center', symbol]` 规范键，report 为其派生键。
 */
export const researchCenterQueryKeys = {
  changes: () => ["research-center", "changes"] as const,
  outcomes: () => ["research-center", "outcomes"] as const,
  actions: () => ["research-center", "actions"] as const,
  tradeReviews: () => ["research-center", "trade-reviews"] as const,
  timeline: (symbol: string) => ["research-center", symbol] as const,
  report: (symbol: string) => ["research-center", symbol, "report"] as const,
};

function retry(failureCount: number, error: Error): boolean {
  if (error instanceof ResearchCenterApiError && (error.status === 401 || error.status === 409 || error.status === 422)) return false;
  return failureCount < 2;
}

const stableErrorPolicy = { retry, retryOnMount: false } as const;

export const researchCenterQueries = {
  changes: () => queryOptions({
    queryKey: researchCenterQueryKeys.changes(),
    queryFn: () => getResearchChanges(),
    ...stableErrorPolicy,
    staleTime: 30_000,
  }),
  outcomes: () => queryOptions({
    queryKey: researchCenterQueryKeys.outcomes(),
    queryFn: () => getResearchOutcomes(),
    ...stableErrorPolicy,
    staleTime: 30_000,
  }),
  actions: () => queryOptions({
    queryKey: researchCenterQueryKeys.actions(),
    queryFn: () => getResearchActions(),
    ...stableErrorPolicy,
    staleTime: 30_000,
  }),
  tradeReviews: () => queryOptions({
    queryKey: researchCenterQueryKeys.tradeReviews(),
    queryFn: () => getTradeReviewCenter(),
    ...stableErrorPolicy,
    staleTime: 30_000,
  }),
  timeline: (symbol: string) => queryOptions({
    queryKey: researchCenterQueryKeys.timeline(symbol),
    queryFn: () => getWorkspaceTimeline(symbol),
    ...stableErrorPolicy,
    staleTime: 30_000,
  }),
  report: (symbol: string) => queryOptions({
    queryKey: researchCenterQueryKeys.report(symbol),
    queryFn: () => getResearchReport(symbol),
    ...stableErrorPolicy,
    staleTime: 60_000,
  }),
};
