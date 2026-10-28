import { useState } from "react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { cleanup, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { changeLanguage } from "../i18n/index.ts"
import { Accordion } from "./Accordion.tsx"
import { Checkbox } from "./Checkbox.tsx"

afterEach(async () => { cleanup(); await changeLanguage("en") })

function Example() {
  const [open, setOpen] = useState(false)
  return <Accordion title="Options" open={open} onOpenChange={setOpen}
    headerAction={<Checkbox label="Enabled" checked onChange={() => {}} />}>
    <label>Value<input defaultValue="original" /></label>
  </Accordion>
}

describe("Accordion", () => {
  it("supports keyboard disclosure, connected ARIA state, and preserves content when collapsed", async () => {
    const user = userEvent.setup()
    render(<Example />)
    const trigger = screen.getByRole("button", { name: "Expand Options" })
    expect(trigger).toHaveAttribute("aria-expanded", "false")
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument()
    expect(screen.getByRole("checkbox", { name: "Enabled" })).toBeVisible()
    trigger.focus()
    await user.keyboard("{Enter}")
    expect(trigger).toHaveAttribute("aria-expanded", "true")
    expect(document.getElementById(trigger.getAttribute("aria-controls")!)).toContainElement(screen.getByRole("textbox"))
    await user.type(screen.getByRole("textbox"), " edited")
    trigger.focus()
    await user.keyboard(" ")
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument()
    await user.click(trigger)
    expect(screen.getByRole("textbox")).toHaveValue("original edited")
  })

  it("blocks disclosure when disabled without disabling or nesting header actions", async () => {
    const onOpenChange = vi.fn()
    const onChange = vi.fn()
    render(<Accordion title="Options" open disabled onOpenChange={onOpenChange}
      headerAction={<Checkbox label="Enabled" checked={false} onChange={onChange} />}>
      <input aria-label="Hidden setting" />
    </Accordion>)
    const trigger = screen.getByRole("button", { name: "Expand Options" })
    expect(trigger).toBeDisabled()
    expect(trigger).toHaveAttribute("aria-expanded", "false")
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole("checkbox", { name: "Enabled" }))
    expect(onChange).toHaveBeenCalledWith(true)
    expect(onOpenChange).not.toHaveBeenCalled()
    expect(trigger).not.toContainElement(screen.getByRole("checkbox"))
    await changeLanguage("es")
    expect(screen.getByRole("button", { name: "Desplegar Options" })).toBeDisabled()
  })
})
