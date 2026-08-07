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

// ---------- K 线 / 行情 ----------

export type CandlePoint = {
  timestamp: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  adjustedClose: number | null;
  volume: number | null;
};

export type HistoryMetrics = {
  latestClose: number | null;
  change1d: number | null;
  return1dPct: number | null;
  return5dPct: number | null;
  return20dPct: number | null;
  return60dPct: number | null;
  return1dBaseDate: string | null;
  return1dEndDate: string | null;
  return5dBaseDate: string | null;
  return5dEndDate: string | null;
  return20dBaseDate: string | null;
  return20dEndDate: string | null;
  return60dBaseDate: string | null;
  return60dEndDate: string | null;
  ma20: number | null;
  ma60: number | null;
  rsi14: number | null;
  macd1226: number | null;
  macdSignal9: number | null;
  macdHistogram: number | null;
  bollingerUpper20: number | null;
  bollingerMiddle20: number | null;
  bollingerLower20: number | null;
  bollingerPosition20: number | null;
  atr14Pct: number | null;
  volumeRatio5to20: number | null;
  maxDrawdown60dPct: number | null;
  volatility20dAnnualizedPct: number | null;
  trendState: string | null;
  technicalState: string | null;
  technicalMethod: string | null;
};

export type StockHistory = {
  symbol: string | null;
  displayName: string | null;
  exchange: string | null;
  currency: string | null;
  timezone: string | null;
  source: string | null;
  sourceUrl: string | null;
  dataGranularity: string | null;
  regularMarketPrice: number | null;
  previousClose: number | null;
  regularMarketTimestamp: string | null;
  marketTimestamp: string | null;
  fetchedAt: string | null;
  isStale: boolean | null;
  cacheHit: boolean | null;
  points: CandlePoint[];
  metrics: HistoryMetrics;
  coverage: {
    requestedRange: string | null;
    points: number | null;
    firstTimestamp: string | null;
    lastTimestamp: string | null;
    interval: string | null;
    droppedInvalidOhlc: number | null;
    droppedIncompleteDaily: number | null;
  };
  warnings: string[];
};

export function parseStockHistory(value: unknown): StockHistory {
  const root = record(value);
  const metrics = optionalRecord(root.metrics);
  const coverage = optionalRecord(root.coverage);
  return {
    symbol: optionalString(root.symbol),
    displayName: optionalString(root.display_name),
    exchange: optionalString(root.exchange),
    currency: optionalString(root.currency),
    timezone: optionalString(root.timezone),
    source: optionalString(root.source),
    sourceUrl: optionalString(root.source_url),
    dataGranularity: optionalString(root.data_granularity),
    regularMarketPrice: optionalNumber(root.regular_market_price),
    previousClose: optionalNumber(root.previous_close),
    regularMarketTimestamp: optionalString(root.regular_market_timestamp),
    marketTimestamp: optionalString(root.market_timestamp),
    fetchedAt: optionalString(root.fetched_at),
    isStale: optionalBoolean(root.is_stale),
    cacheHit: optionalBoolean(root.cache_hit),
    points: list(root.points).flatMap((raw) => {
      const point = optionalRecord(raw);
      const timestamp = optionalString(point?.timestamp);
      if (!point || !timestamp) return [];
      return [{
        timestamp,
        open: optionalNumber(point.open),
        high: optionalNumber(point.high),
        low: optionalNumber(point.low),
        close: optionalNumber(point.close),
        adjustedClose: optionalNumber(point.adjusted_close),
        volume: optionalNumber(point.volume),
      }];
    }),
    metrics: {
      // 所有价格/均线/布林带为价格原值；*_pct 后端已是百分数；return_*_pct 直通不缩放。
      latestClose: optionalNumber(metrics?.latest_close),
      change1d: optionalNumber(metrics?.change_1d),
      return1dPct: optionalNumber(metrics?.return_1d_pct),
      return5dPct: optionalNumber(metrics?.return_5d_pct),
      return20dPct: optionalNumber(metrics?.return_20d_pct),
      return60dPct: optionalNumber(metrics?.return_60d_pct),
      return1dBaseDate: optionalString(metrics?.return_1d_base_date),
      return1dEndDate: optionalString(metrics?.return_1d_end_date),
      return5dBaseDate: optionalString(metrics?.return_5d_base_date),
      return5dEndDate: optionalString(metrics?.return_5d_end_date),
      return20dBaseDate: optionalString(metrics?.return_20d_base_date),
      return20dEndDate: optionalString(metrics?.return_20d_end_date),
      return60dBaseDate: optionalString(metrics?.return_60d_base_date),
      return60dEndDate: optionalString(metrics?.return_60d_end_date),
      ma20: optionalNumber(metrics?.ma20),
      ma60: optionalNumber(metrics?.ma60),
      rsi14: optionalNumber(metrics?.rsi_14),
      macd1226: optionalNumber(metrics?.macd_12_26),
      macdSignal9: optionalNumber(metrics?.macd_signal_9),
      macdHistogram: optionalNumber(metrics?.macd_histogram),
      bollingerUpper20: optionalNumber(metrics?.bollinger_upper_20),
      bollingerMiddle20: optionalNumber(metrics?.bollinger_middle_20),
      bollingerLower20: optionalNumber(metrics?.bollinger_lower_20),
      bollingerPosition20: optionalNumber(metrics?.bollinger_position_20),
      // atr_14_pct 为百分数；volume_ratio_5_20 为 0-N 量比小数，均直通不缩放。
      atr14Pct: optionalNumber(metrics?.atr_14_pct),
      volumeRatio5to20: optionalNumber(metrics?.volume_ratio_5_20),
      maxDrawdown60dPct: optionalNumber(metrics?.max_drawdown_60d_pct),
      volatility20dAnnualizedPct: optionalNumber(metrics?.volatility_20d_annualized_pct),
      trendState: optionalString(metrics?.trend_state),
      technicalState: optionalString(metrics?.technical_state),
      technicalMethod: optionalString(metrics?.technical_method),
    },
    coverage: {
      requestedRange: optionalString(coverage?.requested_range),
      points: optionalNumber(coverage?.points),
      firstTimestamp: optionalString(coverage?.first_timestamp),
      lastTimestamp: optionalString(coverage?.last_timestamp),
      interval: optionalString(coverage?.interval),
      droppedInvalidOhlc: optionalNumber(coverage?.dropped_invalid_ohlc),
      droppedIncompleteDaily: optionalNumber(coverage?.dropped_incomplete_daily),
    },
    warnings: strings(root.warnings),
  };
}

