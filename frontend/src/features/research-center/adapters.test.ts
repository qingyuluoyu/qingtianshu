import { describe, expect, it } from "vitest";
import {
  ContractError,
  parseResearchActions,
  parseResearchChanges,
  parseResearchOutcomes,
  parseResearchReport,
  parsePendingWritebacks,
  parseTradeReviewCenter,
  parseWorkspaceTimeline,
} from "./adapters";
import {
  actionsPayload,
  changesPayload,
  outcomesPayload,
  reportPayload,
  timelinePayload,
  tradeReviewCenterPayload,
} from "./testFixtures";

describe("parseResearchChanges", () => {
  it("locks the type marker and rejects non-object payloads", () => {
    expect(() => parseResearchChanges(null)).toThrow(ContractError);
    expect(() => parseResearchChanges([])).toThrow(ContractError);
    expect(() => parseResearchChanges({ type: "other_v9", items: [] })).toThrow(/research_tracking/);
  });

  it("parses items with passthrough percents (no scaling, no abs)", () => {
    const parsed = parseResearchChanges(changesPayload());
    expect(parsed.items).toHaveLength(2);
    const first = parsed.items[0]!;
    expect(first.symbol).toBe("000063.SZ");
    // return_*_pct 直通：-13.9598 保持原值。
    expect(first.currentState?.return20dPct).toBe(-13.9598);
    expect(first.currentState?.return1dPct).toBe(-0.1151);
    expect(first.latestChange?.changes[1]?.before).toBe("-10.20%");
    expect(first.nextReview?.horizonSessions).toBe(3);
    expect(parsed.coverage.withChangeArchive).toBe(1);
    expect(parsed.boundary).toContain("长期证据记录");
  });

  it("distinguishes null thesis from a saved thesis", () => {
    const parsed = parseResearchChanges(changesPayload());
    expect(parsed.items[0]!.thesisSummary).toBeNull();
    expect(parsed.items[1]!.thesisSummary).toBe("渠道批价与动销是核心变量。");
    expect(parsed.items[1]!.latestChange).toBeNull();
  });

  it("drops items without a symbol instead of inventing one", () => {
    const payload = changesPayload();
    (payload.items as unknown[]).push({ name: "无代码" });
    const parsed = parseResearchChanges(payload);
    expect(parsed.items).toHaveLength(2);
  });
});

describe("parseResearchOutcomes", () => {
  it("locks the type marker", () => {
    expect(() => parseResearchOutcomes({ type: "research_tracking", items: [] })).toThrow(/research_outcome/);
  });

  it("keeps anchor, window, protocol and data-availability times", () => {
    const parsed = parseResearchOutcomes(outcomesPayload());
    const item = parsed.items[0]!;
    expect(item.coverage).toEqual({ anchors: 5, available: 2, pending: 3 });
    const done = item.latestAvailable[0]!;
    // 锚点 / 交易日窗口 / 基准（价格口径）/ 数据可得时间齐全。
    expect(done.anchorClose).toBe(34.02);
    expect(done.anchorTimestamp).toBe("2026-07-30T01:30:00+00:00");
    expect(done.horizonSessions).toBe(3);
    expect(done.targetTimestamp).toBe("2026-08-04T01:30:00+00:00");
    expect(done.protocol?.priceSeries).toContain("复权收盘价");
    expect(done.dataAsOf).toBe("2026-08-04T01:30:00+00:00");
    // pct 直通：负值保持负值，不取绝对值。
    expect(done.closeReturnPct).toBe(-1.8524);
    expect(done.maximumAdverseExcursionPct).toBe(-3.4027);
    expect(done.maximumFavorableExcursionPct).toBe(2.1164);
  });

  it("keeps not-started anchors as null results, not zero", () => {
    const parsed = parseResearchOutcomes(outcomesPayload());
    const pending = parsed.items[0]!.latestAnchor[0]!;
    expect(pending.resultStatus).toBe("pending");
    expect(pending.observedSessions).toBe(0);
    expect(pending.closeReturnPct).toBeNull();
    expect(pending.targetClose).toBeNull();
    // 0% 的 MFE 是有效数值，不是缺失。
    const progress = parsed.items[0]!.latestProgress!;
    expect(progress.maximumFavorableExcursionPct).toBe(0);
    expect(progress.partialReturnPct).toBe(-0.1151);
  });
});

