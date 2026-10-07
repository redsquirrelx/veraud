import { describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { ItemList, ItemListItem } from "./ItemList.tsx"

const entries = [
  { id: "gpt-4o", name: "gpt-4o", description: "OpenAI flagship" },
  { id: "claude-3", name: "claude-3", description: "Anthropic model" },
]

describe("ItemList", () => {
  it("renders the default name and description template", () => {
    render(<ItemList items={entries} selectedIds={[]} onSelectionChange={() => {}} />)

    expect(screen.getByRole("option", { name: /gpt-4o/ })).toBeDefined()
    expect(screen.getByText("OpenAI flagship")).toBeDefined()
    expect(screen.getByRole("option", { name: /claude-3/ })).toBeDefined()
  })

  it("toggles ids in multiple mode", async () => {
    const onSelectionChange = vi.fn()
    render(<ItemList items={entries} selectedIds={["gpt-4o"]} onSelectionChange={onSelectionChange} />)

    expect(screen.getByRole("option", { name: /gpt-4o/ }).getAttribute("aria-selected")).toBe("true")
    expect(screen.getByRole("option", { name: /claude-3/ }).getAttribute("aria-selected")).toBe("false")

    await userEvent.click(screen.getByRole("option", { name: /claude-3/ }))

    expect(onSelectionChange).toHaveBeenCalledWith(["gpt-4o", "claude-3"])
  })

  it("toggles from the keyboard", async () => {
    const onSelectionChange = vi.fn()
    render(<ItemList items={entries} selectedIds={[]} onSelectionChange={onSelectionChange} />)

    screen.getByRole("option", { name: /gpt-4o/ }).focus()
    await userEvent.keyboard("{Enter}")

    expect(onSelectionChange).toHaveBeenCalledWith(["gpt-4o"])
  })

  it("keeps a single selection in single mode", async () => {
    const onSelectionChange = vi.fn()
    render(<ItemList items={entries} selectedIds={["gpt-4o"]} onSelectionChange={onSelectionChange} mode="single" />)

    expect(screen.getByRole("listbox").getAttribute("aria-multiselectable")).toBe("false")

    await userEvent.click(screen.getByRole("option", { name: /claude-3/ }))

    expect(onSelectionChange).toHaveBeenCalledWith(["claude-3"])
  })

  it("shows the empty text without options", () => {
    render(<ItemList items={[]} selectedIds={[]} onSelectionChange={() => {}} emptyText="No models yet" />)

    expect(screen.getByText("No models yet")).toBeDefined()
    expect(screen.queryByRole("option")).toBeNull()
  })

  it("shows skeletons while loading instead of options", () => {
    const { container } = render(<ItemList items={[]} selectedIds={[]} onSelectionChange={() => {}} loading />)

    expect(container.querySelectorAll(".ui-item-list-skeleton").length).toBe(3)
    expect(screen.queryByRole("option")).toBeNull()
  })

  it("accepts a custom template instead of the default one", () => {
    render(
      <ItemList
        items={entries}
        selectedIds={[]}
        onSelectionChange={() => {}}
        renderItem={(item) => <span>custom-{item.id}</span>}
      />
    )

    expect(screen.getByText("custom-gpt-4o")).toBeDefined()
    expect(screen.queryByText("OpenAI flagship")).toBeNull()
  })
})

describe("ItemListItem", () => {
  it("hides the description when it is missing", () => {
    render(<ItemListItem name="gpt-4o" />)

    expect(screen.getByText("gpt-4o")).toBeDefined()
  })
})
