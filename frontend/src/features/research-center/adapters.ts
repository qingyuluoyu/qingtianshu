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

function optionalBoolean(value: unknown): boolean | null {
  return typeof value === "boolean" ? value : null;
}

function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function strings(value: unknown): string[] {
  return list(value).filter((item): item is string => typeof item === "string");
}

// ---------- 共享：变化事件（research-changes / workspace timeline 同一形状） ----------

export type ChangeDiff = {
  dimension: string | null;
  label: string | null;
  before: string | null;
  after: string | null;
  detail: string | null;
  severity: string | null;
};

export type ChangeEvidence = {
  categoryLabel: string | null;
  title: string | null;
  publishedAt: string | null;
};

export type NextReview = {
  horizonSessions: number | null;
  focus: string | null;
  checks: string[];
};

export type ChangeEvent = {
  id: string | null;
  eventType: string | null;
  severity: string | null;
  summary: string | null;
  createdAt: string | null;
  dataAsOf: string | null;
  changes: ChangeDiff[];
  newEvidence: ChangeEvidence[];
  nextReview: NextReview | null;
  boundary: string | null;
};

function parseNextReview(value: unknown): NextReview | null {
  const root = optionalRecord(value);
  if (!root) return null;
  return {
    horizonSessions: optionalNumber(root.horizon_sessions),
    focus: optionalString(root.focus),
    checks: strings(root.checks),
  };
}

export function parseChangeEvent(value: unknown): ChangeEvent | null {
  const root = optionalRecord(value);
  if (!root) return null;
  return {
    id: optionalString(root.id),
    eventType: optionalString(root.event_type),
    severity: optionalString(root.severity),
    summary: optionalString(root.summary),
    createdAt: optionalString(root.created_at),
    dataAsOf: optionalString(root.data_as_of),
    changes: list(root.changes).flatMap((raw) => {
      const item = optionalRecord(raw);
      if (!item) return [];
      return [{
        dimension: optionalString(item.dimension),
        label: optionalString(item.label),
        before: optionalString(item.before),
        after: optionalString(item.after),
        detail: optionalString(item.detail),
        severity: optionalString(item.severity),
      }];
    }),
    newEvidence: list(root.new_evidence).flatMap((raw) => {
      const item = optionalRecord(raw);
      if (!item) return [];
      return [{
        categoryLabel: optionalString(item.category_label),
        title: optionalString(item.title),
        publishedAt: optionalString(item.published_at),
      }];
    }),
    nextReview: parseNextReview(root.next_review),
    boundary: optionalString(root.boundary),
  };
}

// ---------- 判断/变化链（GET /me/research-changes，type="research_tracking" 直通锁） ----------

export type ResearchChangeItem = {
  symbol: string;
  name: string | null;
  thesisSummary: string | null;
  inWatchlist: boolean | null;
  latestReportAt: string | null;
  latestChange: ChangeEvent | null;
  nextReview: NextReview | null;
  currentState: {
    latestClose: number | null;
    return1dPct: number | null;
    return20dPct: number | null;
    trendState: string | null;
    technicalState: string | null;
  } | null;
};

export type ResearchChanges = {
  items: ResearchChangeItem[];
  coverage: {
    requested: number | null;
    withReport: number | null;
    withChangeArchive: number | null;
  };
  boundary: string | null;
  generatedAt: string | null;
};

export function parseResearchChanges(value: unknown): ResearchChanges {
  const root = record(value);
  if (root.type !== "research_tracking") {
    throw new ContractError("type 不是 research_tracking");
  }
  const coverage = optionalRecord(root.coverage);
  return {
    items: list(root.items).flatMap((raw) => {
      const item = optionalRecord(raw);
      const symbol = optionalString(item?.symbol);
      if (!item || !symbol) return [];
      const thesis = optionalRecord(item.thesis);
      const state = optionalRecord(item.current_state);
      return [{
        symbol,
        name: optionalString(item.name),
        // thesis 为对象时取 summary 直通；为 null 表示「尚未保存当前判断」，与接口失败区分。
        thesisSummary: optionalString(thesis?.summary),
        inWatchlist: optionalBoolean(item.in_watchlist),
        latestReportAt: optionalString(item.latest_report_at),
        latestChange: parseChangeEvent(item.latest_change),
        nextReview: parseNextReview(item.next_review),
        currentState: state === null ? null : {
          latestClose: optionalNumber(state.latest_close),
          // return_*_pct 后端已是百分数，直通不缩放。
          return1dPct: optionalNumber(state.return_1d_pct),
          return20dPct: optionalNumber(state.return_20d_pct),
          trendState: optionalString(state.trend_state),
          technicalState: optionalString(state.technical_state),
        },
      }];
    }),
    coverage: {
      requested: optionalNumber(coverage?.requested),
      withReport: optionalNumber(coverage?.with_report),
      withChangeArchive: optionalNumber(coverage?.with_change_archive),
    },
    boundary: optionalString(root.boundary),
    generatedAt: optionalString(root.generated_at),
  };
}

