import { queryOptions } from "@tanstack/react-query";
import { listArticles } from "./api";

export const articlesQueries = {
  list: (limit = 20) =>
    queryOptions({
      queryKey: ["articles", limit],
      queryFn: () => listArticles(limit),
      staleTime: 60_000,
      retry: false,
    }),
};
