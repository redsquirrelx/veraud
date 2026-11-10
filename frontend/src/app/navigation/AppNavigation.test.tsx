import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, useLocation } from "react-router-dom"
import { afterEach, describe, expect, it, vi } from "vitest"
import { ToastProvider } from "../toasts.tsx"
import { AppMainNavigation } from "./AppNavigation.tsx"

afterEach(() => vi.unstubAllGlobals())

function Location() {
  return <p data-testid="location">{useLocation().pathname}</p>
}

describe("settings navigation", () => {
  it("opens settings without navigating and closes only with the X", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("[]", { status: 200 })))
    const user = userEvent.setup()
    render(<MemoryRouter><ToastProvider>
      <AppMainNavigation />
      <Location />
    </ToastProvider></MemoryRouter>)
    await user.click(screen.getByRole("button", { name: "Settings" }))
    const dialog = screen.getByRole("dialog", { name: "Settings" })
    expect(within(dialog).getByRole("tab", { name: "Models & credentials" })).toBeInTheDocument()
    expect(screen.getByTestId("location")).toHaveTextContent("/")
    await user.click(dialog.closest(".ui-modal-overlay")!)
    await user.keyboard("{Escape}")
    expect(dialog).toBeInTheDocument()
    await user.click(within(dialog).getByRole("button", { name: "Close" }))
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  })
})
