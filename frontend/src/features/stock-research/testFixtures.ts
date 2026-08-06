import { parseStockPage, parseStockHistory, parsePeerComparisons, parseObservationTasks, type StockPage } from "./adapters";

// 与 adapters.test.ts 同口径的最小真实形状 fixture，供 Page 测试水合 QueryClient 使用。

export function historyFixture() {
  return {
    symbol: "000063.SZ",
    display_name: "中兴通讯",
    exchange: "SHZ",
    currency: "CNY",
    timezone: "Asia/Shanghai",
    source: "Yahoo Finance Chart",
    data_granularity: "1d",
    regular_market_price: 34.7,
    previous_close: 34.55,
    regular_market_timestamp: "2026-08-06T06:58:39+00:00",
    market_timestamp: "2026-08-05T01:30:00+00:00",
    fetched_at: "2026-08-06T07:13:46+00:00",
    is_stale: false,
    points: Array.from({ length: 30 }, (_, index) => ({
      timestamp: `2026-07-${String((index % 28) + 1).padStart(2, "0")}T01:30:00+00:00`,
      open: 33 + index * 0.05,
      high: 34 + index * 0.05,
      low: 32.5 + index * 0.05,
      close: 33.8 + index * 0.05,
      adjusted_close: 33.6 + index * 0.05,
      volume: 60_000_000 + index * 1000,
    })),
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
      technical_method: "只描述已发生的技术结构，不生成买卖信号。",
    },
    coverage: {
      requested_range: "1y",
      points: 30,
      first_timestamp: "2026-07-01T01:30:00+00:00",
      last_timestamp: "2026-08-05T01:30:00+00:00",
      interval: "1d",
      dropped_invalid_ohlc: 0,
      dropped_incomplete_daily: 0,
    },
    warnings: [],
  };
}

export function workspaceFixture() {
  return {
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
      latest_change: { id: "c-1", summary: "核心研究判断暂未出现实质变化。", severity: "stable", event_type: "evidence_change", created_at: "2026-08-06T06:50:12+00:00", data_as_of: "2026-08-05T01:30:00+00:00", next_review: { focus: "确认短期价格结构与信息增量" } },
    },
    important_changes: [
      { id: "c-1", summary: "核心研究判断暂未出现实质变化。", severity: "stable", event_type: "evidence_change", created_at: "2026-08-06T06:50:12+00:00", data_as_of: "2026-08-05T01:30:00+00:00", next_review: { focus: "确认短期价格结构与信息增量" } },
    ],
    next_evidence: [{ status: "watching", source: "tracking_plan", description: "收盘与 MA20 36.3445 的相对位置是否变化" }],
    pending_actions: [],
    observation_tasks: { items: [], summary: { total: 0, active: 0, pending: 0, in_progress: 0, completed: 0, waiting_data: 0 }, boundary: "观察任务只保存需要核验的事实；不是交易指令。" },
    position_snapshot: { available: false, status: "not_configured" },
    history_summary: { change_count: 3, observation_task_count: 0, recent_report_count: 3, thesis_version_count: 0, latest_report_at: "2026-08-06T06:50:12+00:00", latest_change_at: "2026-08-06T06:50:12+00:00" },
    latest_report: { id: "r-1", title: "中兴通讯 每日研究", status: "ready", generated_at: "2026-08-06T06:50:12+00:00", market_timestamp: "2026-08-05T01:30:00+00:00" },
    data_meta: { status: "ready", quote_as_of: "2026-08-06T14:50:06+08:00", daily_as_of: "2026-08-05T01:30:00+00:00", financial_report_period: "2026-03-31", report_generated_at: "2026-08-06T06:50:12+00:00" },
    boundary: "股票研究空间不提供无来源综合评分、自产目标价或确定性买卖建议。",
  };
}

