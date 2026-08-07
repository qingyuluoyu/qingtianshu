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

export type TodayTheme = {
  key: string;
  title: string;
  status: string;
  tone: string;
  summary: string;
  basis: string | null;
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
  marketDate: string | null;
  priorityCount: number;
  relatedChangeCount: number;
  priorityItems: PriorityItem[];
  priorityTotal: number;
  priorityEmptyMessage: string | null;
  rankingMethod: string;
  coverageStatus: string;
  themes: TodayTheme[];
  warnings: string[];
  boundary: string;
};

export type IndexCard = {
  symbol: string;
  name: string;
  status: string;
  latestClose: number | null;
  change1d: number | null;
  return1dPct: number | null;
  marketTimestamp: string | null;
  dailyMarketTimestamp: string | null;
  dataGranularity: "realtime_quote" | "daily_close" | "unknown";
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
  unchangedRatio: number | null;
  coverageRatio: number | null;
  turnoverStatus: string | null;
  turnover100mCny: number | null;
  historyStatus: string | null;
  turnoverChangeVsPreviousPct: number | null;
  medianPctChange: number | null;
  distributionBins: Array<{ key: string; label: string; count: number }> | null;
  limitUpCount: number | null;
  limitDownCount: number | null;
  limitMethod: string | null;
  turnoverHistory: Array<{ date: string; amount100mCny: number }>;
};

