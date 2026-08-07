import { queryOptions } from "@tanstack/react-query";
import {
  AdvisorApiError,
  getAiWritebacks,
  getConversation,
  getConversations,
} from "./api";

/** 合同 §2.3：会话详情用 ['conversation', id]；列表与候选写回各自独立可失效。 */
export const advisorQueryKeys = {
  conversations: () => ["conversations"] as const,
  conversation: (id: string) => ["conversation", id] as const,
  writebacks: () => ["ai-writebacks"] as const,
};

function retry(failureCount: number, error: Error): boolean {
  if (error instanceof AdvisorApiError && [401, 404, 409, 422].includes(error.status)) return false;
  return failureCount < 2;
}

const stableErrorPolicy = { retry, retryOnMount: false } as const;

export const advisorQueries = {
  conversations: () => queryOptions({
    queryKey: advisorQueryKeys.conversations(),
    queryFn: () => getConversations(),
    ...stableErrorPolicy,
    staleTime: 30_000,
  }),
  conversation: (id: string) => queryOptions({
    queryKey: advisorQueryKeys.conversation(id),
    queryFn: () => getConversation(id),
    ...stableErrorPolicy,
    staleTime: 15_000,
  }),
  writebacks: () => queryOptions({
    queryKey: advisorQueryKeys.writebacks(),
    queryFn: () => getAiWritebacks(),
    ...stableErrorPolicy,
    staleTime: 15_000,
  }),
};
