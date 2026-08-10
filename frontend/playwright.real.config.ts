import { defineConfig, devices } from "@playwright/test";

const browserChannel = process.env.PLAYWRIGHT_BROWSER_CHANNEL || undefined;

export default defineConfig({
  testDir: "./e2e-real",
  timeout: 180_000,
  expect: { timeout: 30_000 },
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:4174",
    ...devices["Desktop Chrome"],
    channel: browserChannel,
  },
  webServer: {
    command: "npm run dev -- --host 127.0.0.1 --port 4174",
    url: "http://127.0.0.1:4174",
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
