import { useState } from "react"
import { describe, expect, it, vi } from "vitest"
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { Drawer } from "./Drawer.tsx"

function StatefulDrawer() {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState("")
  return <>
    <button onClick={() => setOpen(true)}>Configure</button>
    <Drawer open={open} title="Agent configuration" onClose={() => setOpen(false)} footer={<button onClick={() => setOpen(false)}>Save</button>}>
      <label>Name<input value={name} onChange={(event) => setName(event.target.value)} /></label>
      <button disabled>Unavailable</button>
      <div hidden><button>Hidden action</button></div>
    </Drawer>
  </>
}

describe("Drawer", () => {
  it("renders nothing when closed and exposes its content when opened", () => {
    const { rerender, container } = render(<Drawer open={false} title="Details" onClose={() => {}}>Content</Drawer>)
    expect(screen.queryByRole("dialog")).toBeNull()
    rerender(<Drawer open title="Details" description="Agent details" size="wide" onClose={() => {}} footer={<button>Done</button>}>Content</Drawer>)
    const dialog = screen.getByRole("dialog", { name: "Details" })
    expect(dialog.parentElement).toHaveAttribute("data-state", "open")
    expect(dialog).toHaveAttribute("aria-modal", "true")
    expect(dialog).toHaveAccessibleDescription("Agent details")
    expect(dialog).toHaveClass("ui-drawer-wide")
    expect(within(dialog).getByRole("button", { name: "Done" })).toBeDefined()
    expect(container.contains(dialog)).toBe(false)
  })

  it("isolates the background, locks scroll and restores both state and opener focus", async () => {
    const user = userEvent.setup()
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = "auto"
    const alreadyInert = document.createElement("div")
    alreadyInert.setAttribute("inert", "")
    document.body.append(alreadyInert)
    const { container } = render(<StatefulDrawer />)
    try {
      const opener = screen.getByRole("button", { name: "Configure" })
      await user.click(opener)
      expect(container).toHaveAttribute("inert")
      expect(document.body.style.overflow).toBe("hidden")
      expect(document.activeElement).toBe(within(screen.getByRole("dialog")).getByRole("button", { name: "Close" }))
      await user.keyboard("{Escape}")
      expect(screen.getByRole("dialog").parentElement).toHaveAttribute("data-state", "closed")
      expect(document.body.style.overflow).toBe("hidden")
      await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
      expect(container).not.toHaveAttribute("inert")
      expect(alreadyInert).toHaveAttribute("inert")
      expect(document.body.style.overflow).toBe("auto")
      expect(document.activeElement).toBe(opener)
    } finally {
      alreadyInert.remove()
      document.body.style.overflow = previousOverflow
    }
  })

  it("keeps Tab focus inside and does not reset focus while editing", async () => {
    const user = userEvent.setup()
    render(<StatefulDrawer />)
    await user.click(screen.getByRole("button", { name: "Configure" }))
    const dialog = screen.getByRole("dialog")
    const close = within(dialog).getByRole("button", { name: "Close" })
    const name = within(dialog).getByRole("textbox", { name: "Name" })
    const save = within(dialog).getByRole("button", { name: "Save" })
    await user.tab({ shift: true })
    expect(document.activeElement).toBe(save)
    await user.tab()
    expect(document.activeElement).toBe(close)
    await user.tab()
    expect(document.activeElement).toBe(name)
    await user.type(name, "Security")
    expect(name).toHaveValue("Security")
    expect(document.activeElement).toBe(name)
    await user.tab()
    expect(document.activeElement).toBe(save)
  })

  it("closes with the cross or backdrop, but not when clicking content", async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    render(<Drawer open title="Details" onClose={onClose}><p>Inside</p></Drawer>)
    await user.click(screen.getByText("Inside"))
    expect(onClose).not.toHaveBeenCalled()
    await user.click(screen.getByRole("button", { name: "Close" }))
    expect(onClose).toHaveBeenCalledTimes(1)
    await user.click(screen.getByRole("dialog").parentElement!)
    expect(onClose).toHaveBeenCalledTimes(2)
  })

  it("can disable backdrop closing while still allowing Escape", async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    render(<Drawer open title="Edit" closeOnOverlay={false} onClose={onClose}>Content</Drawer>)
    await user.click(screen.getByRole("dialog").parentElement!)
    expect(onClose).not.toHaveBeenCalled()
    await user.keyboard("{Escape}")
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it("restores scroll and background interaction when unmounted while open", () => {
    const originalOverflow = document.body.style.overflow
    const { unmount, container } = render(<Drawer open title="Details" onClose={() => {}}>Content</Drawer>)
    expect(container).toHaveAttribute("inert")
    unmount()
    expect(container).not.toHaveAttribute("inert")
    expect(document.body.style.overflow).toBe(originalOverflow)
  })

  it("finishes closing after the slide animation and cancels cleanup on reopening", async () => {
    const { rerender } = render(<Drawer open title="Details" onClose={() => {}}>Content</Drawer>)
    await waitFor(() => expect(screen.getByRole("dialog").parentElement).toHaveAttribute("data-state", "open"))
    rerender(<Drawer open={false} title="Details" onClose={() => {}}>Content</Drawer>)
    expect(screen.getByRole("dialog").parentElement).toHaveAttribute("data-state", "closed")
    rerender(<Drawer open title="Details" onClose={() => {}}>Content</Drawer>)
    expect(screen.getByRole("dialog").parentElement).toHaveAttribute("data-state", "open")
    fireEvent.animationEnd(screen.getByRole("dialog"), { animationName: "ui-drawer-slide-out" })
    expect(screen.getByRole("dialog")).toBeDefined()
    rerender(<Drawer open={false} title="Details" onClose={() => {}}>Content</Drawer>)
    fireEvent.animationEnd(screen.getByRole("dialog"), { animationName: "ui-drawer-slide-out" })
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
  })

  it("reverses native animation timelines without recreating or resetting them", () => {
    const original = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "animate")
    function createAnimation() {
      return {
        currentTime: 0,
        playbackRate: 1,
        onfinish: null as (() => void) | null,
        pause: vi.fn(),
        play: vi.fn(),
        cancel: vi.fn(),
        updatePlaybackRate(rate: number) { this.playbackRate = rate },
      }
    }
    const panel = createAnimation()
    const backdrop = createAnimation()
    const animate = vi.fn().mockReturnValueOnce(panel).mockReturnValueOnce(backdrop)
    Object.defineProperty(HTMLElement.prototype, "animate", { configurable: true, value: animate })
    try {
      const { rerender, unmount } = render(<Drawer open title="Details" onClose={() => {}}>Content</Drawer>)
      expect(animate).toHaveBeenCalledTimes(2)
      expect(panel.playbackRate).toBe(1)
      expect(screen.getByRole("dialog").parentElement).toHaveAttribute("data-motion", "native")
      panel.currentTime = 200
      backdrop.currentTime = 200
      rerender(<Drawer open={false} title="Details" onClose={() => {}}>Content</Drawer>)
      expect(panel.playbackRate).toBe(-1)
      expect(panel.currentTime).toBe(200)
      rerender(<Drawer open title="Details" onClose={() => {}}>Content</Drawer>)
      expect(animate).toHaveBeenCalledTimes(2)
      expect(panel.playbackRate).toBe(1)
      expect(panel.currentTime).toBe(200)
      rerender(<Drawer open={false} title="Details" onClose={() => {}}>Content</Drawer>)
      act(() => panel.onfinish?.())
      expect(screen.queryByRole("dialog")).toBeNull()
      expect(panel.cancel).toHaveBeenCalled()
      expect(backdrop.cancel).toHaveBeenCalled()
      unmount()
    } finally {
      if (original) Object.defineProperty(HTMLElement.prototype, "animate", original)
      else Reflect.deleteProperty(HTMLElement.prototype, "animate")
    }
  })
})
