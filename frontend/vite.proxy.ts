export function resolveProxyTarget(value = process.env.VITE_PROXY_TARGET): string {
  return value?.trim() || "http://127.0.0.1:8000";
}
