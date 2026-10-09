import { describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { Button } from "./Button.tsx"

describe("Button", () => {
  it("renders its children", () => {
    render(<Button>Register project</Button>)

    expect(screen.getByRole("button", { name: "Register project" })).toBeDefined()
  })

  it("disables and shows a spinner while loading", () => {
    render(<Button loading>Register project</Button>)

    const button = screen.getByRole("button")

    expect(button.hasAttribute("disabled")).toBe(true)
    expect(screen.getByRole("status", { name: "Loading" })).toBeDefined()
  })

  it("calls onClick when enabled", async () => {
    const onClick = vi.fn()
    render(<Button onClick={onClick}>Register project</Button>)

    await userEvent.click(screen.getByRole("button", { name: "Register project" }))

    expect(onClick).toHaveBeenCalledTimes(1)
  })

  it("shows loadingText instead of spinner when provided", () => {
    render(
      <Button loading loadingText="Wait">
        Register project
      </Button>
    )

    expect(screen.getByRole("button", { name: "Wait" })).toBeDefined()
    expect(screen.queryByRole("status", { name: "Loading" })).toBeNull()
  })
})
