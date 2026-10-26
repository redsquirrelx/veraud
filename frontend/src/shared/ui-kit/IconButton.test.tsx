import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"
import { IconButton } from "./IconButton.tsx"

describe("IconButton", () => {
  it("requires and exposes its accessible label while forwarding button props", async () => {
    const onClick = vi.fn()
    const user = userEvent.setup()
    render(<IconButton ariaLabel="Refresh list" title="Refresh" onClick={onClick}>↻</IconButton>)

    const button = screen.getByRole("button", { name: "Refresh list" })
    expect(button).toHaveAttribute("title", "Refresh")
    expect(button).toHaveClass("ui-icon-button-outline", "ui-icon-button-md")
    await user.click(button)
    expect(onClick).toHaveBeenCalledOnce()
  })

  it("applies explicit compact ghost and pagination variants", () => {
    const { container } = render(<>
      <IconButton ariaLabel="Close" size="sm" variant="ghost">x</IconButton>
      <IconButton ariaLabel="Previous" size="sm" variant="pagination" disabled>‹</IconButton>
    </>)
    expect(screen.getByRole("button", { name: "Close" })).toHaveClass("ui-icon-button-ghost", "ui-icon-button-sm")
    expect(screen.getByRole("button", { name: "Previous" })).toHaveClass("ui-icon-button-pagination")
    expect(container.querySelectorAll(".ui-icon-button")).toHaveLength(2)
  })
})
