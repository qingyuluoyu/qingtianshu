import { queryOptions } from "@tanstack/react-query";
import {
  getEvidenceTasks,
  getResearchActions,
  getResearchChanges,
  getResearchOutcomes,
  getResearchPriority,
  getRunReviews,
  ResearchCenterApiError,
} from "./api";

export const researchCenterQueryKeys = {
  priority: () => ["research-center", "priority"] as const,
  changes: () => ["research-center", "changes", 30] as const,
  actions: () => ["research-center", "actions"] as const,
  evidenceTasks: () => ["research-center", "evidence-tasks", 50] as const,
  outcomes: () => ["research-center", "outcomes", 120] as const,
  runReviews: () => ["research-center", "run-reviews", 30, 30] as const,
};

function retry(failureCount: number, error: Error): boolean {
  if (error instanceof ResearchCenterApiError && [401, 403, 404, 422].includes(error.status)) return false;
  return failureCount < 2;
}

const stablePolicy = { retry, retryOnMount: false, staleTime: 30_000 } as const;

export const researchCenterQueries = {
  priority: () => queryOptions({ queryKey: researchCenterQueryKeys.priority(), queryFn: getResearchPriority, ...stablePolicy }),
  changes: () => queryOptions({ queryKey: researchCenterQueryKeys.changes(), queryFn: getResearchChanges, ...stablePolicy }),
  actions: () => queryOptions({ queryKey: researchCenterQueryKeys.actions(), queryFn: getResearchActions, ...stablePolicy }),
  evidenceTasks: () => queryOptions({ queryKey: researchCenterQueryKeys.evidenceTasks(), queryFn: getEvidenceTasks, ...stablePolicy }),
  outcomes: () => queryOptions({ queryKey: researchCenterQueryKeys.outcomes(), queryFn: getResearchOutcomes, ...stablePolicy }),
  runReviews: () => queryOptions({ queryKey: researchCenterQueryKeys.runReviews(), queryFn: getRunReviews, ...stablePolicy }),
};
