import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import { Card } from "./Card.tsx"
import { Panel } from "./Panel.tsx"

describe("Card", () => {
  it("renders its children", () => {
    render(
      <Card>
        <span>card content</span>
      </Card>
    )

    expect(screen.getByText("card content")).toBeDefined()
  })
})

describe("Panel", () => {
  it("renders its children", () => {
    render(
      <Panel>
        <span>panel content</span>
      </Panel>
    )

    expect(screen.getByText("panel content")).toBeDefined()
  })
})
