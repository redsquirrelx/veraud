import { afterEach, describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { SettingsPage } from "./SettingsPage.tsx"

afterEach(() => {
  window.localStorage.removeItem("tasks.visibility")
})

describe("SettingsPage", () => {
  it("shows the title with task notification toggles", () => {
    render(<SettingsPage />)

    expect(screen.getByRole("heading", { name: "General settings" })).toBeDefined()
    expect(screen.getByText("Task notifications")).toBeDefined()
    expect(screen.getByRole("checkbox", { name: /Clone/ })).toBeDefined()
  })

  it("persists muted read tasks as visible", async () => {
    render(<SettingsPage />)

    const toggle = screen.getByRole("checkbox", { name: /List branches/ })
    expect(toggle).not.toBeChecked()

    await userEvent.click(toggle)

    expect(toggle).toBeChecked()
    expect(JSON.parse(window.localStorage.getItem("tasks.visibility") as string)["list-branches"]).toBe(true)
  })
})
