import { afterEach, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { SplitView } from "./SplitView.tsx"

afterEach(() => {
  vi.restoreAllMocks()
})

function renderSplit(initialRatio = 0.5) {
  render(<SplitView left={<p>left pane</p>} right={<p>right pane</p>} initialRatio={initialRatio} label="Resize panes" />)
  return screen.getByRole("separator", { name: "Resize panes" })
}

describe("SplitView", () => {
  it("renders both panes with the initial ratio", () => {
    renderSplit(0.4)

    expect(screen.getByText("left pane")).toBeDefined()
    expect(screen.getByText("right pane")).toBeDefined()
    const handle = screen.getByRole("separator", { name: "Resize panes" })
    expect(handle.getAttribute("aria-valuenow")).toBe("40")
  })

  it("clamps the initial ratio to the minimum", () => {
    renderSplit(0.99)

    expect(screen.getByRole("separator", { name: "Resize panes" }).getAttribute("aria-valuenow")).toBe("80")
  })

  it("moves with the arrow keys within the limits", async () => {
    renderSplit()
    const handle = screen.getByRole("separator", { name: "Resize panes" })

    await userEvent.click(handle)
    await userEvent.keyboard("{ArrowRight}")

    expect(handle.getAttribute("aria-valuenow")).toBe("55")

    await userEvent.keyboard("{ArrowLeft}{ArrowLeft}")

    expect(handle.getAttribute("aria-valuenow")).toBe("45")
  })

  it("jumps to the edges with home and end", async () => {
    renderSplit()
    const handle = screen.getByRole("separator", { name: "Resize panes" })

    await userEvent.click(handle)
    await userEvent.keyboard("{End}")

    expect(handle.getAttribute("aria-valuenow")).toBe("80")

    await userEvent.keyboard("{Home}")

    expect(handle.getAttribute("aria-valuenow")).toBe("20")
  })

  it("drags the handle with the pointer inside the limits", () => {
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({
      left: 0, top: 0, right: 1000, bottom: 10, width: 1000, height: 10, x: 0, y: 0, toJSON: () => ({}),
    })
    renderSplit()
    const handle = screen.getByRole("separator", { name: "Resize panes" })

    fireEvent.pointerDown(handle, { clientX: 500, button: 0 })
    fireEvent.pointerMove(handle, { clientX: 950, button: 0 })
    fireEvent.pointerUp(handle)

    expect(handle.getAttribute("aria-valuenow")).toBe("80")

    fireEvent.pointerDown(handle, { clientX: 950, button: 0 })
    fireEvent.pointerMove(handle, { clientX: 50, button: 0 })
    fireEvent.pointerUp(handle)

    expect(handle.getAttribute("aria-valuenow")).toBe("20")
  })

  it("ignores moves without a drag and non-primary buttons", () => {
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({
      left: 0, top: 0, right: 1000, bottom: 10, width: 1000, height: 10, x: 0, y: 0, toJSON: () => ({}),
    })
    renderSplit()
    const handle = screen.getByRole("separator", { name: "Resize panes" })

    fireEvent.pointerMove(handle, { clientX: 900 })
    expect(handle.getAttribute("aria-valuenow")).toBe("50")

    fireEvent.pointerDown(handle, { clientX: 500, button: 2 })
    fireEvent.pointerMove(handle, { clientX: 900 })
    expect(handle.getAttribute("aria-valuenow")).toBe("50")
  })
})