export function stockPageFixture(overrides: { modules?: Record<string, unknown>; summary?: Record<string, unknown> } = {}) {
  return {
    contract_version: "stock_page_v1",
    symbol: "000063.SZ",
    market: "a_share",
    status: "ready",
    summary: { available: 9, failed: 0, total: 9, required_failed: [], ...overrides.summary },
    modules: {
      history: { status: "available", data: historyFixture() },
      fundamentals: {
        status: "available",
        data: {
          symbol: "000063.SZ",
          generated_at: "2026-08-06T07:14:35+00:00",
          warnings: ["市盈率分为 TTM、动态年化与静态口径，三者不可混用。"],
          methodology: [],
          valuation: { price: 34.7, previous_close: 34.74, pct_change: -0.12, pe_ttm: 37.09, pe_dynamic: 31.67, pe_static: 29.55, pb: 2.22, total_market_cap: 165989000000, float_market_cap: 139758000000, turnover_rate_pct: 3.73, market_date: "2026-08-06", market_timestamp: "2026-08-06T15:05:15+08:00", current_session_label: "已收盘", source: "Tencent Finance Realtime Quote", currency: "CNY", warnings: ["估值倍数是事实快照。"] },
          financial_periods: [
            { report_date: "2026-03-31", report_date_name: "2026一季报", report_type: "一季报", notice_date: "2026-04-25", revenue: 34988057000, parent_net_profit: 1310444000, revenue_yoy_pct: 6.126696, net_profit_yoy_pct: -46.58165, gross_margin_pct: 28.276157, net_margin_pct: 3.767657, roe_weighted_pct: 1.72, debt_asset_ratio_pct: 65.870976, eps_basic: 0.27, period_basis: "year_to_date_cumulative", source: "Eastmoney F10 Main Financial Data", currency: "CNY" },
            { report_date: "2025-12-31", report_date_name: "2025年报", report_type: "年报", notice_date: "2026-03-07", revenue: 133895460000, parent_net_profit: 5617745000, revenue_yoy_pct: 4.2, net_profit_yoy_pct: 3.1, gross_margin_pct: 31.5, net_margin_pct: 4.2, roe_weighted_pct: 7.5, debt_asset_ratio_pct: 66.1, eps_basic: 1.17, period_basis: "annual", source: "Eastmoney F10 Main Financial Data", currency: "CNY" },
          ],
        },
      },
      workspace: { status: "available", data: workspaceFixture() },
      information: {
        status: "available",
        data: {
          announcements: [{ title: "中兴通讯:2025年度A股权益分派实施公告", url: "https://example.com/a1", source: "Eastmoney Announcements", published_at: "2026-08-04T16:48:06+08:00", category: "announcement", summary: null }],
          news: [{ title: "中兴路由器G5TS Pro 5G CPE开售", url: "https://example.com/n1", source: "Sina Finance Company News", published_at: "2026-08-06T12:51:00+08:00", category: "news", summary: null }],
          social_posts: [],
          sentiment: { confidence: "low", evidence: { caveat: "社区表达存在噪声、反讽和操纵风险。" }, sample_size: 0 },
          methodology: [],
          generated_at: "2026-08-06T07:14:35+00:00",
        },
      },
      shareholders: {
        status: "available",
        data: { status: "available", holder_count: 637909, holder_count_as_of: "2026-07-31", previous_holder_count: 620081, holder_count_change_pct: 2.875108251986, holder_count_signal: "dispersion_clue", holder_count_signal_label: "持有人分散线索", top10_ratio_pct: 41.34, top3_ratio_pct: 36.96, top10_report_date: "2026-03-31", top_holders: [{ rank: 1, name: "中兴新通讯有限公司", holding: 960978400, holding_ratio_pct: 20.09, holding_change: "不变" }], average_holding: 6314.43, summary: "股东户数较上次变化 +2.875%。", boundary: "股东户数下降仅是持股集中度线索。", announced_at: "2026-08-03", latest_fetched_at: "2026-08-06T06:21:52+00:00" },
      },
      event_timeline: {
        status: "available",
        data: {
          status: "available",
          as_of_date: "2026-08-05",
          themes: [{ event_type: "contract_order", label: "订单与合同", count: 5 }, { event_type: "capital_return", label: "回购与股东回报", count: 7 }],
          recent_official_events: [{ title: "中兴通讯:关于证券变动月报表的公告", url: "https://example.com/e1", event_label: "其他官方披露", event_type: "other", category: "announcement", evidence_label: "公司公告", source: "Eastmoney Announcements", published_at: "2026-08-04T16:48:06+08:00", event_date: "2026-08-04", event_status: "confirmed_disclosure", research_relevance_label: "中性事件" }],
          supportive_events: [{ title: "中兴通讯中标中国铁塔采购项目", url: "https://example.com/e2", event_label: "订单与合同", event_type: "contract_order", category: "news", evidence_label: "媒体报道", source: "Sina Finance Company News", published_at: "2026-08-05T08:55:00+08:00", event_date: "2026-08-05", event_status: "reported_clue", research_relevance_label: "可能的支持事件" }],
          risk_events: [],
          coverage: { official_events: 17, media_events: 8, events_returned: 25, risk_events: 0 },
          review_points: [],
          boundary: "事件分类由确定性关键词规则生成；不估算事件概率、股价影响或交易方向。",
          generated_at: "2026-08-06T07:14:35+00:00",
        },
      },
      earnings_quality: {
        status: "available",
        data: { status: "available", overall_label: "盈利质量承压", summary: "营收增长但净利润下降。", confidence: "high", factors: [{ key: "revenue_growth", label: "营收增速", status: "support", value_pct: 6.1267, comparable_pct: 7.8157, change_pp: -1.689, interpretation: "同比 6.13%，较可比期变化 -1.69 个百分点。" }], contradictions: ["营收增长但净利润下降。"], review_points: [], latest_report: { report_date_name: "2026一季报", report_date: "2026-03-31" }, comparable_report: { report_date_name: "2025一季报" }, coverage: { periods: 8, comparable: true, available_fields: 8 }, boundary: "财报质量分析不等于公司好坏或股票涨跌判断。", generated_at: "2026-08-06T07:14:35+00:00" },
      },
      financial_drivers: {
        status: "available",
        data: { status: "available", overall_label: "利润与经营现金流双重承压", summary: "归母净利润变化 -11.427 亿元。", confidence: "high", confirmed_mechanical_drivers: [{ key: "net_profit_change", label: "归母净利润变化", statement: "归母净利润较上一年度同类报告期变化 -11.427 亿元。", amount: -1142728000, direction: "negative", currency: "CNY", attribution_level: "confirmed" }], plausible_clues: [{ key: "inventory", label: "存货增速快于收入", evidence: "存货同比 +16.899%。" }], expense_analysis: [], working_capital_analysis: [], cashflow_analysis: { operating_cashflow: -1978648000, investing_cashflow: -5689949000, operating_cashflow_change_pct: -206.882, cash_received_from_sales_ratio_change_pp: -10.285 }, company_explanations: [{ label: "财务费用、汇兑与利息", excerpt: "财务费用变动主要因汇率波动。", report_title: "中兴通讯:2026年第一季度报告", notice_date: "2026-04-25", report_period: "2026-03-31", classification: "explicit_company_explanation" }], unresolved_causes: ["毛利率变化具体原因尚未确认。"], review_points: [], profit_bridge: { net_profit_change: -1142728000, gross_margin_change_pp: -5.995, currency: "CNY" }, boundary: "该分析不构成利润预测、目标价或交易指令。", generated_at: "2026-08-06T07:14:35+00:00" },
      },
      analyst_expectations: {
        status: "available",
        data: { status: "available", as_of_date: "2026-05-05", industry: "通信设备", rating_statement: "近六个月统计覆盖 9 家机构：买入 7，增持 2。", rating_window: "近六个月", rating_counts: { buy: 7, add: 2, neutral: 0, reduce: 0, sell: 0 }, rating_organization_count: 9, forecast_eps: [{ year: 2025, kind: "actual", value: 1.174392 }, { year: 2026, kind: "estimate", value: 1.335667 }], forecast_statement: "每股收益汇总：2025A 1.174392，2026E 1.335667。", revision: { available: true, summary: "同财年EPS和评级覆盖未见可计算变化。", previous_snapshot_at: "2026-08-03T06:21:11+00:00" }, latest_reports: [{ title: "连接+算力双轮驱动", institution: "国金证券", researchers: "张真桢", published_at: "2026-05-05", rating: "买入", previous_rating: "买入", report_url: "https://example.com/r1" }], coverage: { estimate_years: 3, forecast_years: 4, rating_organizations: 9, reports_returned: 16 }, review_points: [], boundary: "评级分布不构成买卖建议；目标价字段不进入证据包。", generated_at: "2026-08-06T06:21:58+00:00" },
      },
      ...overrides.modules,
    },
  };
}

