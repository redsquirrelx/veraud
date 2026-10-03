import { describe, expect, it, vi } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { Toast } from "./Toast.tsx"

describe("Toast", () => {
  it("shows a success message", () => {
    render(<Toast kind="success" message="Project registered" />)

    expect(screen.getByRole("status").textContent).toContain("Project registered")
  })

  it("announces errors as alerts", () => {
    render(<Toast kind="error" message="Repository is not accessible" />)

    expect(screen.getByRole("alert").textContent).toContain("Repository is not accessible")
  })

  it("closes through its button", async () => {
    const onClose = vi.fn()
    render(<Toast kind="error" message="oops" onClose={onClose} />)

    await userEvent.click(screen.getByRole("button", { name: "Close" }))

    await waitFor(() => {
      expect(onClose).toHaveBeenCalledTimes(1)
    })
  })

  it("hides the close button when onClose is missing", () => {
    render(<Toast kind="success" message="done" />)

    expect(screen.queryByRole("button", { name: "Close" })).toBeNull()
  })

  it("dismisses itself after its duration", async () => {
    const onClose = vi.fn()
    render(<Toast kind="success" message="done" durationMs={50} onClose={onClose} />)

    await waitFor(() => {
      expect(onClose).toHaveBeenCalledTimes(1)
    })
  })

  it("pauses dismissal while hovered", async () => {
    const onClose = vi.fn()
    const user = userEvent.setup()
    render(<Toast kind="success" message="done" durationMs={150} onClose={onClose} />)

    await user.hover(screen.getByRole("status"))
    await new Promise((resolve) => setTimeout(resolve, 250))
    expect(onClose).not.toHaveBeenCalled()

    await user.unhover(screen.getByRole("status"))
    await waitFor(() => {
      expect(onClose).toHaveBeenCalledTimes(1)
    })
  })

  it("offers an expander for long messages", async () => {
    render(<Toast kind="error" message={"x".repeat(200)} />)

    expect(screen.getByRole("button", { name: "Show more" })).toBeDefined()

    await userEvent.click(screen.getByRole("button", { name: "Show more" }))

    expect(screen.getByRole("button", { name: "Show less" })).toBeDefined()
  })
})
