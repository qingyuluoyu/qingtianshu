import { queryOptions } from "@tanstack/react-query";
import { searchFunds, listFunds } from "./api";

export const fundsQueries = {
  search: (q: string, limit = 20) =>
    queryOptions({
      queryKey: ["funds", "search", q, limit],
      queryFn: () => searchFunds(q, limit),
      staleTime: 60_000,
      retry: false,
    }),
  list: (limit = 50) =>
    queryOptions({
      queryKey: ["funds", "list", limit],
      queryFn: () => listFunds(limit),
      staleTime: 5 * 60_000,
      retry: false,
    }),
};
