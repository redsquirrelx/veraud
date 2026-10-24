import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { AuditSettings } from "./AuditSettings.tsx"
import { parseLimit, sharedBudgetFits, MIN_TOTAL_TOKENS } from "./auditConfiguration.ts"

function renderAudit() {
  render(<AuditSettings />)
  return {
    context: screen.getByLabelText("Context characters per call") as HTMLInputElement,
    allowance: screen.getByLabelText("Personal token allowance") as HTMLInputElement,
    budget: screen.getByLabelText("Total tokens") as HTMLInputElement,
  }
}

describe("audit limits", () => {
  it("refuses values below the server minimum", () => {
    expect(parseLimit("500", MIN_TOTAL_TOKENS)).toBeNull()
    expect(parseLimit("1000.5", MIN_TOTAL_TOKENS)).toBeNull()
    expect(parseLimit("", MIN_TOTAL_TOKENS)).toBeNull()
    expect(parseLimit("3000000", MIN_TOTAL_TOKENS)).toBe(3_000_000)
  })

  it("requires a shared budget that leaves an agent its full allowance", () => {
    expect(sharedBudgetFits(3_000_000, 500_000)).toBe(true)
    expect(sharedBudgetFits(500_000, 500_000)).toBe(true)
    expect(sharedBudgetFits(499_999, 500_000)).toBe(false)
  })
})

describe("AuditSettings", () => {
  it("exposes the audit limits for every agent and for the run as a whole", () => {
    const { context, allowance, budget } = renderAudit()

    expect(context.value).toBe("160000")
    expect(allowance.value).toBe("500000")
    expect(budget.value).toBe("3000000")
    expect(screen.getByText(/Headroom: 2,500,000 tokens/)).toBeDefined()
  })

  it("blocks a shared budget below one agent's personal allowance", async () => {
    const { budget } = renderAudit()
    await userEvent.clear(budget)
    await userEvent.type(budget, "1000")

    expect(budget).toHaveAttribute("aria-invalid", "true")
    expect(screen.getByRole("alert")).toHaveTextContent("below one agent's personal allowance")
  })

  it("rejects an allowance under the minimum and restores it on reset", async () => {
    const { allowance, budget } = renderAudit()
    await userEvent.clear(allowance)
    await userEvent.type(allowance, "999")

    expect(allowance).toHaveAttribute("aria-invalid", "true")
    expect(screen.getByRole("alert")).toHaveTextContent("1,000 tokens or more")

    await userEvent.click(screen.getByRole("button", { name: "Reset" }))
    expect(allowance.value).toBe("500000")
    expect(budget.value).toBe("3000000")
    expect(screen.queryByRole("alert")).toBeNull()
  })
})
