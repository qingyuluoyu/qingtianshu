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

/** 数值型筛选默认值直通（0 是有效阈值，不能当缺失）。 */
function numberRecord(value: unknown): Record<string, number> {
  const root = optionalRecord(value);
  const result: Record<string, number> = {};
  if (!root) return result;
  for (const [key, item] of Object.entries(root)) {
    const num = optionalNumber(item);
    if (num !== null) result[key] = num;
  }
  return result;
}

// ---------- 筛选配置（GET /stock-screener/profiles） ----------

export type ScreenerProfile = {
  key: string;
  label: string | null;
  description: string | null;
  sortRule: string | null;
  /** 服务端给定的可修改筛选默认值；键即 StockScreenFilters 字段名。 */
  defaultFilters: Record<string, number>;
};

export type ScreenerProfiles = {
  items: ScreenerProfile[];
  boundary: string | null;
};

export function parseScreenerProfiles(value: unknown): ScreenerProfiles {
  const root = record(value);
  return {
    items: list(root.items).flatMap((raw) => {
      const item = optionalRecord(raw);
      const key = optionalString(item?.key);
      if (!item || !key) return [];
      return [{
        key,
        label: optionalString(item.label),
        description: optionalString(item.description),
        sortRule: optionalString(item.sort_rule),
        defaultFilters: numberRecord(item.default_filters),
      }];
    }),
    boundary: optionalString(root.boundary),
  };
}

// ---------- 通用筛选结果（POST /me/stock-screener） ----------

export type ScreenRule = {
  field: string | null;
  operator: string | null;
  /** 阈值原值直通：数字不缩放，字符串直通；两者都没有才算缺失。 */
  value: number | string | null;
  unit: string | null;
  reason: string | null;
};

export type ScreenUniverse = {
  listedInput: number | null;
  expectedListed: number | null;
  marketCoverage: number | null;
  afterCommonRules: number | null;
  afterMarketRules: number | null;
  valuationCoverage: number | null;
  financialCandidatePool: number | null;
  financialsChecked: number | null;
  matched: number | null;
  representsFullMarket: boolean | null;
};

export type ScreenItemMetrics = {
  latestClose: number | null;
  pctChange: number | null;
  totalMvYi: number | null;
  circMvYi: number | null;
  peTtm: number | null;
  pb: number | null;
  psTtm: number | null;
  turnoverRatePct: number | null;
  volumeRatio: number | null;
  return5dPct: number | null;
  return20dPct: number | null;
  industryExcess20dPct: number | null;
  industryAvgReturn20dPct: number | null;
};

export type ScreenItemFinancials = {
  status: string | null;
  coverageStatus: string | null;
  reportPeriod: string | null;
  announcementDate: string | null;
  revenueYoy: number | null;
  netProfitYoy: number | null;
  roe: number | null;
  grossMargin: number | null;
  netMargin: number | null;
  debtToAssets: number | null;
} | null;

export type ScreenItem = {
  symbol: string;
  internalSymbol: string | null;
  name: string | null;
  industry: string | null;
  market: string | null;
  listDate: string | null;
  metrics: ScreenItemMetrics;
  financials: ScreenItemFinancials;
  coverageStatus: { financialQuality: string | null; valuation: string | null; marketAndTrend: string | null };
  matchedReasons: string[];
  missingFields: string[];
  missingReasons: string[];
  notApplicableFields: string[];
  limitations: string[];
  attentionFlags: string[];
  researchFocus: string | null;
  evidenceTimes: {
    marketDate: string | null;
    financialReportPeriod: string | null;
    financialAnnouncementDate: string | null;
  };
};

export type StockScreen = {
  status: string;
  profile: { key: string; label: string | null; description: string | null; sortRule: string | null };
  market: string | null;
  rules: ScreenRule[];
  effectiveFilters: Record<string, number | string | boolean>;
  universe: ScreenUniverse;
  warnings: string[];
  dataContract: {
    contractVersion: string | null;
    marketDate: string | null;
    generatedAt: string | null;
    return5dBaseDate: string | null;
    return20dBaseDate: string | null;
    financialReportPeriods: string[];
    coverageStatus: string | null;
    representsFullMarket: boolean | null;
    representationNote: string | null;
    actualScopeLabel: string | null;
  };
  items: ScreenItem[];
  boundary: string | null;
};

