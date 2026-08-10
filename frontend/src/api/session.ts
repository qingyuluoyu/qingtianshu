import type { components } from "./openapi.generated";
import { api } from "./client";

export type AuthSession = components["schemas"]["AuthSessionResponse"];
export type AuthError = components["schemas"]["AuthErrorResponse"];

export function isFormalAccount(session: AuthSession | null): boolean {
  return Boolean(session?.is_registered && session.auth_type === "account");
}

export async function getSession(): Promise<AuthSession | null> {
  try {
    const response = await fetch("/session/status", { credentials: "same-origin" });
    if (!response.ok) throw new Error(`会话状态请求失败 (${response.status})`);
    const payload = await response.json() as { authenticated?: unknown; session?: AuthSession };
    if (payload.authenticated === false) return null;
    if (payload.authenticated === true && payload.session) return payload.session;
    throw new Error("会话状态响应不符合契约");
  } catch (error) {
    // 网络错误、JSON 解析失败、端点不存在等情况统一视为未登录。
    throw error;
  }
}

export async function signOut(): Promise<void> {
  const { response } = await api.DELETE("/session");
  if (!response.ok && response.status !== 401) throw new Error("退出登录失败");
}
