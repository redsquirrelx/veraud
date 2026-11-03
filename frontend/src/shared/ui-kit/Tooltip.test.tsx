import { describe, expect, it } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { Tooltip } from "./Tooltip.tsx"

function show(disabled = false) {
  return render(<Tooltip content="Project analysis" disabled={disabled}>
    {(props) => <button {...props}>Analyze</button>}
  </Tooltip>)
}

describe("Tooltip", () => {
  it("shows a linked tooltip on hover and hides it on leave", async () => {
    const user = userEvent.setup()
    show()
    const button = screen.getByRole("button")
    expect(screen.queryByRole("tooltip")).toBeNull()
    await user.hover(button)
    expect(screen.getByRole("tooltip")).toHaveTextContent("Project analysis")
    expect(button).toHaveAttribute("aria-describedby", screen.getByRole("tooltip").id)
    await user.unhover(button)
    await waitFor(() => expect(screen.queryByRole("tooltip")).toBeNull())
  })

  it("supports keyboard focus, Escape and blur without stealing focus", async () => {
    const user = userEvent.setup()
    show()
    await user.tab()
    expect(screen.getByRole("tooltip")).toBeVisible()
    await user.keyboard("{Escape}")
    expect(screen.getByRole("tooltip")).toHaveAttribute("data-closing", "true")
    await waitFor(() => expect(screen.queryByRole("tooltip")).toBeNull())
    expect(screen.getByRole("button")).toHaveFocus()
    await user.tab()
    await user.tab({ shift: true })
    expect(screen.getByRole("tooltip")).toBeVisible()
    await user.tab()
    await waitFor(() => expect(screen.queryByRole("tooltip")).toBeNull())
  })

  it("stays visible while hovering the tooltip itself", async () => {
    const user = userEvent.setup()
    show()
    await user.hover(screen.getByRole("button"))
    await user.hover(screen.getByRole("tooltip"))
    expect(screen.getByRole("tooltip")).toBeVisible()
    await user.unhover(screen.getByRole("tooltip"))
    await waitFor(() => expect(screen.queryByRole("tooltip")).toBeNull())
  })

  it("does not display when disabled", async () => {
    const user = userEvent.setup()
    show(true)
    await user.hover(screen.getByRole("button"))
    await user.tab()
    expect(screen.queryByRole("tooltip")).toBeNull()
    expect(screen.getByRole("button")).not.toHaveAttribute("aria-describedby")
  })

  it("cancels disappearance when the pointer returns during the exit", async () => {
    const user = userEvent.setup()
    show()
    await user.hover(screen.getByRole("button"))
    await user.keyboard("{Escape}")
    expect(screen.getByRole("tooltip")).toHaveAttribute("data-closing", "true")
    await user.unhover(screen.getByRole("button"))
    await user.hover(screen.getByRole("button"))
    expect(screen.getByRole("tooltip")).toHaveAttribute("data-closing", "false")
    await user.unhover(screen.getByRole("button"))
    await waitFor(() => expect(screen.queryByRole("tooltip")).toBeNull())
  })
})
