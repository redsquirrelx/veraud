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
  it("marks the active tab", () => {
    render(<StatefulTabs />)

    expect(screen.getByRole("tab", { name: "All (18)" }).getAttribute("aria-selected")).toBe("true")
    expect(screen.getByRole("tab", { name: "Running (2)" }).getAttribute("aria-selected")).toBe("false")
  })

  it("switches tabs on click", async () => {
    const onChange = vi.fn()
    render(<FilterTabs options={options} value="all" onChange={onChange} />)

    await userEvent.click(screen.getByRole("tab", { name: "Running (2)" }))

    expect(onChange).toHaveBeenCalledWith("running")
  })
})
