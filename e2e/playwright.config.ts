import { defineConfig } from "@playwright/test";

// Runs against a real stack (UI + API + FalkorDB). Start it first; see README "End-to-end tests".
export default defineConfig({
  testDir: "./tests",
  workers: 1, // the tests share one graph, so they run one at a time
  fullyParallel: false,
  timeout: 120_000,
  expect: { timeout: 20_000 },
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3001",
    viewport: { width: 1440, height: 900 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    launchOptions: process.env.E2E_CHROME ? { executablePath: process.env.E2E_CHROME } : {},
  },
});
