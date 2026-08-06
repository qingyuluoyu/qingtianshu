import { queryOptions } from "@tanstack/react-query";
import {
  getStockHistory,
  getStockWorkspace,
  getStockWorkspaces,
  WatchlistApiError,
} from "./api";

/**
 * 筛选/排序目前在浏览器侧作用于同一份聚合列表（后端暂无筛选参数）；
 * query key 仍按合同 §2.3 携带 filters，后续服务端支持筛选时无需改缓存结构。
 */
export const watchlistQueryKeys = {
  assets: () => ["stock-workspaces"] as const,
  workspace: (symbol: string) => ["stock-workspace", symbol] as const,
  history: (symbol: string) => ["stock-history", symbol, "3mo"] as const,
};

function retry(failureCount: number, error: Error): boolean {
  if (error instanceof WatchlistApiError && (error.status === 401 || error.status === 409 || error.status === 422)) return false;
  return failureCount < 2;
}

const stableErrorPolicy = { retry, retryOnMount: false } as const;

export const watchlistQueries = {
  assets: () => queryOptions({
    queryKey: watchlistQueryKeys.assets(),
    queryFn: () => getStockWorkspaces(),
    // 服务端暂无筛选参数，filters 变化只换缓存键；保留上一份数据避免整页闪骨架，
    // 重新拉取的仍是同一个聚合端点（不是逐股请求）。
    placeholderData: (previous) => previous,
    ...stableErrorPolicy,
    staleTime: 30_000,
  }),
  workspace: (symbol: string) => queryOptions({
    queryKey: watchlistQueryKeys.workspace(symbol),
    queryFn: () => getStockWorkspace(symbol),
    ...stableErrorPolicy,
    staleTime: 30_000,
  }),
  history: (symbol: string) => queryOptions({
    queryKey: watchlistQueryKeys.history(symbol),
    queryFn: () => getStockHistory(symbol),
    ...stableErrorPolicy,
    staleTime: 60_000,
  }),
};
