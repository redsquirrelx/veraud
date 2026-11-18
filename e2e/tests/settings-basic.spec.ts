import { test, expect, type Page } from "@playwright/test"

async function openSettings(page: Page, tabName: string) {
  await page.getByRole("button", { name: "Settings" }).click()
  const tablist = page.getByRole("tablist", { name: "Settings sections" })
  await tablist.getByRole("tab", { name: tabName, exact: true }).click()
}

test.describe("Settings", () => {
  test("opens with the settings tablist and all four tabs", async ({ page }) => {
    await page.goto("/")
    await page.getByRole("button", { name: "Settings" }).click()
    const tablist = page.getByRole("tablist", { name: "Settings sections" })
    await expect(tablist).toBeVisible()
    for (const tab of ["Agents", "Audit", "Models & credentials", "Preferences"]) {
      await expect(tablist.getByRole("tab", { name: tab, exact: true })).toBeVisible()
    }
  })

  test("models editor lists the seeded providers through the API", async ({ page }) => {
    await page.goto("/")
    await openSettings(page, "Models & credentials")
    const panel = page.getByRole("tabpanel", { name: "Models & credentials" })
    await panel.getByRole("button", { name: "Add model", exact: true }).click()
    const editor = page.getByRole("dialog", { name: /Add a model/ })
    await expect(editor).toBeVisible()
    await editor.getByRole("button", { name: /Select a provider/ }).click()
    for (const provider of ["OpenAI", "Anthropic", "Google", "Groq"]) {
      await expect(editor.getByRole("option", { name: provider, exact: true })).toBeVisible()
    }
  })

  test("agents pane shows the seeded maintainability agent", async ({ page }) => {
    await page.goto("/")
    await openSettings(page, "Agents")
    const panel = page.getByRole("tabpanel", { name: "Agents" })
    await expect(panel.getByText(/maintainability/i).first()).toBeVisible()
  })
})
