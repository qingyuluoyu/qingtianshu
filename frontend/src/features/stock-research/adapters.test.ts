import { describe, expect, it } from "vitest";
import {
  ContractError,
  parseAnalystExpectations,
  parseEarningsQuality,
  parseFinancialDrivers,
  parseFundamentals,
  parseObservationTasks,
  parsePeerComparisons,
  parseShareholders,
  parseStockHistory,
  parseStockPage,
  parseWorkspace,
} from "./adapters";

const historyPayload = {
  symbol: "000063.SZ",
  display_name: "中兴通讯",
  exchange: "SHZ",
  currency: "CNY",
  timezone: "Asia/Shanghai",
  source: "Yahoo Finance Chart",
  source_url: "https://query1.finance.yahoo.com/v8/finance/chart",
  data_granularity: "1d",
  regular_market_price: 34.7,
  previous_close: 34.55,
  regular_market_timestamp: "2026-08-06T06:58:39+00:00",
  market_timestamp: "2026-08-05T01:30:00+00:00",
  fetched_at: "2026-08-06T07:13:46+00:00",
  is_stale: false,
  cache_hit: true,
  points: [
    { timestamp: "2026-08-04T01:30:00+00:00", open: 34.35, high: 35.05, low: 34.08, close: 34.55, adjusted_close: 34.13, volume: 60412669 },
    { timestamp: "2026-08-05T01:30:00+00:00", open: 34.0, high: 34.97, low: 33.96, close: 34.74, adjusted_close: 34.74, volume: 166013226 },
  ],
  metrics: {
    latest_close: 34.74,
    change_1d: 0.37,
    return_1d_pct: 1.0765,
    return_5d_pct: 1.9366,
    return_20d_pct: -5.777,
    return_60d_pct: -8.795,
    return_1d_base_date: "2026-08-04T01:30:00+00:00",
    return_1d_end_date: "2026-08-05T01:30:00+00:00",
    return_5d_base_date: "2026-07-29T01:30:00+00:00",
    return_5d_end_date: "2026-08-05T01:30:00+00:00",
    return_20d_base_date: "2026-07-08T01:30:00+00:00",
    return_20d_end_date: "2026-08-05T01:30:00+00:00",
    return_60d_base_date: "2026-05-12T01:30:00+00:00",
    return_60d_end_date: "2026-08-05T01:30:00+00:00",
    ma20: 36.3445,
    ma60: 36.777,
    rsi_14: 33.8452,
    macd_12_26: -0.8883,
    macd_signal_9: -0.7244,
    macd_histogram: -0.1638,
    bollinger_upper_20: 41.5301,
    bollinger_middle_20: 36.3445,
    bollinger_lower_20: 31.1589,
    bollinger_position_20: 0.3453,
    atr_14_pct: 5.0868,
    volume_ratio_5_20: 0.494,
    max_drawdown_60d_pct: -17.8386,
    volatility_20d_annualized_pct: 67.8486,
    trend_state: "中期偏弱",
    technical_state: "动量转弱",
    technical_method: "RSI14、MACD(12,26,9)；只描述已发生的技术结构，不生成买卖信号。",
  },
  coverage: {
    requested_range: "1y",
    points: 2,
    first_timestamp: "2026-08-04T01:30:00+00:00",
    last_timestamp: "2026-08-05T01:30:00+00:00",
    interval: "1d",
    dropped_invalid_ohlc: 0,
    dropped_incomplete_daily: 0,
  },
  warnings: ["上游有 1 根当前交易日未完成日线，已保留上一完整交易日。"],
};

