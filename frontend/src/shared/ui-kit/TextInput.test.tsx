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
  it("reports typed text through onChange", async () => {
    render(<StatefulInput />)

    await userEvent.type(screen.getByPlaceholderText("repo url"), "https://github.com/a/b")

    expect(screen.getByPlaceholderText("repo url")).toHaveValue("https://github.com/a/b")
  })

  it("can be disabled", () => {
    render(<TextInput value="x" onChange={() => {}} disabled />)

    expect(screen.getByRole("textbox").hasAttribute("disabled")).toBe(true)
  })

  it("renders a floating legend only when labeled", () => {
    const { unmount } = render(<TextInput value="" placeholder="repo url" onChange={() => {}} />)

    expect(screen.queryByText("Model name")).toBeNull()
    unmount()

    render(<TextInput value="" label="Model name" placeholder="gpt-4o" onChange={() => {}} />)

    expect(screen.getByText("Model name")).toBeDefined()
    expect(screen.getByLabelText("Model name")).toBeDefined()
  })

  it("hides password values", () => {
    render(<TextInput value="secret" label="Api Key" type="password" onChange={() => {}} />)

    expect(screen.getByLabelText("Api Key").getAttribute("type")).toBe("password")
  })
})
