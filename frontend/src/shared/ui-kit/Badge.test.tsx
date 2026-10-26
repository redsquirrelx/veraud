import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { Badge } from "./Badge.tsx"

describe("Badge", () => {
  it("renders its full content and supports the shared status tones", () => {
    const { container, rerender } = render(<Badge tone="danger">Servidor de agentes: Sin conexión</Badge>)
    const badge = container.querySelector(".ui-badge")!
    expect(badge).toHaveClass("ui-badge-danger")
    expect(badge.textContent).toBe("Servidor de agentes: Sin conexión")

    rerender(<Badge tone="unknown">Unknown status</Badge>)
    expect(container.querySelector(".ui-badge")).toHaveClass("ui-badge-unknown")
  })

  it("renders a decorative dot and preserves the complete accessible label in compact mode", () => {
    render(<Badge tone="danger" dot compact title="Servidor de agentes: Sin conexión" aria-label="Servidor de agentes: Sin conexión">
      Servidor de agentes: Sin conexión
    </Badge>)

    const badge = screen.getByLabelText("Servidor de agentes: Sin conexión")
    expect(badge).toHaveAttribute("title", "Servidor de agentes: Sin conexión")
    expect(badge.querySelector(".ui-badge-dot")).toHaveAttribute("aria-hidden", "true")
    expect(badge.querySelector(".ui-badge-content")?.textContent).toBe("Servidor de agentes: Sin conexión")
  })

  it("applies the shared highlighted state", () => {
    const { container } = render(<Badge tone="neutral" highlighted>Planning</Badge>)
    expect(container.querySelector(".ui-badge")).toHaveClass("ui-badge-highlightable", "ui-badge-highlighted")
  })
})