function parseScreenItem(raw: unknown): ScreenItem | null {
  const root = optionalRecord(raw);
  const symbol = optionalString(root?.ts_code) ?? optionalString(root?.internal_symbol);
  if (!root || !symbol) return null;
  const metrics = optionalRecord(root.metrics);
  const fin = optionalRecord(root.financials);
  const coverage = optionalRecord(root.coverage_status);
  const evidence = optionalRecord(root.evidence_times);
  return {
    symbol,
    internalSymbol: optionalString(root.internal_symbol),
    name: optionalString(root.name),
    industry: optionalString(root.industry),
    market: optionalString(root.market),
    listDate: optionalString(root.list_date),
    metrics: {
      latestClose: optionalNumber(metrics?.latest_close),
      // pct_change / return_*_pct 后端已是百分数，直通不缩放。
      pctChange: optionalNumber(metrics?.pct_change),
      totalMvYi: optionalNumber(metrics?.total_mv_yi),
      circMvYi: optionalNumber(metrics?.circ_mv_yi),
      peTtm: optionalNumber(metrics?.pe_ttm),
      pb: optionalNumber(metrics?.pb),
      psTtm: optionalNumber(metrics?.ps_ttm),
      turnoverRatePct: optionalNumber(metrics?.turnover_rate_pct),
      volumeRatio: optionalNumber(metrics?.volume_ratio),
      return5dPct: optionalNumber(metrics?.return_5d_pct),
      return20dPct: optionalNumber(metrics?.return_20d_pct),
      industryExcess20dPct: optionalNumber(metrics?.industry_excess_20d_pct),
      industryAvgReturn20dPct: optionalNumber(metrics?.industry_avg_return_20d_pct),
    },
    financials: fin === null ? null : {
      status: optionalString(fin.status),
      coverageStatus: optionalString(fin.coverage_status),
      reportPeriod: optionalString(fin.report_period),
      announcementDate: optionalString(fin.announcement_date),
      revenueYoy: optionalNumber(fin.revenue_yoy),
      netProfitYoy: optionalNumber(fin.net_profit_yoy),
      roe: optionalNumber(fin.roe),
      grossMargin: optionalNumber(fin.gross_margin),
      netMargin: optionalNumber(fin.net_margin),
      debtToAssets: optionalNumber(fin.debt_to_assets),
    },
    coverageStatus: {
      financialQuality: optionalString(coverage?.financial_quality),
      valuation: optionalString(coverage?.valuation),
      marketAndTrend: optionalString(coverage?.market_and_trend),
    },
    matchedReasons: strings(root.matched_reasons),
    missingFields: strings(root.missing_fields),
    missingReasons: strings(root.missing_reasons),
    notApplicableFields: strings(root.not_applicable_fields),
    limitations: strings(root.limitations),
    attentionFlags: strings(root.attention_flags),
    researchFocus: optionalString(root.research_focus),
    evidenceTimes: {
      marketDate: optionalString(evidence?.market_date),
      financialReportPeriod: optionalString(evidence?.financial_report_period),
      financialAnnouncementDate: optionalString(evidence?.financial_announcement_date),
    },
  };
}

