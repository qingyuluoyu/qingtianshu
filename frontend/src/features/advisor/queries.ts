import { queryOptions } from "@tanstack/react-query";
import {
  AdvisorApiError,
  getAdvisorConversation,
  getAdvisorRun,
  listAdvisorConversations,
  listAdvisorWritebacks,
} from "./api";

export const advisorQueryKeys = {
  all: ["advisor"] as const,
  conversations: () => ["advisor", "conversations"] as const,
  conversation: (id: string) => ["advisor", "conversation", id] as const,
  run: (id: string) => ["advisor", "run", id] as const,
  writebacks: () => ["advisor", "writebacks"] as const,
};

function retry(failureCount: number, error: Error): boolean {
  if (error instanceof AdvisorApiError && [401, 403, 404, 409, 422].includes(error.status)) return false;
  return failureCount < 2;
}

const stableErrorPolicy = { retry, retryOnMount: false } as const;

export const advisorQueries = {
  conversations: () => queryOptions({
    queryKey: advisorQueryKeys.conversations(),
    queryFn: listAdvisorConversations,
    ...stableErrorPolicy,
    staleTime: 15_000,
  }),
  conversation: (id: string) => queryOptions({
    queryKey: advisorQueryKeys.conversation(id),
    queryFn: () => getAdvisorConversation(id),
    ...stableErrorPolicy,
    staleTime: 5_000,
  }),
  run: (id: string) => queryOptions({
    queryKey: advisorQueryKeys.run(id),
    queryFn: () => getAdvisorRun(id),
    ...stableErrorPolicy,
    staleTime: 5_000,
  }),
  writebacks: () => queryOptions({
    queryKey: advisorQueryKeys.writebacks(),
    queryFn: listAdvisorWritebacks,
    ...stableErrorPolicy,
    staleTime: 5_000,
  }),
};
