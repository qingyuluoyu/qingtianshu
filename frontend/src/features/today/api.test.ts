import { describe, expect, it, vi } from "vitest";
import { api } from "../../api/client";
import { getIndices } from "./api";

describe("Today API request lifecycle", () => {
  it("passes the TanStack Query abort signal into the transport", async () => {
    const signal = new AbortController().signal;
    const get = vi.spyOn(api, "GET").mockResolvedValue({
      data: undefined,
      error: { detail: "unavailable" },
      response: new Response(null, { status: 503 }),
    } as never);

    await expect(getIndices(signal)).rejects.toMatchObject({ status: 503 });
    expect(get).toHaveBeenCalledWith("/indices", {
      params: { query: { scope: "all", group: "china" } },
      signal,
    });
  });
});
