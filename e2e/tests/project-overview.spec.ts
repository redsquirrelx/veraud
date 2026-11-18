import { test, expect } from "@playwright/test"
import { seed } from "./helpers.ts"

test.describe("Project overview", () => {
  test("shows repository identity, sync and analysis controls", async ({ page }) => {
    await page.goto(`/projects/${seed.projectId}`)

    await expect(page.getByRole("heading", { name: "e2e-owner/e2e-sandbox" })).toBeVisible()
    await expect(page.getByRole("status").filter({ hasText: "READY" }).or(page.getByText("READY", { exact: true }).first())).toBeVisible()
    await expect(page.getByRole("button", { name: /Sync/i })).toBeVisible()
    await expect(page.getByRole("button", { name: "Analyze", exact: true })).toBeVisible()
    await expect(page.getByRole("heading", { name: /owner\/e2e-sandbox/ })).toBeVisible()
  })

  test("applied version line identifies main at its short hash", async ({ page }) => {
    await page.goto(`/projects/${seed.projectId}`)
    await expect(page.getByText(new RegExp(`On main at ${seed.mainCommit.slice(0, 7)}`))).toBeVisible()
  })

  test("audit summary routes to the audits section", async ({ page }) => {
    await page.goto(`/projects/${seed.projectId}`)
    const summary = page.getByRole("region", { name: "Audits" })
    await expect(summary).toBeVisible()
    await summary.getByRole("link", { name: /Audits/ }).click()
    await expect(page).toHaveURL(new RegExp(`/projects/${seed.projectId}/audits`))
  })
})
