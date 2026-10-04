import { describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { Sidebar } from "./Sidebar.tsx"
import { FolderIcon } from "./icons.tsx"

const items = [
  { id: "home", label: "Home", icon: <FolderIcon /> },
  { id: "settings", label: "Settings", icon: <FolderIcon /> },
]

describe("Sidebar", () => {
  it("shows details while expanded", () => {
    render(<Sidebar title="Menu" items={items} activeId="home" />)

    expect(screen.getByText("Menu")).toBeDefined()
    expect(screen.getByText("Home")).toBeDefined()
    expect(screen.getByText("Settings")).toBeDefined()
  })

  it("hides details when collapsed", async () => {
    render(<Sidebar title="Menu" items={items} />)

    await userEvent.click(screen.getByRole("button", { name: "Collapse sidebar" }))

    expect(screen.queryByText("Menu")).toBeNull()
    expect(screen.queryByText("Home")).toBeNull()
    expect(screen.getByRole("button", { name: "Expand sidebar" })).toBeDefined()
  })

  it("notifies the selected item", async () => {
    const onSelect = vi.fn()
    render(<Sidebar title="Menu" items={items} onSelect={onSelect} />)

    await userEvent.click(screen.getByRole("button", { name: "Settings" }))

    expect(onSelect).toHaveBeenCalledWith("settings")
  })

  it("persists the collapsed state through storage", async () => {
    window.localStorage.clear()
    const { unmount } = render(<Sidebar title="Menu" items={items} storageKey="sidebar.test" />)

    await userEvent.click(screen.getByRole("button", { name: "Collapse sidebar" }))
    unmount()

    render(<Sidebar title="Menu" items={items} storageKey="sidebar.test" />)

    expect(screen.queryByText("Home")).toBeNull()
    expect(screen.getByRole("button", { name: "Expand sidebar" })).toBeDefined()
    window.localStorage.clear()
  })
})
