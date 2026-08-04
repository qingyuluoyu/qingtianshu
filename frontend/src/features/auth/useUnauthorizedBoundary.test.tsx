import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useUnauthorizedBoundary } from "./useUnauthorizedBoundary";

class UnauthorizedError extends Error {
  readonly status = 401;
}

function Boundary({ onUnauthorized }: { onUnauthorized: () => void }) {
  useUnauthorizedBoundary(true, onUnauthorized);
  return null;
}

describe("useUnauthorizedBoundary", () => {
  it("handles concurrent query 401 errors through one centralized transition", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const onUnauthorized = vi.fn();
    render(<QueryClientProvider client={client}><Boundary onUnauthorized={onUnauthorized} /></QueryClientProvider>);

    await Promise.allSettled([
      client.fetchQuery({ queryKey: ["private", 1], queryFn: () => Promise.reject(new UnauthorizedError()) }),
      client.fetchQuery({ queryKey: ["private", 2], queryFn: () => Promise.reject(new UnauthorizedError()) }),
    ]);

    await waitFor(() => expect(onUnauthorized).toHaveBeenCalledTimes(1));
  });
});
