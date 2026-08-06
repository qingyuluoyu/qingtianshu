import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { getGlobalSearch } from "../../api/search";
import { GlobalSearch } from "./GlobalSearch";

vi.mock("../../api/search", () => ({ getGlobalSearch: vi.fn() }));

const resultGroups = [{
  key: "stocks",
  label: "股票",
  items: [{ id: "600519.SS", title: "贵州茅台", subtitle: "600519.SS", url: "/stocks/600519.SS" }],
}];

function renderSearch() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route element={<GlobalSearch />} path="/" />
          <Route element={<div>个股落地页</div>} path="/stocks/:symbol" />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("GlobalSearch", () => {
  afterEach(() => vi.clearAllMocks());

  it("does not request search for whitespace-only input", async () => {
    renderSearch();

    fireEvent.change(screen.getByRole("combobox", { name: "全局搜索" }), { target: { value: "   " } });
    await new Promise((resolve) => window.setTimeout(resolve, 300));

    expect(getGlobalSearch).not.toHaveBeenCalled();
  });

  it("does not navigate on Enter until the user explicitly selects a result", async () => {
    vi.mocked(getGlobalSearch).mockResolvedValue(resultGroups);
    renderSearch();
    const input = screen.getByRole("combobox", { name: "全局搜索" });

    fireEvent.change(input, { target: { value: "茅台" } });
    await screen.findByText("贵州茅台");
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.queryByText("个股落地页")).not.toBeInTheDocument();

    fireEvent.keyDown(input, { key: "ArrowDown" });
    await waitFor(() => expect(input).toHaveAttribute("aria-activedescendant", "global-search-option-stocks-600519-SS"));
    fireEvent.keyDown(input, { key: "Enter" });
    expect(await screen.findByText("个股落地页")).toBeInTheDocument();
  });
});
