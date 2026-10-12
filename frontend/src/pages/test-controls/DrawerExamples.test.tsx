import { describe, expect, it } from "vitest"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { DrawerExamples } from "./DrawerExamples.tsx"

describe("Drawer playground examples", () => {
  it("discards cancelled edits and retains locally saved values on reopening", async () => {
    const user = userEvent.setup()
    render(<DrawerExamples />)
    const open = screen.getByRole("button", { name: "Open form drawer" })
    await user.click(open)
    let dialog = screen.getByRole("dialog", { name: "Demo agent configuration" })
    let name = within(dialog).getByRole("textbox", { name: "Agent name" })
    await user.clear(name)
    expect(within(dialog).getByRole("button", { name: "Save changes" })).toBeDisabled()
    await user.type(name, "Cancelled name")
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }))
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
    await user.click(open)
    dialog = screen.getByRole("dialog")
    name = within(dialog).getByRole("textbox", { name: "Agent name" })
    expect(name).toHaveValue("Demo agent")
    await user.clear(name)
    await user.type(name, "Security agent")
    await user.click(within(dialog).getByRole("button", { name: "Save changes" }))
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
    expect(screen.getByText("Saved name: Security agent")).toBeDefined()
    await user.click(open)
    expect(within(screen.getByRole("dialog")).getByRole("textbox", { name: "Agent name" })).toHaveValue("Security agent")
  })
})
