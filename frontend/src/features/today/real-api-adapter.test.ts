import { describe, expect, it } from "vitest";
import breadthFixture from "./__fixtures__/breadth-real.json";
import { parseBreadth, parseSectors } from "./adapters";

describe("candidate real API adapter fixtures", () => {
  it("keeps the real turnover contract exact without inventing turnover_history", () => {
    expect((breadthFixture as Record<string, unknown>).turnover_history).toEqual([]);
    const result = parseBreadth(breadthFixture);
    expect(result.turnoverStatus).toBe("available");
    expect(result.historyStatus).toBe("available");
    expect(result.turnoverChangeVsPreviousPct).toBe(-4.941);
    expect(result.turnoverHistory).toEqual([]);
  });

  it("does not turn a missing sector inflow into zero", () => {
    const result = parseSectors({ sectors: [{ code: "BK1", name: "测试行业", pct_change: null, main_net_inflow: null }] });
    expect(result.items[0]?.mainNetInflow100mCny).toBeNull();
    expect(result.items[0]?.pctChange).toBeNull();
  });
});
