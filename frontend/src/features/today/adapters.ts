export type JsonRecord = Record<string, unknown>;

export class ContractError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ContractError";
  }
}

export type PriorityItem = {
  id: string;
  kind: string;
  title: string;
  detail: string | null;
  symbol: string | null;
  statusLabel: string | null;
  rankReason: string | null;
  updatedAt: string | null;
};

export type Overview = {
  generatedAt: string;
  session: {
    key: string;
    label: string;
    exchangeStatus: string;
    exchangeLabel: string;
    marketLocalTime: string;
  };
  headline: string;
  marketDate: string;
  priorityCount: number;
  relatedChangeCount: number;
  priorityItems: PriorityItem[];
  priorityTotal: number;
  priorityEmptyMessage: string;
  rankingMethod: string;
  coverageStatus: string;
  warnings: string[];
  boundary: string;
};

export type IndexCard = {
  symbol: string;
  name: string;
  status: string;
  latestClose: number | null;
  return1dPct: number | null;
  marketTimestamp: string | null;
  isStale: boolean | null;
};

export type Indices = { generatedAt: string | null; items: IndexCard[]; warnings: string[] };

export type Breadth = {
  status: string;
  marketDate: string | null;
  marketTimestamp: string | null;
  isStale: boolean | null;
  state: string | null;
  total: number | null;
  advancers: number | null;
  decliners: number | null;
  unchanged: number | null;
  advanceRatio: number | null;
  declineRatio: number | null;
  coverageRatio: number | null;
  turnoverStatus: string | null;
  turnover100mCny: number | null;
  historyStatus: string | null;
  medianPctChange: number | null;
};

export type Sector = {
  code: string;
  name: string;
  pctChange: number | null;
  advancers: number | null;
  decliners: number | null;
};

export type Sectors = {
  source: string | null;
  marketTimestamp: string | null;
  fetchedAt: string | null;
  isStale: boolean | null;
  items: Sector[];
  hasWarnings: boolean;
};

export type WatchlistBrief = {
  generatedAt: string;
  requested: number;
  available: number;
  items: Array<{ symbol: string; name: string | null }>;
};

export type ResearchAction = {
  id: string;
  symbol: string;
  name: string | null;
  title: string;
  status: string | null;
  statusLabel: string | null;
  nextStep: string | null;
};

export type ResearchActions = {
  generatedAt: string;
  items: ResearchAction[];
  empty: boolean;
  boundary: string;
};

export type ResearchChange = {
  id: string;
  symbol: string | null;
  summary: string;
  severity: string | null;
  dataAsOf: string | null;
};

export type ResearchChanges = {
  generatedAt: string;
  items: ResearchChange[];
  requested: number;
  withChangeArchive: number;
  boundary: string;
};

export type DataHealth = {
  status: string;
  userLabel: string;
  createdAt: string;
  summary: { total: number; healthy: number; attention: number; critical: number };
  categories: Array<{ key: string; label: string; status: string; count: number }>;
  actionableChecks: Array<{ key: string; category: string; status: string; label: string }>;
};

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

function requiredNumber(value: unknown, field: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) throw new ContractError(`${field} 缺失`);
  return value;
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

export function parseOverview(value: unknown): Overview {
  const root = record(value);
  if (root.contract_version !== "today_overview_v1") {
    throw new ContractError("contract_version 不是 today_overview_v1");
  }
  const session = record(root.session, "session");
  const summary = record(root.summary, "summary");
  const priorities = record(root.priority_items, "priority_items");
  const coverage = record(root.coverage, "coverage");
  const items = list(priorities.items).slice(0, 5).map((raw, index) => {
    const item = record(raw, `priority_items.items[${index}]`);
    return {
      id: requiredString(item.id, `priority_items.items[${index}].id`),
      kind: requiredString(item.kind, `priority_items.items[${index}].kind`),
      title: requiredString(item.title, `priority_items.items[${index}].title`),
      detail: optionalString(item.detail),
      symbol: optionalString(item.symbol),
      statusLabel: optionalString(item.status_label),
      rankReason: optionalString(item.rank_reason),
      updatedAt: optionalString(item.updated_at) ?? optionalString(item.due_at),
    };
  });
  return {
    generatedAt: requiredString(root.generated_at, "generated_at"),
    session: {
      key: requiredString(session.key, "session.key"),
      label: requiredString(session.label, "session.label"),
      exchangeStatus: requiredString(session.exchange_status, "session.exchange_status"),
      exchangeLabel: requiredString(session.exchange_label, "session.exchange_label"),
      marketLocalTime: requiredString(session.market_local_time, "session.market_local_time"),
    },
    headline: requiredString(summary.headline, "summary.headline"),
    marketDate: requiredString(summary.market_date, "summary.market_date"),
    priorityCount: requiredNumber(summary.priority_count, "summary.priority_count"),
    relatedChangeCount: requiredNumber(summary.related_change_count, "summary.related_change_count"),
    priorityItems: items,
    priorityTotal: requiredNumber(priorities.total_visible, "priority_items.total_visible"),
    priorityEmptyMessage: requiredString(priorities.empty_message, "priority_items.empty_message"),
    rankingMethod: requiredString(priorities.ranking_method, "priority_items.ranking_method"),
    coverageStatus: requiredString(coverage.status, "coverage.status"),
    warnings: strings(root.warnings),
    boundary: requiredString(root.boundary, "boundary"),
  };
}

