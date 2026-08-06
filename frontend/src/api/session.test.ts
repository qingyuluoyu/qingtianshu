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
});
