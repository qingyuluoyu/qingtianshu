import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { resolveProxyTarget } from "./vite.proxy";

const backend = resolveProxyTarget();
const apiProxy = { target: backend, changeOrigin: true };
const stocksProxy = {
  ...apiProxy,
  bypass(request: { method?: string; headers: { accept?: string } }) {
    if (request.method === "GET" && request.headers.accept?.includes("text/html")) return "/index.html";
    return undefined;
  },
};

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: "./src/tests/setup.ts",
    globals: true,
    exclude: ["e2e/**", "e2e-real/**", "e2e-production/**", "src/tests/**/*.spec.ts", "node_modules/**"],
  },
  server: {
    proxy: {
      "/auth": apiProxy,
      "/session/*": apiProxy,
      "/sessions": apiProxy,
      "/users": apiProxy,
      "/v1": apiProxy,
      "/me": apiProxy,
      "/markets": apiProxy,
      "/indices": apiProxy,
      "/sectors": apiProxy,
      "/a-share": apiProxy,
      "/system": apiProxy,
      "/research-reports": apiProxy,
      "/peer-comparisons": apiProxy,
      "/stock-screener": apiProxy,
      "/events": apiProxy,
      "/stocks": stocksProxy,
    },
  },
});