const INDEX_ORDER = ["000001.SS", "399001.SZ", "399006.SZ", "000300.SS", "000688.SS"] as const;
const INDEX_NAMES: Record<(typeof INDEX_ORDER)[number], string> = {
  "000001.SS": "上证综指",
  "399001.SZ": "深证成指",
  "399006.SZ": "创业板指",
  "000688.SS": "科创50",
  "000300.SS": "沪深300",
};

export function parseIndices(value: unknown): Indices {
  const root = record(value);
  const bySymbol = new Map<string, JsonRecord>();
  for (const raw of list(root.indices)) {
    const item = optionalRecord(raw);
    const symbol = optionalString(item?.symbol);
    if (item && symbol) bySymbol.set(symbol, item);
  }
  return {
    generatedAt: optionalString(root.generated_at),
    warnings: strings(root.warnings),
    items: INDEX_ORDER.map((symbol) => {
      const item = bySymbol.get(symbol);
      const metrics = optionalRecord(item?.metrics);
      return {
        symbol,
        name: optionalString(item?.name) ?? INDEX_NAMES[symbol],
        status: optionalString(item?.status) ?? "unavailable",
        latestClose: optionalNumber(metrics?.latest_close),
        return1dPct: optionalNumber(metrics?.return_1d_pct),
        marketTimestamp: optionalString(item?.market_timestamp),
        isStale: optionalBoolean(item?.is_stale),
      };
    }),
  };
}

export function parseBreadth(value: unknown): Breadth {
  const root = record(value);
  const breadth = optionalRecord(root.breadth);
  const coverage = optionalRecord(root.coverage);
  const turnover = optionalRecord(root.turnover);
  const history = optionalRecord(turnover?.history_comparison);
  const distribution = optionalRecord(root.distribution);
  return {
    status: optionalString(root.status) ?? "unavailable",
    marketDate: optionalString(root.market_date),
    marketTimestamp: optionalString(root.market_timestamp),
    isStale: optionalBoolean(root.is_stale),
    state: optionalString(breadth?.state),
    total: optionalNumber(breadth?.total),
    advancers: optionalNumber(breadth?.advancers),
    decliners: optionalNumber(breadth?.decliners),
    unchanged: optionalNumber(breadth?.unchanged),
    advanceRatio: optionalNumber(breadth?.advance_ratio),
    declineRatio: optionalNumber(breadth?.decline_ratio),
    coverageRatio: optionalNumber(coverage?.coverage_ratio),
    turnoverStatus: optionalString(turnover?.status),
    turnover100mCny: optionalNumber(turnover?.total_amount_100m_cny),
    historyStatus: optionalString(history?.status),
    medianPctChange: optionalNumber(distribution?.median_pct_change),
  };
}

export function parseSectors(value: unknown): Sectors {
  const root = record(value);
  return {
    source: optionalString(root.source),
    marketTimestamp: optionalString(root.market_timestamp),
    fetchedAt: optionalString(root.fetched_at),
    isStale: optionalBoolean(root.is_stale),
    hasWarnings: strings(root.warnings).length > 0,
    items: list(root.sectors).slice(0, 10).flatMap((raw) => {
      const item = optionalRecord(raw);
      const code = optionalString(item?.code);
      const name = optionalString(item?.name);
      if (!item || !code || !name) return [];
      return [{
        code,
        name,
        pctChange: optionalNumber(item.pct_change),
        advancers: optionalNumber(item.advancers),
        decliners: optionalNumber(item.decliners),
      }];
    }),
  };
}

