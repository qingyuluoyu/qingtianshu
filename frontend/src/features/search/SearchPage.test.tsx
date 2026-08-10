import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

const getGlobalSearchMock = vi.hoisted(() => vi.fn());

vi.mock("../../api/search", () => ({
  getGlobalSearch: getGlobalSearchMock,
}));

import { SearchPage } from "./SearchPage";

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter><SearchPage authenticated /></MemoryRouter></QueryClientProvider>);
}

describe("SearchPage", () => {
  it("distinguishes a failed search request from an empty result", async () => {
    getGlobalSearchMock.mockRejectedValueOnce(new Error("全局搜索请求失败 (502)"));
    renderPage();

    fireEvent.change(screen.getByRole("textbox", { name: "搜索关键词" }), { target: { value: "中兴" } });

    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("搜索暂时不可用"), { timeout: 1_000 });
    expect(screen.getByRole("status")).not.toHaveTextContent("没有匹配");
  });
});
