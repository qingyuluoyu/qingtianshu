import { useCallback, useEffect, useId, useRef } from "react";
import type { KeyboardEvent, ReactNode, RefObject } from "react";
import styles from "./workbench.module.css";

const focusableSelector = [
  "button:not([disabled])",
  "a[href]",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

export function OverlayDialog({
  open,
  title,
  children,
  onClose,
  returnFocusRef,
}: {
  open: boolean;
  title: string;
  children: ReactNode;
  onClose: () => void;
  returnFocusRef?: RefObject<HTMLElement | null>;
}) {
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);

  const restoreFocus = useCallback(() => {
    (returnFocusRef?.current ?? previousFocusRef.current)?.focus();
  }, [returnFocusRef]);

  const close = useCallback(() => {
    onClose();
    restoreFocus();
  }, [onClose, restoreFocus]);

  useEffect(() => {
    if (!open) return;
    previousFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    dialogRef.current?.focus();
    return restoreFocus;
  }, [open, restoreFocus]);

  if (!open) return null;

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      close();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = Array.from(dialogRef.current?.querySelectorAll<HTMLElement>(focusableSelector) ?? []);
    if (focusable.length === 0) {
      event.preventDefault();
      dialogRef.current?.focus();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  return (
    <div
      className={styles.dialogBackdrop}
      onMouseDown={(event) => { if (event.target === event.currentTarget) close(); }}
    >
      <div
        aria-labelledby={titleId}
        aria-modal="true"
        className={styles.dialog}
        onKeyDown={handleKeyDown}
        ref={dialogRef}
        role="dialog"
        tabIndex={-1}
      >
        <header className={styles.dialogHeader}>
          <h2 id={titleId}>{title}</h2>
          <button aria-label="关闭" onClick={close} type="button">×</button>
        </header>
        <div className={styles.dialogBody}>{children}</div>
      </div>
    </div>
  );
}
