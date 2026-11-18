import { test, expect } from "@playwright/test"

// Opt-in live test: clones a tiny public repository from GitHub. Skipped by
// default; run with `VERAUD_E2E_LIVE=1 pnpm --dir e2e test`.
const REPO_URL = process.env.VERAUD_E2E_LIVE_REPO ?? "https://github.com/octocat/Hello-World"
const REPO_NAME = REPO_URL.replace(/\/$/, "").split("/").slice(-1)[0] ?? "Hello-World"

test.skip(process.env.VERAUD_E2E_LIVE !== "1", "live network test is opt-in: set VERAUD_E2E_LIVE=1")

test("registers a public GitHub repository end to end", async ({ page }) => {
  await page.goto("/")
  await page.getByRole("textbox", { name: /Repository URL/i }).fill(REPO_URL)
  await page.getByRole("button", { name: "Register project" }).click()

  await expect(page.getByRole("status").filter({ hasText: new RegExp(REPO_NAME, "i") })).toBeVisible({ timeout: 30_000 })
  await expect(page.getByText(REPO_NAME, { exact: false }).first()).toBeVisible()
})
