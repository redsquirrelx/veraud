import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import { Badge } from "./Badge.tsx"

describe("Badge", () => {
  it("renders with its tone", () => {
    render(<Badge tone="success">READY</Badge>)

    const badge = screen.getByText("READY")
    expect(badge.getAttribute("class")).toContain("ui-badge-success")
  })

  it("renders the neutral tone", () => {
    render(<Badge tone="neutral">In use</Badge>)

    expect(screen.getByText("In use").getAttribute("class")).toContain("ui-badge-neutral")
  })
})
