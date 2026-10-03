import { useState } from "react"
import { describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { RefreshButton } from "./RefreshButton.tsx"
import { SortButton } from "./SortButton.tsx"
import { Spinner } from "./Spinner.tsx"

function StatefulSort() {
  const [direction, setDirection] = useState<"asc" | "desc">("asc")

  return <SortButton direction={direction} onToggle={() => setDirection(direction === "asc" ? "desc" : "asc")} />
}

describe("Spinner", () => {
  it("announces loading", () => {
    render(<Spinner />)

    expect(screen.getByRole("status", { name: "Loading" })).toBeDefined()
  })
})

describe("SortButton", () => {
  it("toggles direction on click", async () => {
    render(<StatefulSort />)

    await userEvent.click(screen.getByRole("button", { name: "Sort descending" }))

    expect(screen.getByRole("button", { name: "Sort ascending" })).toBeDefined()
  })
})

describe("RefreshButton", () => {
  it("notifies clicks when idle", async () => {
    const onClick = vi.fn()
    render(<RefreshButton onClick={onClick} />)

    await userEvent.click(screen.getByRole("button", { name: "Refresh" }))

    expect(onClick).toHaveBeenCalledTimes(1)
  })

  it("spins and disables while loading", () => {
    render(<RefreshButton loading onClick={() => {}} />)

    const button = screen.getByRole("button", { name: "Refresh" })

    expect(button.hasAttribute("disabled")).toBe(true)
    expect(screen.getByRole("status", { name: "Loading" })).toBeDefined()
  })
})
