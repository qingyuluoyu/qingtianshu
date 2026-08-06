import { describe, expect, it, vi } from "vitest";
import { ensureAuthenticatedScreenshotSession } from "./authenticated-screenshot-session.mjs";

describe("ensureAuthenticatedScreenshotSession", () => {
  it("registers through the frontend origin before checking session status", async () => {
    const post = vi.fn().mockResolvedValue({ ok: () => true, status: () => 201 });
    const get = vi.fn().mockResolvedValue({
      ok: () => true,
      status: () => 200,
      json: async () => ({ authenticated: true }),
    });

    await ensureAuthenticatedScreenshotSession(
      { request: { post, get } },
      { frontend: "http://localhost:5173", account: "screenshot-user", phone: "13800138003", password: "Safe-Test-Password-2026" },
    );

    expect(post).toHaveBeenCalledWith("http://localhost:5173/auth/register", {
      data: { account: "screenshot-user", phone: "13800138003", password: "Safe-Test-Password-2026" },
    });
    expect(get).toHaveBeenCalledWith("http://localhost:5173/session/status");
  });

  it("refuses to capture when the frontend-origin session is anonymous", async () => {
    const get = vi.fn().mockResolvedValue({
      ok: () => true,
      status: () => 200,
      json: async () => ({ authenticated: false }),
    });

    await expect(ensureAuthenticatedScreenshotSession(
      { request: { post: vi.fn().mockResolvedValue({ ok: () => true, status: () => 201 }), get } },
      { frontend: "http://localhost:5173", account: "screenshot-user", phone: "13800138003", password: "Safe-Test-Password-2026" },
    )).rejects.toThrow("session/status");
  });
});
