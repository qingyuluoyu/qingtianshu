import { queryOptions } from "@tanstack/react-query";
import {
  getLiZongStrategy,
  getStrategyCandidates,
  getObservationPool,
  getStrategyHistory,
  getBacktestResult,
  getStrategyTriggers,
} from "./api";

export const strategiesQueries = {
  strategy: () =>
    queryOptions({
      queryKey: ["strategies", "li-zong"],
      queryFn: getLiZongStrategy,
      staleTime: 30_000,
      retry: false,
    }),
  candidates: (limit = 30) =>
    queryOptions({
      queryKey: ["strategies", "li-zong", "candidates", limit],
      queryFn: () => getStrategyCandidates(limit),
      staleTime: 30_000,
      retry: false,
    }),
  observationPool: (limit = 50) =>
    queryOptions({
      queryKey: ["strategies", "li-zong", "observation-pool", limit],
      queryFn: () => getObservationPool(limit),
      staleTime: 30_000,
      retry: false,
    }),
  history: (limit = 20) =>
    queryOptions({
      queryKey: ["strategies", "li-zong", "history", limit],
      queryFn: () => getStrategyHistory(limit),
      staleTime: 30_000,
      retry: false,
    }),
  backtest: (period: "3m" | "1y" | "3y" = "1y") =>
    queryOptions({
      queryKey: ["strategies", "li-zong", "backtest", period],
      queryFn: () => getBacktestResult(period),
      staleTime: 5 * 60_000,
      retry: false,
    }),
  triggers: (limit = 20) =>
    queryOptions({
      queryKey: ["strategies", "li-zong", "triggers", limit],
      queryFn: () => getStrategyTriggers(limit),
      staleTime: 30_000,
      retry: false,
    }),
};
