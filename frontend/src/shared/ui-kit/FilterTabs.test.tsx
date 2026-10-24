import { useState } from "react"
import { describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { FilterTabs, type FilterOption } from "./FilterTabs.tsx"

const options: FilterOption[] = [
  { id: "all", label: "All", count: 18 },
  { id: "running", label: "Running", count: 2 },
]

function StatefulTabs() {
  const [value, setValue] = useState("all")

  return <FilterTabs options={options} value={value} onChange={setValue} />
}

describe("FilterTabs", () => {
  it("moves focus and selection with arrows, Home and End", async () => {
    const user = userEvent.setup()
    render(<StatefulTabs />)
    const all = screen.getByRole("tab", { name: "All (18)" })
    const running = screen.getByRole("tab", { name: "Running (2)" })
    expect(all).toHaveAttribute("aria-selected", "true")
    expect(running).toHaveAttribute("aria-selected", "false")
    all.focus()
    await user.keyboard("{ArrowRight}")
    expect(running).toHaveFocus()
    expect(running).toHaveAttribute("aria-selected", "true")
    expect(all).toHaveAttribute("tabindex", "-1")
    await user.keyboard("{Home}")
    expect(all).toHaveFocus()
    await user.keyboard("{End}{ArrowRight}")
    expect(all).toHaveFocus()
    expect(all).toHaveAttribute("aria-selected", "true")
  })

  it("switches tabs on click", async () => {
    const onChange = vi.fn()
    render(<FilterTabs options={options} value="all" onChange={onChange} />)

    await userEvent.click(screen.getByRole("tab", { name: "Running (2)" }))

    expect(onChange).toHaveBeenCalledWith("running")
  })
})
