import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { TestFileViewerPage } from "./TestFileViewerPage.tsx"

describe("TestFileViewerPage", () => {
  it("shows a file with line numbers and an empty one", () => {
    const { container } = render(
      <MemoryRouter>
        <TestFileViewerPage />
      </MemoryRouter>
    )

    expect(screen.getByText("File viewer playground")).toBeDefined()
    expect(screen.getByText("payment-gateway-v2/src/modules/settlement.ts (13 lines)")).toBeDefined()
    expect(screen.getByText("payment-gateway-v2/src/modules/settlement.ts with agent marks")).toBeDefined()
    expect(container.querySelectorAll(".ui-code-line-danger").length).toBe(2)
    expect(container.querySelectorAll(".ui-code-line-warning").length).toBe(7)
    expect(container.querySelectorAll(".ui-code-line-info").length).toBe(5)
    expect(screen.getByText("Unvalidated amount")).toBeDefined()
    expect(screen.getByText("Lines 8 to 9 throw a generic error instead of a domain one.")).toBeDefined()
    expect(screen.getByText("payment-gateway-v2/src/modules/settlement.ts grouped by finding")).toBeDefined()
    expect(screen.getByText("Missing domain types")).toBeDefined()
    expect(screen.getByText("Lines 2 to 4 and 7 to 9 repeat the same structural smell in two places.")).toBeDefined()
    expect(screen.getByText("No content to show")).toBeDefined()
    expect(screen.getByText("payment-gateway-v2/src/generated/ledger-entries.ts (120 lines)")).toBeDefined()
    expect(screen.getByText("export const entry120 = { id: 120, amount: 563, currency: \"USD\" }")).toBeDefined()
    expect(screen.getByText("payment-gateway-v2/src/settle.py (highlighted)")).toBeDefined()
    expect(screen.getByText("payment-gateway-v2/src/modules/settlement.highlighted.ts (highlighted)")).toBeDefined()
    expect(screen.getByText("payment-gateway-v2/src/charge.js (highlighted)")).toBeDefined()
    expect(screen.getByText("payment-gateway-v2/config.json (highlighted)")).toBeDefined()
    expect(screen.getByText("payment-gateway-v2/scripts/deploy.sh (highlighted)")).toBeDefined()
    expect(screen.getByText("payment-gateway-v2/dist/bundle.min.json (long lines)")).toBeDefined()
    expect(container.querySelectorAll(".ui-code-line").length).toBe(215)
    expect(container.querySelectorAll(".hljs-keyword").length).toBeGreaterThan(0)
  })
})
