import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AccessGate } from "./AccessGate";

describe("AccessGate", () => {
  it("does not mount protected content when access is denied", () => {
    render(<AccessGate allowed={false} fallback={<p>登录后查看个人研究</p>}><p>private content</p></AccessGate>);

    expect(screen.getByText("登录后查看个人研究")).toBeInTheDocument();
    expect(screen.queryByText("private content")).not.toBeInTheDocument();
  });

  it("renders protected content when access is allowed", () => {
    render(<AccessGate allowed fallback={<p>登录后查看个人研究</p>}><p>private content</p></AccessGate>);

    expect(screen.getByText("private content")).toBeInTheDocument();
    expect(screen.queryByText("登录后查看个人研究")).not.toBeInTheDocument();
  });
});