// ---------- 基本面 / 估值 ----------

export type Valuation = {
  price: number | null;
  previousClose: number | null;
  pctChange: number | null;
  peTtm: number | null;
  peDynamic: number | null;
  peStatic: number | null;
  pb: number | null;
  totalMarketCap: number | null;
  floatMarketCap: number | null;
  turnoverRatePct: number | null;
  marketDate: string | null;
  marketTimestamp: string | null;
  quoteLabel: string | null;
  sessionLabel: string | null;
  source: string | null;
  currency: string | null;
  fetchedAt: string | null;
  warnings: string[];
};

export type FinancialPeriod = {
  reportDate: string | null;
  reportDateName: string | null;
  reportType: string | null;
  noticeDate: string | null;
  revenue: number | null;
  parentNetProfit: number | null;
  revenueYoyPct: number | null;
  netProfitYoyPct: number | null;
  grossMarginPct: number | null;
  netMarginPct: number | null;
  roeWeightedPct: number | null;
  debtAssetRatioPct: number | null;
  epsBasic: number | null;
  bookValuePerShare: number | null;
  operatingCashflow: number | null;
  operatingCashflowPerShare: number | null;
  totalAssets: number | null;
  totalEquity: number | null;
  periodBasis: string | null;
  source: string | null;
  currency: string | null;
};

export type Fundamentals = {
  valuation: Valuation | null;
  periods: FinancialPeriod[];
  warnings: string[];
  methodology: string[];
  generatedAt: string | null;
};

function parseValuation(value: unknown): Valuation | null {
  const root = optionalRecord(value);
  if (!root) return null;
  return {
    price: optionalNumber(root.price),
    previousClose: optionalNumber(root.previous_close),
    // pct_change 为百分数直通。
    pctChange: optionalNumber(root.pct_change),
    peTtm: optionalNumber(root.pe_ttm),
    peDynamic: optionalNumber(root.pe_dynamic),
    peStatic: optionalNumber(root.pe_static),
    pb: optionalNumber(root.pb),
    // total_market_cap / float_market_cap 单位为元（CNY），直通不缩放；展示层再标注换算。
    totalMarketCap: optionalNumber(root.total_market_cap),
    floatMarketCap: optionalNumber(root.float_market_cap),
    turnoverRatePct: optionalNumber(root.turnover_rate_pct),
    marketDate: optionalString(root.market_date),
    marketTimestamp: optionalString(root.market_timestamp),
    quoteLabel: optionalString(root.quote_label),
    sessionLabel: optionalString(root.current_session_label) ?? optionalString(root.quote_session_label),
    source: optionalString(root.source),
    currency: optionalString(root.currency),
    fetchedAt: optionalString(root.fetched_at),
    warnings: strings(root.warnings),
  };
}

function parseFinancialPeriod(raw: unknown): FinancialPeriod | null {
  const root = optionalRecord(raw);
  if (!root) return null;
  return {
    reportDate: optionalString(root.report_date),
    reportDateName: optionalString(root.report_date_name),
    reportType: optionalString(root.report_type),
    noticeDate: optionalString(root.notice_date),
    // revenue/profit/cashflow/assets/equity 单位为元（CNY），直通不缩放。
    revenue: optionalNumber(root.revenue),
    parentNetProfit: optionalNumber(root.parent_net_profit),
    // *_yoy_pct 与 margin/ratio/roe pct 均为百分数，直通不缩放。
    revenueYoyPct: optionalNumber(root.revenue_yoy_pct),
    netProfitYoyPct: optionalNumber(root.net_profit_yoy_pct),
    grossMarginPct: optionalNumber(root.gross_margin_pct),
    netMarginPct: optionalNumber(root.net_margin_pct),
    roeWeightedPct: optionalNumber(root.roe_weighted_pct),
    debtAssetRatioPct: optionalNumber(root.debt_asset_ratio_pct),
    epsBasic: optionalNumber(root.eps_basic),
    bookValuePerShare: optionalNumber(root.book_value_per_share),
    operatingCashflow: optionalNumber(root.operating_cashflow),
    operatingCashflowPerShare: optionalNumber(root.operating_cashflow_per_share),
    totalAssets: optionalNumber(root.total_assets),
    totalEquity: optionalNumber(root.total_equity),
    periodBasis: optionalString(root.period_basis),
    source: optionalString(root.source),
    currency: optionalString(root.currency),
  };
}

export function parseFundamentals(value: unknown): Fundamentals {
  const root = record(value);
  return {
    valuation: parseValuation(root.valuation),
    periods: list(root.financial_periods).flatMap((raw) => {
      const period = parseFinancialPeriod(raw);
      return period ? [period] : [];
    }),
    warnings: strings(root.warnings),
    methodology: strings(root.methodology),
    generatedAt: optionalString(root.generated_at),
  };
}

// ---------- 盈利质量 ----------

export type EarningsFactor = {
  key: string;
  label: string | null;
  status: string | null;
  valuePct: number | null;
  comparablePct: number | null;
  changePp: number | null;
  interpretation: string | null;
};

export type EarningsQuality = {
  status: string | null;
  overallLabel: string | null;
  summary: string | null;
  confidence: string | null;
  factors: EarningsFactor[];
  contradictions: string[];
  reviewPoints: string[];
  latestReportDateName: string | null;
  latestReportDate: string | null;
  comparableReportDateName: string | null;
  coveragePeriods: number | null;
  coverageComparable: boolean | null;
  boundary: string | null;
  generatedAt: string | null;
};

