import { defineConfig, devices } from "@playwright/test"
import { join, resolve, dirname } from "node:path"
import { fileURLToPath } from "node:url"

const here = dirname(fileURLToPath(import.meta.url))

export const appdata = join(here, ".appdata")
export const FRONTEND_PORT = 7600
export const BACKEND_PORT = 7601
export const AGENT_SERVER_PORT = 7602

export default defineConfig({
  testDir: "./tests",
  testIgnore: ["**/live/**"],
  fullyParallel: false,
  workers: 1,
  retries: 1,
  timeout: 45_000,
  expect: { timeout: 5_000 },
  globalSetup: "./global-setup.ts",
  use: {
    baseURL: `http://127.0.0.1:${FRONTEND_PORT}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
})
