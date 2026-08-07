import { describe, expect, it } from "vitest";
import {
  ContractError,
  parseBreadth,
  parseCapitalFlow,
  parseDataHealth,
  parseGlobalIndices,
  parseIndexHistory,
  parseIndices,
  parseLatestResearchReports,
  parseLiveMarkets,
  parseMarketAnomalies,
  parseOverview,
  parsePositions,
  parseSectors,
} from "./adapters";

describe("today runtime contract adapters", () => {
  it("keeps the five required China index cards and passes percent values through unscaled", () => {
    const result = parseIndices({
      generated_at: "2026-08-04T02:35:07+00:00",
      indices: [
        ["000001.SS", "上证综指", 3809.66, -0.5897],
        ["399001.SZ", "深证成指", 13448.29, -0.9621],
        ["399006.SZ", "创业板指", 3302.55, -1.2384],
        ["000688.SS", "科创50", 1552.89, -5.0778],
        ["000300.SS", "沪深300", 4543.18, -0.9812],
        ["000905.SS", "中证500", 7414.52, -1.0604],
      ].map(([symbol, name, close, change]) => ({
        symbol,
        name,
        status: "available",
        metrics: { latest_close: close, change_1d: 9.31, return_1d_pct: change },
        market_timestamp: "2026-08-03T01:30:00+00:00",
        is_stale: false,
      })),
    });

    expect(result.items.map((item) => item.symbol)).toEqual([
      "000001.SS",
      "399001.SZ",
      "399006.SZ",
      "000300.SS",
      "000688.SS",
    ]);
    expect(result.items[3]?.name).toBe("沪深300");
    // change_1d and return_1d_pct are already point/percentage values from the backend; the adapter must not rescale them.
    expect(result.items[0]?.change1d).toBe(9.31);
    expect(result.items[0]?.return1dPct).toBe(-0.5897);
    expect(result.items).toHaveLength(5);
  });

  it("keeps a daily close explicitly separate from a realtime index quote", () => {
    const result = parseIndices({
      indices: [{
        symbol: "000001.SS",
        name: "上证综指",
        status: "available",
        metrics: { latest_close: 3348.37, change_1d: 9.31, return_1d_pct: 0.28 },
        market_timestamp: "2026-08-07T14:30:05+08:00",
        daily_market_timestamp: "2026-08-06T01:30:00+00:00",
        data_granularity: "realtime_quote",
        is_stale: false,
      }],
    });

    expect(result.items[0]).toMatchObject({
      dataGranularity: "realtime_quote",
      dailyMarketTimestamp: "2026-08-06T01:30:00+00:00",
    });
  });

  it("does not turn nullable or missing breadth values into zero", () => {
    const result = parseBreadth({
      status: "available",
      market_timestamp: null,
      market_date: "2026-08-04",
      is_stale: false,
      breadth: {
        total: 5535,
        advancers: 3549,
        decliners: 1804,
        unchanged: 182,
        advance_ratio: 0.6412,
        decline_ratio: 0.3259,
        unchanged_ratio: 0.0329,
        state: "上涨家数占优",
      },
      turnover: {
        status: "unavailable",
        total_amount_100m_cny: null,
        history_comparison: { status: "available", change_vs_previous_pct: -5.41 },
      },
      distribution: {
        status: "available",
        median_pct_change: 0.679,
        bins: {
          strong_advancers_ge_3: 512,
          mild_advancers_gt_0_lt_3: 3037,
          unchanged: 182,
          mild_decliners_lt_0_gt_neg3: 1500,
          strong_decliners_le_neg3: 304,
        },
      },
      coverage: { coverage_ratio: 0.9671 },
    });

    expect(result.marketTimestamp).toBeNull();
    expect(result.turnover100mCny).toBeNull();
    // median_pct_change and change_vs_previous_pct are percentages; ratios are 0-1 fractions. None may be rescaled.
    expect(result.medianPctChange).toBe(0.679);
    expect(result.coverageRatio).toBe(0.9671);
    expect(result.unchangedRatio).toBe(0.0329);
    expect(result.turnoverChangeVsPreviousPct).toBe(-5.41);
    expect(result.distributionBins?.map((bin) => [bin.label, bin.count])).toEqual([
      ["≤-3%", 304],
      ["-3~0%", 1500],
      ["平盘", 182],
      ["0~3%", 3037],
      ["≥3%", 512],
    ]);
  });

  it("passes sector pct_change through and converts main_net_inflow to 100m CNY", () => {
    const result = parseSectors({
      sectors: [
        { code: "BK1318", name: "光伏主材", pct_change: 4.56, advancers: 2, decliners: 0, main_net_inflow: 12_562_000_000 },
        { code: "BK0001", name: "降级板块", pct_change: 1.2, advancers: null, decliners: null, main_net_inflow: null },
      ],
    });

    expect(result.items).toHaveLength(2);
    expect(result.items[0]?.pctChange).toBe(4.56);
    // 东财 f62 原始单位元，adapter 统一换算为亿元。
    expect(result.items[0]?.mainNetInflow100mCny).toBeCloseTo(125.62);
    expect(result.items[1]?.mainNetInflow100mCny).toBeNull();
  });

  it("prefers bins_7, parses limit counts and turnover history", () => {
    const result = parseBreadth({
      status: "available",
      market_date: "2026-08-04",
      breadth: {
        total: 5535, advancers: 3549, decliners: 1804, unchanged: 182,
        limit_up_count: 42, limit_down_count: 7,
        limit_method: "按板块规则近似判定",
        state: "上涨家数占优",
      },
      distribution: {
        median_pct_change: 0.679,
        bins: { strong_advancers_ge_3: 512, mild_advancers_gt_0_lt_3: 3037, unchanged: 182, mild_decliners_lt_0_gt_neg3: 1500, strong_decliners_le_neg3: 304 },
        bins_7: { le_neg7: 68, gt_neg7_le_neg3: 236, gt_neg3_lt_0: 1500, unchanged: 182, gt_0_lt_3: 3037, ge_3_lt_7: 400, ge_7: 112 },
      },
      turnover_history: [
        { date: "2026-07-31", amount_100m_cny: 25590.66 },
        { date: "2026-08-04", amount_100m_cny: 22280.15 },
        { date: null, amount_100m_cny: 1 },
      ],
    });

    expect(result.limitUpCount).toBe(42);
    expect(result.limitDownCount).toBe(7);
    expect(result.limitMethod).toBe("按板块规则近似判定");
    // bins_7 优先于旧 5 桶；标签与家数直通。
    expect(result.distributionBins?.map((bin) => [bin.label, bin.count])).toEqual([
      ["≤-7%", 68],
      ["-7~-3%", 236],
      ["-3~0%", 1500],
      ["平盘", 182],
      ["0~3%", 3037],
      ["3~7%", 400],
      ["≥7%", 112],
    ]);
    expect(result.turnoverHistory).toEqual([
      { date: "2026-07-31", amount100mCny: 25590.66 },
      { date: "2026-08-04", amount100mCny: 22280.15 },
    ]);
  });

  it("parses market anomalies with percentage passthrough", () => {
    const result = parseMarketAnomalies({
      status: "available",
      market_timestamp: "2026-08-04T02:00:00+00:00",
      items: [
        { symbol: "sh603019", name: "中科曙光", kind: "快速拉升", pct_change: 8.65, amount_100m_cny: 125.62, tick_time: "10:36:00" },
        { symbol: "sz001696", name: null, kind: "快速下挫", pct_change: -7.21, amount_100m_cny: null, tick_time: null },
      ],
    });

    expect(result.items).toHaveLength(2);
    expect(result.items[0]?.pctChange).toBe(8.65);
    expect(result.items[0]?.amount100mCny).toBe(125.62);
    expect(result.items[1]?.name).toBeNull();
  });

  it("limits priority items to five and preserves the backend ranking reason", () => {
    const result = parseOverview({
      contract_version: "today_overview_v1",
      generated_at: "2026-08-04T02:35:06+00:00",
      session: {
        key: "intraday",
        label: "盘中",
        exchange_status: "open",
        exchange_label: "交易中",
        market_local_time: "2026-08-04T10:35:06+08:00",
      },
      summary: {
        headline: "当前有研究事项需要复核。",
        priority_count: 6,
        related_change_count: 1,
        market_date: "2026-08-04",
      },
      priority_items: {
        items: Array.from({ length: 6 }, (_, index) => ({
          id: `item-${index}`,
          kind: "research_action",
          title: `事项 ${index}`,
          detail: "核验证据",
          status_label: "需要复核",
          rank_reason: `排序原因 ${index}`,
        })),
        total_visible: 6,
        ranking_method: "后端确定性排序",
        empty_message: "当前没有事项",
      },
      coverage: { status: "ready", components: {} },
      warnings: [],
      boundary: "不构成买卖建议。",
    });

    expect(result.priorityItems).toHaveLength(5);
    expect(result.priorityItems[0].rankReason).toBe("排序原因 0");
    expect(result.priorityTotal).toBe(6);
  });

  it("accepts null market_date and null empty_message from degraded responses", () => {
    const result = parseOverview({
      contract_version: "today_overview_v1",
      generated_at: "2026-08-04T02:35:06+00:00",
      session: {
        key: "intraday",
        label: "盘中",
        exchange_status: "open",
        exchange_label: "交易中",
        market_local_time: "2026-08-04T10:35:06+08:00",
      },
      summary: {
        headline: "市场广度暂不可用。",
        priority_count: 1,
        related_change_count: 0,
        market_date: null,
      },
      priority_items: {
        items: [{ id: "item-0", kind: "research_action", title: "事项 0" }],
        total_visible: 1,
        ranking_method: "后端确定性排序",
        empty_message: null,
      },
      coverage: { status: "partial", components: {} },
      warnings: [],
      boundary: "不构成买卖建议。",
    });

    expect(result.marketDate).toBeNull();
    expect(result.priorityEmptyMessage).toBeNull();
    expect(result.priorityItems).toHaveLength(1);
  });

  it("rejects a response that is missing the overview contract identity", () => {
    expect(() => parseOverview({ generated_at: "2026-08-04" })).toThrow(ContractError);
  });

  it("keeps the health label and only actionable checks", () => {
    const result = parseDataHealth({
      status: "degraded",
      user_label: "部分数据同步中",
      created_at: "2026-08-04T02:34:35+00:00",
      summary: { total: 3, healthy: 1, attention: 1, critical: 1 },
      checks: [
        { key: "market:china", category: "market", status: "healthy", label: "正常" },
        { key: "filing:1", category: "fundamentals", status: "critical", label: "缺少财报全文" },
        { key: "peer:1", category: "fundamentals", status: "attention", label: "同行口径待齐" },
      ],
    });

    expect(result.userLabel).toBe("部分数据同步中");
    expect(result.actionableChecks.map((check) => check.status)).toEqual(["critical", "attention"]);
    expect(result.categories).toEqual([
      { key: "market", label: "行情", status: "healthy", count: 1 },
      { key: "fundamentals", label: "财务", status: "critical", count: 2 },
    ]);
  });

  it("extracts close prices from index history points", () => {
    const result = parseIndexHistory({
      market_timestamp: "2026-08-03T07:00:00+00:00",
      points: [
        { timestamp: "2026-07-06T01:30:00+00:00", open: 100, high: 102, low: 99, close: 101.5, adjusted_close: 101.5, volume: 1 },
        { timestamp: "2026-07-07T01:30:00+00:00", open: 101, high: 103, low: 100, close: 102.25, adjusted_close: 102.25, volume: 1 },
        { timestamp: "2026-07-08T01:30:00+00:00", open: null, high: null, low: null, close: null },
      ],
    });

    expect(result.closes).toEqual([101.5, 102.25]);
    expect(result.marketTimestamp).toBe("2026-08-03T07:00:00+00:00");
  });

  it("parses latest broker research reports and passes forecast_eps through unscaled", () => {
    const result = parseLatestResearchReports({
      status: "ready",
      items: [
        { symbol: "000063.SZ", name: "中兴通讯", title: "中兴通讯：算力基建加速", institution: "中信证券", researchers: "张三", published_at: "2026-08-03", rating: "买入", previous_rating: "增持", forecast_eps: 1.85, report_url: "https://example.com/r1", summary: "摘要" },
        { symbol: "600519.SS", name: null, title: null },
      ],
    });

    expect(result.status).toBe("ready");
    expect(result.items).toHaveLength(1);
    expect(result.items[0]?.title).toBe("中兴通讯：算力基建加速");
    expect(result.items[0]?.institution).toBe("中信证券");
    expect(result.items[0]?.publishedAt).toBe("2026-08-03");
    // forecast_eps 单位元/股，直通不缩放。
    expect(result.items[0]?.forecastEps).toBe(1.85);
  });

  it("parses capital flow with 100m CNY passthrough and keeps the northbound method note", () => {
    const result = parseCapitalFlow({
      status: "available",
      market_timestamp: "2026-08-04T07:00:00+00:00",
      is_stale: false,
      summary: { main_net_inflow_100m_cny: -128.45, unit: "CNY_100m_yuan" },
      points: [
        { time: "09:30", main_net_inflow_100m_cny: -12.5 },
        { time: "10:30", main_net_inflow_100m_cny: -60.2 },
        { time: "15:00", main_net_inflow_100m_cny: -128.45 },
      ],
      method: "主力资金口径；北向资金 2024-08 起港交所停披。",
      warnings: [],
    });

    // 金额为后端已换算的亿元，直通不缩放。
    expect(result.mainNetInflow100mCny).toBe(-128.45);
    expect(result.unit).toBe("CNY_100m_yuan");
    expect(result.points.map((point) => point.value100mCny)).toEqual([-12.5, -60.2, -128.45]);
    expect(result.method).toContain("北向");
  });

  it("parses the position ledger without inventing market-value fields", () => {
    const result = parsePositions({
      contract_version: "position_ledger_v1",
      status: "ready",
      items: [
        { workspace_id: "w-1", symbol: "000063.SZ", name: "中兴通讯", status: "open", current: { quantity: 200, cost_basis: 6400, average_cost: 32 } },
        { workspace_id: "w-1", symbol: "", name: "无代码", status: "open", current: { quantity: 1 } },
      ],
      warnings: [],
    });

    expect(result.items).toHaveLength(1);
    // 数量 / 成本 / 均价均为账本原值，直通不缩放。
    expect(result.items[0]?.quantity).toBe(200);
    expect(result.items[0]?.costBasis).toBe(6400);
    expect(result.items[0]?.averageCost).toBe(32);
    expect(() => parsePositions({ contract_version: "other", items: [] })).toThrow(ContractError);
  });

  it("parses overview themes in backend order with tone passthrough", () => {
    const result = parseOverview({
      contract_version: "today_overview_v1",
      generated_at: "2026-08-04T02:35:06+00:00",
      session: { key: "intraday", label: "盘中", exchange_status: "open", exchange_label: "交易中", market_local_time: "2026-08-04T10:35:06+08:00" },
      summary: { headline: "摘要", priority_count: 0, related_change_count: 0, market_date: "2026-08-04" },
      priority_items: { items: [], total_visible: 0, ranking_method: "后端确定性排序", empty_message: null },
      coverage: { status: "ready", components: {} },
      themes: [
        { key: "market_sentiment", title: "市场情绪", status: "ready", tone: "positive", summary: "上涨家数占优。", basis: "市场广度" },
        { key: "capital_flow", title: "资金流向", status: "unavailable", tone: "unknown", summary: "数据源暂不可用。", basis: null },
      ],
      warnings: [],
      boundary: "不构成买卖建议。",
    });

    expect(result.themes.map((theme) => theme.key)).toEqual(["market_sentiment", "capital_flow"]);
    expect(result.themes[0]?.tone).toBe("positive");
    expect(result.themes[1]?.status).toBe("unavailable");
    expect(result.themes[1]?.summary).toBe("数据源暂不可用。");
  });

  it("parses global indices without the china display-order filter", () => {
    const result = parseGlobalIndices({
      indices: [
        { symbol: "^GSPC", name: "标普500", status: "available", metrics: { latest_close: 2348.6, change_1d: 14.8, return_1d_pct: 0.63 }, market_timestamp: "2026-08-04T20:00:00+00:00", is_stale: false },
        { symbol: "^IXIC", name: "纳斯达克综合", status: "unavailable", metrics: null, market_timestamp: null, is_stale: null },
      ],
    });

    expect(result.items.map((item) => item.symbol)).toEqual(["^GSPC", "^IXIC"]);
    expect(result.items[0]?.change1d).toBe(14.8);
    expect(result.items[0]?.return1dPct).toBe(0.63);
    expect(result.items[1]?.latestClose).toBeNull();
  });

  it("parses live markets and keeps gold pct_change unscaled", () => {
    const result = parseLiveMarkets({
      markets: [
        { key: "london_gold", name: "伦敦金（现货黄金）", status: "available", latest_price: 2358.6, pct_change: 0.78, currency: "USD", market_timestamp: "2026-08-04T12:00:00+00:00", is_stale: false },
        { key: "china_a", name: "A股", status: "degraded", latest_price: null, pct_change: null },
      ],
    });

    expect(result.items).toHaveLength(2);
    expect(result.items[0]?.pctChange).toBe(0.78);
    expect(result.items[1]?.status).toBe("degraded");
  });
});