describe("parseResearchActions", () => {
  it("locks the type marker and parses triggered/pending actions", () => {
    expect(() => parseResearchActions({ type: "nope", items: [] })).toThrow(/research_actions/);
    const parsed = parseResearchActions(actionsPayload());
    const item = parsed.items[0]!;
    expect(item.researchStatusLabel).toBe("优先研究");
    expect(item.priorityScore).toBe(87);
    expect(item.actions[0]!.status).toBe("triggered");
    expect(item.actions[1]!.status).toBe("pending_data");
  });
});

describe("parseWorkspaceTimeline", () => {
  it("locks the contract version", () => {
    expect(() => parseWorkspaceTimeline({ contract_version: "other" })).toThrow(/stock_workspace_timeline_v1/);
    expect(() => parseWorkspaceTimeline(null)).toThrow(ContractError);
  });

  it("parses thesis, changes, tasks and data times", () => {
    const parsed = parseWorkspaceTimeline(timelinePayload());
    expect(parsed.symbol).toBe("000063.SZ");
    expect(parsed.thesisHistory[0]?.versionNo).toBe(2);
    expect(parsed.importantChanges).toHaveLength(1);
    expect(parsed.observationTasks.items[0]?.title).toBe("跟踪 MA20 收复情况");
    expect(parsed.tradeReviewSummary.needsConfirmation).toBe(1);
    expect(parsed.dataMeta.financialReportPeriod).toBe("2026-03-31");
    expect(parsed.historySummary.changeCount).toBe(3);
  });
});

describe("parseTradeReviewCenter", () => {
  it("locks the contract version and parses the state machine fields", () => {
    expect(() => parseTradeReviewCenter({ contract_version: "other" })).toThrow(/trade_review_center_v1/);
    const parsed = parseTradeReviewCenter(tradeReviewCenterPayload());
    expect(parsed.summary.actionable).toBe(1);
    expect(parsed.summary.needsConfirmation).toBe(1);
    const draft = parsed.items[0]!;
    expect(draft.status).toBe("draft");
    expect(draft.canConfirm).toBe(true);
    // confirm/archive 的 base_version 来自 current_version.version_no。
    expect(draft.currentVersion?.versionNo).toBe(2);
    expect(draft.currentVersion?.createdSource).toBe("ai");
    expect(parsed.items[1]!.status).toBe("confirmed");
    expect(parsed.items[1]!.canConfirm).toBe(false);
  });

  it("drops items without an id", () => {
    const payload = tradeReviewCenterPayload();
    (payload.items as unknown[]).push({ symbol: "000063.SZ", status: "draft" });
    const parsed = parseTradeReviewCenter(payload);
    expect(parsed.items).toHaveLength(2);
  });
});

describe("parsePendingWritebacks", () => {
  it("keeps only pending review-draft writebacks with their originating review", () => {
    const parsed = parsePendingWritebacks({
      items: [
        {
          id: "candidate-1",
          candidate_type: "review_draft",
          status: "pending_confirmation",
          payload: {
            review_id: "review-1",
            logic_result: "需要复核兑现节奏。",
            plan_deviation: "未按计划设置复核窗口。",
            improvement_text: "下次先验证订单进度。",
            bias_tags: ["锚定"],
          },
          created_at: "2026-08-07T08:00:00+00:00",
        },
        { id: "candidate-2", candidate_type: "thesis", status: "pending_confirmation" },
        { id: "candidate-3", candidate_type: "review_draft", status: "confirmed" },
      ],
    });

    expect(parsed.items).toEqual([
      expect.objectContaining({
        id: "candidate-1",
        reviewId: "review-1",
        logicResult: "需要复核兑现节奏。",
        biasTags: ["锚定"],
      }),
    ]);
  });
});

describe("parseResearchReport", () => {
  it("parses the report snapshot and requires a symbol", () => {
    const parsed = parseResearchReport(reportPayload());
    expect(parsed.title).toContain("研究快照");
    expect(parsed.status).toBe("preview");
    expect(parsed.marketTimestamp).toBe("2026-08-06T01:30:00+00:00");
    expect(() => parseResearchReport({ title: "无代码" })).toThrow(ContractError);
  });
});
