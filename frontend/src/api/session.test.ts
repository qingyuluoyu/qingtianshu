import { afterEach, describe, expect, it, vi } from "vitest";
import { getSession } from "./session";

describe("getSession", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("uses the 200-only session status contract for an anonymous visitor", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ authenticated: false }), { status: 200 }));
    vi.stubGlobal("fetch", fetch);
    await expect(getSession()).resolves.toBeNull();
    expect(fetch).toHaveBeenCalledWith("/session/status", { credentials: "same-origin" });
  });

  it("preserves a non-200 session response as a query failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("unavailable", { status: 503 })));

    await expect(getSession()).rejects.toThrow("会话状态请求失败 (503)");
  });

  it("preserves a network failure as a query failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("network unavailable")));

    await expect(getSession()).rejects.toThrow("network unavailable");
  });
});
