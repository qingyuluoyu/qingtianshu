import { afterEach, describe, expect, it, vi } from "vitest";
import { getSession } from "./session";

describe("getSession", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("uses a same-origin XHR probe and treats 401 as an anonymous session", async () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    class AnonymousSessionRequest {
      status = 401;
      responseText = '{"code":"session_expired"}';
      withCredentials = false;
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;
      open(method: string, url: string) { expect(method).toBe("GET"); expect(url).toBe("/session"); }
      send() { this.onload?.(); }
    }
    vi.stubGlobal("XMLHttpRequest", AnonymousSessionRequest);

    await expect(getSession()).resolves.toBeNull();
    expect(fetch).not.toHaveBeenCalled();
  });
});
