import { test, expect, type Page } from "@playwright/test"
import { seed, useSpanish } from "./helpers.ts"

async function openExplorer(page: Page) {
  await page.getByRole("button", { name: "Executions" }).click()
  return page.getByRole("dialog", { name: "Execution Explorer" })
}

const auditName = (title: string, id: number) => `${title} · #${id}`

test.describe("Execution Explorer", () => {
  test("opens with its tabs and the seeded executions", async ({ page }) => {
    await page.goto(`/projects/${seed.projectId}`)
    const dialog = await openExplorer(page)

    await expect(dialog).toBeVisible()
    await expect(dialog.getByRole("tab", { name: /All executions/ })).toBeVisible()
    await expect(dialog.getByRole("tab", { name: /Audits/ })).toBeVisible()
    await expect(dialog.getByRole("tab", { name: /Standalone agents/ })).toBeVisible()
    await expect(dialog.getByRole("tab", { name: /^(All|Running|Completed|Failed)/ }).first()).toBeVisible()
    await expect(dialog.getByRole("list", { name: "Executions" })).toBeVisible()
  })

  test("shows every seeded execution row", async ({ page }) => {
    await page.goto(`/projects/${seed.projectId}`)
    const dialog = await openExplorer(page)

    await expect(dialog.getByRole("button", { name: auditName("Maintainability", seed.executions.runningAudit) })).toBeVisible()
    await expect(dialog.getByRole("button", { name: auditName("Maintainability + Security", seed.executions.jointCompletedMaintainability) })).toBeVisible()
    await expect(dialog.getByRole("button", { name: auditName("Maintainability", seed.executions.failedAudit) })).toBeVisible()
    await expect(dialog.getByRole("button", { name: /Architecture Context/ })).toBeVisible()
    await expect(dialog.getByRole("button", { name: /Verification Suite/ })).toBeVisible()
  })

  test("standalone agents tab excludes audits", async ({ page }) => {
    await page.goto(`/projects/${seed.projectId}`)
    const dialog = await openExplorer(page)

    await dialog.getByRole("tab", { name: /Standalone agents/ }).click()
    await expect(dialog.getByRole("button", { name: auditName("Maintainability", seed.executions.runningAudit) })).toHaveCount(0)
    await expect(dialog.getByRole("button", { name: /Architecture Context/ })).toBeVisible()
    await expect(dialog.getByRole("button", { name: /Verification Suite/ })).toBeVisible()
  })

  test("failed audit shows its error receipts when selected", async ({ page }) => {
    await page.goto(`/projects/${seed.projectId}`)
    const dialog = await openExplorer(page)

    await dialog.getByRole("button", { name: auditName("Maintainability", seed.executions.failedAudit) }).click()
    // Machine error strings are sanitized before display; assert the error surface exists.
    await expect(dialog.getByRole("alert").first()).toBeVisible()
    await expect(dialog.getByText("Failed", { exact: true }).first()).toBeVisible()
    await expect(dialog.getByRole("button", { name: "Cancel audit" })).toHaveCount(0)
  })

  test("an agent without nested receipts renders detail without a hierarchy", async ({ page }) => {
    await page.goto(`/projects/${seed.projectId}`)
    const dialog = await openExplorer(page)

    await dialog.getByRole("button", { name: "Architecture Context" }).click()
    await expect(dialog.getByRole("heading", { name: "Architecture Context", level: 3 })).toBeVisible()
    // Single receipt: no hierarchy, so no tree pane and no separator.
    await expect(dialog.getByRole("separator")).toHaveCount(0)
  })

  test("verification suite renders its generator receipts", async ({ page }) => {
    await page.goto(`/projects/${seed.projectId}`)
    const dialog = await openExplorer(page)

    await dialog.getByRole("button", { name: "Verification Suite" }).click()
    // Root plus two nested generator agents = the receipts render as a tree.
    await expect(dialog.getByRole("button", { name: /Finding test generation/ }).first()).toBeVisible()
    await expect(dialog.getByRole("button", { name: /Testability probe/ }).first()).toBeVisible()
    await expect(dialog.getByRole("separator")).toHaveCount(1)
  })

  test("tree pane widens and persists across reloads", async ({ page }) => {
    await page.goto(`/projects/${seed.projectId}`)
    const dialog = await openExplorer(page)

    await dialog.getByRole("button", { name: auditName("Maintainability", seed.executions.runningAudit) }).click()
    const separator = dialog.getByRole("separator", { name: "Resize the agent list" })
    await expect(separator).toBeVisible()

    const treePane = dialog.locator(".execution-explorer-tree-pane").first()
    const initialWidth = (await treePane.boundingBox())!.width

    await separator.focus()
    await page.keyboard.press("ArrowRight")
    await page.keyboard.press("ArrowRight")
    const widened = (await treePane.boundingBox())!.width
    expect(widened).toBeGreaterThan(initialWidth)

    await page.reload()
    const dialogAfterReload = await openExplorer(page)
    await dialogAfterReload.getByRole("button", { name: auditName("Maintainability", seed.executions.runningAudit) }).click()
    const treePaneAfterReload = dialogAfterReload.locator(".execution-explorer-tree-pane").first()
    await expect(treePaneAfterReload).toBeVisible()
    const widthAfterReload = (await treePaneAfterReload.boundingBox())!.width
    expect(Math.abs(widthAfterReload - widened)).toBeLessThanOrEqual(1)
  })

  test("spanish locale renders the explorer in Spanish", async ({ page }) => {
    await useSpanish(page)
    await page.goto(`/projects/${seed.projectId}`)
    await page.getByRole("button", { name: "Ejecuciones" }).click()
    const dialog = page.getByRole("dialog", { name: "Explorador de ejecuciones" })
    await expect(dialog).toBeVisible()
    await expect(dialog.getByRole("tab", { name: /Todas las ejecuciones/ })).toBeVisible()
    await expect(dialog.getByRole("tab", { name: /Auditorías/ })).toBeVisible()
  })
})
