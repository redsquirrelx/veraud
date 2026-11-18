import { test, expect } from "@playwright/test"
import { seed } from "./helpers.ts"

test.describe("Home", () => {
  test("lists the seeded project with READY badge", async ({ page }) => {
    await page.goto("/")
    await expect(page.getByRole("button", { name: "e2e-owner/e2e-sandbox" })).toBeVisible()
    await expect(page.getByText("READY", { exact: true }).first()).toBeVisible()
  })

  test("register button is disabled while the URL is empty", async ({ page }) => {
    await page.goto("/")
    const submit = page.getByRole("button", { name: "Register project" })
    await expect(submit).toBeDisabled()
    await page.getByRole("textbox", { name: /Repository URL/i }).fill("https://github.com/e2e-owner/e2e-sandbox")
    await expect(submit).toBeEnabled()
  })

  test("registering an invalid URL reports a backend error as a toast", async ({ page }) => {
    await page.goto("/")
    await page.getByRole("textbox", { name: /Repository URL/i }).fill("not a url at all")
    await page.getByRole("button", { name: "Register project" }).click()
    await expect(page.getByRole("alert").first()).toContainText(/github/i)
  })

  test("pinning persists across a reload", async ({ page }) => {
    await page.goto("/")
    const pin = page.getByRole("button", { name: "Pin project" })
    await pin.click()
    await expect(page.getByRole("button", { name: "Unpin project" })).toBeVisible()
    await page.reload()
    await expect(page.getByRole("button", { name: "Unpin project" })).toBeVisible()
    // Restore the clean state for any later scenario.
    await page.getByRole("button", { name: "Unpin project" }).click()
    await expect(page.getByRole("button", { name: "Pin project" })).toBeVisible()
  })

  test("inspect opens the project detail page", async ({ page }) => {
    await page.goto("/")
    await page.getByRole("button", { name: "Inspect" }).click()
    await expect(page).toHaveURL(new RegExp(`/projects/${seed.projectId}(\\?|$|/)`))
  })
})
