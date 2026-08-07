import { describe, expect, it } from "vitest";
import {
  ContractError,
  parseLiZongBacktest,
  parseLiZongCandidates,
  parseLiZongObservationPool,
  parseLiZongRunLatest,
  parseScreenerProfiles,
  parseStockScreen,
} from "./adapters";
import {
  liZongBacktestPayload,
  liZongCandidatesPayload,
  liZongObservationPoolPayload,
  liZongRunLatestPayload,
  profilesPayload,
  screenPayload,
} from "./testFixtures";

describe("parseScreenerProfiles", () => {
  it("parses profiles with passthrough default filters (0 is a valid threshold)", () => {
    const parsed = parseScreenerProfiles(profilesPayload());
    expect(parsed.items).toHaveLength(2);
    expect(parsed.items[0]!.key).toBe("quality");
    expect(parsed.items[0]!.defaultFilters.min_revenue_yoy).toBe(0);
    expect(parsed.items[0]!.defaultFilters.min_market_cap_yi).toBe(50);
    expect(parsed.boundary).toContain("不构成推荐");
  });

  it("drops profiles without a key and rejects non-object payloads", () => {
    expect(() => parseScreenerProfiles(null)).toThrow(ContractError);
    const parsed = parseScreenerProfiles({ items: [{ label: "无键" }], boundary: null });
    expect(parsed.items).toHaveLength(0);
  });
});

describe("parseStockScreen", () => {
  it("locks the response type and rejects wrong shapes", () => {
    expect(() => parseStockScreen(null)).toThrow(ContractError);
    expect(() => parseStockScreen([])).toThrow(ContractError);
    expect(() => parseStockScreen({ type: "other", items: [] })).toThrow(/stock_screen/);
  });

  it("parses items with passthrough percents and real totals", () => {
    const parsed = parseStockScreen(screenPayload());
    expect(parsed.status).toBe("ready");
    expect(parsed.universe.matched).toBe(2);
    expect(parsed.universe.representsFullMarket).toBe(false);
    const first = parsed.items[0]!;
    expect(first.symbol).toBe("600549.SH");
    // pct_change / return_*_pct 为百分数直通：8.789 保持 8.789，不缩放。
    expect(first.metrics.pctChange).toBe(8.789);
    expect(first.metrics.return5dPct).toBe(13.4051);
    expect(first.financials?.roe).toBe(6.2352);
    expect(parsed.dataContract.coverageStatus).toBe("constrained");
    expect(parsed.rules).toHaveLength(3);
    expect(parsed.rules[1]!.value).toBe(50);
  });

  it("distinguishes 0, missing fields, empty strings and null financials", () => {
    const parsed = parseStockScreen(screenPayload());
    const second = parsed.items[1]!;
    // pct_change = 0 是有效数值，直通为 0 而不是 null。
    expect(second.metrics.pctChange).toBe(0);
    // financials 整体为 null（接口未提供）与字段为 0 不是同一状态。
    expect(second.financials).toBeNull();
    expect(second.missingFields).toEqual(["revenue_yoy", "net_profit_yoy"]);
    expect(second.coverageStatus.financialQuality).toBe("insufficient");
    expect(second.researchFocus).toBeNull();
    expect(second.evidenceTimes.financialReportPeriod).toBeNull();
  });

  it("drops items without a symbol instead of inventing one", () => {
    const payload = screenPayload();
    payload.items.push({ name: "无代码" } as never);
    const parsed = parseStockScreen(payload);
    expect(parsed.items).toHaveLength(2);
  });
});