export function parseEarningsQuality(value: unknown): EarningsQuality {
  const root = record(value);
  const latest = optionalRecord(root.latest_report);
  const comparable = optionalRecord(root.comparable_report);
  const coverage = optionalRecord(root.coverage);
  return {
    status: optionalString(root.status),
    overallLabel: optionalString(root.overall_label),
    summary: optionalString(root.summary),
    confidence: optionalString(root.confidence),
    factors: list(root.factors).flatMap((raw) => {
      const item = optionalRecord(raw);
      const key = optionalString(item?.key);
      if (!item || !key) return [];
      // value_pct / comparable_pct 为百分数，change_pp 为百分点，均直通不缩放。
      return [{
        key,
        label: optionalString(item.label),
        status: optionalString(item.status),
        valuePct: optionalNumber(item.value_pct),
        comparablePct: optionalNumber(item.comparable_pct),
        changePp: optionalNumber(item.change_pp),
        interpretation: optionalString(item.interpretation),
      }];
    }),
    contradictions: strings(root.contradictions),
    reviewPoints: strings(root.review_points),
    latestReportDateName: optionalString(latest?.report_date_name),
    latestReportDate: optionalString(latest?.report_date),
    comparableReportDateName: optionalString(comparable?.report_date_name),
    coveragePeriods: optionalNumber(coverage?.periods),
    coverageComparable: optionalBoolean(coverage?.comparable),
    boundary: optionalString(root.boundary),
    generatedAt: optionalString(root.generated_at),
  };
}

// ---------- 利润与现金流驱动 ----------

export type DriverItem = {
  key: string;
  label: string | null;
  statement: string | null;
  amount: number | null;
  direction: string | null;
  currency: string | null;
  attributionLevel: string | null;
};

export type RatioPairItem = {
  key: string;
  label: string | null;
  current: number | null;
  comparable: number | null;
  currentRatioPct: number | null;
  comparableRatioPct: number | null;
  ratioChangePp: number | null;
};

export type WorkingCapitalItem = {
  key: string;
  label: string | null;
  current: number | null;
  comparable: number | null;
  growthPct: number | null;
  growthMinusRevenuePp: number | null;
};

export type CompanyExplanation = {
  label: string | null;
  excerpt: string | null;
  reportTitle: string | null;
  noticeDate: string | null;
  reportPeriod: string | null;
  classification: string | null;
};

export type FinancialDrivers = {
  status: string | null;
  overallLabel: string | null;
  summary: string | null;
  confidence: string | null;
  confirmedDrivers: DriverItem[];
  plausibleClues: Array<{ key: string; label: string | null; evidence: string | null }>;
  expenseAnalysis: RatioPairItem[];
  workingCapital: WorkingCapitalItem[];
  cashflow: {
    operatingCashflow: number | null;
    investingCashflow: number | null;
    operatingCashflowChangePct: number | null;
    cashReceivedFromSalesRatioChangePp: number | null;
  } | null;
  companyExplanations: CompanyExplanation[];
  unresolvedCauses: string[];
  reviewPoints: string[];
  profitBridge: { netProfitChange: number | null; grossMarginChangePp: number | null; currency: string | null } | null;
  boundary: string | null;
  generatedAt: string | null;
};

export function parseFinancialDrivers(value: unknown): FinancialDrivers {
  const root = record(value);
  const cashflow = optionalRecord(root.cashflow_analysis);
  const bridge = optionalRecord(root.profit_bridge);
  return {
    status: optionalString(root.status),
    overallLabel: optionalString(root.overall_label),
    summary: optionalString(root.summary),
    confidence: optionalString(root.confidence),
    confirmedDrivers: list(root.confirmed_mechanical_drivers).flatMap((raw) => {
      const item = optionalRecord(raw);
      const key = optionalString(item?.key);
      if (!item || !key) return [];
      // amount 单位为元，直通不缩放。
      return [{
        key,
        label: optionalString(item.label),
        statement: optionalString(item.statement),
        amount: optionalNumber(item.amount),
        direction: optionalString(item.direction),
        currency: optionalString(item.currency),
        attributionLevel: optionalString(item.attribution_level),
      }];
    }),
    plausibleClues: list(root.plausible_clues).flatMap((raw) => {
      const item = optionalRecord(raw);
      const key = optionalString(item?.key);
      if (!item || !key) return [];
      return [{ key, label: optionalString(item.label), evidence: optionalString(item.evidence) }];
    }),
    expenseAnalysis: list(root.expense_analysis).flatMap((raw) => {
      const item = optionalRecord(raw);
      const key = optionalString(item?.key);
      if (!item || !key) return [];
      // current/comparable 单位为元；*_ratio_pct 为百分数；ratio_change_pp 为百分点，直通。
      return [{
        key,
        label: optionalString(item.label),
        current: optionalNumber(item.current),
        comparable: optionalNumber(item.comparable),
        currentRatioPct: optionalNumber(item.current_ratio_pct),
        comparableRatioPct: optionalNumber(item.comparable_ratio_pct),
        ratioChangePp: optionalNumber(item.ratio_change_pp),
      }];
    }),
    workingCapital: list(root.working_capital_analysis).flatMap((raw) => {
      const item = optionalRecord(raw);
      const key = optionalString(item?.key);
      if (!item || !key) return [];
      // growth_pct 为百分数；growth_minus_revenue_pp 为百分点，直通。
      return [{
        key,
        label: optionalString(item.label),
        current: optionalNumber(item.current),
        comparable: optionalNumber(item.comparable),
        growthPct: optionalNumber(item.growth_pct),
        growthMinusRevenuePp: optionalNumber(item.growth_minus_revenue_pp),
      }];
    }),
    cashflow: cashflow === null ? null : {
      operatingCashflow: optionalNumber(cashflow.operating_cashflow),
      investingCashflow: optionalNumber(cashflow.investing_cashflow),
      operatingCashflowChangePct: optionalNumber(cashflow.operating_cashflow_change_pct),
      cashReceivedFromSalesRatioChangePp: optionalNumber(cashflow.cash_received_from_sales_ratio_change_pp),
    },
    companyExplanations: list(root.company_explanations).flatMap((raw) => {
      const item = optionalRecord(raw);
      if (!item) return [];
      return [{
        label: optionalString(item.label),
        excerpt: optionalString(item.excerpt),
        reportTitle: optionalString(item.report_title),
        noticeDate: optionalString(item.notice_date),
        reportPeriod: optionalString(item.report_period),
        classification: optionalString(item.classification),
      }];
    }),
    unresolvedCauses: strings(root.unresolved_causes),
    reviewPoints: strings(root.review_points),
    profitBridge: bridge === null ? null : {
      netProfitChange: optionalNumber(bridge.net_profit_change),
      grossMarginChangePp: optionalNumber(bridge.gross_margin_change_pp),
      currency: optionalString(bridge.currency),
    },
    boundary: optionalString(root.boundary),
    generatedAt: optionalString(root.generated_at),
  };
}

