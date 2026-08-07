import { queryOptions } from "@tanstack/react-query";
import {
  getLiZongBacktest,
  getLiZongCandidates,
  getLiZongRunLatest,
  getScreenerProfiles,
  runStockScreen,
  ScreeningApiError,
  type BacktestPeriod,
  type LiZongStatusFilter,
  type ScreenParams,
} from "./api";
import { ApiTransportError } from "../../api/client";

/**
 * Query key 遵循合同 §2.3：`['screener', profile, params, page]`。
 * 服务端暂无分页参数，page 槽位保留为 null，后端支持后无需改缓存结构。
 */
export const screeningQueryKeys = {
  profiles: () => ["screener-profiles"] as const,
  screen: (params: ScreenParams) => ["screener", params.profile, { market: params.market, maxResults: params.maxResults, filters: params.filters }, null] as const,
  liZongCandidates: (status: LiZongStatusFilter) => ["li-zong-candidates", status ?? "all"] as const,
  liZongRunLatest: () => ["li-zong-run-latest"] as const,
  liZongBacktest: (period: BacktestPeriod) => ["li-zong-backtest", period] as const,
};

function retry(failureCount: number, error: Error): boolean {
  if (error instanceof ApiTransportError) return false;
  if (error instanceof ScreeningApiError && (error.status === 401 || error.status === 422 || error.status === 503)) return false;
  return failureCount < 2;
}

const stableErrorPolicy = { retry, retryOnMount: false } as const;

export const screeningQueries = {
  profiles: () => queryOptions({
    queryKey: screeningQueryKeys.profiles(),
    queryFn: () => getScreenerProfiles(),
    ...stableErrorPolicy,
    staleTime: 300_000,
  }),
  screen: (params: ScreenParams) => queryOptions({
    queryKey: screeningQueryKeys.screen(params),
    queryFn: ({ signal }) => runStockScreen(params, signal),
    // 切换筛选条件时保留上一份结果，避免整表闪骨架。
    placeholderData: (previous) => previous,
    ...stableErrorPolicy,
    staleTime: 60_000,
  }),
  liZongCandidates: (status: LiZongStatusFilter) => queryOptions({
    queryKey: screeningQueryKeys.liZongCandidates(status),
    queryFn: () => getLiZongCandidates(status),
    placeholderData: (previous) => previous,
    ...stableErrorPolicy,
    staleTime: 60_000,
  }),
  liZongRunLatest: () => queryOptions({
    queryKey: screeningQueryKeys.liZongRunLatest(),
    queryFn: () => getLiZongRunLatest(),
    ...stableErrorPolicy,
    staleTime: 60_000,
  }),
  liZongBacktest: (period: BacktestPeriod) => queryOptions({
    queryKey: screeningQueryKeys.liZongBacktest(period),
    queryFn: () => getLiZongBacktest(period),
    placeholderData: (previous) => previous,
    ...stableErrorPolicy,
    staleTime: 120_000,
  }),
};
