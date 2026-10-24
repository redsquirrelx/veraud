import { describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { ItemSelector } from "./ItemSelector.tsx"

const items = [
  { id: "main", label: "main" },
  { id: "feature-a", label: "feature-a", detail: "3 commits ahead" },
]

describe("ItemSelector", () => {
  it("supports arrow-key selection, Escape focus restoration and tabbing out", async () => {
    const user = userEvent.setup()
    const onSelect = vi.fn()
    render(<><ItemSelector items={items} selectedId="main" label="Branch" onSelect={onSelect} hasMore={false} onLoadMore={() => {}} /><button>After selector</button></>)
    const trigger = screen.getByRole("button", { name: "main" })
    expect(trigger).toHaveAccessibleDescription("Branch")
    trigger.focus()
    await user.keyboard("{ArrowDown}")
    expect(screen.getByRole("listbox", { name: "Branch" })).toBeDefined()
    expect(screen.getByRole("option", { name: "main" })).toHaveFocus()
    await user.keyboard("{ArrowDown}{Enter}")
    expect(onSelect).toHaveBeenCalledWith("feature-a")
    expect(trigger).toHaveFocus()
    await user.keyboard("{ArrowDown}{Escape}")
    expect(trigger).toHaveFocus()
    expect(screen.queryByRole("option")).toBeNull()
    await user.click(trigger)
    await user.tab({ shift: true })
    expect(screen.queryByRole("option")).toBeNull()
  })

  it("opens the list on button press and closes on select", async () => {
    const onSelect = vi.fn()
    render(
      <ItemSelector items={items} selectedId="main" onSelect={onSelect} hasMore={false} onLoadMore={() => {}} />
    )

    const trigger = screen.getByRole("button", { name: /main/ })
    expect(screen.queryByRole("option")).toBeNull()
    await userEvent.click(trigger)

    expect(screen.getByRole("option", { selected: true }).textContent).toContain("main")
    expect(screen.getByText("3 commits ahead")).toBeDefined()

    await userEvent.click(screen.getByRole("option", { name: /feature-a/ }))

    expect(onSelect).toHaveBeenCalledWith("feature-a")
    expect(screen.queryByRole("option")).toBeNull()
  })

  it("refreshes the list when the dropdown opens", async () => {
    const onOpen = vi.fn()
    render(
      <ItemSelector items={items} selectedId="main" onSelect={() => {}} hasMore={false} onLoadMore={() => {}} onOpen={onOpen} />
    )

    await userEvent.click(screen.getByRole("button", { name: /main/ }))

    expect(onOpen).toHaveBeenCalledTimes(1)

    await userEvent.click(screen.getByRole("option", { name: /feature-a/ }))

    expect(onOpen).toHaveBeenCalledTimes(1)
  })

  it("shows the placeholder without selection", async () => {
    render(
      <ItemSelector items={items} selectedId={null} onSelect={() => {}} hasMore={false} onLoadMore={() => {}} />
    )

    expect(screen.getByRole("button", { name: "Select an item" })).toBeDefined()
  })

  it("appends more items through load more without closing", async () => {
    const onLoadMore = vi.fn()
    render(
      <ItemSelector items={items} selectedId={null} onSelect={() => {}} hasMore onLoadMore={onLoadMore} />
    )

    await userEvent.click(screen.getByRole("button", { name: "Select an item" }))
    await userEvent.click(screen.getByText("Load more..."))

    expect(onLoadMore).toHaveBeenCalledTimes(1)
    expect(screen.getByRole("option", { name: /main/ })).toBeDefined()
  })

  it("disables load more while loading", async () => {
    const onLoadMore = vi.fn()
    render(
      <ItemSelector items={items} selectedId={null} onSelect={() => {}} hasMore loadingMore onLoadMore={onLoadMore} />
    )

    await userEvent.click(screen.getByRole("button", { name: "Select an item" }))
    expect(screen.getByText("Loading")).toBeDefined()
    await userEvent.click(screen.getByText("Loading"))

    expect(onLoadMore).not.toHaveBeenCalled()
  })

  it("shows the empty text without items", async () => {
    render(
      <ItemSelector items={[]} selectedId={null} onSelect={() => {}} hasMore={false} onLoadMore={() => {}} />
    )

    await userEvent.click(screen.getByRole("button", { name: "Select an item" }))

    expect(screen.getByText("No items yet")).toBeDefined()
  })

  it("renders the floating label and loading state", () => {
    render(
      <ItemSelector items={[]} selectedId={null} onSelect={() => {}} hasMore={false} onLoadMore={() => {}} label="Branch" loading />
    )

    expect(screen.getByText("Branch")).toBeDefined()
    expect(screen.getByText("Loading")).toBeDefined()
    expect(screen.getByRole("button")).toBeDisabled()
  })
})
