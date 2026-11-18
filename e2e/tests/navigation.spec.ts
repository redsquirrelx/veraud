import { test, expect } from "@playwright/test"
import { seed } from "./helpers.ts"

test.describe("Project detail navigation", () => {
  test("sidebar switches between sections", async ({ page }) => {
    const sidebar = page.getByRole("complementary", { name: "Project" })

    await page.goto(`/projects/${seed.projectId}`)
    await expect(sidebar.getByRole("button", { name: "Overview" })).toHaveAttribute("aria-current", "page")

    await sidebar.getByRole("button", { name: "Files" }).click()
    await expect(page).toHaveURL(new RegExp(`/projects/${seed.projectId}/files`))
    await expect(page.getByText("README.md")).toBeVisible()

    await sidebar.getByRole("button", { name: "Audits" }).click()
    await expect(page).toHaveURL(new RegExp(`/projects/${seed.projectId}/audits$`))

    await sidebar.getByRole("button", { name: "Overview" }).click()
    await expect(page).toHaveURL(new RegExp(`/projects/${seed.projectId}(\\?|$|/)`))
  })

  test("an unknown section falls back to the overview", async ({ page }) => {
    const sidebar = page.getByRole("complementary", { name: "Project" })

    await page.goto(`/projects/${seed.projectId}/this-section-does-not-exist`)
    await expect(page).toHaveURL(new RegExp(`/projects/${seed.projectId}(\\?|$|/)`))
    await expect(sidebar.getByRole("button", { name: "Overview" })).toHaveAttribute("aria-current", "page")
  })

  test("opening a file shows its content", async ({ page }) => {
    await page.goto(`/projects/${seed.projectId}/files`)
    await page.getByRole("button", { name: "README.md" }).click()
    await expect(page.getByText("Veraud E2E sandbox")).toBeVisible()
  })

  test("the files section shows src/index.ts content", async ({ page }) => {
    await page.goto(`/projects/${seed.projectId}/files`)
    await page.getByRole("button", { name: "src" }).click()
    await page.getByRole("button", { name: "index.ts" }).click()
    await expect(page.getByText("releaseNotes")).toBeVisible()
  })
})
