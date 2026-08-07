import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiTransportError, fetchWithTimeout } from "./client";

describe("fetchWithTimeout", () => {
  afterEach(() => vi.useRealTimers());

  it("rejects a request that does not settle before the deadline", async () => {
    vi.useFakeTimers();
    const fetchImpl = vi.fn((_input: RequestInfo | URL, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(init.signal?.reason));
    }));

    const pending = fetchWithTimeout("/indices", { fetchImpl, timeoutMs: 20 });
    const rejected = expect(pending).rejects.toMatchObject({
      name: "ApiTransportError",
      code: "timeout",
      status: 0,
    });
    await vi.advanceTimersByTimeAsync(20);

    await rejected;
  });

  it("keeps a caller initiated abort distinct from a timeout", async () => {
    const controller = new AbortController();
    const fetchImpl = vi.fn((_input: RequestInfo | URL, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(init.signal?.reason));
    }));

    const pending = fetchWithTimeout("/markets/breadth", { fetchImpl, signal: controller.signal, timeoutMs: 10_000 });
    controller.abort(new DOMException("cancelled", "AbortError"));

    await expect(pending).rejects.toMatchObject({
      code: "aborted",
      status: 0,
    });
  });
});
