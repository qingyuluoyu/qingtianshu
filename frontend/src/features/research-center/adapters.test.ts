import { describe, expect, it } from "vitest";
import {
  parseEvidenceTasks,
  parseResearchActions,
  parseResearchChanges,
  parseResearchOutcomes,
  parseResearchPriority,
  parseRunReviews,
  ResearchCenterContractError,
} from "./adapters";
import {
  actionsPayload,
  changesPayload,
  evidenceTasksPayload,
  outcomesPayload,
  priorityPayload,
  runReviewsPayload,
} from "./testFixtures";

describe("research center adapters", () => {
  it("parses priority and change evidence without inventing missing values", () => {
    const priority = parseResearchPriority(priorityPayload());
    const changes = parseResearchChanges(changesPayload());
    expect(priority.items[0]).toMatchObject({ symbol: "000063.SZ", priorityScore: 78 });
    expect(priority.items[1]?.dataAsOf).toBeNull();
    expect(priority.coverage.missingBaseline).toBe(1);
    expect(changes.events[0]).toMatchObject({ severity: "attention", dataAsOf: "2026-08-06" });
  });

  it("keeps action, evidence task and historical outcome states distinct", () => {
    const actions = parseResearchActions(actionsPayload());
    const tasks = parseEvidenceTasks(evidenceTasksPayload());
    const outcomes = parseResearchOutcomes(outcomesPayload());
    expect(actions.summary.triggered).toBe(1);
    expect(actions.items[0]?.actions.map((item) => item.status)).toEqual(["triggered", "pending_data"]);
    expect(tasks.items[1]).toMatchObject({ status: "pending_external", priority: 60 });
    expect(outcomes.items[0]?.latestAvailable[0]).toMatchObject({ closeReturnPct: -2.35, horizonSessions: 3 });
  });

  it("parses formal run reviews and preserves a valid false repaired flag", () => {
    const reviews = parseRunReviews(runReviewsPayload());
    expect(reviews.summary.total).toBe(1);
    expect(reviews.items[0]).toMatchObject({ status: "completed", repaired: false, readyModules: 7, totalModules: 9 });
  });

  it("rejects an unexpected packet type instead of rendering a misleading empty page", () => {
    expect(() => parseResearchPriority({ type: "other", items: [] })).toThrow(ResearchCenterContractError);
  });
});