// ---------- 信息（公告/新闻/社区） ----------

export type InfoItem = {
  title: string;
  url: string | null;
  source: string | null;
  publishedAt: string | null;
  summary: string | null;
  category: string | null;
};

export type Information = {
  announcements: InfoItem[];
  news: InfoItem[];
  socialPosts: InfoItem[];
  sentiment: { confidence: string | null; caveat: string | null; sampleSize: number | null } | null;
  methodology: string[];
  generatedAt: string | null;
};

function parseInfoItems(value: unknown): InfoItem[] {
  return list(value).flatMap((raw) => {
    const item = optionalRecord(raw);
    const title = optionalString(item?.title);
    if (!item || !title) return [];
    return [{
      title,
      url: optionalString(item.url),
      source: optionalString(item.source),
      publishedAt: optionalString(item.published_at),
      summary: optionalString(item.summary),
      category: optionalString(item.category),
    }];
  });
}

export function parseInformation(value: unknown): Information {
  const root = record(value);
  const sentiment = optionalRecord(root.sentiment);
  const evidence = optionalRecord(sentiment?.evidence);
  return {
    announcements: parseInfoItems(root.announcements),
    news: parseInfoItems(root.news),
    socialPosts: parseInfoItems(root.social_posts),
    sentiment: sentiment === null ? null : {
      confidence: optionalString(sentiment.confidence),
      caveat: optionalString(evidence?.caveat),
      sampleSize: optionalNumber(sentiment.sample_size),
    },
    methodology: strings(root.methodology),
    generatedAt: optionalString(root.generated_at),
  };
}

// ---------- 股东 ----------

export type TopHolder = {
  rank: number | null;
  name: string;
  holding: number | null;
  holdingRatioPct: number | null;
  holdingChange: string | null;
};

export type Shareholders = {
  status: string | null;
  holderCount: number | null;
  holderCountAsOf: string | null;
  previousHolderCount: number | null;
  holderCountChangePct: number | null;
  signal: string | null;
  signalLabel: string | null;
  top10RatioPct: number | null;
  top3RatioPct: number | null;
  top10ReportDate: string | null;
  topHolders: TopHolder[];
  averageHolding: number | null;
  summary: string | null;
  boundary: string | null;
  announcedAt: string | null;
  latestFetchedAt: string | null;
};

export function parseShareholders(value: unknown): Shareholders {
  const root = record(value);
  return {
    status: optionalString(root.status),
    holderCount: optionalNumber(root.holder_count),
    holderCountAsOf: optionalString(root.holder_count_as_of),
    previousHolderCount: optionalNumber(root.previous_holder_count),
    // holder_count_change_pct / top*_ratio_pct 为百分数，直通不缩放。
    holderCountChangePct: optionalNumber(root.holder_count_change_pct),
    signal: optionalString(root.holder_count_signal),
    signalLabel: optionalString(root.holder_count_signal_label),
    top10RatioPct: optionalNumber(root.top10_ratio_pct),
    top3RatioPct: optionalNumber(root.top3_ratio_pct),
    top10ReportDate: optionalString(root.top10_report_date),
    topHolders: list(root.top_holders).flatMap((raw) => {
      const item = optionalRecord(raw);
      const name = optionalString(item?.name);
      if (!item || !name) return [];
      return [{
        rank: optionalNumber(item.rank),
        name,
        // holding 单位为股，直通不缩放。
        holding: optionalNumber(item.holding),
        holdingRatioPct: optionalNumber(item.holding_ratio_pct),
        holdingChange: optionalString(item.holding_change),
      }];
    }),
    averageHolding: optionalNumber(root.average_holding),
    summary: optionalString(root.summary),
    boundary: optionalString(root.boundary),
    announcedAt: optionalString(root.announced_at),
    latestFetchedAt: optionalString(root.latest_fetched_at),
  };
}

// ---------- 事件脉络 ----------

export type TimelineEvent = {
  title: string;
  url: string | null;
  eventLabel: string | null;
  eventType: string | null;
  category: string | null;
  evidenceLabel: string | null;
  evidenceLevel: string | null;
  source: string | null;
  publishedAt: string | null;
  eventDate: string | null;
  eventStatus: string | null;
  researchRelevanceLabel: string | null;
};

export type EventTimeline = {
  status: string | null;
  asOfDate: string | null;
  themes: Array<{ eventType: string; label: string | null; count: number | null }>;
  recentOfficialEvents: TimelineEvent[];
  supportiveEvents: TimelineEvent[];
  riskEvents: TimelineEvent[];
  coverage: {
    officialEvents: number | null;
    mediaEvents: number | null;
    eventsReturned: number | null;
    riskEvents: number | null;
  };
  reviewPoints: string[];
  boundary: string | null;
  generatedAt: string | null;
};