// ---------- 历史结果（GET /me/research-outcomes，type="research_outcome" 直通锁） ----------

export type OutcomeAnchor = {
  id: string | null;
  reportId: string | null;
  anchorTimestamp: string | null;
  anchorClose: number | null;
  horizonSessions: number | null;
  resultStatus: string | null;
  observedSessions: number | null;
  targetTimestamp: string | null;
  targetClose: number | null;
  closeReturnPct: number | null;
  maximumFavorableExcursionPct: number | null;
  maximumAdverseExcursionPct: number | null;
  partialReturnPct: number | null;
  progressTimestamp: string | null;
  scenarioResult: string | null;
  scenarioLabel: string | null;
  originalOutlookLabel: string | null;
  reviewConclusion: string | null;
  calculatedAt: string | null;
  dataAsOf: string | null;
  protocol: {
    anchor: string | null;
    horizon: string | null;
    priceSeries: string | null;
    mfeMae: string | null;
  } | null;
  boundary: string | null;
};

function parseOutcomeAnchor(value: unknown): OutcomeAnchor | null {
  const root = optionalRecord(value);
  if (!root) return null;
  const protocol = optionalRecord(root.protocol);
  return {
    id: optionalString(root.id),
    reportId: optionalString(root.report_id),
    anchorTimestamp: optionalString(root.anchor_timestamp),
    anchorClose: optionalNumber(root.anchor_close),
    horizonSessions: optionalNumber(root.horizon_sessions),
    resultStatus: optionalString(root.result_status),
    observedSessions: optionalNumber(root.observed_sessions),
    targetTimestamp: optionalString(root.target_timestamp),
    targetClose: optionalNumber(root.target_close),
    // 全部 *_pct 为百分数直通，不缩放、不取绝对值；null 表示尚未形成，不是 0。
    closeReturnPct: optionalNumber(root.close_return_pct),
    maximumFavorableExcursionPct: optionalNumber(root.maximum_favorable_excursion_pct),
    maximumAdverseExcursionPct: optionalNumber(root.maximum_adverse_excursion_pct),
    partialReturnPct: optionalNumber(root.partial_return_pct),
    progressTimestamp: optionalString(root.progress_timestamp),
    scenarioResult: optionalString(root.scenario_result),
    scenarioLabel: optionalString(root.scenario_label),
    originalOutlookLabel: optionalString(root.original_outlook_label),
    reviewConclusion: optionalString(root.review_conclusion),
    calculatedAt: optionalString(root.calculated_at),
    dataAsOf: optionalString(root.data_as_of),
    protocol: protocol === null ? null : {
      anchor: optionalString(protocol.anchor),
      horizon: optionalString(protocol.horizon),
      priceSeries: optionalString(protocol.price_series),
      mfeMae: optionalString(protocol.mfe_mae),
    },
    boundary: optionalString(root.boundary),
  };
}

export type ResearchOutcomeItem = {
  symbol: string;
  name: string | null;
  thesisSummary: string | null;
  latestAnchorAt: string | null;
  /** 最新锚点组（可含多个 horizon 的待形成结果）。 */
  latestAnchor: OutcomeAnchor[];
  /** 进行中的结果（已观察到部分交易日，未到期）。 */
  latestProgress: OutcomeAnchor | null;
  /** 已到期、可查看的结果。 */
  latestAvailable: OutcomeAnchor[];
  coverage: {
    anchors: number | null;
    available: number | null;
    pending: number | null;
  };
};

export type ResearchOutcomes = {
  items: ResearchOutcomeItem[];
  boundary: string | null;
  generatedAt: string | null;
};

