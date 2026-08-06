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

// ---------- 关注资产列表（GET /v1/stock-workspaces） ----------

export type AssetQuote = {
  price: number | null;
  pctChange: number | null;
  label: string | null;
  marketTimestamp: string | null;
  status: string | null;
  currency: string | null;
};

export type AssetChange = {
  eventId: string | null;
  eventType: string | null;
  title: string | null;
  summary: string | null;
  occurredAt: string | null;
  createdAt: string | null;
  sourceName: string | null;
  sourceUrl: string | null;
};

export type AssetNextAction = {
  title: string | null;
  nextStep: string | null;
  status: string | null;
};

export type AssetReportMeta = {
  id: string | null;
  title: string | null;
  summary: string | null;
  status: string | null;
  generatedAt: string | null;
  marketTimestamp: string | null;
};

export type WatchlistAsset = {
  workspaceId: string | null;
  /** 关系版本号：PATCH /v1/stocks/{symbol}/relation 的 base_version。 */
  version: number | null;
  symbol: string;
  name: string | null;
  market: string | null;
  relationType: string | null;
  relationLabel: string | null;
  priority: string | null;
  trackingStatus: string | null;
  workflowStatus: string | null;
  attentionTags: string[];
  activeThesis: { summary: string | null; version: number | null } | null;
  latestChange: AssetChange | null;
  nextAction: AssetNextAction | null;
  openTaskCount: number | null;
  positionSnapshot: { available: boolean | null; status: string | null };
  reportMeta: AssetReportMeta | null;
  reportFreshness: { status: string | null; label: string | null; isToday: boolean | null };
  dataTimes: {
    quoteAsOf: string | null;
    dailyAsOf: string | null;
    financialReportPeriod: string | null;
    reportGeneratedAt: string | null;
  };
  quote: AssetQuote;
  dataStatus: string | null;
  warnings: string[];
};

export type WatchlistSummary = {
  total: number | null;
  watching: number | null;
  holding: number | null;
  ended: number | null;
  paused: number | null;
  waitingData: number | null;
};

export type WatchlistAssets = {
  /** 列表级状态：empty（无资产）/ ready / partial（部分行数据不完整）。 */
  status: string;
  items: WatchlistAsset[];
  summary: WatchlistSummary;
  boundary: string | null;
};

function parseQuote(value: unknown): AssetQuote {
  const root = optionalRecord(value);
  return {
    price: optionalNumber(root?.price),
    // pct_change 为百分数，直通不缩放。
    pctChange: optionalNumber(root?.pct_change),
    label: optionalString(root?.label),
    marketTimestamp: optionalString(root?.market_timestamp),
    // quote.status：available/unavailable 直通；价格缺失与行情不可用不是同一状态。
    status: optionalString(root?.status),
    currency: optionalString(root?.currency),
  };
}

function parseChange(value: unknown): AssetChange | null {
  const root = optionalRecord(value);
  if (!root) return null;
  return {
    eventId: optionalString(root.event_id),
    eventType: optionalString(root.event_type),
    title: optionalString(root.title),
    summary: optionalString(root.summary),
    occurredAt: optionalString(root.occurred_at),
    createdAt: optionalString(root.created_at),
    sourceName: optionalString(root.source_name),
    sourceUrl: optionalString(root.source_url),
  };
}

function parseAsset(raw: unknown): WatchlistAsset | null {
  const root = optionalRecord(raw);
  const symbol = optionalString(root?.symbol);
  if (!root || !symbol) return null;
  const thesis = optionalRecord(root.active_thesis);
  const nextAction = optionalRecord(root.next_action);
  const position = optionalRecord(root.position_snapshot);
  const report = optionalRecord(root.report_meta);
  const freshness = optionalRecord(root.report_freshness);
  const dataTimes = optionalRecord(root.data_times);
  return {
    workspaceId: optionalString(root.workspace_id),
    version: optionalNumber(root.version),
    symbol,
    name: optionalString(root.name),
    market: optionalString(root.market),
    relationType: optionalString(root.relation_type),
    relationLabel: optionalString(root.relation_label),
    priority: optionalString(root.priority),
    trackingStatus: optionalString(root.tracking_status),
    workflowStatus: optionalString(root.workflow_status),
    attentionTags: strings(root.attention_tags),
    activeThesis: thesis === null ? null : {
      summary: optionalString(thesis.summary),
      version: optionalNumber(thesis.version),
    },
    latestChange: parseChange(root.latest_change),
    nextAction: nextAction === null ? null : {
      title: optionalString(nextAction.title),
      nextStep: optionalString(nextAction.next_step),
      status: optionalString(nextAction.status),
    },
    // 0 表示已知没有任务；缺失表示合同未提供，不能伪装成 0。
    openTaskCount: optionalNumber(root.open_task_count),
    positionSnapshot: {
      available: optionalBoolean(position?.available),
      status: optionalString(position?.status),
    },
    reportMeta: report === null ? null : {
      id: optionalString(report.id),
      title: optionalString(report.title),
      summary: optionalString(report.summary),
      status: optionalString(report.status),
      generatedAt: optionalString(report.generated_at),
      marketTimestamp: optionalString(report.market_timestamp),
    },
    reportFreshness: {
      status: optionalString(freshness?.status),
      label: optionalString(freshness?.label),
      isToday: optionalBoolean(freshness?.is_today),
    },
    dataTimes: {
      quoteAsOf: optionalString(dataTimes?.quote_as_of),
      dailyAsOf: optionalString(dataTimes?.daily_as_of),
      financialReportPeriod: optionalString(dataTimes?.financial_report_period),
      reportGeneratedAt: optionalString(dataTimes?.report_generated_at),
    },
    quote: parseQuote(root.quote),
    dataStatus: optionalString(root.data_status),
    warnings: strings(root.warnings),
  };
}

