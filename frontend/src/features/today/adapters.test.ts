import { describe, expect, it } from "vitest";
import {
  ContractError,
  parseBreadth,
  parseDataHealth,
  parseIndices,
  parseOverview,
} from "./adapters";

describe("today runtime contract adapters", () => {
  it("keeps only the five required index cards and obtains CSI 300 from /indices", () => {
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
        metrics: { latest_close: close, return_1d_pct: change },
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
        state: "上涨家数占优",
      },
      turnover: { status: "unavailable", total_amount_100m_cny: null },
      distribution: { status: "available", median_pct_change: 0.679 },
    });

    expect(result.marketTimestamp).toBeNull();
    expect(result.turnover100mCny).toBeNull();
    expect(result.medianPctChange).toBe(0.679);
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
});
