import { queryOptions } from "@tanstack/react-query";
import { getIndicesByGroup, getSectors } from "./api";

export const marketDataQueryKeys = {
  indices: (group: string) => ["market-data", "indices", group] as const,
  sectors: (limit: number) => ["market-data", "sectors", limit] as const,
};

const marketStaleTime = 5 * 60_000;
// Retry once with exponential backoff for transient failures (network blips, 502/503).
// 404 / 400 / 422 are terminal — no retry. 500 / network errors get one retry.
const stableErrorPolicy = {
  retry: (_failureCount: number, _error: unknown) => _failureCount < 1,
  retryOnMount: false,
  refetchOnWindowFocus: false,
} as const;

export const marketDataQueries = {
  indices: (group: string) => queryOptions({ queryKey: marketDataQueryKeys.indices(group), queryFn: () => getIndicesByGroup(group), ...stableErrorPolicy, staleTime: marketStaleTime }),
  sectors: (limit: number) => queryOptions({ queryKey: marketDataQueryKeys.sectors(limit), queryFn: () => getSectors(limit), ...stableErrorPolicy, staleTime: marketStaleTime }),
};
