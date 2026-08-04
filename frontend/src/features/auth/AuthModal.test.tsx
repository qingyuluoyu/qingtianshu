import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useRef, useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthModal } from "./AuthModal";

const postMock = vi.hoisted(() => vi.fn());
vi.mock("../../api/client", () => ({ api: { POST: postMock } }));

function Harness() {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  return (
    <>
      <button ref={triggerRef} type="button" onClick={() => setOpen(true)}>登录 / 注册</button>
      {open ? <AuthModal onClose={() => setOpen(false)} returnFocusRef={triggerRef} /> : null}
    </>
  );
}

function renderHarness() {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><Harness /></QueryClientProvider>);
}

async function openModal() {
  fireEvent.click(screen.getByRole("button", { name: "登录 / 注册" }));
  return screen.findByRole("dialog", { name: "登录或注册" });
}

afterEach(() => {
  postMock.mockReset();
  vi.unstubAllGlobals();
});

describe("AuthModal", () => {
  it("moves focus into the dialog and restores it to the auth trigger after X closes", async () => {
    renderHarness();
    const dialog = await openModal();
    await waitFor(() => expect(dialog).toHaveFocus());
    expect(dialog).toHaveAttribute("aria-modal", "true");
    const titleId = dialog.getAttribute("aria-labelledby");
    expect(titleId).toBeTruthy();
    expect(document.getElementById(String(titleId))).toHaveTextContent("登录或注册");

    fireEvent.click(screen.getByRole("button", { name: "关闭登录或注册弹窗" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "登录 / 注册" })).toHaveFocus();
  });

  it("closes with Escape", async () => {
    renderHarness();
    await openModal();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("closes when the backdrop is clicked", async () => {
    renderHarness();
    await openModal();
    fireEvent.click(screen.getByTestId("auth-backdrop"));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("does not close when content inside the dialog is clicked", async () => {
    renderHarness();
    await openModal();
    fireEvent.click(screen.getByRole("heading", { name: "登录或注册" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("keeps all close paths available while a request is pending", async () => {
    postMock.mockImplementation(() => new Promise(() => undefined));
    renderHarness();
    await openModal();
    fireEvent.change(screen.getByLabelText("账号"), { target: { value: "pending-user" } });
    fireEvent.change(screen.getByLabelText("手机号"), { target: { value: "13800138000" } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "Pending-Password-2026" } });
    fireEvent.click(screen.getByRole("button", { name: "注册并进入" }));
    await waitFor(() => expect(screen.getByText("提交中…")).toBeDisabled());
    fireEvent.click(screen.getByRole("button", { name: "关闭登录或注册弹窗" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
