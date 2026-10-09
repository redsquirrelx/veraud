import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import { CodeExplanations } from "./CodeExplanations.tsx"

describe("CodeExplanations", () => {
  it("renders nothing without items", () => {
    const { container } = render(<CodeExplanations items={[]} />)

    expect(container).toBeEmptyDOMElement()
  })

  it("pairs every box with its mark reference and tone", () => {
    render(
      <CodeExplanations
        items={[
          { id: "A", tone: "danger", title: "Unvalidated amount", body: "The guard throws a generic error." },
          { id: "B", tone: "info", title: "Pure helper", body: "No side effects here." },
        ]}
      />
    )

    expect(screen.getByText("Unvalidated amount")).toBeDefined()
    expect(screen.getByText("The guard throws a generic error.")).toBeDefined()
    expect(screen.getByText("Pure helper")).toBeDefined()

    const boxes = screen.getAllByText(/^(A|B)$/)
    expect(boxes.length).toBe(2)
    expect(boxes[0]?.closest("li")?.className).not.toBe(boxes[1]?.closest("li")?.className)
  })
})
