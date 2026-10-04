import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { ToastProvider } from "./toasts.tsx"; import { useToasts } from "./use-toasts.ts"

function PushButton() {
  const { toasts, pushToast, dismissToast } = useToasts()
  return (
    <>
      <span data-testid="count">{toasts.length}</span>
      <button type="button" onClick={() => pushToast("success", "done")}>
        push
      </button>
      <button type="button" onClick={() => dismissToast(toasts[0]?.id ?? 0)}>
        dismiss
      </button>
    </>
  )
}

describe("ToastProvider", () => {
  it("pushes and dismisses toasts", async () => {
    render(
      <ToastProvider>
        <PushButton />
      </ToastProvider>
    )

    expect(screen.getByTestId("count").textContent).toBe("0")

    await userEvent.click(screen.getByRole("button", { name: "push" }))
    expect(screen.getByTestId("count").textContent).toBe("1")

    await userEvent.click(screen.getByRole("button", { name: "dismiss" }))
    expect(screen.getByTestId("count").textContent).toBe("0")
  })

  it("throws outside the provider", () => {
    expect(() => render(<PushButton />)).toThrow("useToasts must be used inside ToastProvider")
  })
})
