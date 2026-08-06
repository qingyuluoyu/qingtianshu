export type JsonRecord = Record<string, unknown>;

export class AdvisorContractError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AdvisorContractError";
  }
}

function record(value: unknown, field = "response"): JsonRecord {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new AdvisorContractError(`${field} 不是对象`);
  }
  return value as JsonRecord;
}

function optionalRecord(value: unknown): JsonRecord | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as JsonRecord
    : null;
}

function requiredString(value: unknown, field: string): string {
  if (typeof value !== "string" || value.trim().length === 0) {
    throw new AdvisorContractError(`${field} 缺失`);
  }
  return value;
}

function optionalString(value: unknown): string | null {
  return typeof value === "string" && value.trim().length > 0 ? value : null;
}

function optionalNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function strings(value: unknown): string[] {
  return list(value).filter((item): item is string => typeof item === "string");
}

export type ResearchTarget = { symbol: string; name: string | null };

export type AdvisorConversationSummary = {
  id: string;
  title: string;
  qualityScope: string | null;
  status: string | null;
  messageCount: number | null;
  lastMessagePreview: string | null;
  lastIntent: string | null;
  conversationScope: string | null;
  researchTargets: ResearchTarget[];
  createdAt: string | null;
  updatedAt: string | null;
};

export type EvidenceSource = {
  title: string;
  kind: string | null;
  copy: string | null;
  meta: string | null;
  url: string | null;
};

export type AdvisorCitation = {
  id: string;
  sourceName: string;
  sourceUrl: string | null;
  evidenceType: string | null;
  dataTime: string | null;
  reportPeriod: string | null;
  excerpt: string | null;
  limitations: string[];
};

export type WritebackCandidate = {
  id: string;
  symbol: string | null;
  candidateType: string;
  status: string;
  payload: JsonRecord;
  citationIds: string[];
  baseVersion: number | null;
  createdAt: string | null;
  resolvedAt: string | null;
};

export type StructuredAnswer = {
  status: string | null;
  citations: AdvisorCitation[];
  candidateWritebacks: WritebackCandidate[];
};

export type AdvisorMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  intent: string | null;
  runId: string | null;
  createdAt: string | null;
  structuredAnswer: StructuredAnswer | null;
  evidenceSources: EvidenceSource[];
};

export type AdvisorConversationDetail = AdvisorConversationSummary & {
  messages: AdvisorMessage[];
};

export type AdvisorEntryContext = {
  sourcePage: string;
  module: string;
  asOf: string | null;
  symbol: string | null;
};

export type AdvisorRun = {
  id: string;
  status: string;
  answer: string | null;
  error: string | null;
  entryContext: AdvisorEntryContext | null;
};

export type AdvisorChatAccepted = {
  runId: string;
  status: string;
  intent: string | null;
  answer: string;
  conversationId: string;
  conversationTitle: string | null;
  assistantMessageId: string | null;
  structuredAnswer: StructuredAnswer | null;
  evidenceSources: EvidenceSource[];
};

function parseResearchTargets(value: unknown): ResearchTarget[] {
  return list(value).flatMap((raw) => {
    const item = optionalRecord(raw);
    const symbol = optionalString(item?.symbol);
    return item && symbol ? [{ symbol, name: optionalString(item.name) }] : [];
  });
}

export function parseConversationSummary(value: unknown): AdvisorConversationSummary {
  const root = record(value, "conversation");
  return {
    id: requiredString(root.id, "conversation.id"),
    title: requiredString(root.title, "conversation.title"),
    qualityScope: optionalString(root.quality_scope),
    status: optionalString(root.status),
    messageCount: optionalNumber(root.message_count),
    lastMessagePreview: optionalString(root.last_message_preview),
    lastIntent: optionalString(root.last_intent),
    conversationScope: optionalString(root.conversation_scope),
    researchTargets: parseResearchTargets(root.research_targets),
    createdAt: optionalString(root.created_at),
    updatedAt: optionalString(root.updated_at),
  };
}

export function parseConversationList(value: unknown): AdvisorConversationSummary[] {
  const root = record(value);
  return list(root.items).map(parseConversationSummary);
}

export function parseEvidenceSource(value: unknown): EvidenceSource | null {
  const root = optionalRecord(value);
  const title = optionalString(root?.title);
  if (!root || !title) return null;
  return {
    title,
    kind: optionalString(root.kind) ?? optionalString(root.tag),
    copy: optionalString(root.copy) ?? optionalString(root.excerpt),
    meta: optionalString(root.meta) ?? optionalString(root.data_time),
    url: optionalString(root.url) ?? optionalString(root.source_url),
  };
}

