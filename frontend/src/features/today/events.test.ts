import { describe, expect, it } from "vitest";
import { queryKeysForEvent } from "./events";
import { todayQueryKeys } from "./queries";

describe("/events invalidation mapping", () => {
  it("invalidates only market queries for market_updated", () => {
    expect(queryKeysForEvent("market_updated")).toEqual([
      todayQueryKeys.overview,
      todayQueryKeys.indices,
      todayQueryKeys.breadth,
      todayQueryKeys.sectors,
      todayQueryKeys.anomalies,
    ]);
  });

  it("maps data and research events to their actual consumers", () => {
    expect(queryKeysForEvent("data_health_updated")).toEqual([todayQueryKeys.dataHealth]);
    expect(queryKeysForEvent("evidence_tasks_updated")).toEqual([
      todayQueryKeys.overview,
      todayQueryKeys.researchActions,
      todayQueryKeys.researchChanges,
    ]);
    expect(queryKeysForEvent("a_share_information_updated")).toEqual([
      todayQueryKeys.overview,
      todayQueryKeys.researchActions,
      todayQueryKeys.researchChanges,
    ]);
    expect(queryKeysForEvent("research_reports_updated")).toEqual([
      todayQueryKeys.overview,
      todayQueryKeys.researchActions,
      todayQueryKeys.researchChanges,
    ]);
    expect(queryKeysForEvent("unknown_event")).toEqual([]);
  });
});