const fundamentalsPayload = {
  symbol: "000063.SZ",
  generated_at: "2026-08-06T07:14:35+00:00",
  warnings: ["市盈率分为 TTM、动态年化与静态口径，三者不可混用。"],
  methodology: ["实时估值来自腾讯完整行情快照。"],
  valuation: {
    price: 34.7,
    previous_close: 34.74,
    pct_change: -0.12,
    pe_ttm: 37.09,
    pe_dynamic: 31.67,
    pe_static: 29.55,
    pb: 2.22,
    total_market_cap: 165989000000,
    float_market_cap: 139758000000,
    turnover_rate_pct: 3.73,
    market_date: "2026-08-06",
    market_timestamp: "2026-08-06T15:05:15+08:00",
    quote_label: "收盘后最新报价",
    current_session_label: "已收盘",
    source: "Tencent Finance Realtime Quote",
    currency: "CNY",
    fetched_at: "2026-08-06T07:05:23+00:00",
    warnings: ["估值倍数是事实快照，不代表便宜或昂贵。"],
  },
  financial_periods: [
    {
      report_date: "2026-03-31",
      report_date_name: "2026一季报",
      report_type: "一季报",
      notice_date: "2026-04-25",
      revenue: 34988057000,
      parent_net_profit: 1310444000,
      revenue_yoy_pct: 6.126696,
      net_profit_yoy_pct: -46.58165,
      gross_margin_pct: 28.276157,
      net_margin_pct: 3.767657,
      roe_weighted_pct: 1.72,
      debt_asset_ratio_pct: 65.870976,
      eps_basic: 0.27,
      book_value_per_share: 16.031486,
      operating_cashflow: -1978648000,
      operating_cashflow_per_share: -0.413637,
      total_assets: 225724240000,
      total_equity: 77037480000,
      period_basis: "year_to_date_cumulative",
      source: "Eastmoney F10 Main Financial Data",
      currency: "CNY",
    },
  ],
};

const workspacePayload = {
  contract_version: "stock_workspace_v1",
  symbol: "000063.SZ",
  name: "中兴通讯",
  relation: { label: "尚未加入关注", in_watchlist: false, preview_state: "candidate" },
  thesis: { status: "empty", summary: null, updated_at: null, version: null },
  completeness: {
    has_stock_space: false,
    has_thesis: false,
    has_research_session: false,
    has_latest_report: true,
    missing_items: ["尚未加入股票研究空间", "尚未建立当前判断"],
  },
  stage_progress: { status: "not_started", current_stage: null, next_question: null, progress: { completed: 0, total: 7, percent: 0 }, updated_at: null },
  overview: {
    data_status: "ready",
    quote: { price: 34.69, pct_change: -0.14, daily_close: 34.74, daily_return_1d_pct: 1.0765, market_timestamp: "2026-08-06T14:50:06+08:00", label: "盘中最新报价", currency: "CNY" },
    latest_change: {
      id: "d87ec1fc",
      summary: "中兴通讯数据时间已更新，核心研究判断暂未出现实质变化。",
      severity: "stable",
      event_type: "evidence_change",
      created_at: "2026-08-06T06:50:12+00:00",
      data_as_of: "2026-08-05T01:30:00+00:00",
      next_review: { focus: "确认短期价格结构与信息增量" },
    },
  },
  important_changes: [
    {
      id: "d87ec1fc",
      summary: "中兴通讯数据时间已更新，核心研究判断暂未出现实质变化。",
      severity: "stable",
      event_type: "evidence_change",
      created_at: "2026-08-06T06:50:12+00:00",
      data_as_of: "2026-08-05T01:30:00+00:00",
      next_review: { focus: "确认短期价格结构与信息增量" },
    },
  ],
  next_evidence: [
    { status: "watching", source: "tracking_plan", description: "收盘与 MA20 36.3445 的相对位置是否变化" },
  ],
  pending_actions: [],
  observation_tasks: {
    items: [],
    summary: { total: 0, active: 0, pending: 0, in_progress: 0, completed: 0, waiting_data: 0 },
    boundary: "观察任务只保存需要核验的事实；不是交易指令。",
  },
  position_snapshot: { available: false, status: "not_configured" },
  history_summary: {
    change_count: 3,
    observation_task_count: 0,
    recent_report_count: 3,
    thesis_version_count: 0,
    latest_report_at: "2026-08-06T06:50:12+00:00",
    latest_change_at: "2026-08-06T06:50:12+00:00",
  },
  latest_report: { id: "r-1", title: "中兴通讯 每日研究", status: "ready", generated_at: "2026-08-06T06:50:12+00:00", market_timestamp: "2026-08-05T01:30:00+00:00" },
  data_meta: {
    status: "ready",
    quote_as_of: "2026-08-06T14:50:06+08:00",
    daily_as_of: "2026-08-05T01:30:00+00:00",
    financial_report_period: "2026-03-31",
    report_generated_at: "2026-08-06T06:50:12+00:00",
  },
  boundary: "股票研究空间不提供无来源综合评分、自产目标价或确定性买卖建议。",
};

