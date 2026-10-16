import { describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { CredentialListItem } from "./CredentialListItem.tsx"
import { changeLanguage } from "../../shared/i18n/index.ts"

describe("CredentialListItem", () => {
  it("shows the name, provider, key preview and usage", () => {
    render(<CredentialListItem name="prod" provider="Google" apiKeyPreview="****1234" inUse onEdit={() => {}} onRemove={() => {}} />)

    expect(screen.getByText("prod")).toBeDefined()
    expect(screen.getByText("Google")).toBeDefined()
    expect(screen.getByText("API key")).toBeDefined()
    expect(screen.getByText("****1234")).toBeDefined()
    expect(screen.getByText("In use")).toBeDefined()
    expect(screen.getByRole("button", { name: "Remove prod" }).hasAttribute("disabled")).toBe(true)
  })

  it("removes without toggling the row", async () => {
    const onRemove = vi.fn()
    const onToggle = vi.fn()
    render(
      <div role="option" aria-selected={false} tabIndex={0} onClick={onToggle}>
        <CredentialListItem name="prod" provider="Google" apiKeyPreview="****1234" inUse={false} onEdit={() => {}} onRemove={onRemove} />
      </div>
    )

    await userEvent.click(screen.getByRole("button", { name: "Remove prod" }))

    expect(onRemove).toHaveBeenCalledTimes(1)
    expect(onToggle).not.toHaveBeenCalled()
  })

  it("edits without toggling the row", async () => {
    const onEdit = vi.fn()
    const onToggle = vi.fn()
    render(
      <div role="option" aria-selected={false} tabIndex={0} onClick={onToggle}>
        <CredentialListItem name="prod" provider="Google" apiKeyPreview="****1234" inUse={false} onEdit={onEdit} onRemove={() => {}} />
      </div>
    )

    await userEvent.click(screen.getByRole("button", { name: "Edit prod" }))

    expect(onEdit).toHaveBeenCalledTimes(1)
    expect(onToggle).not.toHaveBeenCalled()
  })

  it("translates chrome to Spanish", async () => {
    await changeLanguage("es")
    render(<CredentialListItem name="prod" provider="Google" apiKeyPreview="****1234" inUse onEdit={() => {}} onRemove={() => {}} />)

    expect(screen.getByText("prod")).toBeDefined()
    expect(screen.getByText("Google")).toBeDefined()
    expect(screen.getByText("Clave de API")).toBeDefined()
    expect(screen.getByText("****1234")).toBeDefined()
    expect(screen.getByText("En uso")).toBeDefined()
    expect(screen.getByRole("button", { name: "Editar prod" })).toBeDefined()
    expect(screen.getByRole("button", { name: "Eliminar prod" })).toBeDefined()

    await changeLanguage("en")
  })
})
