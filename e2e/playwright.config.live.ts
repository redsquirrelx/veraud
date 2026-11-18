import { defineConfig, devices } from "@playwright/test"
import { join, dirname } from "node:path"
import { fileURLToPath } from "node:url"

const here = dirname(fileURLToPath(import.meta.url))

export const appdata = process.env.VERAUD_E2E_LIVE_APPDATA ?? join(here, ".live-appdata")

export default defineConfig({
  testDir: "./tests/live",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 30 * 60_000,
  expect: { timeout: 10_000 },
  globalSetup: "./global-setup-live.ts",
  use: {
    baseURL: "http://127.0.0.1:7600",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
})
