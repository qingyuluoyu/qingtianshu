import { describe, expect, it, vi } from "vitest";

const getMock = vi.hoisted(() => vi.fn());

vi.mock("../../api/client", () => ({
  api: { GET: getMock },
}));

import { listArticles } from "./api";

describe("listArticles", () => {
  it("keeps a successful empty article list distinct from an unavailable endpoint", async () => {
    getMock.mockResolvedValueOnce({
      data: { items: [] },
      error: undefined,
      response: { ok: true },
    });
    await expect(listArticles()).resolves.toEqual([]);

    getMock.mockResolvedValueOnce({
      data: undefined,
      error: { detail: "upstream unavailable" },
      response: { ok: false, status: 502 },
    });
    await expect(listArticles()).rejects.toThrow("文章列表请求失败 (502)");
  });
});
