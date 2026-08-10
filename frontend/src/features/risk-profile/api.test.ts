import { describe, expect, it, vi } from "vitest";

const getMock = vi.hoisted(() => vi.fn());

vi.mock("../../api/client", () => ({
  api: { GET: getMock },
}));

import { getRiskProfile } from "./api";

describe("getRiskProfile", () => {
  it("keeps an absent profile distinct from an unavailable profile endpoint", async () => {
    getMock.mockResolvedValueOnce({
      data: { profile: null },
      error: undefined,
      response: { ok: true },
    });
    await expect(getRiskProfile()).resolves.toBeNull();

    getMock.mockResolvedValueOnce({
      data: undefined,
      error: { detail: "service unavailable" },
      response: { ok: false, status: 503 },
    });
    await expect(getRiskProfile()).rejects.toThrow("风险档案请求失败 (503)");
  });
});
