export type JsonRecord = Record<string, unknown>;

export class ContractError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ContractError";
  }
}

function record(value: unknown, field = "response"): JsonRecord {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new ContractError(`${field} 不是对象`);
  }
  return value as JsonRecord;
}

function optionalRecord(value: unknown): JsonRecord | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as JsonRecord)
    : null;
}

function requiredString(value: unknown, field: string): string {
  if (typeof value !== "string" || value.length === 0) throw new ContractError(`${field} 缺失`);
  return value;
}

function optionalString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
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

// ---------- 会话列表（GET /me/conversations） ----------

export type ResearchTarget = { symbol: string | null; name: string | null };

export type ConversationSummary = {
  id: string;
  title: string | null;
  status: string | null;
  messageCount: number | null;
  lastMessagePreview: string | null;
  lastIntent: string | null;
  conversationScope: string | null;
  researchTargets: ResearchTarget[];
  createdAt: string | null;
  updatedAt: string | null;
};

function parseResearchTargets(value: unknown): ResearchTarget[] {
  return list(value).flatMap((raw) => {
    const root = optionalRecord(raw);
    if (!root) return [];
    return [{
      symbol: optionalString(root.symbol),
      name: optionalString(root.name),
    }];
  });
}

export function parseConversationSummary(raw: unknown): ConversationSummary | null {
  const root = optionalRecord(raw);
  const id = optionalString(root?.id);
  if (!root || !id) return null;
  return {
    id,
    title: optionalString(root.title),
    status: optionalString(root.status),
    // 0 是有效数值（空对话），缺字段才是未知。
    messageCount: optionalNumber(root.message_count),
    lastMessagePreview: optionalString(root.last_message_preview),
    lastIntent: optionalString(root.last_intent),
    conversationScope: optionalString(root.conversation_scope),
    researchTargets: parseResearchTargets(root.research_targets),
    createdAt: optionalString(root.created_at),
    updatedAt: optionalString(root.updated_at),
  };
}

export type ConversationList = {
  items: ConversationSummary[];
};

export function parseConversationList(value: unknown): ConversationList {
  const root = record(value);
  return {
    items: list(root.items).flatMap((raw) => {
      const item = parseConversationSummary(raw);
      return item ? [item] : [];
    }),
  };
}

// ---------- 会话详情（GET /me/conversations/{id}） ----------

export type EvidenceSource = {
  kind: string | null;
  title: string | null;
  summary: string | null;
  asOf: string | null;
  source: string | null;
  url: string | null;
};

export function parseEvidenceSource(raw: unknown): EvidenceSource | null {
  const root = optionalRecord(raw);
  if (!root) return null;
  const title = optionalString(root.title);
  if (!title) return null;
  return {
    kind: optionalString(root.kind),
    title,
    summary: optionalString(root.summary),
    asOf: optionalString(root.as_of),
    source: optionalString(root.source),
    url: optionalString(root.url),
  };
}

export function parseEvidenceSources(value: unknown): EvidenceSource[] {
  return list(value).flatMap((raw) => {
    const item = parseEvidenceSource(raw);
    return item ? [item] : [];
  });
}

// ---------- AI 候选写回（GET /v1/ai-writebacks，contract structured_ai_response_v1） ----------

export type WritebackCandidate = {
  id: string;
  symbol: string | null;
  /** thesis / observation_task / action_plan / review_draft，直通。 */
  candidateType: string | null;
  /** pending_confirmation / confirmed / rejected / stale，直通。 */
  status: string | null;
  /** 候选内容，按类型由 UI 翻译；未识别类型仅展示原始键值，不编造。 */
  payload: JsonRecord;
  citationIds: string[];
  /** 服务端内嵌的乐观锁版本（正式对象版本）；confirm 不重复传，409 时后端把候选置 stale。 */
  baseVersion: number | null;
  createdAt: string | null;
  resolvedAt: string | null;
};

export function parseWritebackCandidate(raw: unknown): WritebackCandidate | null {
  const root = optionalRecord(raw);
  const id = optionalString(root?.id);
  if (!root || !id) return null;
  return {
    id,
    symbol: optionalString(root.symbol),
    candidateType: optionalString(root.candidate_type),
    status: optionalString(root.status),
    payload: optionalRecord(root.payload) ?? {},
    citationIds: strings(root.citation_ids),
    baseVersion: optionalNumber(root.base_version),
    createdAt: optionalString(root.created_at),
    resolvedAt: optionalString(root.resolved_at),
  };
}

