import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests run against a *live* stack (API + Postgres + Qdrant already
 * seeded), because the point of these tests is to prove the real pipeline works
 * in the browser — not to re-mock what the unit tests already cover.
 *
 *   make up && make seed && make dev-api && make dev-web
 *   cd web && npx playwright test
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  expect: { timeout: 30_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3100",
    viewport: { width: 1600, height: 1000 },
    deviceScaleFactor: 2,
    colorScheme: "dark",
    locale: "pt-BR",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
