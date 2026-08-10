import { describe, expect, it, vi } from "vitest";

const getMock = vi.hoisted(() => vi.fn());

vi.mock("../../api/client", () => ({ api: { GET: getMock } }));

import { listKnowledgeDocuments } from "./api";

describe("listKnowledgeDocuments", () => {
  it("keeps a successful empty library distinct from an unavailable endpoint", async () => {
    getMock.mockResolvedValueOnce({ data: { items: [] }, error: undefined, response: { ok: true } });
    await expect(listKnowledgeDocuments()).resolves.toEqual([]);

    getMock.mockResolvedValueOnce({ data: undefined, error: { detail: "unavailable" }, response: { ok: false, status: 502 } });
    await expect(listKnowledgeDocuments()).rejects.toThrow("知识库列表请求失败 (502)");
  });
});
