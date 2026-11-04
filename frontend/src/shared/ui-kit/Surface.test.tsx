import { render } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { Card } from "./Card.tsx"
import { Panel } from "./Panel.tsx"

describe("shared surfaces", () => {
  it("preserves Card and Panel classes and default surface tones", () => {
    const { container, rerender } = render(<Card>Card content</Card>)
    expect(container.querySelector(".ui-card")).toHaveClass("ui-surface", "ui-surface-card")

    rerender(<Panel>Panel content</Panel>)
    expect(container.querySelector(".ui-panel")).toHaveClass("ui-surface", "ui-surface-tinted")
    expect(container.querySelector(".ui-card")).toBeNull()
  })

  it("applies explicit layout, spacing, alignment, padding and Panel tone variants", () => {
    const { container, rerender } = render(<Card layout="stack" gap="md" align="stretch" padding="responsive">Stacked</Card>)
    expect(container.querySelector(".ui-card")).toHaveClass(
      "ui-surface-stack", "ui-surface-gap-md", "ui-surface-align-stretch", "ui-surface-padding-responsive",
    )

    rerender(<Panel tone="subtle" className="custom-panel">Subtle panel</Panel>)
    expect(container.querySelector(".ui-panel")).toHaveClass("ui-surface-subtle", "custom-panel")
  })
})
