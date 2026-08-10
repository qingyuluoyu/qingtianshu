import { describe, expect, it } from "vitest";
import { resolveProxyTarget, sessionProxyPaths } from "./vite.proxy";

describe("resolveProxyTarget", () => {
  it("keeps the documented FastAPI default when no local override is supplied", () => {
    expect(resolveProxyTarget()).toBe("http://127.0.0.1:8000");
  });

  it("uses an explicit local FastAPI target", () => {
    expect(resolveProxyTarget("http://127.0.0.1:8001")).toBe("http://127.0.0.1:8001");
  });

  it("proxies both the session root and nested session status paths", () => {
    expect(sessionProxyPaths).toEqual(["/session", "/session/*"]);
  });
});
