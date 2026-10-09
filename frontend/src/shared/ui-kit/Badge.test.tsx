import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import { Badge } from "./Badge.tsx"

describe("Badge", () => {
  it("renders its children with a tone", () => {
    const { unmount } = render(<Badge tone="success">READY</Badge>)

    const success = screen.getByText("READY").getAttribute("class") ?? ""
    unmount()

    render(<Badge tone="neutral">In use</Badge>)

    const neutral = screen.getByText("In use").getAttribute("class") ?? ""
    expect(success).not.toBe(neutral)
  })
})