export function parseAdvisorCitation(value: unknown): AdvisorCitation | null {
  const root = optionalRecord(value);
  const id = optionalString(root?.id);
  const sourceName = optionalString(root?.source_name);
  if (!root || !id || !sourceName) return null;
  return {
    id,
    sourceName,
    sourceUrl: optionalString(root.source_url),
    evidenceType: optionalString(root.evidence_type),
    dataTime: optionalString(root.data_time),
    reportPeriod: optionalString(root.report_period),
    excerpt: optionalString(root.excerpt),
    limitations: strings(root.limitations),
  };
}

export function parseWritebackCandidate(value: unknown): WritebackCandidate {
  const root = record(value, "writeback");
  return {
    id: requiredString(root.id, "writeback.id"),
    symbol: optionalString(root.symbol),
    candidateType: requiredString(root.candidate_type, "writeback.candidate_type"),
    status: requiredString(root.status, "writeback.status"),
    payload: optionalRecord(root.payload) ?? {},
    citationIds: strings(root.citation_ids),
    baseVersion: optionalNumber(root.base_version),
    createdAt: optionalString(root.created_at),
    resolvedAt: optionalString(root.resolved_at),
  };
}

export function parseStructuredAnswer(value: unknown): StructuredAnswer | null {
  const root = optionalRecord(value);
  if (!root) return null;
  return {
    status: optionalString(root.status),
    citations: list(root.citations).flatMap((raw) => {
      const citation = parseAdvisorCitation(raw);
      return citation ? [citation] : [];
    }),
    candidateWritebacks: list(root.candidate_writebacks).map(parseWritebackCandidate),
  };
}

function parseMessage(value: unknown): AdvisorMessage {
  const root = record(value, "message");
  const role = requiredString(root.role, "message.role");
  if (role !== "user" && role !== "assistant") {
    throw new AdvisorContractError("message.role 不受支持");
  }
  const metadata = optionalRecord(root.metadata);
  return {
    id: requiredString(root.id, "message.id"),
    role,
    content: requiredString(root.content, "message.content"),
    intent: optionalString(root.intent),
    runId: optionalString(root.run_id),
    createdAt: optionalString(root.created_at),
    structuredAnswer: parseStructuredAnswer(metadata?.structured_answer),
    evidenceSources: list(metadata?.evidence_sources).flatMap((raw) => {
      const source = parseEvidenceSource(raw);
      return source ? [source] : [];
    }),
  };
}

export function parseConversationDetail(value: unknown): AdvisorConversationDetail {
  const root = record(value);
  return {
    ...parseConversationSummary(root),
    messages: list(root.messages).map(parseMessage),
  };
}

function parseEntryContext(value: unknown): AdvisorEntryContext | null {
  const root = optionalRecord(value);
  const sourcePage = optionalString(root?.source_page);
  const module = optionalString(root?.module);
  if (!root || !sourcePage || !module) return null;
  return {
    sourcePage,
    module,
    asOf: optionalString(root.as_of),
    symbol: optionalString(root.symbol),
  };
}

export function parseAdvisorRun(value: unknown): AdvisorRun {
  const root = record(value);
  const input = optionalRecord(root.input);
  return {
    id: requiredString(root.id, "run.id"),
    status: requiredString(root.status, "run.status"),
    answer: optionalString(root.answer),
    error: optionalString(root.error),
    entryContext: parseEntryContext(input?.entry_context),
  };
}

export function parseChatAccepted(value: unknown): AdvisorChatAccepted {
  const root = record(value);
  return {
    runId: requiredString(root.run_id, "chat.run_id"),
    status: requiredString(root.status, "chat.status"),
    intent: optionalString(root.intent),
    answer: requiredString(root.answer, "chat.answer"),
    conversationId: requiredString(root.conversation_id, "chat.conversation_id"),
    conversationTitle: optionalString(root.conversation_title),
    assistantMessageId: optionalString(root.assistant_message_id),
    structuredAnswer: parseStructuredAnswer(root.structured_answer),
    evidenceSources: list(root.evidence_sources).flatMap((raw) => {
      const source = parseEvidenceSource(raw);
      return source ? [source] : [];
    }),
  };
}

export function parseWritebackList(value: unknown): { items: WritebackCandidate[]; pendingCount: number | null } {
  const root = record(value);
  const summary = optionalRecord(root.summary);
  return {
    items: list(root.items).map(parseWritebackCandidate),
    pendingCount: optionalNumber(summary?.pending_confirmation),
  };
}
