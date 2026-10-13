import { useState } from "react"
import { describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { Checkbox } from "./Checkbox.tsx"
import { Combobox } from "./Combobox.tsx"
import { RadioButton } from "./RadioButton.tsx"
import { Switch } from "./Switch.tsx"

describe("form controls", () => {
  it("toggles an indeterminate checkbox with the keyboard", async () => {
    const onChange = vi.fn()
    render(<Checkbox label="All files" checked={false} indeterminate onChange={onChange} />)
    const input = screen.getByRole("checkbox", { name: "All files" }) as HTMLInputElement
    expect(input.indeterminate).toBe(true)
    await userEvent.tab()
    await userEvent.keyboard(" ")
    expect(onChange).toHaveBeenCalledWith(true)
  })

  it("keeps disabled controls unchanged and associates validation messages", async () => {
    const onChange = vi.fn()
    render(<><Checkbox label="Locked files" checked disabled onChange={onChange} /><Switch label="Audit logging" checked={false} disabled onChange={onChange} error="Logging is required" /></>)
    await userEvent.click(screen.getByRole("checkbox"))
    await userEvent.click(screen.getByRole("switch"))
    expect(onChange).not.toHaveBeenCalled()
    expect(screen.getByRole("switch")).toHaveAccessibleDescription("Logging is required")
    expect(screen.getByRole("switch")).toHaveAttribute("aria-invalid", "true")
  })

  it("toggles a switch and moves between radio choices using arrow keys", async () => {
    function Harness() {
      const [checked, setChecked] = useState(false)
      const [value, setValue] = useState("https")
      return <><Switch label="Notifications" checked={checked} onChange={setChecked} /><RadioButton label="HTTPS" name="protocol" value="https" checked={value === "https"} onChange={setValue} /><RadioButton label="SSH" name="protocol" value="ssh" checked={value === "ssh"} onChange={setValue} /></>
    }
    render(<Harness />)
    await userEvent.tab()
    await userEvent.keyboard(" ")
    expect(screen.getByRole("switch")).toBeChecked()
    await userEvent.tab()
    await userEvent.keyboard("{ArrowRight}")
    expect(screen.getByRole("radio", { name: "SSH" })).toBeChecked()
    expect(screen.getByRole("radio", { name: "HTTPS" })).not.toBeChecked()
  })

  it("navigates the combobox, skips disabled options, and commits only on Enter", async () => {
    const onChange = vi.fn()
    render(<Combobox label="Provider" value="one" options={[{ value: "one", label: "One" }, { value: "two", label: "Two", disabled: true }, { value: "three", label: "Three" }]} onChange={onChange} />)
    await userEvent.tab()
    await userEvent.keyboard("{ArrowDown}{ArrowDown}")
    expect(onChange).not.toHaveBeenCalled()
    expect(screen.getByRole("combobox")).toHaveAttribute("aria-activedescendant", screen.getByRole("option", { name: "Three" }).id)
    await userEvent.keyboard("{Enter}")
    expect(onChange).toHaveBeenCalledWith("three")
    expect(screen.getByRole("combobox")).toHaveAttribute("aria-expanded", "false")
    expect(screen.getByRole("combobox")).toHaveFocus()
  })

  it("supports type-ahead, Escape, outside dismissal, and clicking combobox options", async () => {
    const onChange = vi.fn()
    render(<><Combobox label="Provider" value="" options={[{ value: "a", label: "Anthropic" }, { value: "g", label: "Google" }]} onChange={onChange} /><button>Outside</button></>)
    await userEvent.tab()
    await userEvent.keyboard("g")
    expect(screen.getByRole("combobox")).toHaveAttribute("aria-activedescendant", screen.getByRole("option", { name: "Google" }).id)
    await userEvent.keyboard("{Escape}")
    expect(onChange).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole("combobox"))
    await userEvent.click(screen.getByRole("button", { name: "Outside" }))
    expect(screen.getByRole("combobox")).toHaveAttribute("aria-expanded", "false")
    await userEvent.click(screen.getByRole("combobox"))
    await userEvent.click(screen.getByRole("option", { name: "Anthropic" }))
    expect(onChange).toHaveBeenCalledWith("a")
  })
})