describe("parseLiZongCandidates", () => {
  it("locks strategy_id and parses the three candidate states", () => {
    expect(() => parseLiZongCandidates({ strategy: { strategy_id: "other" }, items: [] })).toThrow(/li_zong/);
    const parsed = parseLiZongCandidates(liZongCandidatesPayload());
    expect(parsed.status).toBe("ready");
    expect(parsed.counts.qualified).toBe(1);
    expect(parsed.counts.dataIncomplete).toBe(1);
    const statuses = parsed.items.map((item) => item.status);
    expect(statuses).toEqual(["qualified", "not_qualified", "data_incomplete"]);
    // 命中理由与缺失字段直通。
    expect(parsed.items[0]!.matchedReasons).toContain("LZ-F-01 已通过");
    expect(parsed.items[2]!.ruleResults[1]!.status).toBe("data_incomplete");
    expect(parsed.items[2]!.limitations[0]).toContain("量价历史不足");
  });

  it("parses the rule dictionary and funnel steps", () => {
    const parsed = parseLiZongCandidates(liZongCandidatesPayload());
    expect(parsed.rules.map((rule) => rule.ruleId)).toEqual(["LZ-F-01", "LZ-F-02", "LZ-C-01", "LZ-T-01"]);
    expect(parsed.rules[3]!.group).toBe("trigger");
    expect(parsed.funnel?.startingCount).toBe(5374);
    expect(parsed.funnel?.steps[1]!.removedAtStep).toBe(891);
    // 0 是有效计数：final_candidate_count = 0 不能当缺失。
    const payload = liZongCandidatesPayload();
    payload.funnel.final_candidate_count = 0;
    expect(parseLiZongCandidates(payload).funnel?.finalCandidateCount).toBe(0);
  });
});

describe("parseLiZongRunLatest", () => {
  it("locks strategy_id and parses run status with warnings", () => {
    expect(() => parseLiZongRunLatest({ strategy_id: "other" })).toThrow(/li_zong/);
    const parsed = parseLiZongRunLatest(liZongRunLatestPayload());
    expect(parsed.run?.status).toBe("partial");
    expect(parsed.run?.coverageRatio).toBe(0.970562);
    expect(parsed.run?.qualifiedCount).toBe(0);
    expect(parsed.run?.warnings[0]).toContain("165");
    expect(parsed.coverage?.fullMarketCoverage).toBe(false);
  });

  it("treats a missing run as a real empty state, not an error", () => {
    const parsed = parseLiZongRunLatest({ strategy_id: "li_zong", run: null, coverage: null });
    expect(parsed.run).toBeNull();
    expect(parsed.coverage).toBeNull();
  });
});

describe("parseLiZongObservationPool", () => {
  it("parses near-match counts and keeps observations outside the strict candidate pool", () => {
    expect(() => parseLiZongObservationPool({ strategy: { strategy_id: "other" } })).toThrow(/li_zong/);
    const parsed = parseLiZongObservationPool(liZongObservationPoolPayload());
    expect(parsed.counts.near8Of9).toBe(1);
    expect(parsed.counts.watch6To7Of9).toBe(159);
    expect(parsed.completeRuleStates).toBe(1208);
    expect(parsed.items[0]!.candidateRulePassCount).toBe(8);
    expect(parsed.items[0]!.failedCandidateRuleIds).toEqual(["LZ-F-02"]);
    expect(parsed.items[0]!.isStrictCandidate).toBe(false);
  });
});

describe("parseLiZongBacktest", () => {
  it("locks strategy_id and parses ready metrics with passthrough percents", () => {
    expect(() => parseLiZongBacktest({ strategy_id: "other" })).toThrow(/li_zong/);
    const parsed = parseLiZongBacktest(liZongBacktestPayload());
    expect(parsed.status).toBe("ready");
    const result = parsed.result!;
    // 百分数直通：28.1046 / -32.7614 不缩放、不取绝对值。
    expect(result.periodReturnPct).toBe(28.1046);
    expect(result.maxDrawdownPct).toBe(-32.7614);
    expect(result.benchmarkReturnPct).toBe(11.1996);
    expect(result.dataCoverageRatio).toBe(0.831536);
    expect(result.points).toHaveLength(5);
    expect(result.points[4]!.nav).toBe(1.281);
    expect(parsed.assumptions.benchmark).toContain("沪深300");
  });

  it("keeps an unfinished backtest as null result with progress status", () => {
    const payload = liZongBacktestPayload();
    const parsed = parseLiZongBacktest({
      ...payload,
      status: "computing",
      result: null,
      progress: { status: "computing", phase: "evaluating", label: "近3年", market_data_ratio: 0.42 },
    });
    expect(parsed.status).toBe("computing");
    expect(parsed.result).toBeNull();
    expect(parsed.progress?.marketDataRatio).toBe(0.42);
  });

  it("drops curve points that are not objects", () => {
    const payload = liZongBacktestPayload();
    (payload.result.points as unknown[]).push("bad");
    const parsed = parseLiZongBacktest(payload);
    expect(parsed.result?.points).toHaveLength(5);
  });
});