export function parsedStockPage(overrides?: Parameters<typeof stockPageFixture>[0]): StockPage {
  return parseStockPage(stockPageFixture(overrides));
}

export const parsedHistory = () => parseStockHistory(historyFixture());

export const parsedPeers = () => parsePeerComparisons({
  symbol: "000063.SZ",
  group_label: "通信设备固定同行样本",
  selection_basis: "业务相邻且可得同一时点估值源一致快照",
  as_of: "2026-08-06T15:05:15+08:00",
  subject: { symbol: "000063.SZ", name: "中兴通讯", pe_ttm: 37.09, pb: 2.22, total_market_cap: 165989000000, market_timestamp: "2026-08-06T15:05:15+08:00", currency: "CNY", source: "Tencent Finance Realtime Quote" },
  peers: [{ symbol: "600498.SS", name: "烽火通信", pe_ttm: 122.49, pb: 2.94, total_market_cap: 51325000000, market_timestamp: "2026-08-06T15:21:22+08:00", currency: "CNY", source: "Tencent Finance Realtime Quote" }],
  warnings: ["同行样本由产品固定配置，不是完整行业指数或投资评级。"],
  coverage: { available_peers: 1, requested_peers: 3 },
  operating_comparison: { status: "available", anchor_report_date_name: "2026一季报", anchor_period_basis: "year_to_date_cumulative", metrics: { revenue_yoy_pct: { subject_value: 6.126696, peer_median: 18.261644, peer_min: 11.402562, peer_max: 34.608772, peer_sample_size: 3 } }, warnings: [] },
});

export const parsedTasks = () => parseObservationTasks({
  items: [],
  summary: { total: 0, active: 0, pending: 0, in_progress: 0, completed: 0, waiting_data: 0 },
  boundary: "观察任务只保存需要核验的事实；不是交易指令。",
});
