import { createRef } from "react";
import { render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { AppShell } from "./AppShell";

function page(path = "/today") {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route element={<AppShell authTriggerRef={createRef<HTMLButtonElement>()} onOpenAuth={vi.fn()} onSignOut={vi.fn()} session={null} />}>
            <Route element={<h1>页面内容</h1>} path="*" />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("AppShell", () => {
  it("shows a human-readable page label instead of the raw route", () => {
    page();
    expect(screen.getByTestId("current-page-label")).toHaveTextContent("今日观察");
    expect(screen.queryByText("/today")).not.toBeInTheDocument();
  });

  it("provides a control to open primary navigation on compact layouts", () => {
    page();
    expect(screen.getByRole("button", { name: "打开主导航" })).toBeInTheDocument();
  });

  it("exposes the formal product workflow before auxiliary tools", () => {
    page();
    const navigation = screen.getByRole("navigation", { name: "产品导航" });
    expect(within(navigation).getAllByRole("link").slice(0, 5).map((link) => link.getAttribute("aria-label"))).toEqual([
      "今日观察",
      "我的关注",
      "个股研究",
      "AI 研究",
      "复盘中心",
    ]);
    expect(within(navigation).getByText("辅助工具")).toBeInTheDocument();
  });
});
