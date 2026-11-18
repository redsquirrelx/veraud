import { test, expect, type Page } from "@playwright/test"
import { seed } from "./helpers.ts"

async function openExplorerAndSelect(page: Page, name: string | RegExp) {
  await page.getByRole("button", { name: "Executions" }).click()
  const dialog = page.getByRole("dialog", { name: "Execution Explorer" })
  await dialog.getByRole("button", { name }).click()
  return dialog
}

test.describe("Cancel audit from the explorer", () => {
  test("a running audit shows the cancel action and asks for confirmation", async ({ page }) => {
    await page.goto(`/projects/${seed.projectId}`)
    const dialog = await openExplorerAndSelect(page, new RegExp(`Maintainability · #${seed.executions.cancelAudit}`))

    const cancel = dialog.getByRole("button", { name: "Cancel audit" })
    await expect(cancel).toBeVisible()

    await cancel.click()
    const confirmDialog = page.getByRole("dialog", { name: "Cancel audit?" })
    await expect(confirmDialog).toBeVisible()
    await confirmDialog.getByRole("button", { name: "Confirm cancellation" }).click()

    // The server persisted cancellation_requested_at, so the action disappears.
    await expect(dialog.getByRole("button", { name: "Cancel audit" })).toHaveCount(0)
  })

  test("agents cannot be cancelled", async ({ page }) => {
    await page.goto(`/projects/${seed.projectId}`)
    const dialog = await openExplorerAndSelect(page, /Verification Suite/)
    await expect(dialog.getByRole("button", { name: "Cancel audit" })).toHaveCount(0)
  })

  test("completed audits are not cancellable", async ({ page }) => {
    await page.goto(`/projects/${seed.projectId}`)
    const dialog = await openExplorerAndSelect(page, new RegExp(`#${seed.executions.jointCompletedMaintainability}`))
    await expect(dialog.getByRole("button", { name: "Cancel audit" })).toHaveCount(0)
  })
})
