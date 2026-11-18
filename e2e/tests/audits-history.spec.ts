import { test, expect } from "@playwright/test"
import { seed } from "./helpers.ts"

test.describe("Audit history", () => {
  const runningId = seed.executions.runningAudit
  const jointMaintainabilityId = seed.executions.jointCompletedMaintainability
  const jointSecurityId = seed.executions.jointCompletedSecurity
  const failedId = seed.executions.failedAudit

  test("lists the seeded audit rows with their badges", async ({ page }) => {
    await page.goto(`/projects/${seed.projectId}/audits`)

    const rows = page.locator("article.quality-audit-run-row")
    await expect(rows).toHaveCount(5)

    await expect(page.getByRole("link", { name: `View audit #${runningId} details` })).toBeVisible()
    await expect(page.getByRole("link", { name: `View audit #${seed.executions.cancelAudit} details` })).toBeVisible()
    await expect(page.getByRole("link", { name: `View audit #${jointMaintainabilityId} details` })).toBeVisible()
    await expect(page.getByRole("link", { name: `View audit #${jointSecurityId} details` })).toBeVisible()
    await expect(page.getByRole("link", { name: `View audit #${failedId} details` })).toBeVisible()

    // The joint audit spans maintainability and security as two rows sharing one evaluation.
    await expect(rows.filter({ hasText: "Maintainability + Security" })).toHaveCount(2)
  })

  test("filters by status", async ({ page }) => {
    await page.goto(`/projects/${seed.projectId}/audits`)

    await page.getByRole("tab", { name: "Failed" }).click()
    await expect(page.locator("article.quality-audit-run-row")).toHaveCount(1)
    await expect(page.getByRole("link", { name: `View audit #${failedId} details` })).toBeVisible()

    await page.getByRole("tab", { name: "Completed" }).click()
    await expect(page.locator("article.quality-audit-run-row")).toHaveCount(2)
    await expect(page.getByRole("link", { name: `View audit #${jointMaintainabilityId} details` })).toBeVisible()

    await page.getByRole("tab", { name: "All" }).click()
    await expect(page.locator("article.quality-audit-run-row")).toHaveCount(5)
  })

  test("audit detail route renders for a completed audit", async ({ page }) => {
    await page.goto(`/projects/${seed.projectId}/audits/${jointMaintainabilityId}`)
    await expect(page.getByRole("heading", { name: new RegExp(`#${jointMaintainabilityId}`) }).first()).toBeVisible()
  })
})
