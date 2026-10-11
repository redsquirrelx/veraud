import { describe, expect, it, vi } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import { MermaidDiagram } from "./MermaidDiagram.tsx"
import mermaid from "mermaid"

vi.mock("mermaid", () => ({
  default: {
    initialize: vi.fn(),
    render: vi.fn(),
  },
}))

const renderMock = vi.mocked(mermaid.render)

function success(svg = "<svg>diagram</svg>") {
  renderMock.mockResolvedValue({ svg, diagramType: "flowchart" })
}

describe("MermaidDiagram", () => {
  it("renders the SVG on success", async () => {
    success()
    render(<MermaidDiagram chart="flowchart LR" label="Containers" />)

    expect(await screen.findByRole("img", { name: "Containers" })).toBeDefined()
    expect(renderMock).toHaveBeenCalledWith(expect.stringMatching(/^mermaid-/), "flowchart LR")
  })

  it("falls back to the source when rendering fails", async () => {
    renderMock.mockRejectedValue(new Error("parse error"))
    render(<MermaidDiagram chart="not a chart" label="Containers" />)

    await waitFor(() => {
      expect(screen.getByText("not a chart")).toBeDefined()
    })
    expect(screen.queryByRole("img")).toBeNull()
  })

  it("re-renders when the chart changes", async () => {
    success()
    const { rerender } = render(<MermaidDiagram chart="flowchart LR" label="Containers" />)
    await screen.findByRole("img")

    success("<svg>other</svg>")
    rerender(<MermaidDiagram chart="flowchart TD" label="Containers" />)

    await waitFor(() => {
      expect(renderMock).toHaveBeenCalledWith(expect.anything(), "flowchart TD")
    })
  })
})
