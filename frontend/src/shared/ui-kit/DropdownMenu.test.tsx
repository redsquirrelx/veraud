import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { DropdownMenu, type DropdownMenuItem } from "./DropdownMenu.tsx"

const items: DropdownMenuItem[] = [
  { id: "classic", label: "Classic audit", description: "Analyzer then architect" },
  { id: "deep", label: "Deep review", disabled: true },
  { id: "project", label: "Project architecture" },
]

describe("DropdownMenu", () => {
  it("reports the chosen option and closes restoring focus", async () => {
    const seen: string[] = []
    const user = userEvent.setup()
    render(<DropdownMenu label="Analyze" items={items} onSelect={(id) => seen.push(id)} />)
    const trigger = screen.getByRole("button", { name: "Analyze" })
    expect(screen.queryByRole("menu")).toBeNull()
    await user.click(trigger)
    const option = screen.getByRole("menuitem", { name: /Classic audit/ })
    expect(screen.getByRole("menuitem", { name: "Deep review" })).toHaveAttribute("disabled")
    await user.click(option)
    expect(seen).toEqual(["classic"])
    expect(trigger.getAttribute("aria-expanded")).toBe("false")
    expect(document.activeElement).toBe(trigger)
  })

  it("marks the selected option and navigates by keyboard skipping disabled items", async () => {
    const user = userEvent.setup()
    render(<DropdownMenu label="Analyze" items={items} selectedId="project" onSelect={() => {}} />)
    const trigger = screen.getByRole("button", { name: "Analyze" })
    trigger.focus()
    await user.keyboard("{ArrowDown}")
    expect(document.activeElement).toBe(screen.getByRole("menuitem", { name: /Classic audit/ }))
    expect(screen.getByRole("menuitem", { name: /Project architecture/ }).getAttribute("aria-current")).toBe("true")
    await user.keyboard("{ArrowDown}")
    expect(document.activeElement).toBe(screen.getByRole("menuitem", { name: /Project architecture/ }))
    await user.keyboard("{Home}")
    expect(document.activeElement).toBe(screen.getByRole("menuitem", { name: /Classic audit/ }))
    await user.keyboard("{End}")
    expect(document.activeElement).toBe(screen.getByRole("menuitem", { name: /Project architecture/ }))
    await user.keyboard("{Escape}")
    expect(document.activeElement).toBe(trigger)
    expect(screen.queryByRole("menu")).toBeNull()
  })

  it("closes when tabbing out or clicking outside and supports empty and loading states", async () => {
    const user = userEvent.setup()
    render(<>
      <DropdownMenu label="Analyze" items={[items[2]!]} onSelect={() => {}} />
      <button>Outside</button>
    </>)
    const trigger = screen.getByRole("button", { name: "Analyze" })
    await user.click(trigger)
    await user.tab()
    expect(document.activeElement).toBe(screen.getByRole("menuitem", { name: "Project architecture" }))
    await user.tab()
    expect(screen.queryByRole("menu")).toBeNull()
    await user.click(trigger)
    await user.click(screen.getByRole("button", { name: "Outside" }))
    expect(screen.queryByRole("menu")).toBeNull()

    render(<DropdownMenu label="Empty" items={[]} emptyText="No pipelines registered" onSelect={() => {}} />)
    await user.click(screen.getByRole("button", { name: "Empty" }))
    expect(screen.getByText("No pipelines registered")).toBeDefined()

    render(<DropdownMenu label="Analyze" items={items} loading loadingText="Analyzing" onSelect={() => {}} />)
    const loading = screen.getByRole("button", { name: "Analyzing" })
    expect(loading.hasAttribute("disabled")).toBe(true)
    await user.click(loading)
    expect(screen.queryByRole("menu")).toBeNull()
  })
})
