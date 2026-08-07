import { queryOptions } from "@tanstack/react-query";
import { listKnowledgeDocuments } from "./api";

export const knowledgeQueries = {
  list: () =>
    queryOptions({
      queryKey: ["knowledge"],
      queryFn: listKnowledgeDocuments,
      staleTime: 60_000,
      retry: false,
    }),
};
