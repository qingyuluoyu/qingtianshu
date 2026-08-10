import { describe, expect, it, vi } from "vitest";

const getMock = vi.hoisted(() => vi.fn());

vi.mock("../../api/client", () => ({
  api: { GET: getMock },
}));

import { searchFunds } from "./api";

describe("searchFunds", () => {
  it("keeps a successful empty result distinct from an unavailable endpoint", async () => {
    getMock.mockResolvedValueOnce({
      data: { items: [] },
      error: undefined,
      response: { ok: true },
    });
    await expect(searchFunds("沪深")).resolves.toEqual([]);

    getMock.mockResolvedValueOnce({
      data: undefined,
      error: { detail: "upstream unavailable" },
      response: { ok: false, status: 502 },
    });
    await expect(searchFunds("沪深")).rejects.toThrow("基金搜索请求失败 (502)");
  });
});