function parseTimelineEvents(value: unknown): TimelineEvent[] {
  return list(value).flatMap((raw) => {
    const item = optionalRecord(raw);
    const title = optionalString(item?.title);
    if (!item || !title) return [];
    return [{
      title,
      url: optionalString(item.url),
      eventLabel: optionalString(item.event_label),
      eventType: optionalString(item.event_type),
      category: optionalString(item.category),
      evidenceLabel: optionalString(item.evidence_label),
      evidenceLevel: optionalString(item.evidence_level),
      source: optionalString(item.source),
      publishedAt: optionalString(item.published_at),
      eventDate: optionalString(item.event_date),
      eventStatus: optionalString(item.event_status),
      researchRelevanceLabel: optionalString(item.research_relevance_label),
    }];
  });
}

export function parseEventTimeline(value: unknown): EventTimeline {
  const root = record(value);
  const coverage = optionalRecord(root.coverage);
  return {
    status: optionalString(root.status),
    asOfDate: optionalString(root.as_of_date),
    themes: list(root.themes).flatMap((raw) => {
      const item = optionalRecord(raw);
      const eventType = optionalString(item?.event_type);
      if (!item || !eventType) return [];
      return [{ eventType, label: optionalString(item.label), count: optionalNumber(item.count) }];
    }),
    recentOfficialEvents: parseTimelineEvents(root.recent_official_events),
    supportiveEvents: parseTimelineEvents(root.supportive_events),
    riskEvents: parseTimelineEvents(root.risk_events),
    coverage: {
      officialEvents: optionalNumber(coverage?.official_events),
      mediaEvents: optionalNumber(coverage?.media_events),
      eventsReturned: optionalNumber(coverage?.events_returned),
      riskEvents: optionalNumber(coverage?.risk_events),
    },
    reviewPoints: strings(root.review_points),
    boundary: optionalString(root.boundary),
    generatedAt: optionalString(root.generated_at),
  };
}

// ---------- 分析师预期 ----------

export type AnalystExpectations = {
  status: string | null;
  asOfDate: string | null;
  industry: string | null;
  ratingStatement: string | null;
  ratingWindow: string | null;
  ratingCounts: { buy: number | null; add: number | null; neutral: number | null; reduce: number | null; sell: number | null };
  ratingOrganizationCount: number | null;
  forecastEps: Array<{ year: number | null; kind: string | null; value: number | null }>;
  forecastStatement: string | null;
  revision: { available: boolean | null; summary: string | null; previousSnapshotAt: string | null } | null;
  latestReports: Array<{
    title: string;
    institution: string | null;
    researchers: string | null;
    publishedAt: string | null;
    rating: string | null;
    previousRating: string | null;
    reportUrl: string | null;
  }>;
  coverage: {
    estimateYears: number | null;
    forecastYears: number | null;
    ratingOrganizations: number | null;
    reportsReturned: number | null;
  };
  reviewPoints: string[];
  boundary: string | null;
  generatedAt: string | null;
};

export function parseAnalystExpectations(value: unknown): AnalystExpectations {
  const root = record(value);
  const ratingCounts = optionalRecord(root.rating_counts);
  const revision = optionalRecord(root.revision);
  const coverage = optionalRecord(root.coverage);
  return {
    status: optionalString(root.status),
    asOfDate: optionalString(root.as_of_date),
    industry: optionalString(root.industry),
    ratingStatement: optionalString(root.rating_statement),
    ratingWindow: optionalString(root.rating_window),
    ratingCounts: {
      buy: optionalNumber(ratingCounts?.buy),
      add: optionalNumber(ratingCounts?.add),
      neutral: optionalNumber(ratingCounts?.neutral),
      reduce: optionalNumber(ratingCounts?.reduce),
      sell: optionalNumber(ratingCounts?.sell),
    },
    ratingOrganizationCount: optionalNumber(root.rating_organization_count),
    // forecast_eps value 单位为元/股，直通不缩放；kind 区分 actual（历史实际）与 estimate（券商预测均值）。
    forecastEps: list(root.forecast_eps).flatMap((raw) => {
      const item = optionalRecord(raw);
      if (!item) return [];
      return [{
        year: optionalNumber(item.year),
        kind: optionalString(item.kind),
        value: optionalNumber(item.value),
      }];
    }),
    forecastStatement: optionalString(root.forecast_statement),
    revision: revision === null ? null : {
      available: optionalBoolean(revision.available),
      summary: optionalString(revision.summary),
      previousSnapshotAt: optionalString(revision.previous_snapshot_at),
    },
    latestReports: list(root.latest_reports).flatMap((raw) => {
      const item = optionalRecord(raw);
      const title = optionalString(item?.title);
      if (!item || !title) return [];
      return [{
        title,
        institution: optionalString(item.institution),
        researchers: optionalString(item.researchers),
        publishedAt: optionalString(item.published_at),
        rating: optionalString(item.rating),
        previousRating: optionalString(item.previous_rating),
        reportUrl: optionalString(item.report_url),
      }];
    }),
    coverage: {
      estimateYears: optionalNumber(coverage?.estimate_years),
      forecastYears: optionalNumber(coverage?.forecast_years),
      ratingOrganizations: optionalNumber(coverage?.rating_organizations),
      reportsReturned: optionalNumber(coverage?.reports_returned),
    },
    reviewPoints: strings(root.review_points),
    boundary: optionalString(root.boundary),
    generatedAt: optionalString(root.generated_at),
  };
}

// ---------- 研究空间 workspace ----------

export type WorkspaceQuote = {
  price: number | null;
  pctChange: number | null;
  dailyClose: number | null;
  dailyReturn1dPct: number | null;
  marketTimestamp: string | null;
  label: string | null;
  currency: string | null;
};

export type WorkspaceChange = {
  id: string;
  summary: string | null;
  severity: string | null;
  eventType: string | null;
  createdAt: string | null;
  dataAsOf: string | null;
  nextReviewFocus: string | null;
};

