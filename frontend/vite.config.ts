import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

const backend = process.env.VITE_PROXY_TARGET ?? "http://127.0.0.1:8000";
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
    exclude: ["e2e/**", "e2e-real/**", "e2e-production/**", "node_modules/**"],
  },
  server: {
    proxy: {
      "/auth": apiProxy,
      "/session": apiProxy,
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
      "/events": apiProxy,
      "/stocks": stocksProxy,
    },
  },
});
