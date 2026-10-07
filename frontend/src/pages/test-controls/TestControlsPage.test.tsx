import { describe, expect, it } from "vitest"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { TestControlsPage } from "./TestControlsPage.tsx"

function favoriteCard(): HTMLElement {
  const label = screen.getByText(/Single-select list \(favorite:/)
  const card = label.closest(".ui-card")
  if (card === null) {
    throw new Error("Favorite card not found")
  }
  return card as HTMLElement
}

describe("TestControlsPage", () => {
  it("renders labeled inputs next to the selectors", async () => {
    render(
      <MemoryRouter>
        <TestControlsPage />
      </MemoryRouter>
    )

    expect(screen.getByText("Controls playground")).toBeDefined()
    expect(screen.getAllByText("Model name").length).toBe(2)
    expect(screen.getAllByText("Provider").length).toBe(2)
    expect(screen.getByText("Find a provider")).toBeDefined()

    const firstField = screen.getAllByPlaceholderText("gpt-4o")[0] as HTMLElement
    await userEvent.type(firstField, "gpt-4o")

    expect(firstField.getAttribute("value")).toBe("gpt-4o")
    expect(screen.getAllByRole("button", { name: "OpenAI" }).length).toBe(2)
  })

  it("submits the demo form once it has a model name", async () => {
    render(
      <MemoryRouter>
        <TestControlsPage />
      </MemoryRouter>
    )

    const submit = screen.getByRole("button", { name: "Add model" })
    expect(submit.hasAttribute("disabled")).toBe(true)

    const fields = screen.getAllByPlaceholderText("gpt-4o")
    await userEvent.type(fields[1] as HTMLElement, "gpt-4o")

    await userEvent.click(screen.getByRole("button", { name: "Add model" }))

    expect(screen.getByText("OpenAI / gpt-4o")).toBeDefined()
  })

  it("steps the counter with the square buttons", async () => {
    render(
      <MemoryRouter>
        <TestControlsPage />
      </MemoryRouter>
    )

    expect(screen.getByText("Square buttons")).toBeDefined()

    await userEvent.click(screen.getByRole("button", { name: "Increase" }))
    await userEvent.click(screen.getByRole("button", { name: "Increase" }))
    await userEvent.click(screen.getByRole("button", { name: "Decrease" }))

    expect(screen.getByText("1")).toBeDefined()
  })

  it("toggles models in both lists at once", async () => {
    render(
      <MemoryRouter>
        <TestControlsPage />
      </MemoryRouter>
    )

    expect(screen.getByText(/Item list with the default template \(1 selected\)/)).toBeDefined()

    await userEvent.click(screen.getAllByRole("option", { name: /claude-3/ })[0] as HTMLElement)

    expect(screen.getByText(/Item list with the default template \(2 selected\)/)).toBeDefined()
  })

  it("replaces the favorite instead of stacking it", async () => {
    render(
      <MemoryRouter>
        <TestControlsPage />
      </MemoryRouter>
    )

    expect(screen.getByText(/Single-select list \(favorite: gpt-4o\)/)).toBeDefined()

    await userEvent.click(within(favoriteCard()).getByRole("option", { name: /claude-3/ }))

    expect(screen.getByText(/Single-select list \(favorite: claude-3\)/)).toBeDefined()
  })

  it("opens and closes the demo modal", async () => {
    render(
      <MemoryRouter>
        <TestControlsPage />
      </MemoryRouter>
    )

    expect(screen.queryByRole("dialog")).toBeNull()

    await userEvent.click(screen.getByRole("button", { name: "Open modal" }))

    expect(screen.getByRole("dialog", { name: "Demo modal" })).toBeDefined()

    await userEvent.click(screen.getByRole("button", { name: "Close" }))

    expect(screen.queryByRole("dialog")).toBeNull()
  })
})