export type WritebackList = {
  status: string;
  items: WritebackCandidate[];
  summary: { total: number | null; pendingConfirmation: number | null };
};

export function parseWritebackList(value: unknown): WritebackList {
  const root = record(value);
  if (root.contract_version !== "structured_ai_response_v1") {
    throw new ContractError("contract_version 不是 structured_ai_response_v1");
  }
  const summary = optionalRecord(root.summary);
  return {
    status: "ready",
    items: list(root.items).flatMap((raw) => {
      const item = parseWritebackCandidate(raw);
      return item ? [item] : [];
    }),
    summary: {
      total: optionalNumber(summary?.total),
      pendingConfirmation: optionalNumber(summary?.pending_confirmation),
    },
  };
}

// ---------- 结构化回答（structured_answer，contract structured_ai_response_v1） ----------

export type Citation = {
  id: string | null;
  sourceName: string | null;
  sourceUrl: string | null;
  evidenceType: string | null;
  dataTime: string | null;
  reportPeriod: string | null;
  excerpt: string | null;
  limitations: string | null;
};

export type StructuredAnswer = {
  /** complete / partial / unavailable，直通。 */
  status: string | null;
  answerSummary: string | null;
  confirmedFacts: string[];
  evidenceBasedInferences: string[];
  hypothesesToVerify: string[];
  counterEvidenceAndRisks: string[];
  informationGaps: string[];
  conclusionBoundary: string | null;
  citations: Citation[];
  candidateWritebacks: WritebackCandidate[];
};

function claimTexts(value: unknown): string[] {
  // 结构化条目可能是字符串，也可能是 {text/claim/summary} 对象；两种都直通文本，不自行改写。
  return list(value).flatMap((raw) => {
    if (typeof raw === "string" && raw.length > 0) return [raw];
    const root = optionalRecord(raw);
    if (!root) return [];
    const text = optionalString(root.text) ?? optionalString(root.claim) ?? optionalString(root.summary);
    return text ? [text] : [];
  });
}

export function parseStructuredAnswer(value: unknown): StructuredAnswer | null {
  const root = optionalRecord(value);
  if (!root) return null;
  if (root.contract_version !== "structured_ai_response_v1") {
    throw new ContractError("structured_answer.contract_version 不是 structured_ai_response_v1");
  }
  return {
    status: optionalString(root.status),
    answerSummary: optionalString(root.answer_summary),
    confirmedFacts: claimTexts(root.confirmed_facts),
    evidenceBasedInferences: claimTexts(root.evidence_based_inferences),
    hypothesesToVerify: claimTexts(root.hypotheses_to_verify),
    counterEvidenceAndRisks: claimTexts(root.counter_evidence_and_risks),
    informationGaps: strings(root.information_gaps),
    conclusionBoundary: optionalString(root.conclusion_boundary),
    citations: list(root.citations).flatMap((raw) => {
      const item = optionalRecord(raw);
      if (!item) return [];
      return [{
        id: optionalString(item.id),
        sourceName: optionalString(item.source_name),
        sourceUrl: optionalString(item.source_url),
        evidenceType: optionalString(item.evidence_type),
        dataTime: optionalString(item.data_time),
        reportPeriod: optionalString(item.report_period),
        excerpt: optionalString(item.excerpt),
        limitations: optionalString(item.limitations),
      } satisfies Citation];
    }),
    candidateWritebacks: list(root.candidate_writebacks).flatMap((raw) => {
      const item = parseWritebackCandidate(raw);
      return item ? [item] : [];
    }),
  };
}

// ---------- 消息与会话详情 ----------

export type MessageMetadata = {
  symbol: string | null;
  modelTier: string | null;
  evidenceSources: EvidenceSource[];
  structuredAnswer: StructuredAnswer | null;
};

export type ConversationMessage = {
  id: string;
  role: string | null;
  content: string | null;
  intent: string | null;
  runId: string | null;
  metadata: MessageMetadata | null;
  createdAt: string | null;
};

