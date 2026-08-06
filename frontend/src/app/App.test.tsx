import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";

describe("正式前端认证入口", () => {
  beforeEach(() => {
    window.history.pushState({}, "", "/watchlist");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ code: "session_expired", message: "会话已失效" }), {
          status: 401,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
  });

  afterEach(() => vi.unstubAllGlobals());

  it("keeps the requested route locked and opens the auth dialog for an anonymous visitor", async () => {
    render(<App />);

    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
    expect(screen.getByRole("heading", { name: "我的关注" })).toBeInTheDocument();
    expect(screen.getByText("登录 / 注册")).toBeInTheDocument();
    expect(window.location.pathname).toBe("/watchlist");
  });

  it("keeps a manually closed prompt closed until the header trigger or another protected route is used", async () => {
    render(<App />);
    await screen.findByRole("dialog");

    fireEvent.click(screen.getByRole("button", { name: "关闭登录或注册弹窗" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByText("业务内容已锁定，请先登录或注册。")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "登录 / 注册" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "关闭登录或注册弹窗" }));

    fireEvent.click(screen.getByRole("link", { name: "选股策略" }));
    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
    expect(window.location.pathname).toBe("/screening");
  });
});
