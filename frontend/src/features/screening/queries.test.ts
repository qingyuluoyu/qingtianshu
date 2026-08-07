import { describe, expect, it } from "vitest";
import { ScreeningApiError, type ScreenParams } from "./api";
import { screeningQueries } from "./queries";

const params: ScreenParams = {
  profile: "value_quality",
  market: "all",
  maxResults: 12,
  filters: {},
};

describe("screening query retry policy", () => {
  it("does not retry a deterministic 503 data-readiness response", () => {
    const retry = screeningQueries.screen(params).retry;

    expect(typeof retry).toBe("function");
    expect((retry as (failureCount: number, error: Error) => boolean)(0, new ScreeningApiError(503, "数据正在准备中"))).toBe(false);
  });
});
