import type { components } from "./openapi.generated";
import { api } from "./client";

export type AuthSession = components["schemas"]["AuthSessionResponse"];
export type AuthError = components["schemas"]["AuthErrorResponse"];

export function isFormalAccount(session: AuthSession | null): boolean {
  return Boolean(session?.is_registered && session.auth_type === "account");
}

export async function getSession(): Promise<AuthSession | null> {
  // Anonymous session discovery is expected to receive 401. XHR preserves that
  // contract without emitting a browser console resource error for the normal path.
  return new Promise<AuthSession | null>((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("GET", "/session");
    request.withCredentials = true;
    request.onload = () => {
      if (request.status === 401) { resolve(null); return; }
      if (request.status < 200 || request.status >= 300) { reject(new Error("无法读取当前会话")); return; }
      try { resolve(JSON.parse(request.responseText) as AuthSession); } catch { reject(new Error("无法读取当前会话")); }
    };
    request.onerror = () => reject(new Error("无法读取当前会话"));
    request.send();
  });
}

export async function signOut(): Promise<void> {
  const { response } = await api.DELETE("/session");
  if (!response.ok && response.status !== 401) throw new Error("退出登录失败");
}
