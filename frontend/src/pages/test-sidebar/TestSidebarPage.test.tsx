import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { TestSidebarPage } from "./TestSidebarPage.tsx"

describe("TestSidebarPage", () => {
  it("shows the sidebar next to other components", async () => {
    render(<TestSidebarPage />)

    expect(screen.getByText("Sidebar playground")).toBeDefined()
    expect(screen.getByText("Workspace")).toBeDefined()
    expect(screen.getByRole("button", { name: "Apply" })).toBeDefined()

    await userEvent.click(screen.getByRole("button", { name: "Audits" }))

    expect(screen.getByText("audits")).toBeDefined()
  })
})
