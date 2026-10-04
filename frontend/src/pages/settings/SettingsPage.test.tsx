import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import { SettingsPage } from "./SettingsPage.tsx"

describe("SettingsPage", () => {
  it("shows only the title", () => {
    render(<SettingsPage />)

    expect(screen.getByRole("heading", { name: "General settings" })).toBeDefined()
  })
})
