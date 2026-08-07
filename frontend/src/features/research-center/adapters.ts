export type JsonRecord = Record<string, unknown>;

export class ResearchCenterContractError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ResearchCenterContractError";
  }
}

function record(value: unknown, field = "response"): JsonRecord {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new ResearchCenterContractError(`${field} 不是对象`);
  }
  return value as JsonRecord;
}

function optionalRecord(value: unknown): JsonRecord | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as JsonRecord
    : null;
}

function optionalString(value: unknown): string | null {
  return typeof value === "string" && value.trim().length > 0 ? value : null;
}

function requiredString(value: unknown, field: string): string {
  const parsed = optionalString(value);
  if (!parsed) throw new ResearchCenterContractError(`${field} 缺失`);
  return parsed;
}

function optionalNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function optionalBoolean(value: unknown): boolean | null {
  return typeof value === "boolean" ? value : null;
}

function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function strings(value: unknown): string[] {
  return list(value).filter((item): item is string => typeof item === "string" && item.length > 0);
}

export type ResearchPriorityItem = {
  symbol: string;
  name: string | null;
  thesis: string | null;
  status: string | null;
  priorityScore: number | null;
  priorityLabel: string | null;
  reasons: string[];
  nextReviewFocus: string | null;
  nextReviewChecks: string[];
  dataAsOf: string | null;
};

export type ResearchPriorityPacket = {
  generatedAt: string | null;
  items: ResearchPriorityItem[];
  coverage: { requested: number | null; available: number | null; missingBaseline: number | null };
  sorting: string | null;
  boundary: string | null;
};

export function parseResearchPriority(value: unknown): ResearchPriorityPacket {
  const root = record(value);
  if (root.type !== "research_priority") throw new ResearchCenterContractError("priority.type 不受支持");
  const coverage = optionalRecord(root.coverage);
  return {
    generatedAt: optionalString(root.generated_at),
    items: list(root.items).flatMap((raw) => {
      const item = optionalRecord(raw);
      const symbol = optionalString(item?.symbol);
      if (!item || !symbol) return [];
      const nextReview = optionalRecord(item.next_review);
      return [{
        symbol,
        name: optionalString(item.name),
        thesis: optionalString(item.thesis),
        status: optionalString(item.status),
        priorityScore: optionalNumber(item.priority_score),
        priorityLabel: optionalString(item.priority_label),
        reasons: strings(item.reasons),
        nextReviewFocus: optionalString(nextReview?.focus),
        nextReviewChecks: strings(nextReview?.checks),
        dataAsOf: optionalString(item.data_as_of),
      }];
    }),
    coverage: {
      requested: optionalNumber(coverage?.requested),
      available: optionalNumber(coverage?.available),
      missingBaseline: optionalNumber(coverage?.missing_baseline),
    },
    sorting: optionalString(root.sorting),
    boundary: optionalString(root.boundary),
  };
}

export type ResearchChangeEvent = {
  id: string;
  symbol: string;
  eventType: string | null;
  severity: string | null;
  summary: string;
  createdAt: string | null;
  dataAsOf: string | null;
  nextReviewFocus: string | null;
};

export type ResearchChangesPacket = {
  generatedAt: string | null;
  events: ResearchChangeEvent[];
  coverage: { requested: number | null; withReport: number | null; withChangeArchive: number | null };
  method: string | null;
  boundary: string | null;
};

export function parseResearchChanges(value: unknown): ResearchChangesPacket {
  const root = record(value);
  if (root.type !== "research_tracking") throw new ResearchCenterContractError("changes.type 不受支持");
  const coverage = optionalRecord(root.coverage);
  return {
    generatedAt: optionalString(root.generated_at),
    events: list(root.events).flatMap((raw) => {
      const item = optionalRecord(raw);
      const id = optionalString(item?.id);
      const symbol = optionalString(item?.symbol);
      const summary = optionalString(item?.summary);
      if (!item || !id || !symbol || !summary) return [];
      const nextReview = optionalRecord(item.next_review);
      return [{
        id,
        symbol,
        eventType: optionalString(item.event_type),
        severity: optionalString(item.severity),
        summary,
        createdAt: optionalString(item.created_at),
        dataAsOf: optionalString(item.data_as_of),
        nextReviewFocus: optionalString(nextReview?.focus),
      }];
    }),
    coverage: {
      requested: optionalNumber(coverage?.requested),
      withReport: optionalNumber(coverage?.with_report),
      withChangeArchive: optionalNumber(coverage?.with_change_archive),
    },
    method: optionalString(root.method),
    boundary: optionalString(root.boundary),
  };
}

export type ResearchAction = {
  id: string;
  title: string;
  status: string;
  severity: string | null;
  condition: string | null;
  currentEvidence: string | null;
  nextStep: string | null;
  checks: string[];
};

