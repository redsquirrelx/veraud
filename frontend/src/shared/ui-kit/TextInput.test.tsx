import { useState } from "react"
import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { TextInput } from "./TextInput.tsx"

function StatefulInput() {
  const [value, setValue] = useState("")

  return <TextInput value={value} placeholder="repo url" onChange={setValue} />
}

describe("TextInput", () => {
  it("renders with a placeholder", () => {
    render(<TextInput value="" placeholder="https://github.com/owner/repo" onChange={() => {}} />)

    expect(screen.getByPlaceholderText("https://github.com/owner/repo")).toBeDefined()
  })

  it("reports typed text through onChange", async () => {
    render(<StatefulInput />)

    await userEvent.type(screen.getByPlaceholderText("repo url"), "https://github.com/a/b")

    expect(screen.getByPlaceholderText("repo url").getAttribute("value")).toBe("https://github.com/a/b")
  })

  it("can be disabled", () => {
    render(<TextInput value="x" onChange={() => {}} disabled />)

    expect(screen.getByRole("textbox").hasAttribute("disabled")).toBe(true)
  })
})
