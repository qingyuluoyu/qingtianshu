import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const runStrategyMock = vi.hoisted(() => vi.fn());

vi.mock("./api", () => ({
  getBacktestResult: vi.fn().mockResolvedValue(null),
  getLiZongStrategy: vi.fn().mockResolvedValue(null),
  getObservationPool: vi.fn().mockResolvedValue([]),
  getStrategyCandidates: vi.fn().mockResolvedValue([]),
  getStrategyHistory: vi.fn().mockResolvedValue([]),
  getStrategyTriggers: vi.fn().mockResolvedValue([]),
  runStrategy: runStrategyMock,
}));

import { StrategiesPage } from "./StrategiesPage";

describe("StrategiesPage", () => {
  it("shows a user-visible failure when starting a strategy request fails", async () => {
    runStrategyMock.mockRejectedValueOnce(new Error("启动策略请求失败 (502)"));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><StrategiesPage authenticated /></QueryClientProvider>);

    fireEvent.click(await screen.findByRole("button", { name: "启动策略" }));

    expect(await screen.findByRole("status")).toHaveTextContent("启动失败，请重试");
  });
});