export function parseWatchlistAssets(value: unknown): WatchlistAssets {
  const root = record(value);
  if (root.contract_version !== "stock_asset_list_v1") {
    throw new ContractError("contract_version 不是 stock_asset_list_v1");
  }
  const summary = optionalRecord(root.summary);
  return {
    status: optionalString(root.status) ?? "unavailable",
    items: list(root.items).flatMap((raw) => {
      const asset = parseAsset(raw);
      return asset ? [asset] : [];
    }),
    summary: {
      total: optionalNumber(summary?.total),
      watching: optionalNumber(summary?.watching),
      holding: optionalNumber(summary?.holding),
      ended: optionalNumber(summary?.ended),
      paused: optionalNumber(summary?.paused),
      waitingData: optionalNumber(summary?.waiting_data),
    },
    boundary: optionalString(root.boundary),
  };
}

// ---------- 关系（GET/PATCH /v1/stocks/{symbol}/relation） ----------

export type StockRelation = {
  contractVersion: string | null;
  symbol: string | null;
  version: number | null;
  relationType: string | null;
  priority: string | null;
  trackingStatus: string | null;
  workflowStatus: string | null;
  attentionTags: string[];
};

export function parseStockRelation(value: unknown): StockRelation {
  const root = record(value);
  return {
    contractVersion: optionalString(root.contract_version),
    symbol: optionalString(root.symbol),
    version: optionalNumber(root.version),
    relationType: optionalString(root.relation_type),
    priority: optionalString(root.priority),
    trackingStatus: optionalString(root.tracking_status),
    workflowStatus: optionalString(root.workflow_status),
    attentionTags: strings(root.attention_tags),
  };
}

export type RelationPatch = {
  baseVersion: number;
  relationType: "watching" | "holding" | "ended";
  priority: "high" | "normal" | "low" | null;
  trackingStatus: "active" | "paused";
  workflowStatus: "idle" | "researching" | "waiting_data";
  attentionTags: string[];
};

const RELATION_TYPES = new Set(["watching", "holding", "ended"]);
const TRACKING_STATUSES = new Set(["active", "paused"]);
const WORKFLOW_STATUSES = new Set(["idle", "researching", "waiting_data"]);

/**
 * 后端 PATCH 是全量替换语义（未传字段回落默认值），所以从行当前状态构造完整载荷，
 * 只改目标字段，避免误清空 tracking_status / workflow_status / attention_tags。
 */
export function buildRelationPatch(
  asset: Pick<WatchlistAsset, "version" | "relationType" | "priority" | "trackingStatus" | "workflowStatus" | "attentionTags">,
  change: Partial<Pick<RelationPatch, "relationType" | "priority" | "trackingStatus">>,
): RelationPatch {
  if (asset.version === null) throw new ContractError("关系版本缺失，无法安全写入");
  const relationType = change.relationType ?? asset.relationType ?? "watching";
  if (!RELATION_TYPES.has(relationType)) throw new ContractError(`关系状态不受支持：${relationType}`);
  // 与后端口径一致：非 watching 关系不携带优先级；watching 未设优先级时回 normal。
  const priority = relationType !== "watching"
    ? null
    : change.priority !== undefined
      ? change.priority
      : (asset.priority as RelationPatch["priority"]) ?? "normal";
  const trackingStatus = change.trackingStatus ?? asset.trackingStatus ?? "active";
  if (!TRACKING_STATUSES.has(trackingStatus)) throw new ContractError(`跟踪状态不受支持：${trackingStatus}`);
  const workflowStatus = asset.workflowStatus ?? "idle";
  if (!WORKFLOW_STATUSES.has(workflowStatus)) throw new ContractError(`研究流程状态不受支持：${workflowStatus}`);
  return {
    baseVersion: asset.version,
    relationType: relationType as RelationPatch["relationType"],
    priority,
    trackingStatus: trackingStatus as RelationPatch["trackingStatus"],
    workflowStatus: workflowStatus as RelationPatch["workflowStatus"],
    attentionTags: asset.attentionTags,
  };
}
