import { describe, expect, it } from "vitest"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { TestSelectorPage } from "./TestSelectorPage.tsx"

function branchesCard(): HTMLElement {
  const label = screen.getByText(/Branches \(/)
  const card = label.closest(".ui-card")
  if (card === null) {
    throw new Error("Branches card not found")
  }
  return card as HTMLElement
}

describe("TestSelectorPage", () => {
  it("pages branches with load more and tracks selection", async () => {
    render(
      <MemoryRouter>
        <TestSelectorPage />
      </MemoryRouter>
    )

    expect(screen.getByText("Selector playground")).toBeDefined()
    expect(screen.getByRole("button", { name: "main" })).toBeDefined()
    expect(screen.queryByRole("option")).toBeNull()

    await userEvent.click(screen.getByRole("button", { name: "main" }))

    expect(screen.queryByText("feature-10")).toBeNull()

    await userEvent.click(within(branchesCard()).getByText("Load more..."))

    expect(screen.getByRole("option", { name: /feature-10/ })).toBeDefined()

    await userEvent.click(screen.getByRole("option", { name: /feature-10/ }))

    expect(screen.getByRole("button", { name: "feature-10" })).toBeDefined()
    expect(screen.getByText("feature-10", { selector: "p" })).toBeDefined()
    expect(screen.queryByRole("option")).toBeNull()

    await userEvent.click(screen.getByRole("button", { name: "feature-10" }))
    await userEvent.click(within(branchesCard()).getByText("Load more..."))

    expect(within(branchesCard()).queryByText("Load more...")).toBeNull()
    expect(screen.getByRole("option", { name: /feature-24/ })).toBeDefined()
  })

  it("selects a branch by typing its id", async () => {
    render(
      <MemoryRouter>
        <TestSelectorPage />
      </MemoryRouter>
    )

    await userEvent.type(screen.getByLabelText("Search items"), "feature-3{enter}")

    expect(screen.getByText("feature-3", { selector: "p" })).toBeDefined()
  })
})
