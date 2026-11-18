import { test, expect } from "@playwright/test"
import { live } from "./helpers-live.ts"

// Opt-in smoke test for the architecture pipeline with offline models.
// Needs BOTH VERAUD_E2E_LIVE=1 and AGENT_SERVER_SMOKE_MODELS=1 in the shell,
// e.g. `VERAUD_E2E_LIVE=1 AGENT_SERVER_SMOKE_MODELS=1 pnpm --dir e2e test`.
// The pipeline executes for real, only model calls are replaced by the
// deterministic smoke models shipped in the agent-server itself.

test.skip(process.env.VERAUD_E2E_LIVE !== "1" || process.env.AGENT_SERVER_SMOKE_MODELS !== "1", "live smoke run is opt-in: set VERAUD_E2E_LIVE=1 and AGENT_SERVER_SMOKE_MODELS=1")

test("architecture pipeline completes with smoke models and appears in the explorer", async ({ page }) => {
  await page.goto(`/projects/${live.projectId}`)

  await page.getByRole("button", { name: "Analyze", exact: true }).click()
  await page.getByRole("menuitem", { name: /Project architecture/ }).click()

  await expect(page.getByRole("status").filter({ hasText: /Completed/i }).first()).toBeVisible({ timeout: 120_000 })

  await page.getByRole("button", { name: "Executions" }).click()
  const dialog = page.getByRole("dialog", { name: "Execution Explorer" })
  await expect(dialog.getByText(/Architecture context/i).first()).toBeVisible()
})
