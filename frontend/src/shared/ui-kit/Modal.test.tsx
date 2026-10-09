import { describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { Modal } from "./Modal.tsx"

describe("Modal", () => {
  it("renders nothing when closed", () => {
    render(<Modal open={false} label="Demo" onClose={() => {}}><p>hidden</p></Modal>)

    expect(screen.queryByRole("dialog")).toBeNull()
    expect(screen.queryByText("hidden")).toBeNull()
  })

  it("renders its content as a dialog when open", () => {
    render(<Modal open label="Demo" onClose={() => {}}><p>visible</p></Modal>)

    expect(screen.getByRole("dialog", { name: "Demo" })).toBeDefined()
    expect(screen.getByText("visible")).toBeDefined()
  })

  it("closes on Escape", async () => {
    const onClose = vi.fn()
    render(<Modal open label="Demo" onClose={onClose}><p>visible</p></Modal>)

    await userEvent.keyboard("{Escape}")

    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it("closes on overlay click but not on dialog click", async () => {
    const onClose = vi.fn()
    render(<Modal open label="Demo" onClose={onClose}><p>visible</p></Modal>)

    await userEvent.click(screen.getByText("visible"))

    expect(onClose).not.toHaveBeenCalled()

    const dialog = screen.getByRole("dialog")
    const overlay = dialog.closest(".ui-modal-overlay")
    if (overlay === null) {
      throw new Error("overlay not found")
    }
    await userEvent.click(overlay)

    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it("renders the title with a closing cross", async () => {
    const onClose = vi.fn()
    render(<Modal open label="Demo" title="Add a model" onClose={onClose}><p>visible</p></Modal>)

    expect(screen.getByText("Add a model")).toBeDefined()

    await userEvent.click(screen.getByRole("button", { name: "Close" }))

    expect(onClose).toHaveBeenCalledTimes(1)
  })
})