function stockPagePayload(overrides: Record<string, unknown> = {}) {
  return {
    contract_version: "stock_page_v1",
    symbol: "000063.SZ",
    market: "a_share",
    status: "ready",
    summary: { available: 9, failed: 0, total: 9, required_failed: [] },
    modules: {
      history: { status: "available", data: historyPayload },
      fundamentals: { status: "available", data: fundamentalsPayload },
      workspace: { status: "available", data: workspacePayload },
      information: { status: "available", data: { announcements: [], news: [], social_posts: [], sentiment: null, methodology: [], generated_at: "2026-08-06T07:14:35+00:00" } },
      shareholders: { status: "available", data: { status: "available", holder_count: 637909, holder_count_as_of: "2026-07-31", previous_holder_count: 620081, holder_count_change_pct: 2.875108251986, holder_count_signal: "dispersion_clue", holder_count_signal_label: "持有人分散线索", top10_ratio_pct: 41.34, top3_ratio_pct: 36.96, top10_report_date: "2026-03-31", top_holders: [{ rank: 1, name: "中兴新通讯有限公司", holding: 960978400, holding_ratio_pct: 20.09, holding_change: "不变" }], average_holding: 6314.43, summary: "股东户数较上次变化 +2.875%。", boundary: "股东户数下降仅是持股集中度线索。", announced_at: "2026-08-03", latest_fetched_at: "2026-08-06T06:21:52+00:00" } },
      event_timeline: { status: "available", data: { status: "available", as_of_date: "2026-08-05", themes: [{ event_type: "contract_order", label: "订单与合同", count: 5 }], recent_official_events: [], supportive_events: [], risk_events: [], coverage: { official_events: 17, media_events: 8, events_returned: 25, risk_events: 0 }, review_points: [], boundary: "事件分类由确定性关键词规则生成。", generated_at: "2026-08-06T07:14:35+00:00" } },
      earnings_quality: { status: "available", data: { status: "available", overall_label: "盈利质量承压", summary: "最新财报为2026一季报。", confidence: "high", factors: [{ key: "revenue_growth", label: "营收增速", status: "support", value_pct: 6.1267, comparable_pct: 7.8157, change_pp: -1.689, interpretation: "同比 6.13%。" }], contradictions: ["营收增长但净利润下降。"], review_points: [], latest_report: { report_date_name: "2026一季报", report_date: "2026-03-31" }, comparable_report: { report_date_name: "2025一季报" }, coverage: { periods: 8, comparable: true, available_fields: 8 }, boundary: "财报质量分析不等于公司好坏判断。", generated_at: "2026-08-06T07:14:35+00:00" } },
      financial_drivers: { status: "available", data: { status: "available", overall_label: "利润与经营现金流双重承压", summary: "归母净利润变化 -11.427 亿元。", confidence: "high", confirmed_mechanical_drivers: [{ key: "net_profit_change", label: "归母净利润变化", statement: "归母净利润较上一年度同类报告期变化 -11.427 亿元。", amount: -1142728000, direction: "negative", currency: "CNY", attribution_level: "confirmed" }], plausible_clues: [{ key: "inventory", label: "存货增速快于收入", evidence: "存货同比 +16.899%。" }], expense_analysis: [{ key: "sales_expense", label: "销售费用", current: 2018281000, comparable: 2302224000, current_ratio_pct: 5.768, comparable_ratio_pct: 6.983, ratio_change_pp: -1.215 }], working_capital_analysis: [{ key: "inventory", label: "存货", current: 51959114000, comparable: 44447940000, growth_pct: 16.899, growth_minus_revenue_pp: 10.772 }], cashflow_analysis: { operating_cashflow: -1978648000, investing_cashflow: -5689949000, operating_cashflow_change_pct: -206.882, cash_received_from_sales_ratio_change_pp: -10.285 }, company_explanations: [{ label: "财务费用、汇兑与利息", excerpt: "财务费用 340,974 千元。", report_title: "中兴通讯:2026年第一季度报告", notice_date: "2026-04-25", report_period: "2026-03-31", classification: "explicit_company_explanation" }], unresolved_causes: ["毛利率变化已量化，具体原因尚未确认。"], review_points: [], profit_bridge: { net_profit_change: -1142728000, gross_margin_change_pp: -5.995, currency: "CNY" }, boundary: "该分析不构成利润预测、目标价或交易指令。", generated_at: "2026-08-06T07:14:35+00:00" } },
      analyst_expectations: { status: "available", data: { status: "available", as_of_date: "2026-05-05", industry: "通信设备", rating_statement: "近六个月统计覆盖 9 家机构：买入 7，增持 2。", rating_window: "近六个月", rating_counts: { buy: 7, add: 2, neutral: 0, reduce: 0, sell: 0 }, rating_organization_count: 9, forecast_eps: [{ year: 2025, kind: "actual", value: 1.174392 }, { year: 2026, kind: "estimate", value: 1.335667 }], forecast_statement: "每股收益汇总为：2025A 1.174392，2026E 1.335667。", revision: { available: true, summary: "同财年EPS和评级覆盖未见可计算变化。", previous_snapshot_at: "2026-08-03T06:21:11+00:00" }, latest_reports: [{ title: "连接+算力双轮驱动", institution: "国金证券", researchers: "张真桢", published_at: "2026-05-05", rating: "买入", previous_rating: "买入", report_url: "https://example.com/r1" }], coverage: { estimate_years: 3, forecast_years: 4, rating_organizations: 9, reports_returned: 16 }, review_points: [], boundary: "评级分布不构成买卖建议；目标价字段不进入证据包。", generated_at: "2026-08-06T06:21:58+00:00" } },
    },
    ...overrides,
  };
}