export type ResearchActionGroup = {
  symbol: string;
  name: string | null;
  thesis: string | null;
  researchStatus: string | null;
  researchStatusLabel: string | null;
  priorityScore: number | null;
  dataAsOf: string | null;
  headline: string | null;
  actions: ResearchAction[];
};

export type ResearchActionsPacket = {
  generatedAt: string | null;
  items: ResearchActionGroup[];
  summary: { symbols: number | null; triggered: number | null; pendingData: number | null; watching: number | null; priorityResearch: number | null };
  boundary: string | null;
};

export function parseResearchActions(value: unknown): ResearchActionsPacket {
  const root = record(value);
  if (root.type !== "research_actions") throw new ResearchCenterContractError("actions.type 不受支持");
  const summary = optionalRecord(root.summary);
  return {
    generatedAt: optionalString(root.generated_at),
    items: list(root.items).flatMap((raw) => {
      const item = optionalRecord(raw);
      const symbol = optionalString(item?.symbol);
      if (!item || !symbol) return [];
      return [{
        symbol,
        name: optionalString(item.name),
        thesis: optionalString(item.thesis),
        researchStatus: optionalString(item.research_status),
        researchStatusLabel: optionalString(item.research_status_label),
        priorityScore: optionalNumber(item.priority_score),
        dataAsOf: optionalString(item.data_as_of),
        headline: optionalString(item.headline),
        actions: list(item.actions).flatMap((actionRaw) => {
          const action = optionalRecord(actionRaw);
          const id = optionalString(action?.id);
          const title = optionalString(action?.title);
          const status = optionalString(action?.status);
          if (!action || !id || !title || !status) return [];
          return [{
            id,
            title,
            status,
            severity: optionalString(action.severity),
            condition: optionalString(action.condition),
            currentEvidence: optionalString(action.current_evidence),
            nextStep: optionalString(action.next_step),
            checks: strings(action.checks),
          }];
        }),
      }];
    }),
    summary: {
      symbols: optionalNumber(summary?.symbols),
      triggered: optionalNumber(summary?.triggered),
      pendingData: optionalNumber(summary?.pending_data),
      watching: optionalNumber(summary?.watching),
      priorityResearch: optionalNumber(summary?.priority_research),
    },
    boundary: optionalString(root.boundary),
  };
}

export type EvidenceTask = {
  id: string;
  conversationId: string | null;
  runId: string | null;
  symbol: string | null;
  title: string;
  description: string | null;
  status: string;
  statusLabel: string | null;
  priority: number | null;
  resolutionNote: string | null;
  updatedAt: string | null;
  resolvedAt: string | null;
};

export type EvidenceTasksPacket = {
  generatedAt: string | null;
  summary: Record<string, number | null>;
  items: EvidenceTask[];
  boundary: string | null;
};

export function parseEvidenceTasks(value: unknown): EvidenceTasksPacket {
  const root = record(value);
  const summary = optionalRecord(root.summary);
  const parsedSummary: Record<string, number | null> = {};
  if (summary) Object.entries(summary).forEach(([key, item]) => { parsedSummary[key] = optionalNumber(item); });
  return {
    generatedAt: optionalString(root.generated_at),
    summary: parsedSummary,
    items: list(root.items).flatMap((raw) => {
      const item = optionalRecord(raw);
      const id = optionalString(item?.id);
      const title = optionalString(item?.title);
      const status = optionalString(item?.status);
      if (!item || !id || !title || !status) return [];
      return [{
        id,
        conversationId: optionalString(item.conversation_id),
        runId: optionalString(item.run_id),
        symbol: optionalString(item.symbol),
        title,
        description: optionalString(item.description),
        status,
        statusLabel: optionalString(item.status_label),
        priority: optionalNumber(item.priority),
        resolutionNote: optionalString(item.resolution_note),
        updatedAt: optionalString(item.updated_at),
        resolvedAt: optionalString(item.resolved_at),
      }];
    }),
    boundary: optionalString(root.boundary),
  };
}

export type ResearchOutcome = {
  id: string;
  horizonSessions: number | null;
  resultStatus: string | null;
  observedSessions: number | null;
  closeReturnPct: number | null;
  partialReturnPct: number | null;
  reviewConclusion: string | null;
  targetTimestamp: string | null;
  progressTimestamp: string | null;
};

export type ResearchOutcomeGroup = {
  symbol: string;
  name: string | null;
  thesis: string | null;
  latestAnchorAt: string | null;
  latestAvailable: ResearchOutcome[];
  latestProgress: ResearchOutcome | null;
  coverage: { anchors: number | null; available: number | null; pending: number | null };
};

