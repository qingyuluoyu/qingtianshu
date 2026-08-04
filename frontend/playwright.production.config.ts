import { defineConfig, devices } from "@playwright/test";

const baseURL = process.env.QINGSHU_PRODUCTION_E2E_BASE_URL;
if (!baseURL) throw new Error("QINGSHU_PRODUCTION_E2E_BASE_URL is required");

export default defineConfig({
  testDir: "./e2e-production",
  timeout: 300_000,
  expect: { timeout: 45_000 },
  workers: 1,
  use: {
    baseURL,
    ...devices["Desktop Chrome"],
  },
});
