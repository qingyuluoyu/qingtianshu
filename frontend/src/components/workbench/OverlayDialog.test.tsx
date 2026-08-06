import { fireEvent, render, screen } from "@testing-library/react";
import { createRef } from "react";
import { describe, expect, it, vi } from "vitest";
import { OverlayDialog } from "./OverlayDialog";

describe("OverlayDialog", () => {
  it("moves focus into the dialog and restores it when Escape closes", () => {
    const trigger = document.createElement("button");
    trigger.textContent = "查看证据";
    document.body.append(trigger);
    trigger.focus();
    const returnFocusRef = createRef<HTMLButtonElement>();
    returnFocusRef.current = trigger;
    const onClose = vi.fn();

    render(
      <OverlayDialog
        onClose={onClose}
        open
        returnFocusRef={returnFocusRef}
        title="证据详情"
      >
        正文
      </OverlayDialog>,
    );

    const dialog = screen.getByRole("dialog", { name: "证据详情" });
    expect(dialog).toHaveFocus();
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(trigger).toHaveFocus();
    trigger.remove();
  });
});