export function parseStockScreen(value: unknown): StockScreen {
  const root = record(value);
  if (root.type !== "stock_screen") {
    throw new ContractError("type 不是 stock_screen");
  }
  const profile = optionalRecord(root.profile);
  const universe = optionalRecord(root.universe);
  const contract = optionalRecord(root.data_contract);
  const asOf = optionalRecord(contract?.as_of);
  const representation = optionalRecord(contract?.representation);
  const effective = optionalRecord(root.effective_filters);
  const effectiveFilters: Record<string, number | string | boolean> = {};
  if (effective) {
    for (const [key, item] of Object.entries(effective)) {
      const num = optionalNumber(item);
      const str = optionalString(item);
      const bool = optionalBoolean(item);
      if (num !== null) effectiveFilters[key] = num;
      else if (bool !== null) effectiveFilters[key] = bool;
      else if (str !== null) effectiveFilters[key] = str;
    }
  }
  return {
    status: optionalString(root.status) ?? "unavailable",
    profile: {
      key: optionalString(profile?.key) ?? "",
      label: optionalString(profile?.label),
      description: optionalString(profile?.description),
      sortRule: optionalString(profile?.sort_rule),
    },
    market: optionalString(root.market),
    rules: list(root.rules).flatMap((raw) => {
      const rule = optionalRecord(raw);
      if (!rule) return [];
      const numValue = optionalNumber(rule.value);
      const strValue = optionalString(rule.value);
      return [{
        field: optionalString(rule.field),
        operator: optionalString(rule.operator),
        value: numValue ?? strValue,
        unit: optionalString(rule.unit),
        reason: optionalString(rule.reason),
      }];
    }),
    effectiveFilters,
    universe: {
      listedInput: optionalNumber(universe?.listed_input),
      expectedListed: optionalNumber(universe?.expected_listed),
      marketCoverage: optionalNumber(universe?.market_coverage),
      afterCommonRules: optionalNumber(universe?.after_common_rules),
      afterMarketRules: optionalNumber(universe?.after_market_rules),
      valuationCoverage: optionalNumber(universe?.valuation_coverage),
      financialCandidatePool: optionalNumber(universe?.financial_candidate_pool),
      financialsChecked: optionalNumber(universe?.financials_checked),
      matched: optionalNumber(universe?.matched),
      representsFullMarket: optionalBoolean(universe?.represents_full_market),
    },
    warnings: strings(root.warnings),
    dataContract: {
      contractVersion: optionalString(contract?.contract_version),
      marketDate: optionalString(asOf?.market_date),
      generatedAt: optionalString(asOf?.generated_at),
      return5dBaseDate: optionalString(asOf?.return_5d_base_date),
      return20dBaseDate: optionalString(asOf?.return_20d_base_date),
      financialReportPeriods: strings(asOf?.financial_report_periods),
      coverageStatus: optionalString(representation?.coverage_status),
      representsFullMarket: optionalBoolean(representation?.represents_full_market),
      representationNote: optionalString(representation?.note),
      actualScopeLabel: optionalString(representation?.actual_scope_label),
    },
    items: list(root.items).flatMap((raw) => {
      const item = parseScreenItem(raw);
      return item ? [item] : [];
    }),
    boundary: optionalString(root.boundary),
  };
}

// ---------- 李总策略候选（GET /v1/stock-strategies/li-zong/candidates） ----------

export type LiZongRuleResult = {
  ruleId: string | null;
  /** 后端状态直通：passed / failed / data_incomplete 等。 */
  status: string | null;
  source: string | null;
  evidenceDate: string | null;
  reportPeriod: string | null;
  limitations: string[];
};

export type LiZongCandidate = {
  id: string | null;
  symbol: string;
  internalSymbol: string | null;
  name: string | null;
  industry: string | null;
  market: string | null;
  asOfDate: string | null;
  /** 评估状态直通：qualified / triggered / not_qualified / data_incomplete / invalidated。 */
  status: string | null;
  previousStatus: string | null;
  candidateQualified: boolean | null;
  triggeredRuleIds: string[];
  matchedReasons: string[];
  limitations: string[];
  summary: {
    marketCapYi: number | null;
    roeMinPct: number | null;
    annualRoeYears: number | null;
    annualLimitUpCount: number | null;
    recentLimitUpCount: number | null;
    nonNaturalHolderCount: number | null;
  };
  ruleResults: LiZongRuleResult[];
};

export type LiZongFunnelStep = {
  ruleId: string | null;
  label: string | null;
  removedAtStep: number | null;
  remainingCount: number | null;
};

export type LiZongCandidates = {
  status: string;
  strategyName: string | null;
  strategyBoundary: string | null;
  /** 策略规则字典（rule_id → 文案/分组），用于把 rule_results 翻译成人话。 */
  rules: { ruleId: string; group: string | null; label: string | null }[];
  counts: {
    total: number | null;
    qualified: number | null;
    triggered: number | null;
    notQualified: number | null;
    dataIncomplete: number | null;
    invalidated: number | null;
  };
  funnel: {
    startingCount: number | null;
    finalCandidateCount: number | null;
    asOfDate: string | null;
    scope: string | null;
    boundary: string | null;
    steps: LiZongFunnelStep[];
  } | null;
  dataMeta: {
    latestAsOfDate: string | null;
    universeCount: number | null;
    coverageRatio: number | null;
    fullMarketCoverage: boolean | null;
    remainingSymbols: number | null;
  };
  items: LiZongCandidate[];
  boundary: string | null;
};