export function parseResearchOutcomes(value: unknown): ResearchOutcomes {
  const root = record(value);
  if (root.type !== "research_outcome") {
    throw new ContractError("type 不是 research_outcome");
  }
  return {
    items: list(root.items).flatMap((raw) => {
      const item = optionalRecord(raw);
      const symbol = optionalString(item?.symbol);
      if (!item || !symbol) return [];
      const thesis = optionalRecord(item.thesis);
      const coverage = optionalRecord(item.coverage);
      return [{
        symbol,
        name: optionalString(item.name),
        thesisSummary: optionalString(thesis?.summary),
        latestAnchorAt: optionalString(item.latest_anchor_at),
        latestAnchor: list(item.latest_anchor).flatMap((entry) => {
          const anchor = parseOutcomeAnchor(entry);
          return anchor ? [anchor] : [];
        }),
        latestProgress: parseOutcomeAnchor(item.latest_progress),
        latestAvailable: list(item.latest_available).flatMap((entry) => {
          const anchor = parseOutcomeAnchor(entry);
          return anchor ? [anchor] : [];
        }),
        coverage: {
          anchors: optionalNumber(coverage?.anchors),
          available: optionalNumber(coverage?.available),
          pending: optionalNumber(coverage?.pending),
        },
      }];
    }),
    boundary: optionalString(root.boundary),
    generatedAt: optionalString(root.generated_at),
  };
}

// ---------- 下一步行动（GET /me/research-actions，type="research_actions" 直通锁） ----------

export type ResearchAction = {
  id: string | null;
  key: string | null;
  category: string | null;
  title: string | null;
  status: string | null;
  severity: string | null;
  condition: string | null;
  currentEvidence: string | null;
  nextStep: string | null;
  checks: string[];
};

export type ResearchActionItem = {
  symbol: string;
  name: string | null;
  researchStatus: string | null;
  researchStatusLabel: string | null;
  priorityScore: number | null;
  priorityLabel: string | null;
  headline: string | null;
  dataAsOf: string | null;
  actions: ResearchAction[];
};

export type ResearchActions = {
  items: ResearchActionItem[];
  generatedAt: string | null;
};

export function parseResearchActions(value: unknown): ResearchActions {
  const root = record(value);
  if (root.type !== "research_actions") {
    throw new ContractError("type 不是 research_actions");
  }
  return {
    items: list(root.items).flatMap((raw) => {
      const item = optionalRecord(raw);
      const symbol = optionalString(item?.symbol);
      if (!item || !symbol) return [];
      return [{
        symbol,
        name: optionalString(item.name),
        researchStatus: optionalString(item.research_status),
        researchStatusLabel: optionalString(item.research_status_label),
        priorityScore: optionalNumber(item.priority_score),
        priorityLabel: optionalString(item.priority_label),
        headline: optionalString(item.headline),
        dataAsOf: optionalString(item.data_as_of),
        actions: list(item.actions).flatMap((entry) => {
          const action = optionalRecord(entry);
          if (!action) return [];
          return [{
            id: optionalString(action.id),
            key: optionalString(action.key),
            category: optionalString(action.category),
            title: optionalString(action.title),
            status: optionalString(action.status),
            severity: optionalString(action.severity),
            condition: optionalString(action.condition),
            currentEvidence: optionalString(action.current_evidence),
            nextStep: optionalString(action.next_step),
            checks: strings(action.checks),
          }];
        }),
      }];
    }),
    generatedAt: optionalString(root.generated_at),
  };
}

// ---------- 判断-变化-处理链（GET /v1/stocks/{symbol}/workspace/timeline） ----------

export type ThesisVersion = {
  id: string | null;
  versionNo: number | null;
  reasonText: string | null;
  status: string | null;
  createdAt: string | null;
  confirmedAt: string | null;
};

export type ObservationTask = {
  id: string | null;
  title: string | null;
  status: string | null;
  description: string | null;
  version: number | null;
  updatedAt: string | null;
};

export type WorkspaceTimeline = {
  symbol: string;
  name: string | null;
  thesisHistory: ThesisVersion[];
  importantChanges: ChangeEvent[];
  observationTasks: {
    items: ObservationTask[];
    summary: { total: number | null; active: number | null; pending: number | null; completed: number | null };
  };
  tradeReviewSummary: {
    total: number | null;
    waitingData: number | null;
    needsConfirmation: number | null;
  };
  historySummary: {
    changeCount: number | null;
    thesisVersionCount: number | null;
    observationTaskCount: number | null;
    tradeReviewCount: number | null;
    recentReportCount: number | null;
    latestChangeAt: string | null;
    latestReportAt: string | null;
  };
  dataMeta: {
    status: string | null;
    dailyAsOf: string | null;
    quoteAsOf: string | null;
    reportGeneratedAt: string | null;
    reportMarketTimestamp: string | null;
    financialReportPeriod: string | null;
  };
};

