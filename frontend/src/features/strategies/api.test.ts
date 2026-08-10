import { describe, expect, it, vi } from "vitest";

const getMock = vi.hoisted(() => vi.fn());
const postMock = vi.hoisted(() => vi.fn());

vi.mock("../../api/client", () => ({ api: { GET: getMock, POST: postMock } }));

import { listStrategies, runStrategy } from "./api";

describe("strategy API", () => {
  it("keeps a successful empty strategy list distinct from an unavailable endpoint", async () => {
    getMock.mockResolvedValueOnce({ data: { strategies: [] }, error: undefined, response: { ok: true } });
    await expect(listStrategies()).resolves.toEqual([]);

    getMock.mockResolvedValueOnce({ data: undefined, error: { detail: "unavailable" }, response: { ok: false, status: 503 } });
    await expect(listStrategies()).rejects.toThrow("策略列表请求失败 (503)");
  });

  it("preserves a failed strategy-run request as an error", async () => {
    postMock.mockResolvedValueOnce({ data: undefined, error: { detail: "unavailable" }, response: { ok: false, status: 502 } });
    await expect(runStrategy()).rejects.toThrow("启动策略请求失败 (502)");
  });
});