function parseLiZongCandidate(raw: unknown): LiZongCandidate | null {
  const root = optionalRecord(raw);
  const symbol = optionalString(root?.symbol) ?? optionalString(root?.internal_symbol);
  if (!root || !symbol) return null;
  const summary = optionalRecord(root.summary);
  return {
    id: optionalString(root.id),
    symbol,
    internalSymbol: optionalString(root.internal_symbol),
    name: optionalString(root.name),
    industry: optionalString(root.industry),
    market: optionalString(root.market),
    asOfDate: optionalString(root.as_of_date),
    status: optionalString(root.evaluation_status) ?? optionalString(root.status),
    previousStatus: optionalString(root.previous_status),
    candidateQualified: optionalBoolean(root.candidate_qualified),
    triggeredRuleIds: strings(root.triggered_rule_ids),
    matchedReasons: strings(root.matched_reasons),
    limitations: strings(root.limitations),
    summary: {
      marketCapYi: optionalNumber(summary?.market_cap_yi),
      roeMinPct: optionalNumber(summary?.roe_min_pct),
      annualRoeYears: optionalNumber(summary?.annual_roe_years),
      annualLimitUpCount: optionalNumber(summary?.annual_limit_up_count),
      recentLimitUpCount: optionalNumber(summary?.recent_limit_up_count),
      nonNaturalHolderCount: optionalNumber(summary?.non_natural_holder_count),
    },
    ruleResults: list(root.rule_results).flatMap((rawRule) => {
      const rule = optionalRecord(rawRule);
      if (!rule) return [];
      return [{
        ruleId: optionalString(rule.rule_id),
        status: optionalString(rule.status),
        source: optionalString(rule.source),
        evidenceDate: optionalString(rule.evidence_date),
        reportPeriod: optionalString(rule.report_period),
        limitations: strings(rule.limitations),
      }];
    }),
  };
}

export function parseLiZongCandidates(value: unknown): LiZongCandidates {
  const root = record(value);
  const strategy = record(root.strategy, "strategy");
  if (strategy.strategy_id !== "li_zong") {
    throw new ContractError("strategy_id 不是 li_zong");
  }
  const version = optionalRecord(strategy.version);
  const counts = optionalRecord(root.counts);
  const funnelRaw = optionalRecord(root.funnel);
  const dataMeta = optionalRecord(root.data_meta);
  return {
    status: optionalString(root.status) ?? "unavailable",
    strategyName: optionalString(strategy.name),
    strategyBoundary: optionalString(strategy.boundary),
    rules: list(version?.rules).flatMap((rawRule) => {
      const rule = optionalRecord(rawRule);
      const ruleId = optionalString(rule?.rule_id);
      if (!rule || !ruleId) return [];
      return [{ ruleId, group: optionalString(rule.group), label: optionalString(rule.label) }];
    }),
    counts: {
      total: optionalNumber(counts?.total),
      qualified: optionalNumber(counts?.qualified),
      triggered: optionalNumber(counts?.triggered),
      notQualified: optionalNumber(counts?.not_qualified),
      dataIncomplete: optionalNumber(counts?.data_incomplete),
      invalidated: optionalNumber(counts?.invalidated),
    },
    funnel: funnelRaw === null ? null : {
      startingCount: optionalNumber(funnelRaw.starting_count),
      finalCandidateCount: optionalNumber(funnelRaw.final_candidate_count),
      asOfDate: optionalString(funnelRaw.as_of_date),
      scope: optionalString(funnelRaw.scope),
      boundary: optionalString(funnelRaw.boundary),
      steps: list(funnelRaw.steps).flatMap((rawStep) => {
        const step = optionalRecord(rawStep);
        if (!step) return [];
        return [{
          ruleId: optionalString(step.rule_id),
          label: optionalString(step.label),
          removedAtStep: optionalNumber(step.removed_at_step),
          remainingCount: optionalNumber(step.remaining_count),
        }];
      }),
    },
    dataMeta: {
      latestAsOfDate: optionalString(dataMeta?.latest_as_of_date),
      universeCount: optionalNumber(dataMeta?.universe_count),
      coverageRatio: optionalNumber(dataMeta?.coverage_ratio),
      fullMarketCoverage: optionalBoolean(dataMeta?.full_market_coverage),
      remainingSymbols: optionalNumber(dataMeta?.remaining_symbols),
    },
    items: list(root.items).flatMap((raw) => {
      const item = parseLiZongCandidate(raw);
      return item ? [item] : [];
    }),
    boundary: optionalString(root.boundary),
  };
}