export function parseWorkspaceTimeline(value: unknown): WorkspaceTimeline {
  const root = record(value);
  if (root.contract_version !== "stock_workspace_timeline_v1") {
    throw new ContractError("contract_version 不是 stock_workspace_timeline_v1");
  }
  const tasks = optionalRecord(root.observation_tasks);
  const taskSummary = optionalRecord(tasks?.summary);
  const tradeReviews = optionalRecord(root.trade_reviews);
  const tradeSummary = optionalRecord(tradeReviews?.summary);
  const history = optionalRecord(root.history_summary);
  const dataMeta = optionalRecord(root.data_meta);
  return {
    symbol: requiredString(root.symbol, "symbol"),
    name: optionalString(root.name),
    thesisHistory: list(root.thesis_history).flatMap((raw) => {
      const item = optionalRecord(raw);
      if (!item) return [];
      return [{
        id: optionalString(item.id),
        versionNo: optionalNumber(item.version_no),
        reasonText: optionalString(item.reason_text),
        status: optionalString(item.status),
        createdAt: optionalString(item.created_at),
        confirmedAt: optionalString(item.confirmed_at),
      }];
    }),
    importantChanges: list(root.important_changes).flatMap((raw) => {
      const change = parseChangeEvent(raw);
      return change ? [change] : [];
    }),
    observationTasks: {
      items: list(tasks?.items).flatMap((raw) => {
        const item = optionalRecord(raw);
        if (!item) return [];
        return [{
          id: optionalString(item.id),
          title: optionalString(item.title),
          status: optionalString(item.status),
          description: optionalString(item.description),
          version: optionalNumber(item.version),
          updatedAt: optionalString(item.updated_at),
        }];
      }),
      summary: {
        total: optionalNumber(taskSummary?.total),
        active: optionalNumber(taskSummary?.active),
        pending: optionalNumber(taskSummary?.pending),
        completed: optionalNumber(taskSummary?.completed),
      },
    },
    tradeReviewSummary: {
      total: optionalNumber(tradeSummary?.total),
      waitingData: optionalNumber(tradeSummary?.waiting_data),
      needsConfirmation: optionalNumber(tradeSummary?.needs_confirmation),
    },
    historySummary: {
      changeCount: optionalNumber(history?.change_count),
      thesisVersionCount: optionalNumber(history?.thesis_version_count),
      observationTaskCount: optionalNumber(history?.observation_task_count),
      tradeReviewCount: optionalNumber(history?.trade_review_count),
      recentReportCount: optionalNumber(history?.recent_report_count),
      latestChangeAt: optionalString(history?.latest_change_at),
      latestReportAt: optionalString(history?.latest_report_at),
    },
    dataMeta: {
      status: optionalString(dataMeta?.status),
      dailyAsOf: optionalString(dataMeta?.daily_as_of),
      quoteAsOf: optionalString(dataMeta?.quote_as_of),
      reportGeneratedAt: optionalString(dataMeta?.report_generated_at),
      reportMarketTimestamp: optionalString(dataMeta?.report_market_timestamp),
      financialReportPeriod: optionalString(dataMeta?.financial_report_period),
    },
  };
}

// ---------- 交易复盘中心（GET /v1/trade-reviews，contract_version 直通锁） ----------

export type TradeReview = {
  id: string;
  symbol: string | null;
  name: string | null;
  status: string | null;
  dataStatus: string | null;
  horizonSessions: number | null;
  readyAt: string | null;
  confirmedAt: string | null;
  archivedAt: string | null;
  updatedAt: string | null;
  canConfirm: boolean | null;
  canGenerateDraft: boolean | null;
  operation: {
    operationType: string | null;
    operatedAt: string | null;
    price: number | null;
    reasonText: string | null;
  } | null;
  priceObservation: {
    ready: boolean | null;
    summary: string | null;
  } | null;
  currentVersion: {
    /** confirm / archive 的 base_version（后端以 current_version.version_no 校验，409 表示已被更新）。 */
    versionNo: number | null;
    status: string | null;
    priceResult: string | null;
    logicResult: string | null;
    planDeviation: string | null;
    biasTags: string[] | null;
    improvementText: string | null;
    createdSource: string | null;
    createdAt: string | null;
  } | null;
};