export function parseConversationMessage(raw: unknown): ConversationMessage | null {
  const root = optionalRecord(raw);
  const id = optionalString(root?.id);
  if (!root || !id) return null;
  const metadata = optionalRecord(root.metadata);
  return {
    id,
    role: optionalString(root.role),
    content: optionalString(root.content),
    intent: optionalString(root.intent),
    runId: optionalString(root.run_id),
    metadata: metadata === null ? null : {
      symbol: optionalString(metadata.symbol),
      modelTier: optionalString(metadata.model_tier),
      evidenceSources: parseEvidenceSources(metadata.evidence_sources),
      structuredAnswer: parseStructuredAnswer(metadata.structured_answer),
    },
    createdAt: optionalString(root.created_at),
  };
}

export type ConversationDetail = ConversationSummary & {
  messages: ConversationMessage[];
};

export function parseConversationDetail(value: unknown): ConversationDetail {
  const summary = parseConversationSummary(value);
  if (!summary) throw new ContractError("会话详情缺少 id");
  const root = record(value);
  return {
    ...summary,
    messages: list(root.messages).flatMap((raw) => {
      const item = parseConversationMessage(raw);
      return item ? [item] : [];
    }),
  };
}

// ---------- 提问响应（POST /me/chat） ----------

export type ChatResponse = {
  runId: string | null;
  /** completed / failed / clarification / blocked 等，直通。 */
  status: string | null;
  intent: string | null;
  modelTier: string | null;
  answer: string | null;
  error: string | null;
  conversationId: string | null;
  conversationTitle: string | null;
  assistantMessageId: string | null;
  evidenceSources: EvidenceSource[];
  researchTargets: ResearchTarget[];
  structuredAnswer: StructuredAnswer | null;
  /** status=clarification 时 evidence.required_fields 的待补充项。 */
  requiredFields: string[];
};

export function parseChatResponse(value: unknown): ChatResponse {
  const root = record(value);
  const evidence = optionalRecord(root.evidence);
  return {
    runId: optionalString(root.run_id),
    status: optionalString(root.status),
    intent: optionalString(root.intent),
    modelTier: optionalString(root.model_tier),
    answer: optionalString(root.answer),
    error: optionalString(root.error),
    conversationId: optionalString(root.conversation_id),
    conversationTitle: optionalString(root.conversation_title),
    assistantMessageId: optionalString(root.assistant_message_id),
    evidenceSources: parseEvidenceSources(root.evidence_sources),
    researchTargets: parseResearchTargets(root.research_targets),
    structuredAnswer: parseStructuredAnswer(root.structured_answer),
    requiredFields: strings(evidence?.required_fields),
  };
}

// ---------- 提问请求构造（合同 §5.5：携带 symbol/sourcePage/module/asOf 与问题上下文） ----------

export type AdvisorContext = {
  symbol: string | null;
  sourcePage: string | null;
  module: string | null;
  asOf: string | null;
};

export type ChatRequestBody = {
  message: string;
  symbol?: string;
  conversationId?: string;
  requestId?: string;
};

/**
 * 后端 ChatRequest 只有 symbol 字段（openapi ChatRequest），sourcePage/module/asOf 没有对应
 * 传输字段；按 §5.5「每次问顾问必须携带上下文」的要求，把它们作为可追溯的上下文行拼进
 * 用户消息正文（落库后可审计），symbol 同时走专用字段。不发送任何前端编造的数据值。
 */
export function buildChatRequestBody(
  question: string,
  context: AdvisorContext,
  options: { conversationId?: string | null; requestId?: string | null } = {},
): ChatRequestBody {
  const text = question.trim();
  if (!text) throw new ContractError("问题为空，不能发送");
  const contextParts: string[] = [];
  if (context.symbol) contextParts.push(`标的=${context.symbol}`);
  if (context.sourcePage) contextParts.push(`来源页=${context.sourcePage}`);
  if (context.module) contextParts.push(`模块=${context.module}`);
  if (context.asOf) contextParts.push(`数据时间=${context.asOf}`);
  const message = contextParts.length > 0
    ? `${text}\n[研究上下文：${contextParts.join("；")}]`
    : text;
  if (message.length > 4000) throw new ContractError("问题超出长度限制（4000 字）");
  const body: ChatRequestBody = { message };
  if (context.symbol) body.symbol = context.symbol;
  if (options.conversationId) body.conversationId = options.conversationId;
  if (options.requestId) body.requestId = options.requestId;
  return body;
}
