import { describe, expect, it } from "vitest";
import { requestError } from "./requestError";

describe("requestError", () => {
  it("records the operation and HTTP status without response details", () => {
    expect(requestError("策略列表", 502).message).toBe("策略列表请求失败 (502)");
  });
});