export type ResearchOutcomesPacket = {
  generatedAt: string | null;
  items: ResearchOutcomeGroup[];
  coverage: { requestedSymbols: number | null; withArchives: number | null; availableOutcomes: number | null; pendingOutcomes: number | null };
  method: string | null;
  boundary: string | null;
};

function parseOutcome(value: unknown): ResearchOutcome | null {
  const item = optionalRecord(value);
  const id = optionalString(item?.id);
  if (!item || !id) return null;
  return {
    id,
    horizonSessions: optionalNumber(item.horizon_sessions),
    resultStatus: optionalString(item.result_status),
    observedSessions: optionalNumber(item.observed_sessions),
    closeReturnPct: optionalNumber(item.close_return_pct),
    partialReturnPct: optionalNumber(item.partial_return_pct),
    reviewConclusion: optionalString(item.review_conclusion),
    targetTimestamp: optionalString(item.target_timestamp),
    progressTimestamp: optionalString(item.progress_timestamp),
  };
}

export function parseResearchOutcomes(value: unknown): ResearchOutcomesPacket {
  const root = record(value);
  if (root.type !== "research_outcome") throw new ResearchCenterContractError("outcomes.type 不受支持");
  const coverage = optionalRecord(root.coverage);
  return {
    generatedAt: optionalString(root.generated_at),
    items: list(root.items).flatMap((raw) => {
      const item = optionalRecord(raw);
      const symbol = optionalString(item?.symbol);
      if (!item || !symbol) return [];
      const progress = parseOutcome(item.latest_progress);
      const itemCoverage = optionalRecord(item.coverage);
      return [{
        symbol,
        name: optionalString(item.name),
        thesis: optionalString(item.thesis),
        latestAnchorAt: optionalString(item.latest_anchor_at),
        latestAvailable: list(item.latest_available).flatMap((outcome) => {
          const parsed = parseOutcome(outcome);
          return parsed ? [parsed] : [];
        }),
        latestProgress: progress,
        coverage: {
          anchors: optionalNumber(itemCoverage?.anchors),
          available: optionalNumber(itemCoverage?.available),
          pending: optionalNumber(itemCoverage?.pending),
        },
      }];
    }),
    coverage: {
      requestedSymbols: optionalNumber(coverage?.requested_symbols),
      withArchives: optionalNumber(coverage?.with_archives),
      availableOutcomes: optionalNumber(coverage?.available_outcomes),
      pendingOutcomes: optionalNumber(coverage?.pending_outcomes),
    },
    method: optionalString(root.method),
    boundary: optionalString(root.boundary),
  };
}

export type RunReview = {
  id: string;
  conversationId: string | null;
  conversationTitle: string | null;
  question: string;
  intentLabel: string | null;
  status: string;
  statusLabel: string | null;
  symbol: string | null;
  displayName: string | null;
  createdAt: string | null;
  durationSeconds: number | null;
  dataAsOf: string | null;
  guardLabel: string | null;
  repaired: boolean | null;
  readyModules: number | null;
  totalModules: number | null;
  knowledgeDocuments: number | null;
  answerExcerpt: string | null;
};

export type RunReviewsPacket = {
  items: RunReview[];
  summary: { total: number | null; filtered: number | null; repaired: number | null; days: number | null };
};

export function parseRunReviews(value: unknown): RunReviewsPacket {
  const root = record(value);
  const summary = optionalRecord(root.summary);
  return {
    items: list(root.items).flatMap((raw) => {
      const item = optionalRecord(raw);
      const id = optionalString(item?.id);
      const question = optionalString(item?.question);
      const status = optionalString(item?.status);
      if (!item || !id || !question || !status) return [];
      const guard = optionalRecord(item.guard);
      const evidence = optionalRecord(item.evidence);
      return [{
        id,
        conversationId: optionalString(item.conversation_id),
        conversationTitle: optionalString(item.conversation_title),
        question,
        intentLabel: optionalString(item.intent_label),
        status,
        statusLabel: optionalString(item.status_label),
        symbol: optionalString(item.symbol),
        displayName: optionalString(item.display_name),
        createdAt: optionalString(item.created_at),
        durationSeconds: optionalNumber(item.duration_seconds),
        dataAsOf: optionalString(item.data_as_of),
        guardLabel: optionalString(guard?.label),
        repaired: optionalBoolean(guard?.repaired),
        readyModules: optionalNumber(evidence?.ready_modules),
        totalModules: optionalNumber(evidence?.total_modules),
        knowledgeDocuments: optionalNumber(evidence?.knowledge_documents),
        answerExcerpt: optionalString(item.answer_excerpt),
      }];
    }),
    summary: {
      total: optionalNumber(summary?.total),
      filtered: optionalNumber(summary?.filtered),
      repaired: optionalNumber(summary?.repaired),
      days: optionalNumber(summary?.days),
    },
  };
}
