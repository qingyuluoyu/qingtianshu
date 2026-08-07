import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";

describe("正式前端认证入口", () => {
  beforeEach(() => {
    window.history.pushState({}, "", "/watchlist");
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

  it("opens the auth dialog when the session endpoint explicitly reports an anonymous visitor", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ authenticated: false }),
    }));
    window.history.pushState({}, "", "/research-center");

    render(<App />);

    await waitFor(() => expect(screen.getByRole("dialog", { name: "登录或注册" })).toBeInTheDocument());
    expect(screen.getByRole("heading", { name: "研究中心" })).toBeInTheDocument();
  });

  it("exposes exactly the six formal product routes and a semantic route title", async () => {
    render(<App />);
    await screen.findByRole("dialog");

    const navigation = screen.getByRole("navigation", { name: "主导航" });
    expect(within(navigation).getAllByRole("link").map((link) => link.textContent)).toEqual([
      "今日观察",
      "透明选股",
      "我的关注",
      "个股研究",
      "金融顾问",
      "研究中心",
    ]);
    expect(within(navigation).queryByText("行情数据")).not.toBeInTheDocument();
    expect(screen.getByTestId("route-title")).toHaveTextContent("我的关注");
  });

  it("opens and closes the single mobile navigation tree with Escape and restores focus", async () => {
    render(<App />);
    await screen.findByRole("dialog");
    fireEvent.click(screen.getByRole("button", { name: "关闭登录或注册弹窗" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const menuButton = screen.getByRole("button", { name: "打开主导航" });

    fireEvent.click(menuButton);
    expect(menuButton).toHaveAttribute("aria-expanded", "true");
    fireEvent.keyDown(document, { key: "Escape" });
    expect(menuButton).toHaveAttribute("aria-expanded", "false");
    expect(menuButton).toHaveFocus();

    fireEvent.click(menuButton);
    fireEvent.click(within(screen.getByRole("navigation", { name: "主导航" })).getByRole("link", { name: "透明选股" }));
    await waitFor(() => expect(window.location.pathname).toBe("/screening"));
    expect(menuButton).toHaveAttribute("aria-expanded", "false");
  });
});
