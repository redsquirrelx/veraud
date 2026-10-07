import { describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { CredentialListItem } from "./CredentialListItem.tsx"

describe("CredentialListItem", () => {
  it("shows the name, provider, key preview and usage", () => {
    render(<CredentialListItem name="prod" provider="Google" apiKeyPreview="****1234" inUse onRemove={() => {}} />)

    expect(screen.getByText("prod")).toBeDefined()
    expect(screen.getByText("Google")).toBeDefined()
    expect(screen.getByText("API key")).toBeDefined()
    expect(screen.getByText("****1234")).toBeDefined()
    expect(screen.getByText("In use")).toBeDefined()
    expect(screen.getByRole("button", { name: "Remove prod" }).hasAttribute("disabled")).toBe(true)
  })

  it("hides the badge and enables remove when idle", () => {
    render(<CredentialListItem name="prod" provider="Google" apiKeyPreview="****1234" inUse={false} onRemove={() => {}} />)

    expect(screen.queryByText("In use")).toBeNull()
    expect(screen.getByRole("button", { name: "Remove prod" }).hasAttribute("disabled")).toBe(false)
  })

  it("removes without toggling the row", async () => {
    const onRemove = vi.fn()
    const onToggle = vi.fn()
    render(
      <button type="button" onClick={onToggle}>
        <CredentialListItem name="prod" provider="Google" apiKeyPreview="****1234" inUse={false} onRemove={onRemove} />
      </button>
    )

    await userEvent.click(screen.getByRole("button", { name: "Remove prod" }))

    expect(onRemove).toHaveBeenCalledTimes(1)
    expect(onToggle).not.toHaveBeenCalled()
  })
})
