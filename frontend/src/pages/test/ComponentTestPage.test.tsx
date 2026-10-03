import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { ComponentTestPage } from "./ComponentTestPage.tsx"

describe("ComponentTestPage", () => {
  it("showcases every reusable component", () => {
    render(
      <MemoryRouter>
        <ComponentTestPage />
      </MemoryRouter>
    )

    expect(screen.getByText("Component playground")).toBeDefined()
    expect(screen.getByText("Card / white surface")).toBeDefined()
    expect(screen.getByText("Panel / tinted surface")).toBeDefined()
    expect(screen.getAllByRole("button", { name: "Register project" }).length).toBeGreaterThan(0)
    expect(screen.getAllByText("Registering").length).toBeGreaterThan(0)
    expect(screen.getByPlaceholderText("Empty")).toBeDefined()
    expect(screen.getAllByText("Project registered").length).toBeGreaterThan(0)
    expect(screen.getAllByText("Repository is not accessible").length).toBeGreaterThan(0)
    expect(screen.getByText("Syncing repository")).toBeDefined()
    expect(screen.getByText("Audit in progress")).toBeDefined()
    expect(screen.getByText("fintech-core/payment-gateway-v2")).toBeDefined()
    expect(screen.getByText("Projects and Repositories")).toBeDefined()
  })
})