// ---------- 最近 run（GET /v1/stock-strategies/li-zong/runs/latest） ----------

export type LiZongRunLatest = {
  run: {
    id: string | null;
    status: string | null;
    asOfDate: string | null;
    runScope: string | null;
    universeCount: number | null;
    prefilteredCount: number | null;
    coverageRatio: number | null;
    processedCount: number | null;
    qualifiedCount: number | null;
    triggeredCount: number | null;
    incompleteCount: number | null;
    invalidatedCount: number | null;
    error: string | null;
    startedAt: string | null;
    finishedAt: string | null;
    warnings: string[];
  } | null;
  coverage: {
    status: string | null;
    asOfDate: string | null;
    coverageRatio: number | null;
    fullMarketCoverage: boolean | null;
    deepCheckComplete: boolean | null;
    evaluatedSymbols: number | null;
    remainingSymbols: number | null;
  } | null;
};

export function parseLiZongRunLatest(value: unknown): LiZongRunLatest {
  const root = record(value);
  if (root.strategy_id !== "li_zong") {
    throw new ContractError("strategy_id 不是 li_zong");
  }
  const run = optionalRecord(root.run);
  const coverage = optionalRecord(root.coverage);
  return {
    run: run === null ? null : {
      id: optionalString(run.id),
      status: optionalString(run.status),
      asOfDate: optionalString(run.as_of_date),
      runScope: optionalString(run.run_scope),
      universeCount: optionalNumber(run.universe_count),
      prefilteredCount: optionalNumber(run.prefiltered_count),
      coverageRatio: optionalNumber(run.coverage_ratio),
      processedCount: optionalNumber(run.processed_count),
      qualifiedCount: optionalNumber(run.qualified_count),
      triggeredCount: optionalNumber(run.triggered_count),
      incompleteCount: optionalNumber(run.incomplete_count),
      invalidatedCount: optionalNumber(run.invalidated_count),
      error: optionalString(run.error),
      startedAt: optionalString(run.started_at),
      finishedAt: optionalString(run.finished_at),
      warnings: strings(run.warnings),
    },
    coverage: coverage === null ? null : {
      status: optionalString(coverage.status),
      asOfDate: optionalString(coverage.as_of_date),
      coverageRatio: optionalNumber(coverage.coverage_ratio),
      fullMarketCoverage: optionalBoolean(coverage.full_market_coverage),
      deepCheckComplete: optionalBoolean(coverage.deep_check_complete),
      evaluatedSymbols: optionalNumber(coverage.evaluated_symbols),
      remainingSymbols: optionalNumber(coverage.remaining_symbols),
    },
  };
}

// ---------- 回测（GET /v1/stock-strategies/li-zong/backtest?period=） ----------

export type BacktestPoint = {
  tradeDate: string | null;
  nav: number | null;
  benchmarkNav: number | null;
  holdingCount: number | null;
};

export type BacktestResult = {
  status: string | null;
  periodLabel: string | null;
  startDate: string | null;
  endDate: string | null;
  tradingDays: number | null;
  // 收益/回撤后端已是百分数，直通不缩放。
  periodReturnPct: number | null;
  annualizedReturnPct: number | null;
  annualizedVolatilityPct: number | null;
  maxDrawdownPct: number | null;
  benchmarkReturnPct: number | null;
  benchmarkAnnualizedReturnPct: number | null;
  excessReturnPct: number | null;
  eligibleSymbolCount: number | null;
  completeSymbolCount: number | null;
  incompleteSymbolCount: number | null;
  dataCoverageRatio: number | null;
  everSelectedSymbolCount: number | null;
  selectionUpdateCount: number | null;
  totalTurnoverPct: number | null;
  tradingCostBpsPerSide: number | null;
  generatedAt: string | null;
  dataVersion: string | null;
  boundary: string | null;
  dataCoverageBoundary: string | null;
  points: BacktestPoint[];
};

