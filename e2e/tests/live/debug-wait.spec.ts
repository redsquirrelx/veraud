import { test, expect } from "@playwright/test"
import { live } from "./helpers-live.ts"

test("snapshot restore: drawer state straight away", async ({ page }) => {
  await page.goto(`/projects/${live.projectId}/analysis`)
  await page.waitForLoadState("networkidle")
  await page.getByRole("button", { name: "Configure audit", exact: true }).click()
  const drawer = page.getByRole("dialog", { name: "Configure audit" })
  await expect(drawer).toBeVisible()
  const html = await drawer.innerHTML()
  const idx = html.indexOf("Maintainability")
  console.log("MAINTAINER region:\n", html.slice(Math.max(0, idx - 250), idx + 80))
  const trigger = page.getByRole("button", { name: /Maintainability/ }).first()
  await expect(trigger).toBeEnabled({ timeout: 5_000 })
  console.log("trigger enabled")
})