export type WorkspaceResearchEntry = {
  sourceKind: string | null;
  sourceLabel: string | null;
  displayName: string | null;
  industry: string | null;
  profileKey: string | null;
  asOfDate: string | null;
  candidateStatus: string | null;
  matchedReasons: string[];
  researchFocus: string | null;
  attentionFlags: string[];
  missingFields: string[];
};

export type Workspace = {
  contractVersion: string | null;
  name: string | null;
  symbol: string | null;
  relation: { label: string | null; inWatchlist: boolean | null; previewState: string | null };
  thesis: { status: string; summary: string | null; updatedAt: string | null; version: number | null };
  completeness: {
    hasStockSpace: boolean | null;
    hasThesis: boolean | null;
    hasResearchSession: boolean | null;
    hasLatestReport: boolean | null;
    missingItems: string[];
  };
  stageProgress: {
    status: string | null;
    currentStage: string | null;
    nextQuestion: string | null;
    progress: { completed: number | null; total: number | null; percent: number | null } | null;
  };
  quote: WorkspaceQuote | null;
  dataStatus: string | null;
  latestChange: WorkspaceChange | null;
  researchEntry: WorkspaceResearchEntry | null;
  importantChanges: WorkspaceChange[];
  nextEvidence: Array<{ status: string | null; description: string; source: string | null }>;
  pendingActionCount: number;
  observationTasksSummary: {
    total: number | null;
    active: number | null;
    pending: number | null;
    inProgress: number | null;
    completed: number | null;
    waitingData: number | null;
  };
  positionSnapshot: { available: boolean | null; status: string | null };
  historySummary: {
    changeCount: number | null;
    observationTaskCount: number | null;
    recentReportCount: number | null;
    thesisVersionCount: number | null;
    latestReportAt: string | null;
    latestChangeAt: string | null;
  };
  latestReport: { id: string | null; title: string | null; status: string | null; generatedAt: string | null; marketTimestamp: string | null } | null;
  dataMeta: {
    status: string | null;
    quoteAsOf: string | null;
    dailyAsOf: string | null;
    financialReportPeriod: string | null;
    reportGeneratedAt: string | null;
  };
  boundary: string | null;
};

function parseWorkspaceChange(raw: unknown, index: number): WorkspaceChange | null {
  const item = optionalRecord(raw);
  if (!item) return null;
  const nextReview = optionalRecord(item.next_review);
  return {
    id: optionalString(item.id) ?? `change-${index}`,
    summary: optionalString(item.summary),
    severity: optionalString(item.severity),
    eventType: optionalString(item.event_type),
    createdAt: optionalString(item.created_at),
    dataAsOf: optionalString(item.data_as_of),
    nextReviewFocus: optionalString(nextReview?.focus),
  };
}

export function parseWorkspace(value: unknown): Workspace {
  const root = record(value);
  const relation = optionalRecord(root.relation);
  const thesis = optionalRecord(root.thesis);
  const completeness = optionalRecord(root.completeness);
  const stage = optionalRecord(root.stage_progress);
  const stageProgress = optionalRecord(stage?.progress);
  const overview = optionalRecord(root.overview);
  const quote = optionalRecord(overview?.quote);
  const researchEntry = optionalRecord(root.research_entry);
  const tasks = optionalRecord(root.observation_tasks);
  const tasksSummary = optionalRecord(tasks?.summary);
  const position = optionalRecord(root.position_snapshot);
  const historySummary = optionalRecord(root.history_summary);
  const latestReport = optionalRecord(root.latest_report);
  const dataMeta = optionalRecord(root.data_meta);
  return {
    contractVersion: optionalString(root.contract_version),
    name: optionalString(root.name),
    symbol: optionalString(root.symbol),
    relation: {
      label: optionalString(relation?.label),
      inWatchlist: optionalBoolean(relation?.in_watchlist),
      previewState: optionalString(relation?.preview_state),
    },
    thesis: {
      // thesis.status: empty 表示尚未保存当前判断，与接口失败（模块级 error）严格区分。
      status: optionalString(thesis?.status) ?? "unknown",
      summary: optionalString(thesis?.summary),
      updatedAt: optionalString(thesis?.updated_at),
      version: optionalNumber(thesis?.version),
    },
    completeness: {
      hasStockSpace: optionalBoolean(completeness?.has_stock_space),
      hasThesis: optionalBoolean(completeness?.has_thesis),
      hasResearchSession: optionalBoolean(completeness?.has_research_session),
      hasLatestReport: optionalBoolean(completeness?.has_latest_report),
      missingItems: strings(completeness?.missing_items),
    },
    stageProgress: {
      status: optionalString(stage?.status),
      currentStage: optionalString(stage?.current_stage),
      nextQuestion: optionalString(stage?.next_question),
      progress: stageProgress === null ? null : {
        completed: optionalNumber(stageProgress.completed),
        total: optionalNumber(stageProgress.total),
        percent: optionalNumber(stageProgress.percent),
      },
    },
    quote: quote === null ? null : {
      price: optionalNumber(quote.price),
      // pct_change 与 daily_return_1d_pct 均为百分数，直通不缩放。
      pctChange: optionalNumber(quote.pct_change),
      dailyClose: optionalNumber(quote.daily_close),
      dailyReturn1dPct: optionalNumber(quote.daily_return_1d_pct),
      marketTimestamp: optionalString(quote.market_timestamp),
      label: optionalString(quote.label),
      currency: optionalString(quote.currency),
    },
    dataStatus: optionalString(overview?.data_status),
    latestChange: overview?.latest_change ? parseWorkspaceChange(overview.latest_change, 0) : null,
    researchEntry: researchEntry === null ? null : {
      sourceKind: optionalString(researchEntry.source_kind),
      sourceLabel: optionalString(researchEntry.source_label),
      displayName: optionalString(researchEntry.display_name),
      industry: optionalString(researchEntry.industry),
      profileKey: optionalString(researchEntry.profile_key),
      asOfDate: optionalString(researchEntry.as_of_date),
      candidateStatus: optionalString(researchEntry.candidate_status),
      matchedReasons: strings(researchEntry.matched_reasons),
      researchFocus: optionalString(researchEntry.research_focus),
      attentionFlags: strings(researchEntry.attention_flags),
      missingFields: strings(researchEntry.missing_fields),
    },
    importantChanges: list(root.important_changes).flatMap((raw, index) => {
      const change = parseWorkspaceChange(raw, index);
      return change ? [change] : [];
    }),
    nextEvidence: list(root.next_evidence).flatMap((raw) => {
      const item = optionalRecord(raw);
      const description = optionalString(item?.description);
      if (!item || !description) return [];
      return [{ status: optionalString(item.status), description, source: optionalString(item.source) }];
    }),
    pendingActionCount: list(root.pending_actions).length,
    observationTasksSummary: {
      total: optionalNumber(tasksSummary?.total),
      active: optionalNumber(tasksSummary?.active),
      pending: optionalNumber(tasksSummary?.pending),
      inProgress: optionalNumber(tasksSummary?.in_progress),
      completed: optionalNumber(tasksSummary?.completed),
      waitingData: optionalNumber(tasksSummary?.waiting_data),
    },
    positionSnapshot: {
      available: optionalBoolean(position?.available),
      status: optionalString(position?.status),
    },
    historySummary: {
      changeCount: optionalNumber(historySummary?.change_count),
      observationTaskCount: optionalNumber(historySummary?.observation_task_count),
      recentReportCount: optionalNumber(historySummary?.recent_report_count),
      thesisVersionCount: optionalNumber(historySummary?.thesis_version_count),
      latestReportAt: optionalString(historySummary?.latest_report_at),
      latestChangeAt: optionalString(historySummary?.latest_change_at),
    },
    latestReport: latestReport === null ? null : {
      id: optionalString(latestReport.id),
      title: optionalString(latestReport.title),
      status: optionalString(latestReport.status),
      generatedAt: optionalString(latestReport.generated_at),
      marketTimestamp: optionalString(latestReport.market_timestamp),
    },
    dataMeta: {
      status: optionalString(dataMeta?.status),
      quoteAsOf: optionalString(dataMeta?.quote_as_of),
      dailyAsOf: optionalString(dataMeta?.daily_as_of),
      financialReportPeriod: optionalString(dataMeta?.financial_report_period),
      reportGeneratedAt: optionalString(dataMeta?.report_generated_at),
    },
    boundary: optionalString(root.boundary),
  };
}