export type Sector = {
  code: string;
  name: string;
  pctChange: number | null;
  advancers: number | null;
  decliners: number | null;
  mainNetInflow100mCny: number | null;
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
  eventType: string | null;
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
    marketDate: optionalString(summary.market_date),
    priorityCount: requiredNumber(summary.priority_count, "summary.priority_count"),
    relatedChangeCount: requiredNumber(summary.related_change_count, "summary.related_change_count"),
    priorityItems: items,
    priorityTotal: requiredNumber(priorities.total_visible, "priority_items.total_visible"),
    priorityEmptyMessage: optionalString(priorities.empty_message),
    rankingMethod: requiredString(priorities.ranking_method, "priority_items.ranking_method"),
    coverageStatus: requiredString(coverage.status, "coverage.status"),
    // themes 为后端固定顺序的主题卡（市场情绪/业绩披露/概念热度/资金流向），字段直通。
    themes: list(root.themes).flatMap((raw) => {
      const item = optionalRecord(raw);
      const key = optionalString(item?.key);
      const title = optionalString(item?.title);
      const summary = optionalString(item?.summary);
      if (!item || !key || !title || !summary) return [];
      return [{
        key,
        title,
        status: optionalString(item.status) ?? "unknown",
        tone: optionalString(item.tone) ?? "unknown",
        summary,
        basis: optionalString(item.basis),
      }];
    }),
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
        // change_1d 与 return_1d_pct 均为后端已计算好的点位/百分数，直通不缩放。
        change1d: optionalNumber(metrics?.change_1d),
        return1dPct: optionalNumber(metrics?.return_1d_pct),
        marketTimestamp: optionalString(item?.market_timestamp),
        dailyMarketTimestamp: optionalString(item?.daily_market_timestamp),
        dataGranularity: optionalString(item?.data_granularity) === "realtime_quote"
          ? "realtime_quote"
          : optionalString(item?.data_granularity) === "daily_close"
            ? "daily_close"
            : "unknown",
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
  const bins7 = optionalRecord(distribution?.bins_7);
  const bins = optionalRecord(distribution?.bins);
  // 优先设计稿 7 桶口径（bins_7）；旧缓存快照没有 bins_7 时回退 5 桶。
  const binSpec7 = [
    ["le_neg7", "≤-7%"],
    ["gt_neg7_le_neg3", "-7~-3%"],
    ["gt_neg3_lt_0", "-3~0%"],
    ["unchanged", "平盘"],
    ["gt_0_lt_3", "0~3%"],
    ["ge_3_lt_7", "3~7%"],
    ["ge_7", "≥7%"],
  ] as const;
  const binSpec5 = [
    ["strong_decliners_le_neg3", "≤-3%"],
    ["mild_decliners_lt_0_gt_neg3", "-3~0%"],
    ["unchanged", "平盘"],
    ["mild_advancers_gt_0_lt_3", "0~3%"],
    ["strong_advancers_ge_3", "≥3%"],
  ] as const;
  const activeBins = bins7 ?? bins;
  const activeSpec = bins7 !== null ? binSpec7 : binSpec5;
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
    unchangedRatio: optionalNumber(breadth?.unchanged_ratio),
    coverageRatio: optionalNumber(coverage?.coverage_ratio),
    turnoverStatus: optionalString(turnover?.status),
    turnover100mCny: optionalNumber(turnover?.total_amount_100m_cny),
    historyStatus: optionalString(history?.status),
    // change_vs_previous_pct 后端已是百分数，直通不缩放。
    turnoverChangeVsPreviousPct: optionalNumber(history?.change_vs_previous_pct),
    medianPctChange: optionalNumber(distribution?.median_pct_change),
    distributionBins: activeBins === null
      ? null
      : activeSpec.flatMap(([key, label]) => {
          const count = optionalNumber(activeBins[key]);
          return count === null ? [] : [{ key, label, count }];
        }),
    limitUpCount: optionalNumber(breadth?.limit_up_count),
    limitDownCount: optionalNumber(breadth?.limit_down_count),
    limitMethod: optionalString(breadth?.limit_method),
    turnoverHistory: list(root.turnover_history).flatMap((raw) => {
      const item = optionalRecord(raw);
      const date = optionalString(item?.date);
      const amount = optionalNumber(item?.amount_100m_cny);
      // amount_100m_cny 后端已换算为亿元，直通。
      return item && date && amount !== null ? [{ date, amount100mCny: amount }] : [];
    }),
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
      // 东财 f62 原始单位为元，此处换算为亿元；新浪降级源为 null。
      const inflowCny = optionalNumber(item.main_net_inflow);
      return [{
        code,
        name,
        pctChange: optionalNumber(item.pct_change),
        advancers: optionalNumber(item.advancers),
        decliners: optionalNumber(item.decliners),
        mainNetInflow100mCny: inflowCny === null ? null : inflowCny / 1e8,
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
        eventType: optionalString(item.event_type),
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

export type IndexHistory = {
  closes: number[];
  marketTimestamp: string | null;
};

export function parseIndexHistory(value: unknown): IndexHistory {
  const root = record(value);
  const closes = list(root.points).flatMap((raw) => {
    const point = optionalRecord(raw);
    const close = optionalNumber(point?.close);
    return close === null ? [] : [close];
  });
  return { closes, marketTimestamp: optionalString(root.market_timestamp) };
}

export type LatestResearchReport = {
  symbol: string | null;
  name: string | null;
  title: string;
  institution: string | null;
  researchers: string | null;
  publishedAt: string | null;
  rating: string | null;
  forecastEps: number | null;
  reportUrl: string | null;
  summary: string | null;
};

export type LatestResearchReports = { status: string; items: LatestResearchReport[] };

export function parseLatestResearchReports(value: unknown): LatestResearchReports {
  const root = record(value);
  return {
    status: optionalString(root.status) ?? "empty",
    items: list(root.items).flatMap((raw) => {
      const item = optionalRecord(raw);
      const title = optionalString(item?.title);
      if (!item || !title) return [];
      return [{
        symbol: optionalString(item.symbol),
        name: optionalString(item.name),
        title,
        institution: optionalString(item.institution),
        researchers: optionalString(item.researchers),
        publishedAt: optionalString(item.published_at),
        rating: optionalString(item.rating),
        // forecast_eps 单位元/股，直通不缩放。
        forecastEps: optionalNumber(item.forecast_eps),
        reportUrl: optionalString(item.report_url),
        summary: optionalString(item.summary),
      }];
    }),
  };
}

export type GlobalIndex = {
  symbol: string;
  name: string;
  status: string;
  latestClose: number | null;
  change1d: number | null;
  return1dPct: number | null;
  marketTimestamp: string | null;
  isStale: boolean | null;
};

export type GlobalIndices = { items: GlobalIndex[] };

export function parseGlobalIndices(value: unknown): GlobalIndices {
  const root = record(value);
  return {
    items: list(root.indices).flatMap((raw) => {
      const item = optionalRecord(raw);
      const symbol = optionalString(item?.symbol);
      const name = optionalString(item?.name);
      if (!item || !symbol || !name) return [];
      const metrics = optionalRecord(item.metrics);
      return [{
        symbol,
        name,
        status: optionalString(item.status) ?? "unavailable",
        latestClose: optionalNumber(metrics?.latest_close),
        change1d: optionalNumber(metrics?.change_1d),
        // return_1d_pct 后端已是百分数，直通不缩放。
        return1dPct: optionalNumber(metrics?.return_1d_pct),
        marketTimestamp: optionalString(item.market_timestamp),
        isStale: optionalBoolean(item.is_stale),
      }];
    }),
  };
}

export type LiveMarket = {
  key: string;
  name: string;
  status: string;
  latestPrice: number | null;
  pctChange: number | null;
  currency: string | null;
  marketTimestamp: string | null;
  isStale: boolean | null;
};

export type LiveMarkets = { items: LiveMarket[] };

export function parseLiveMarkets(value: unknown): LiveMarkets {
  const root = record(value);
  return {
    items: list(root.markets).flatMap((raw) => {
      const item = optionalRecord(raw);
      const key = optionalString(item?.key);
      const name = optionalString(item?.name);
      if (!item || !key || !name) return [];
      return [{
        key,
        name,
        status: optionalString(item.status) ?? "unavailable",
        latestPrice: optionalNumber(item.latest_price),
        // pct_change 后端已是百分数，直通不缩放。
        pctChange: optionalNumber(item.pct_change),
        currency: optionalString(item.currency),
        marketTimestamp: optionalString(item.market_timestamp),
        isStale: optionalBoolean(item.is_stale),
      }];
    }),
  };
}

export type MarketAnomaly = {
  symbol: string;
  name: string | null;
  kind: string;
  pctChange: number | null;
  amount100mCny: number | null;
  tickTime: string | null;
};

export type MarketAnomalies = {
  status: string;
  marketTimestamp: string | null;
  items: MarketAnomaly[];
};

export function parseMarketAnomalies(value: unknown): MarketAnomalies {
  const root = record(value);
  return {
    status: optionalString(root.status) ?? "unavailable",
    marketTimestamp: optionalString(root.market_timestamp),
    items: list(root.items).flatMap((raw) => {
      const item = optionalRecord(raw);
      const symbol = optionalString(item?.symbol);
      if (!item || !symbol) return [];
      return [{
        symbol,
        name: optionalString(item.name),
        kind: optionalString(item.kind) ?? "异动",
        // pct_change 为百分数直通；amount_100m_cny 后端已换算为亿元。
        pctChange: optionalNumber(item.pct_change),
        amount100mCny: optionalNumber(item.amount_100m_cny),
        tickTime: optionalString(item.tick_time),
      }];
    }),
  };
}

export type CapitalFlowPoint = { time: string; value100mCny: number };

export type CapitalFlow = {
  status: string;
  marketTimestamp: string | null;
  isStale: boolean | null;
  mainNetInflow100mCny: number | null;
  unit: string | null;
  points: CapitalFlowPoint[];
  method: string | null;
  warnings: string[];
};

export function parseCapitalFlow(value: unknown): CapitalFlow {
  const root = record(value);
  const summary = optionalRecord(root.summary);
  return {
    status: optionalString(root.status) ?? "unavailable",
    marketTimestamp: optionalString(root.market_timestamp),
    isStale: optionalBoolean(root.is_stale),
    // main_net_inflow_100m_cny 后端已换算为亿元，直通不缩放。
    mainNetInflow100mCny: optionalNumber(summary?.main_net_inflow_100m_cny),
    unit: optionalString(summary?.unit),
    points: list(root.points).flatMap((raw) => {
      const point = optionalRecord(raw);
      const time = optionalString(point?.time);
      const amount = optionalNumber(point?.main_net_inflow_100m_cny);
      return point && time && amount !== null ? [{ time, value100mCny: amount }] : [];
    }),
    method: optionalString(root.method),
    warnings: strings(root.warnings),
  };
}

export type PositionItem = {
  workspaceId: string | null;
  symbol: string;
  name: string | null;
  status: string | null;
  quantity: number | null;
  costBasis: number | null;
  averageCost: number | null;
};

export type Positions = { status: string; items: PositionItem[] };

export function parsePositions(value: unknown): Positions {
  const root = record(value);
  if (root.contract_version !== "position_ledger_v1") {
    throw new ContractError("contract_version 不是 position_ledger_v1");
  }
  return {
    status: optionalString(root.status) ?? "unavailable",
    items: list(root.items).flatMap((raw) => {
      const item = optionalRecord(raw);
      const symbol = optionalString(item?.symbol);
      if (!item || !symbol) return [];
      const current = optionalRecord(item.current);
      // quantity/cost_basis/average_cost 均为账本原值，直通；账本不含行情市值字段。
      return [{
        workspaceId: optionalString(item.workspace_id),
        symbol,
        name: optionalString(item.name),
        status: optionalString(item.status),
        quantity: optionalNumber(current?.quantity),
        costBasis: optionalNumber(current?.cost_basis),
        averageCost: optionalNumber(current?.average_cost),
      }];
    }),
  };
}
