import { describe, expect, it, vi } from "vitest";

const getMock = vi.hoisted(() => vi.fn());

vi.mock("./client", () => ({
  api: { GET: getMock },
}));

import { getGlobalSearch } from "./search";

describe("getGlobalSearch", () => {
  it("keeps a successful empty result distinct from an unavailable endpoint", async () => {
    getMock.mockResolvedValueOnce({
      data: { groups: [] },
      error: undefined,
      response: { ok: true },
    });
    await expect(getGlobalSearch("中兴")).resolves.toEqual([]);

    getMock.mockResolvedValueOnce({
      data: undefined,
      error: { detail: "upstream unavailable" },
      response: { ok: false, status: 502 },
    });
    await expect(getGlobalSearch("中兴")).rejects.toThrow("全局搜索请求失败 (502)");
  });
});
