import { afterEach, describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { ProjectRegistrationForm } from "./ProjectRegistrationForm.tsx"
import { useRegisterProject } from "./useRegisterProject.ts"

const realFetch = globalThis.fetch

afterEach(() => {
  globalThis.fetch = realFetch
})

function FormHarness() {
  const registration = useRegisterProject()
  return (
    <>
      <span data-testid="state">{registration.state}</span>
      <ProjectRegistrationForm registration={registration} />
    </>
  )
}

describe("ProjectRegistrationForm", () => {
  it("enables submit only with a url", async () => {
    render(<FormHarness />)

    const button = screen.getByRole("button", { name: "Register project" })
    expect(button.hasAttribute("disabled")).toBe(true)

    await userEvent.type(screen.getByPlaceholderText("https://github.com/owner/repo"), "https://github.com/acme/Demo")
    expect(button.hasAttribute("disabled")).toBe(false)
  })

  it("enters loading while registering", async () => {
    globalThis.fetch = (() => new Promise<Response>(() => {})) as typeof fetch
    render(<FormHarness />)

    await userEvent.type(screen.getByPlaceholderText("https://github.com/owner/repo"), "https://github.com/acme/Demo")
    await userEvent.click(screen.getByRole("button", { name: "Register project" }))

    expect(screen.getByTestId("state").textContent).not.toBe("idle")
  })
})