export type LiZongBacktest = {
  status: string;
  selectedPeriod: string | null;
  periodLabel: string | null;
  backtestVersion: string | null;
  portfolioVersion: string | null;
  progress: {
    status: string | null;
    phase: string | null;
    label: string | null;
    resultAsOfDate: string | null;
    marketDataRatio: number | null;
    availableMarketDays: number | null;
    requiredMarketDays: number | null;
  } | null;
  assumptions: {
    benchmark: string | null;
    weighting: string | null;
    rebalance: string | null;
    costBpsPerSide: number | null;
    priceBasis: string | null;
    cashPolicy: string | null;
    selection: string | null;
  };
  /** 仅当服务端返回完成的回测结果时非空；前端不自行推算。 */
  result: BacktestResult | null;
  boundary: string | null;
};

export function parseLiZongBacktest(value: unknown): LiZongBacktest {
  const root = record(value);
  if (root.strategy_id !== "li_zong") {
    throw new ContractError("strategy_id 不是 li_zong");
  }
  const progress = optionalRecord(root.progress);
  const assumptions = optionalRecord(root.assumptions);
  const result = optionalRecord(root.result);
  return {
    status: optionalString(root.status) ?? "unavailable",
    selectedPeriod: optionalString(root.selected_period),
    periodLabel: optionalString(root.period_label),
    backtestVersion: optionalString(root.backtest_version),
    portfolioVersion: optionalString(root.portfolio_version),
    progress: progress === null ? null : {
      status: optionalString(progress.status),
      phase: optionalString(progress.phase),
      label: optionalString(progress.label),
      resultAsOfDate: optionalString(progress.result_as_of_date),
      marketDataRatio: optionalNumber(progress.market_data_ratio),
      availableMarketDays: optionalNumber(progress.available_market_days),
      requiredMarketDays: optionalNumber(progress.required_market_days),
    },
    assumptions: {
      benchmark: optionalString(assumptions?.benchmark),
      weighting: optionalString(assumptions?.weighting),
      rebalance: optionalString(assumptions?.rebalance),
      costBpsPerSide: optionalNumber(assumptions?.cost_bps_per_side),
      priceBasis: optionalString(assumptions?.price_basis),
      cashPolicy: optionalString(assumptions?.cash_policy),
      selection: optionalString(assumptions?.selection),
    },
    result: result === null ? null : {
      status: optionalString(result.status),
      periodLabel: optionalString(result.period_label),
      startDate: optionalString(result.start_date),
      endDate: optionalString(result.end_date),
      tradingDays: optionalNumber(result.trading_days),
      periodReturnPct: optionalNumber(result.period_return_pct),
      annualizedReturnPct: optionalNumber(result.annualized_return_pct),
      annualizedVolatilityPct: optionalNumber(result.annualized_volatility_pct),
      maxDrawdownPct: optionalNumber(result.max_drawdown_pct),
      benchmarkReturnPct: optionalNumber(result.benchmark_return_pct),
      benchmarkAnnualizedReturnPct: optionalNumber(result.benchmark_annualized_return_pct),
      excessReturnPct: optionalNumber(result.excess_return_pct),
      eligibleSymbolCount: optionalNumber(result.eligible_symbol_count),
      completeSymbolCount: optionalNumber(result.complete_symbol_count),
      incompleteSymbolCount: optionalNumber(result.incomplete_symbol_count),
      dataCoverageRatio: optionalNumber(result.data_coverage_ratio),
      everSelectedSymbolCount: optionalNumber(result.ever_selected_symbol_count),
      selectionUpdateCount: optionalNumber(result.selection_update_count),
      totalTurnoverPct: optionalNumber(result.total_turnover_pct),
      tradingCostBpsPerSide: optionalNumber(result.trading_cost_bps_per_side),
      generatedAt: optionalString(result.generated_at),
      dataVersion: optionalString(result.data_version),
      boundary: optionalString(result.boundary),
      dataCoverageBoundary: optionalString(result.data_coverage_boundary),
      points: list(result.points).flatMap((rawPoint) => {
        const point = optionalRecord(rawPoint);
        if (!point) return [];
        return [{
          tradeDate: optionalString(point.trade_date),
          nav: optionalNumber(point.nav),
          benchmarkNav: optionalNumber(point.benchmark_nav),
          holdingCount: optionalNumber(point.holding_count),
        }];
      }),
    },
    boundary: optionalString(root.boundary),
  };
}
