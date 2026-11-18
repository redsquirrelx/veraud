import { test, expect, type Page, type Locator } from "@playwright/test"
import { live } from "./helpers-live.ts"

test.describe.configure({ mode: "serial" })
const projectId = live.projectId

test.describe("Live — polleria real: analysis pipeline, maintainability audit (Testability/test_isolation), verification suite", () => {

  test("polleria renders READY with its real revision", async ({ page }) => {
    await page.goto(`/projects/${projectId}`)
    await expect(page.getByRole("heading", { name: "Cesar-Sanchez-sof/Polleria" })).toBeVisible()
    await expect(page.getByText("READY", { exact: true })).toBeVisible()
    await expect(page.getByText(new RegExp(`On develop at ${live.commit.slice(0, 7)}`))).toBeVisible()
  })

  test("analysis pipeline dispatch runs and architecture context becomes available", async ({ page }) => {
    await page.goto(`/projects/${projectId}`)
    await page.getByRole("button", { name: "Analyze", exact: true }).click()

    const architectureContext = page.getByRole("button", { name: "Architecture Context" })
    await expect(architectureContext).toBeEnabled({ timeout: 20 * 60_000 })
  })

  async function openAndConfigureAuditDrawer(page: Page) {
    await page.goto(`/projects/${projectId}/analysis`)
    await page.getByRole("button", { name: "Configure audit", exact: true }).click()
    const drawer = page.getByRole("dialog", { name: "Configure audit" })
    await expect(drawer).toBeVisible()
    // Wait until the maintainability drawer is interactive (context cascade completed).
    await expect(drawer.getByRole("button", { name: /Expand Maintainability/ })).toBeEnabled({ timeout: 20 * 60_000 })
    return drawer
  }

  /** Clears the default selection down to Testability with only TestIsolationAgent. */
  async function selectTestabilityIsolationOnly(drawer: Locator) {
    const enableSecurity = drawer.getByRole("checkbox", { name: "Enable Security" })
    if (await enableSecurity.isChecked()) await enableSecurity.click()
    await expect(enableSecurity).not.toBeChecked()

    for (const name of ["Modularity", "Reusability"]) {
      const box = drawer.getByRole("checkbox", { name, exact: true })
      if (await box.isChecked()) await box.click()
      await expect(box).not.toBeChecked()
    }

    const testControllability = drawer.getByRole("checkbox", { name: "TestControllabilityAgent" })
    if (await testControllability.isChecked()) await testControllability.click()
    await expect(testControllability).not.toBeChecked()
    await expect(drawer.getByRole("checkbox", { name: "TestIsolationAgent" })).toBeChecked()
    await expect(drawer.getByRole("checkbox", { name: "Testability", exact: true })).toBeChecked()
  }

  test("analysis page opens with Testability -> isolation only configured", async ({ page }) => {
    const drawer = await openAndConfigureAuditDrawer(page)
    await selectTestabilityIsolationOnly(drawer)

    const trigger = drawer.getByRole("button", { name: /Maintainability/ }).first()
    await expect(trigger).toBeEnabled()
    await drawer.getByRole("button", { name: "Close" }).click()
    await expect(page.getByRole("button", { name: "Start audit" })).toBeEnabled()
  })

  test("dispatch the maintainability audit with test_isolation only and wait for completion", async ({ page }) => {
    const drawer = await openAndConfigureAuditDrawer(page)
    await selectTestabilityIsolationOnly(drawer)
    await drawer.getByRole("button", { name: "Close" }).click()

    await page.getByRole("button", { name: "Start audit" }).click()

    await page.goto(`/projects/${projectId}/audits`)
    await expect(page.getByText("Running", { exact: true }).first()).toBeVisible()

    const deadline = Date.now() + 25 * 60_000
    for (;;) {
      await page.getByRole("button", { name: "Refresh" }).click().catch(() => {})
      try {
        await expect(page.getByText("Evaluation completed", { exact: true }).first()).toBeVisible({ timeout: 10_000 })
        break
      } catch {
        if (Date.now() > deadline) throw new Error("Maintainability audit did not complete within 25 minutes")
      }
    }
  })

  test("create the verification suite from the completed audit", async ({ page }) => {
    await page.goto(`/projects/${projectId}/audits`)
    const completed = page.getByRole("link", { name: /View audit #\d+ details/ }).first()
    await expect(completed).toBeVisible()
    await completed.click()

    await page.getByRole("tab", { name: "Verification" }).click()
    await page.getByRole("button", { name: /Create verification suite/ }).click()

    await expect(page.getByRole("button", { name: "Download suite" })).toBeEnabled({ timeout: 20 * 60_000 })
  })
})
