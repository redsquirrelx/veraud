import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { DropdownLinks, type DropdownLinkItem } from "./DropdownLinks.tsx"

const items: DropdownLinkItem[] = [
  { label: "Backend docs", href: "https://backend.example/docs", external: true },
  { label: "Reports", href: "/reports", disabled: true },
  { label: "Settings", href: "/settings" },
]

describe("DropdownLinks", () => {
  it("provides real external links and closes without changing the trigger label", async () => {
    const user = userEvent.setup()
    render(<MemoryRouter><DropdownLinks label="API docs" items={items} /></MemoryRouter>)
    const trigger = screen.getByRole("button", { name: "API docs" })
    expect(screen.queryByRole("navigation")).toBeNull()
    await user.click(trigger)
    const link = screen.getByRole("link", { name: "Backend docs (opens in a new tab)" })
    expect(link.getAttribute("href")).toBe("https://backend.example/docs")
    expect(link.getAttribute("target")).toBe("_blank")
    expect(link.getAttribute("rel")).toBe("noopener noreferrer")
    expect(screen.queryByRole("link", { name: "Reports" })).toBeNull()
    await user.click(link)
    expect(trigger.getAttribute("aria-expanded")).toBe("false")
    expect(document.activeElement).toBe(trigger)
  })

  it("navigates by keyboard, skips unavailable items and restores focus with Escape", async () => {
    const user = userEvent.setup()
    render(<MemoryRouter><DropdownLinks label="Navigate" items={items} /></MemoryRouter>)
    const trigger = screen.getByRole("button", { name: "Navigate" })
    trigger.focus()
    await user.keyboard("{ArrowDown}")
    expect(document.activeElement).toBe(screen.getByRole("link", { name: /Backend docs/ }))
    await user.keyboard("{ArrowDown}")
    expect(document.activeElement).toBe(screen.getByRole("link", { name: "Settings" }))
    await user.keyboard("{Home}")
    expect(document.activeElement).toBe(screen.getByRole("link", { name: /Backend docs/ }))
    await user.keyboard("{End}")
    expect(document.activeElement).toBe(screen.getByRole("link", { name: "Settings" }))
    await user.keyboard("{Escape}")
    expect(document.activeElement).toBe(trigger)
    expect(screen.queryByRole("navigation")).toBeNull()
  })

  it("closes when tabbing out or clicking outside and navigates internally", async () => {
    const user = userEvent.setup()
    render(<MemoryRouter>
      <DropdownLinks label="Navigate" items={[items[2]!]} />
      <button>Outside</button>
      <Routes>
        <Route path="/" element={null} />
        <Route path="/settings" element={<h1>Settings page</h1>} />
      </Routes>
    </MemoryRouter>)
    const trigger = screen.getByRole("button", { name: "Navigate" })
    await user.click(trigger)
    await user.tab()
    expect(document.activeElement).toBe(screen.getByRole("link", { name: "Settings" }))
    await user.tab()
    expect(screen.queryByRole("navigation")).toBeNull()
    await user.click(trigger)
    await user.click(screen.getByRole("button", { name: "Outside" }))
    expect(screen.queryByRole("navigation")).toBeNull()
    await user.click(trigger)
    await user.click(screen.getByRole("link", { name: "Settings" }))
    expect(screen.getByRole("heading", { name: "Settings page" })).toBeDefined()
    expect(screen.queryByRole("navigation")).toBeNull()
  })

  it("supports an empty menu and a disabled trigger", async () => {
    const user = userEvent.setup()
    render(<MemoryRouter>
      <DropdownLinks label="Empty" items={[]} emptyText="No documentation registered" />
      <DropdownLinks label="Disabled" items={items} disabled />
    </MemoryRouter>)
    await user.click(screen.getByRole("button", { name: "Disabled" }))
    expect(screen.queryByRole("navigation")).toBeNull()
    await user.click(screen.getByRole("button", { name: "Empty" }))
    expect(screen.getByText("No documentation registered")).toBeDefined()
  })
})
