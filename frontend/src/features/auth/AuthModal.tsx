import { FormEvent, type MouseEvent, type RefObject, useEffect, useId, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import styles from "./AuthModal.module.css";

type Mode = "register" | "login";

function messageFor(error: unknown): string {
  const value = error as { code?: string; message?: string } | undefined;
  if (value?.code === "invalid_credentials") return "账号或密码错误";
  if (value?.code === "account_exists") return "账号已存在";
  if (value?.code === "phone_exists") return "手机号已存在";
  return value?.message || "请求失败，请稍后重试";
}

type Props = {
  onClose: () => void;
  returnFocusRef: RefObject<HTMLElement | null>;
};

export function AuthModal({ onClose, returnFocusRef }: Props) {
  const [mode, setMode] = useState<Mode>("register");
  const [error, setError] = useState("");
  const dialogRef = useRef<HTMLElement>(null);
  const onCloseRef = useRef(onClose);
  const titleId = useId();
  const queryClient = useQueryClient();
  onCloseRef.current = onClose;

  useEffect(() => {
    dialogRef.current?.focus();
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCloseRef.current();
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("keydown", closeOnEscape);
      returnFocusRef.current?.focus();
    };
  }, [returnFocusRef]);
  const mutation = useMutation({
    mutationFn: async (form: FormData) => {
      if (mode === "register") {
        const { data, error: apiError } = await api.POST("/auth/register", {
          body: {
            account: String(form.get("account") || ""),
            phone: String(form.get("phone") || ""),
            password: String(form.get("password") || ""),
          },
        });
        if (apiError || !data) throw apiError;
        return data;
      }
      const { data, error: apiError } = await api.POST("/auth/login", {
        body: {
          login: String(form.get("login") || ""),
          password: String(form.get("password") || ""),
        },
      });
      if (apiError || !data) throw apiError;
      return data;
    },
    onSuccess: () => {
      // Invalidate the session query so App.tsx refetches /session/status,
      // the authoritative source. This ensures isFormalAccount is computed
      // from verified server data rather than the auth endpoint response.
      void queryClient.invalidateQueries({ queryKey: ["session"] });
      onClose();
    },
    onError: (reason) => setError(messageFor(reason)),
  });

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError("");
    mutation.mutate(new FormData(event.currentTarget));
  };

  const closeFromBackdrop = (event: MouseEvent<HTMLDivElement>) => {
    if (event.target === event.currentTarget) onClose();
  };

  return (
    <div className={styles.backdrop} data-testid="auth-backdrop" role="presentation" onClick={closeFromBackdrop}>
      <section aria-labelledby={titleId} aria-modal="true" className={styles.modal} ref={dialogRef} role="dialog" tabIndex={-1}>
        <div className={styles.titleRow}>
          <h2 id={titleId}>登录或注册</h2>
          <button aria-label="关闭登录或注册弹窗" className={styles.close} onClick={onClose} type="button">×</button>
        </div>
        <div className={styles.tabs}>
          <button className={mode === "register" ? styles.selected : ""} onClick={() => setMode("register")} type="button">注册</button>
          <button className={mode === "login" ? styles.selected : ""} onClick={() => setMode("login")} type="button">登录</button>
        </div>
        <p className={styles.modeTitle}>{mode === "register" ? "创建正式账户" : "登录正式账户"}</p>
        <form onSubmit={submit}>
          {mode === "register" ? <>
            <label>账号<input autoComplete="username" name="account" required /></label>
            <label>手机号<input autoComplete="tel" inputMode="tel" name="phone" required /></label>
          </> : <label>账号或手机号<input autoComplete="username" name="login" required /></label>}
          <label>密码<input autoComplete={mode === "register" ? "new-password" : "current-password"} minLength={mode === "register" ? 8 : undefined} name="password" required type="password" /></label>
          {error ? <p className={styles.error} role="alert">{error}</p> : null}
          <button className={styles.submit} disabled={mutation.isPending} type="submit">{mutation.isPending ? "提交中…" : mode === "register" ? "注册并进入" : "登录"}</button>
        </form>
      </section>
    </div>
  );
}