describe("stock-research adapters", () => {
  it("locks the aggregate contract version and module envelope statuses", () => {
    const page = parseStockPage(stockPagePayload());
    expect(page.symbol).toBe("000063.SZ");
    expect(page.status).toBe("ready");
    expect(page.summary).toEqual({ available: 9, failed: 0, total: 9, requiredFailed: [] });
    expect(page.modules.history.status).toBe("available");
    expect(page.modules.history.data?.points).toHaveLength(2);
    expect(() => parseStockPage({ contract_version: "other", modules: {}, summary: {} })).toThrow(ContractError);
  });

  it("keeps a failed module isolated instead of dropping the whole page", () => {
    const payload = stockPagePayload();
    (payload.modules as Record<string, unknown>).shareholders = { status: "unavailable", reason: "上游数据源失败", data: null };
    const page = parseStockPage(payload);
    expect(page.modules.shareholders.status).toBe("unavailable");
    expect(page.modules.shareholders.reason).toBe("上游数据源失败");
    expect(page.modules.shareholders.data).toBeNull();
    expect(page.modules.history.data?.metrics.latestClose).toBe(34.74);
  });

  it("passes percent, ratio and price metrics through unscaled", () => {
    const history = parseStockHistory(historyPayload);
    // *_pct 已是百分数，直通锁。
    expect(history.metrics.return1dPct).toBe(1.0765);
    expect(history.metrics.return20dPct).toBe(-5.777);
    expect(history.metrics.atr14Pct).toBe(5.0868);
    expect(history.metrics.maxDrawdown60dPct).toBe(-17.8386);
    expect(history.metrics.volatility20dAnnualizedPct).toBe(67.8486);
    // 0-1 小数量比，不乘 100。
    expect(history.metrics.volumeRatio5to20).toBe(0.494);
    expect(history.metrics.bollingerPosition20).toBe(0.3453);
    // 价格原值直通。
    expect(history.metrics.latestClose).toBe(34.74);
    expect(history.points[1]?.close).toBe(34.74);
    expect(history.coverage.lastTimestamp).toBe("2026-08-05T01:30:00+00:00");
    expect(history.dataGranularity).toBe("1d");
  });

  it("passes raw CNY amounts and percent fields through without rescaling", () => {
    const fundamentals = parseFundamentals(fundamentalsPayload);
    const period = fundamentals.periods[0];
    // 接口单位为元，adapter 不做亿元换算。
    expect(period?.revenue).toBe(34988057000);
    expect(period?.parentNetProfit).toBe(1310444000);
    expect(period?.operatingCashflow).toBe(-1978648000);
    // 百分数直通锁。
    expect(period?.revenueYoyPct).toBe(6.126696);
    expect(period?.netProfitYoyPct).toBe(-46.58165);
    expect(period?.grossMarginPct).toBe(28.276157);
    expect(period?.debtAssetRatioPct).toBe(65.870976);
    expect(fundamentals.valuation?.totalMarketCap).toBe(165989000000);
    expect(fundamentals.valuation?.peTtm).toBe(37.09);
  });

  it("keeps earnings factor percent and pp values unscaled", () => {
    const quality = parseEarningsQuality(stockPagePayload().modules.earnings_quality.data);
    expect(quality.factors[0]?.valuePct).toBe(6.1267);
    expect(quality.factors[0]?.comparablePct).toBe(7.8157);
    expect(quality.factors[0]?.changePp).toBe(-1.689);
    expect(quality.overallLabel).toBe("盈利质量承压");
    expect(quality.latestReportDateName).toBe("2026一季报");
  });

  it("keeps driver amounts in yuan and ratios unscaled", () => {
    const drivers = parseFinancialDrivers(stockPagePayload().modules.financial_drivers.data);
    expect(drivers.confirmedDrivers[0]?.amount).toBe(-1142728000);
    expect(drivers.expenseAnalysis[0]?.current).toBe(2018281000);
    expect(drivers.expenseAnalysis[0]?.currentRatioPct).toBe(5.768);
    expect(drivers.expenseAnalysis[0]?.ratioChangePp).toBe(-1.215);
    expect(drivers.workingCapital[0]?.growthPct).toBe(16.899);
    expect(drivers.cashflow?.operatingCashflowChangePct).toBe(-206.882);
    expect(drivers.profitBridge?.grossMarginChangePp).toBe(-5.995);
  });

  it("distinguishes empty thesis from missing data and never fabricates progress", () => {
    const workspace = parseWorkspace(workspacePayload);
    expect(workspace.thesis.status).toBe("empty");
    expect(workspace.thesis.summary).toBeNull();
    expect(workspace.stageProgress.status).toBe("not_started");
    expect(workspace.stageProgress.progress).toEqual({ completed: 0, total: 7, percent: 0 });
    expect(workspace.completeness.hasThesis).toBe(false);
    expect(workspace.quote?.pctChange).toBe(-0.14);
    expect(workspace.quote?.dailyReturn1dPct).toBe(1.0765);
    expect(workspace.observationTasksSummary.total).toBe(0);
  });

  it("passes shareholder percents and raw share counts through", () => {
    const shareholders = parseShareholders(stockPagePayload().modules.shareholders.data);
    expect(shareholders.holderCount).toBe(637909);
    expect(shareholders.holderCountChangePct).toBe(2.875108251986);
    expect(shareholders.top10RatioPct).toBe(41.34);
    expect(shareholders.topHolders[0]?.holding).toBe(960978400);
    expect(shareholders.topHolders[0]?.holdingRatioPct).toBe(20.09);
  });

  it("passes forecast EPS through unscaled and keeps rating counts factual", () => {
    const expectations = parseAnalystExpectations(stockPagePayload().modules.analyst_expectations.data);
    expect(expectations.forecastEps[0]).toEqual({ year: 2025, kind: "actual", value: 1.174392 });
    expect(expectations.forecastEps[1]).toEqual({ year: 2026, kind: "estimate", value: 1.335667 });
    expect(expectations.ratingCounts).toEqual({ buy: 7, add: 2, neutral: 0, reduce: 0, sell: 0 });
    expect(expectations.revision?.summary).toContain("未见可计算变化");
    expect(expectations.latestReports[0]?.rating).toBe("买入");
  });

  it("keeps peer multiples, raw market cap and 0-1 ratio distinct", () => {
    const peers = parsePeerComparisons({
      symbol: "000063.SZ",
      group_label: "通信设备固定同行样本",
      selection_basis: "业务相邻且可得同一时点估值源一致快照",
      as_of: "2026-08-06T15:05:15+08:00",
      subject: { symbol: "000063.SZ", name: "中兴通讯", pe_ttm: 37.09, pb: 2.22, total_market_cap: 165989000000, market_timestamp: "2026-08-06T15:05:15+08:00", currency: "CNY", source: "Tencent Finance Realtime Quote" },
      peers: [{ symbol: "600498.SS", name: "烽火通信", pe_ttm: 122.49, pb: 2.94, total_market_cap: 51325000000, market_timestamp: "2026-08-06T15:21:22+08:00", currency: "CNY", source: "Tencent Finance Realtime Quote" }],
      warnings: ["同行样本由产品固定配置，不是完整行业指数或投资评级。"],
      coverage: { available_peers: 1, requested_peers: 3 },
      operating_comparison: {
        status: "available",
        anchor_report_date_name: "2026一季报",
        anchor_period_basis: "year_to_date_cumulative",
        metrics: {
          revenue_yoy_pct: { subject_value: 6.126696, peer_median: 18.261644, peer_min: 11.402562, peer_max: 34.608772, peer_sample_size: 3 },
          operating_cashflow_to_net_profit: { subject_value: -1.5099, peer_median: -11.9432, peer_min: -20.5236, peer_max: -3.9252, peer_sample_size: 3 },
        },
        warnings: [],
      },
    });
    expect(peers.subject?.peTtm).toBe(37.09);
    expect(peers.subject?.totalMarketCap).toBe(165989000000);
    expect(peers.peers[0]?.peTtm).toBe(122.49);
    const metrics = peers.operatingComparison?.metrics ?? [];
    expect(metrics.find((m) => m.key === "营收同比")?.subjectValue).toBe(6.126696);
    // 0-1 比值直通，UI 层才乘 100。
    expect(metrics.find((m) => m.key === "经营现金流/净利润")?.subjectValue).toBe(-1.5099);
  });

  it("keeps 0, empty string, missing field and failure as four distinct states", () => {
    const history = parseStockHistory({
      points: [],
      metrics: { rsi_14: 0, macd_12_26: null, trend_state: "" },
      coverage: {},
    });
    // 0 是有效数值，不得显示为缺失。
    expect(history.metrics.rsi14).toBe(0);
    // null / 缺字段 → null（显示 --）。
    expect(history.metrics.macd1226).toBeNull();
    expect(history.metrics.return1dPct).toBeNull();
    // 空字符串 → null（与 0 区分）。
    expect(history.metrics.trendState).toBeNull();
    // 接口失败在 api 层抛错，不进入 adapter；此处验证空列表不是 null。
    expect(history.points).toEqual([]);
  });

  it("parses observation task summaries without inventing items", () => {
    const tasks = parseObservationTasks({
      items: [],
      summary: { total: 0, active: 0, pending: 0, in_progress: 0, completed: 0, waiting_data: 0 },
      boundary: "观察任务只保存需要核验的事实。",
    });
    expect(tasks.items).toEqual([]);
    expect(tasks.summary.total).toBe(0);
    expect(tasks.boundary).toContain("核验");
  });
});
