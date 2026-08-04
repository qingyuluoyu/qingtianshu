import type { components } from "./openapi.generated";
import { api } from "./client";

export type AuthSession = components["schemas"]["AuthSessionResponse"];
export type AuthError = components["schemas"]["AuthErrorResponse"];

export function isFormalAccount(session: AuthSession | null): boolean {
  return Boolean(session?.is_registered && session.auth_type === "account");
}

export async function getSession(): Promise<AuthSession | null> {
  const { data, error, response } = await api.GET("/session");
  if (response.status === 401) return null;
  if (error || !data) throw new Error("无法读取当前会话");
  return data;
}

export async function signOut(): Promise<void> {
  const { response } = await api.DELETE("/session");
  if (!response.ok && response.status !== 401) throw new Error("退出登录失败");
}