export function parseWatchlistBrief(value: unknown): WatchlistBrief {
  const root = record(value);
  const coverage = record(root.coverage, "coverage");
  return {
    generatedAt: requiredString(root.generated_at, "generated_at"),
    requested: requiredNumber(coverage.requested, "coverage.requested"),
    available: requiredNumber(coverage.available, "coverage.available"),
    items: list(root.items).flatMap((raw) => {
      const item = optionalRecord(raw);
      const symbol = optionalString(item?.symbol);
      return item && symbol ? [{ symbol, name: optionalString(item.name) }] : [];
    }),
  };
}

export function parseResearchActions(value: unknown): ResearchActions {
  const root = record(value);
  const result: ResearchAction[] = [];
  for (const rawStock of list(root.items)) {
    const stock = optionalRecord(rawStock);
    const symbol = optionalString(stock?.symbol);
    if (!stock || !symbol) continue;
    for (const rawAction of list(stock.actions)) {
      const action = optionalRecord(rawAction);
      const id = optionalString(action?.id);
      const title = optionalString(action?.title);
      if (!action || !id || !title) continue;
      result.push({
        id,
        symbol,
        name: optionalString(stock.name),
        title,
        status: optionalString(action.status),
        statusLabel: optionalString(stock.research_status_label),
        nextStep: optionalString(action.next_step),
      });
    }
  }
  return {
    generatedAt: requiredString(root.generated_at, "generated_at"),
    items: result,
    empty: result.length === 0,
    boundary: requiredString(root.boundary, "boundary"),
  };
}

export function parseResearchChanges(value: unknown): ResearchChanges {
  const root = record(value);
  const coverage = record(root.coverage, "coverage");
  const sourceItems = list(root.events).length > 0 ? list(root.events) : list(root.items);
  return {
    generatedAt: requiredString(root.generated_at, "generated_at"),
    requested: requiredNumber(coverage.requested, "coverage.requested"),
    withChangeArchive: requiredNumber(coverage.with_change_archive, "coverage.with_change_archive"),
    boundary: requiredString(root.boundary, "boundary"),
    items: sourceItems.flatMap((raw, index) => {
      const item = optionalRecord(raw);
      const summary = optionalString(item?.summary)
        ?? optionalString(item?.headline)
        ?? optionalString(item?.title);
      if (!item || !summary) return [];
      return [{
        id: optionalString(item.id) ?? `${optionalString(item.symbol) ?? "change"}-${index}`,
        symbol: optionalString(item.symbol),
        summary,
        severity: optionalString(item.severity),
        dataAsOf: optionalString(item.data_as_of) ?? optionalString(item.created_at),
      }];
    }),
  };
}

export function parseDataHealth(value: unknown): DataHealth {
  const root = record(value);
  const summary = record(root.summary, "summary");
  const actionableChecks = list(root.checks).flatMap((raw) => {
    const item = optionalRecord(raw);
    const status = optionalString(item?.status);
    const key = optionalString(item?.key);
    const label = optionalString(item?.label);
    if (!item || !key || !label || (status !== "critical" && status !== "attention")) return [];
    return [{ key, category: optionalString(item.category) ?? "unknown", status, label }];
  });
  const categoryLabels: Record<string, string> = {
    market: "行情",
    fundamentals: "财务",
    information: "公告与信息",
    reports: "研报",
    background: "后台同步",
  };
  const categoryMap = new Map<string, { key: string; label: string; status: string; count: number }>();
  const statusWeight: Record<string, number> = { healthy: 0, ready: 0, attention: 1, waiting: 1, degraded: 1, critical: 2, unavailable: 2 };
  for (const raw of list(root.checks)) {
    const item = optionalRecord(raw);
    const key = optionalString(item?.category);
    const status = optionalString(item?.status);
    if (!key || !status) continue;
    const current = categoryMap.get(key);
    categoryMap.set(key, {
      key,
      label: categoryLabels[key] ?? key,
      status: !current || (statusWeight[status] ?? 1) > (statusWeight[current.status] ?? 1) ? status : current.status,
      count: (current?.count ?? 0) + 1,
    });
  }
  actionableChecks.sort((a, b) => (a.status === "critical" ? -1 : 1) - (b.status === "critical" ? -1 : 1));
  return {
    status: requiredString(root.status, "status"),
    userLabel: requiredString(root.user_label, "user_label"),
    createdAt: requiredString(root.created_at, "created_at"),
    summary: {
      total: requiredNumber(summary.total, "summary.total"),
      healthy: requiredNumber(summary.healthy, "summary.healthy"),
      attention: requiredNumber(summary.attention, "summary.attention"),
      critical: requiredNumber(summary.critical, "summary.critical"),
    },
    categories: [...categoryMap.values()],
    actionableChecks: actionableChecks.slice(0, 5),
  };
}
