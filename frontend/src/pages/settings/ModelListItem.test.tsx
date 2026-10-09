import { describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { ModelListItem } from "./ModelListItem.tsx"

describe("ModelListItem", () => {
  it("shows the name, provider and usage", () => {
    render(<ModelListItem name="gpt-4o" provider="OpenAI" inUse onRemove={() => {}} />)

    expect(screen.getByText("gpt-4o")).toBeDefined()
    expect(screen.getByText("OpenAI")).toBeDefined()
    expect(screen.getByText("In use")).toBeDefined()
    expect(screen.getByRole("button", { name: "Remove gpt-4o" })).toBeDefined()
  })

  it("removes without toggling the row", async () => {
    const onRemove = vi.fn()
    const onToggle = vi.fn()
    render(
      <button type="button" onClick={onToggle}>
        <ModelListItem name="gpt-4o" provider="OpenAI" inUse={false} onRemove={onRemove} />
      </button>
    )

    await userEvent.click(screen.getByRole("button", { name: "Remove gpt-4o" }))

    expect(onRemove).toHaveBeenCalledTimes(1)
    expect(onToggle).not.toHaveBeenCalled()
  })
})