function parseTradeReview(value: unknown): TradeReview | null {
  const root = optionalRecord(value);
  const id = optionalString(root?.id);
  if (!root || !id) return null;
  const operation = optionalRecord(root.operation);
  const observation = optionalRecord(root.price_observation);
  const version = optionalRecord(root.current_version);
  return {
    id,
    symbol: optionalString(root.symbol),
    name: optionalString(root.name),
    status: optionalString(root.status),
    dataStatus: optionalString(root.data_status),
    horizonSessions: optionalNumber(root.horizon_sessions),
    readyAt: optionalString(root.ready_at),
    confirmedAt: optionalString(root.confirmed_at),
    archivedAt: optionalString(root.archived_at),
    updatedAt: optionalString(root.updated_at),
    canConfirm: optionalBoolean(root.can_confirm),
    canGenerateDraft: optionalBoolean(root.can_generate_draft),
    operation: operation === null ? null : {
      operationType: optionalString(operation.operation_type),
      operatedAt: optionalString(operation.operated_at),
      price: optionalNumber(operation.price),
      reasonText: optionalString(operation.reason_text),
    },
    priceObservation: observation === null ? null : {
      ready: optionalBoolean(observation.ready),
      summary: optionalString(observation.summary),
    },
    currentVersion: version === null ? null : {
      versionNo: optionalNumber(version.version_no),
      status: optionalString(version.status),
      priceResult: optionalString(version.price_result),
      logicResult: optionalString(version.logic_result),
      planDeviation: optionalString(version.plan_deviation),
      biasTags: Array.isArray(version.bias_tags) ? strings(version.bias_tags) : null,
      improvementText: optionalString(version.improvement_text),
      createdSource: optionalString(version.created_source),
      createdAt: optionalString(version.created_at),
    },
  };
}

export type PendingWriteback = {
  id: string;
  reviewId: string;
  symbol: string | null;
  logicResult: string | null;
  planDeviation: string | null;
  improvementText: string | null;
  biasTags: string[];
  createdAt: string | null;
};

export type PendingWritebacks = { items: PendingWriteback[] };

export function parsePendingWritebacks(value: unknown): PendingWritebacks {
  const root = record(value);
  return {
    items: list(root.items).flatMap((raw) => {
      const item = optionalRecord(raw);
      const payload = optionalRecord(item?.payload);
      const id = optionalString(item?.id);
      const reviewId = optionalString(payload?.review_id);
      if (!item || item.candidate_type !== "review_draft" || item.status !== "pending_confirmation" || !id || !reviewId) return [];
      return [{
        id,
        reviewId,
        symbol: optionalString(item.symbol),
        logicResult: optionalString(payload.logic_result),
        planDeviation: optionalString(payload.plan_deviation),
        improvementText: optionalString(payload.improvement_text),
        biasTags: strings(payload.bias_tags),
        createdAt: optionalString(item.created_at),
      }];
    }),
  };
}

export type TradeReviewCenter = {
  items: TradeReview[];
  summary: {
    total: number | null;
    actionable: number | null;
    waitingData: number | null;
    ready: number | null;
    needsConfirmation: number | null;
    confirmed: number | null;
    archived: number | null;
  };
  boundary: string | null;
};

export function parseTradeReviewCenter(value: unknown): TradeReviewCenter {
  const root = record(value);
  if (root.contract_version !== "trade_review_center_v1") {
    throw new ContractError("contract_version 不是 trade_review_center_v1");
  }
  const summary = optionalRecord(root.summary);
  return {
    items: list(root.items).flatMap((raw) => {
      const item = parseTradeReview(raw);
      return item ? [item] : [];
    }),
    summary: {
      total: optionalNumber(summary?.total),
      actionable: optionalNumber(summary?.actionable),
      waitingData: optionalNumber(summary?.waiting_data),
      ready: optionalNumber(summary?.ready),
      needsConfirmation: optionalNumber(summary?.needs_confirmation),
      confirmed: optionalNumber(summary?.confirmed),
      archived: optionalNumber(summary?.archived),
    },
    boundary: optionalString(root.boundary),
  };
}

// ---------- 研究快照（GET /research-reports/{symbol}，无 contract_version，做结构校验） ----------

export type ResearchReport = {
  id: string | null;
  symbol: string;
  name: string | null;
  title: string | null;
  summary: string | null;
  status: string | null;
  marketTimestamp: string | null;
  generatedAt: string | null;
};

export function parseResearchReport(value: unknown): ResearchReport {
  const root = record(value);
  return {
    id: optionalString(root.id),
    symbol: requiredString(root.symbol, "symbol"),
    name: optionalString(root.name),
    title: optionalString(root.title),
    summary: optionalString(root.summary),
    status: optionalString(root.status),
    marketTimestamp: optionalString(root.market_timestamp),
    generatedAt: optionalString(root.generated_at),
  };
}