// ---------- 首屏聚合 ----------

export type ModuleEnvelope<T> = { status: string; reason: string | null; data: T | null };

export type StockPageModules = {
  history: ModuleEnvelope<StockHistory>;
  fundamentals: ModuleEnvelope<Fundamentals>;
  workspace: ModuleEnvelope<Workspace>;
  information: ModuleEnvelope<Information>;
  shareholders: ModuleEnvelope<Shareholders>;
  eventTimeline: ModuleEnvelope<EventTimeline>;
  earningsQuality: ModuleEnvelope<EarningsQuality>;
  financialDrivers: ModuleEnvelope<FinancialDrivers>;
  analystExpectations: ModuleEnvelope<AnalystExpectations>;
};

export type StockPage = {
  symbol: string;
  market: string | null;
  status: string;
  summary: { available: number; failed: number; total: number; requiredFailed: string[] };
  modules: StockPageModules;
};

function envelope<T>(value: unknown, field: string, parse: (data: unknown) => T): ModuleEnvelope<T> {
  const root = optionalRecord(value);
  if (!root) return { status: "unavailable", reason: "模块未返回", data: null };
  return {
    // 模块级 status 直通后端（available/partial/unavailable/...），UI 层按合同 §6.3 翻译。
    status: optionalString(root.status) ?? "unavailable",
    reason: optionalString(root.reason),
    data: root.data === undefined || root.data === null ? null : parse(root.data),
  };
}

export function parseStockPage(value: unknown): StockPage {
  const root = record(value);
  if (root.contract_version !== "stock_page_v1") {
    throw new ContractError("contract_version 不是 stock_page_v1");
  }
  const modules = record(root.modules, "modules");
  const summary = record(root.summary, "summary");
  return {
    symbol: requiredString(root.symbol, "symbol"),
    market: optionalString(root.market),
    status: requiredString(root.status, "status"),
    summary: {
      available: optionalNumber(summary.available) ?? 0,
      failed: optionalNumber(summary.failed) ?? 0,
      total: optionalNumber(summary.total) ?? 0,
      requiredFailed: strings(summary.required_failed),
    },
    modules: {
      history: envelope(modules.history, "modules.history", parseStockHistory),
      fundamentals: envelope(modules.fundamentals, "modules.fundamentals", parseFundamentals),
      workspace: envelope(modules.workspace, "modules.workspace", parseWorkspace),
      information: envelope(modules.information, "modules.information", parseInformation),
      shareholders: envelope(modules.shareholders, "modules.shareholders", parseShareholders),
      eventTimeline: envelope(modules.event_timeline, "modules.event_timeline", parseEventTimeline),
      earningsQuality: envelope(modules.earnings_quality, "modules.earnings_quality", parseEarningsQuality),
      financialDrivers: envelope(modules.financial_drivers, "modules.financial_drivers", parseFinancialDrivers),
      analystExpectations: envelope(modules.analyst_expectations, "modules.analyst_expectations", parseAnalystExpectations),
    },
  };
}

// ---------- 同行对比 ----------

export type PeerValuation = {
  symbol: string | null;
  name: string;
  peTtm: number | null;
  pb: number | null;
  totalMarketCap: number | null;
  marketTimestamp: string | null;
  currency: string | null;
  source: string | null;
};

export type OperatingMetricComparison = {
  key: string;
  subjectValue: number | null;
  peerMedian: number | null;
  peerMin: number | null;
  peerMax: number | null;
  peerSampleSize: number | null;
};

