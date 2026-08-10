import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App, RouteLoadingFallback } from "./App";

describe("正式前端认证入口", () => {
  beforeEach(() => {
    window.history.pushState({}, "", "/watchlist");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ authenticated: false }), { status: 200 }),
      ),
    );
    class AnonymousSessionRequest {
      status = 401;
      responseText = '{"code":"session_expired","message":"会话已失效"}';
      withCredentials = false;
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;
      open() {}
      send() { this.onload?.(); }
    }
    vi.stubGlobal("XMLHttpRequest", AnonymousSessionRequest);
  });

  afterEach(() => vi.unstubAllGlobals());

  it("keeps the requested route locked and opens the auth dialog for an anonymous visitor", async () => {
    render(<App />);

    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
    expect(screen.getByRole("heading", { name: "我的关注" })).toBeInTheDocument();
    expect(screen.getByText("登录 / 注册")).toBeInTheDocument();
    expect(window.location.pathname).toBe("/watchlist");
  });

  it("keeps the public today snapshot readable without forcing an auth dialog", async () => {
    let resolveSession!: (response: Response) => void;
    vi.stubGlobal(
      "fetch",
      vi.fn(
        () =>
          new Promise<Response>((resolve) => {
            resolveSession = resolve;
          }),
      ),
    );
    window.history.pushState({}, "", "/today");
    render(<App />);

    await waitFor(() =>
      expect(globalThis.fetch).toHaveBeenCalledWith("/session/status", {
        credentials: "same-origin",
      }),
    );
    await act(async () => {
      resolveSession(
        new Response(JSON.stringify({ authenticated: false }), {
          headers: { "Content-Type": "application/json" },
        }),
      );
      await Promise.resolve();
    });
    await screen.findByRole("heading", { name: "今日观察" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "登录 / 注册" })).toBeInTheDocument();
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

    fireEvent.click(screen.getByRole("link", { name: "透明选股" }));
    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
    expect(window.location.pathname).toBe("/screening");
  });

  it("shows a session transport error without opening the login dialog", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("unavailable", { status: 503 })));
    render(<App />);

    expect(await screen.findByRole("alert")).toHaveTextContent("会话状态暂不可用");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("renders a status fallback while a heavy route module loads", () => {
    render(<RouteLoadingFallback />);
    expect(screen.getByRole("status")).toHaveTextContent("页面加载中…");
  });
});
