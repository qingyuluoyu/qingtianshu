import createClient from "openapi-fetch";
import type { paths } from "./openapi.generated";

export const API_TIMEOUT_MS = 15_000;

export class ApiTransportError extends Error {
  constructor(
    public readonly code: "timeout" | "aborted",
    public readonly status = 0,
  ) {
    super(code === "timeout" ? "请求超时，请稍后重试" : "请求已取消");
    this.name = "ApiTransportError";
  }
}

type FetchWithTimeoutOptions = RequestInit & {
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
};

/**
 * Keep every API request finite. A transport timeout is intentionally distinct
 * from an HTTP error so callers can avoid retrying a slow upstream indefinitely.
 */
export async function fetchWithTimeout(
  input: RequestInfo | URL,
  options: FetchWithTimeoutOptions = {},
): Promise<Response> {
  const { fetchImpl = fetch, signal: callerSignal, timeoutMs = API_TIMEOUT_MS, ...init } = options;
  if (callerSignal?.aborted) throw new ApiTransportError("aborted");

  const controller = new AbortController();
  let timedOut = false;
  const onCallerAbort = () => controller.abort();
  callerSignal?.addEventListener("abort", onCallerAbort, { once: true });
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);

  try {
    return await fetchImpl(input, { ...init, signal: controller.signal });
  } catch (error) {
    if (timedOut) throw new ApiTransportError("timeout");
    if (controller.signal.aborted) throw new ApiTransportError("aborted");
    throw error;
  } finally {
    clearTimeout(timer);
    callerSignal?.removeEventListener("abort", onCallerAbort);
  }
}

export const api = createClient<paths>({
  baseUrl: "",
  credentials: "same-origin",
  fetch: fetchWithTimeout,
});