export type PeerComparisons = {
  groupLabel: string | null;
  selectionBasis: string | null;
  asOf: string | null;
  subject: PeerValuation | null;
  peers: PeerValuation[];
  warnings: string[];
  coverage: { availablePeers: number | null; requestedPeers: number | null };
  operatingComparison: {
    status: string | null;
    anchorReportDateName: string | null;
    anchorPeriodBasis: string | null;
    metrics: OperatingMetricComparison[];
    warnings: string[];
  } | null;
};

function parsePeerValuation(raw: unknown): PeerValuation | null {
  const item = optionalRecord(raw);
  const name = optionalString(item?.name);
  if (!item || !name) return null;
  // pe_ttm/pb 为倍数原值；total_market_cap 单位为元，直通不缩放。
  return {
    symbol: optionalString(item.symbol),
    name,
    peTtm: optionalNumber(item.pe_ttm),
    pb: optionalNumber(item.pb),
    totalMarketCap: optionalNumber(item.total_market_cap),
    marketTimestamp: optionalString(item.market_timestamp),
    currency: optionalString(item.currency),
    source: optionalString(item.source),
  };
}

const OPERATING_METRIC_LABELS: Record<string, string> = {
  revenue_yoy_pct: "营收同比",
  net_margin_pct: "净利率",
  gross_margin_pct: "毛利率",
  debt_asset_ratio_pct: "资产负债率",
  operating_cashflow_to_net_profit: "经营现金流/净利润",
};

export function parsePeerComparisons(value: unknown): PeerComparisons {
  const root = record(value);
  const coverage = optionalRecord(root.coverage);
  const operating = optionalRecord(root.operating_comparison);
  const operatingMetrics = optionalRecord(operating?.metrics);
  return {
    groupLabel: optionalString(root.group_label),
    selectionBasis: optionalString(root.selection_basis),
    asOf: optionalString(root.as_of),
    subject: parsePeerValuation(root.subject),
    peers: list(root.peers).flatMap((raw) => {
      const peer = parsePeerValuation(raw);
      return peer ? [peer] : [];
    }),
    warnings: strings(root.warnings),
    coverage: {
      availablePeers: optionalNumber(coverage?.available_peers),
      requestedPeers: optionalNumber(coverage?.requested_peers),
    },
    operatingComparison: operating === null ? null : {
      status: optionalString(operating.status),
      anchorReportDateName: optionalString(operating.anchor_report_date_name),
      anchorPeriodBasis: optionalString(operating.anchor_period_basis),
      // *_pct 指标为百分数直通；operating_cashflow_to_net_profit 为 0-1 附近比值小数，UI 乘 100 展示。
      metrics: Object.entries(operatingMetrics ?? {}).flatMap(([key, raw]) => {
        const item = optionalRecord(raw);
        if (!item) return [];
        return [{
          key: OPERATING_METRIC_LABELS[key] ?? key,
          subjectValue: optionalNumber(item.subject_value),
          peerMedian: optionalNumber(item.peer_median),
          peerMin: optionalNumber(item.peer_min),
          peerMax: optionalNumber(item.peer_max),
          peerSampleSize: optionalNumber(item.peer_sample_size),
        }];
      }),
      warnings: strings(operating.warnings),
    },
  };
}

// ---------- 我的研究独立端点 ----------

export type ObservationTasks = {
  items: Array<{ id: string | null; title: string | null; status: string | null; summary: string | null }>;
  summary: {
    total: number | null;
    active: number | null;
    pending: number | null;
    inProgress: number | null;
    completed: number | null;
    waitingData: number | null;
  };
  boundary: string | null;
};

export function parseObservationTasks(value: unknown): ObservationTasks {
  const root = record(value);
  const summary = optionalRecord(root.summary);
  return {
    items: list(root.items).flatMap((raw) => {
      const item = optionalRecord(raw);
      if (!item) return [];
      return [{
        id: optionalString(item.id),
        title: optionalString(item.title),
        status: optionalString(item.status),
        summary: optionalString(item.summary),
      }];
    }),
    summary: {
      total: optionalNumber(summary?.total),
      active: optionalNumber(summary?.active),
      pending: optionalNumber(summary?.pending),
      inProgress: optionalNumber(summary?.in_progress),
      completed: optionalNumber(summary?.completed),
      waitingData: optionalNumber(summary?.waiting_data),
    },
    boundary: optionalString(root.boundary),
  };
}

export type Theses = {
  items: Array<{ id: string | null; status: string | null; summary: string | null; version: number | null; updatedAt: string | null }>;
};

export function parseTheses(value: unknown): Theses {
  const root = record(value);
  const source = Array.isArray(root) ? root : (root.items ?? root.theses ?? []);
  return {
    items: list(source).flatMap((raw) => {
      const item = optionalRecord(raw);
      if (!item) return [];
      return [{
        id: optionalString(item.id),
        status: optionalString(item.status),
        summary: optionalString(item.summary),
        version: optionalNumber(item.version),
        updatedAt: optionalString(item.updated_at),
      }];
    }),
  };
}

export type StockPosition = {
  status: string | null;
  quantity: number | null;
  costBasis: number | null;
  averageCost: number | null;
};

export function parseStockPosition(value: unknown): StockPosition {
  const root = record(value);
  const current = optionalRecord(root.current) ?? root;
  return {
    status: optionalString(root.status),
    // quantity/cost_basis/average_cost 为账本原值，直通不缩放。
    quantity: optionalNumber(current.quantity),
    costBasis: optionalNumber(current.cost_basis),
    averageCost: optionalNumber(current.average_cost),
  };
}

export type DeepStockSession = {
  status: string | null;
  sessionId: string | null;
  conversationId: string | null;
  currentStage: string | null;
};

export function parseDeepStockSession(value: unknown): DeepStockSession {
  const root = record(value);
  return {
    status: optionalString(root.status),
    sessionId: optionalString(root.session_id) ?? optionalString(root.id),
    conversationId: optionalString(root.conversation_id),
    currentStage: optionalString(root.current_stage),
  };
}
