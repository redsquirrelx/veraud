import { describe, expect, it } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import { CodeViewer } from "./CodeViewer.tsx"

const code = "export function settle(amount: number) {\n  return amount * 2\n}\n"

describe("CodeViewer", () => {
  it("renders every line with its number", () => {
    const { container } = render(<CodeViewer code={code} />)

    expect(container.querySelectorAll(".ui-code-line").length).toBe(3)
    expect(container.querySelectorAll(".ui-code-number")[0]?.textContent).toBe("1")
    expect(container.querySelectorAll(".ui-code-number")[2]?.textContent).toBe("3")
    expect(screen.getByText("export function settle(amount: number) {")).toBeDefined()
  })

  it("keeps blank lines selectable", () => {
    const { container } = render(<CodeViewer code={"first\n\nthird"} />)

    expect(container.querySelectorAll(".ui-code-line").length).toBe(3)
  })

  it("does not count a single trailing newline as a line", () => {
    const { container } = render(<CodeViewer code={"only\n"} />)

    expect(container.querySelectorAll(".ui-code-line").length).toBe(1)
  })

  it("shows the empty text without code", () => {
    render(<CodeViewer code="" />)

    expect(screen.getByText("No content to show")).toBeDefined()
  })

  it("highlights TypeScript keywords only when enabled", () => {
    const { container, rerender } = render(<CodeViewer code={code} />)

    expect(container.querySelectorAll(".hljs-keyword").length).toBe(0)

    rerender(<CodeViewer code={code} language="ts" highlight />)

    const classes = new Set(
      [...container.querySelectorAll(".ui-code-text span")].map((node) => node.className)
    )
    expect(container.querySelectorAll(".hljs-keyword").length).toBeGreaterThan(0)
    expect(classes.has("hljs-title function_")).toBe(true)
  })

  it("highlights Python keywords by extension", () => {
    const { container } = render(
      <CodeViewer code={"import os\ndef run():\n    return None\n"} language="py" highlight />
    )

    expect(container.querySelectorAll(".hljs-keyword").length).toBeGreaterThan(0)
    expect(container.querySelectorAll(".hljs-literal").length).toBeGreaterThan(0)
  })

  it("highlights JSON literals by extension", () => {
    const { container } = render(
      <CodeViewer code={'{"ok": true, "name": "x"}'} language="json" highlight />
    )

    expect(container.querySelectorAll(".hljs-literal").length).toBe(1)
  })

  it("highlights JavaScript with its own grammar", () => {
    const { container } = render(
      <CodeViewer code={"const x = 1\nmodule.exports = { x }\n"} language="js" highlight />
    )

    expect(container.querySelectorAll(".hljs-keyword").length).toBeGreaterThan(0)
  })

  it("highlights shell keywords", () => {
    const { container } = render(
      <CodeViewer code={"if [ ok ]; then\n  exit 0\nfi\n"} language="sh" highlight />
    )

    expect(container.querySelectorAll(".hljs-keyword").length).toBeGreaterThan(0)
  })

  it("shows the file bar with size, lines, syntax, encoding and read-only", () => {
    const { container } = render(<CodeViewer code={"ab\ncd"} language="py" highlight />)

    const bar = container.querySelector(".ui-code-bar")
    expect(bar?.textContent).toContain("5 B")
    expect(bar?.textContent).toContain("2 lines")
    expect(bar?.textContent).toContain("Python")
    expect(bar?.textContent).toContain("UTF-8")
    expect(bar?.textContent).toContain("Read-only")
    expect(bar?.querySelectorAll("svg").length).toBe(5)
  })

  it("shows plain text syntax and zero counts for an empty file", () => {
    const { container } = render(<CodeViewer code="" />)

    const bar = container.querySelector(".ui-code-bar")
    expect(bar?.textContent).toContain("0 B")
    expect(bar?.textContent).toContain("0 lines")
    expect(bar?.textContent).toContain("Plain text")
    expect(screen.getByText("No content to show")).toBeDefined()
  })

  it("shows a single line and kilobytes for bigger files", () => {
    const { container } = render(<CodeViewer code={"x".repeat(2048)} />)

    expect(container.querySelector(".ui-code-bar")?.textContent).toContain("2.0 KB")
    expect(container.querySelector(".ui-code-bar")?.textContent).toContain("1 line")
    expect(container.querySelector(".ui-code-bar")?.textContent).toContain("Plain text")
  })

  it("paints marked ranges by tone and ignores invalid marks", () => {
    const { container } = render(
      <CodeViewer
        code={code}
        marks={[
          { id: "A", from: 1, to: 1, tone: "danger", note: "throws without handling" },
          { id: "B", from: 2, to: 3, tone: "info" },
          { id: "D", from: 99, to: 100, tone: "danger" },
          { id: "E", from: 0, to: 1, tone: "warning" },
          { id: "F", from: 3, to: 2, tone: "info" },
        ]}
      />
    )

    const rows = container.querySelectorAll(".ui-code-line")
    expect(rows[0]?.className).toContain("ui-code-line-danger")
    expect(rows[0]?.getAttribute("title")).toBe("throws without handling")
    expect(rows[0]?.querySelector(".ui-code-ref-danger")?.textContent).toBe("A")
    expect(rows[1]?.className).toContain("ui-code-line-info")
    expect(rows[1]?.getAttribute("title")).toBeNull()
    expect(rows[1]?.querySelector(".ui-code-ref-info")?.textContent).toBe("B")
    expect(rows[2]?.className).toContain("ui-code-line-info")
    expect(rows[2]?.querySelector(".ui-code-ref")).toBeNull()
  })

  it("keeps the first mark on overlapping lines", () => {
    const { container } = render(
      <CodeViewer
        code={code}
        marks={[
          { id: "A", from: 1, to: 2, tone: "danger" },
          { id: "B", from: 2, to: 3, tone: "warning" },
        ]}
      />
    )

    const rows = container.querySelectorAll(".ui-code-line")
    expect(rows[1]?.className).toContain("ui-code-line-danger")
    expect(rows[2]?.className).toContain("ui-code-line-warning")
  })

  it("groups disjoint ranges under one reference", () => {
    const { container } = render(
      <CodeViewer
        code={code}
        marks={[
          { id: "D", from: 1, to: 1, tone: "warning" },
          { id: "D", from: 3, to: 3, tone: "warning" },
        ]}
      />
    )

    const chips = [...container.querySelectorAll(".ui-code-ref-warning")].map((node) => node.textContent)
    expect(chips).toEqual(["D", "D"])
    expect(container.querySelectorAll(".ui-code-line-warning").length).toBe(2)
    expect(container.querySelectorAll(".ui-code-line")[1]?.className).not.toContain("ui-code-line-warning")
  })

  it("combines marks with highlighting", () => {
    const { container } = render(
      <CodeViewer code={code} language="ts" highlight marks={[{ id: "A", from: 1, to: 1, tone: "danger" }]} />
    )

    const first = container.querySelectorAll(".ui-code-line")[0]
    expect(first?.className).toContain("ui-code-line-danger")
    expect(first?.querySelectorAll(".hljs-keyword").length).toBeGreaterThan(0)
  })

  it("ignores unknown languages and casing", () => {
    const { container } = render(<CodeViewer code={code} language="TS" highlight />)

    expect(container.querySelectorAll(".hljs-keyword").length).toBeGreaterThan(0)

    const { container: other } = render(<CodeViewer code={code} language="rs" highlight />)

    expect(other.querySelectorAll("[class*='hljs-']").length).toBe(0)
  })

  it("renders small files at once without progress", () => {
    const small = Array.from({ length: 100 }, (_, index) => `line ${index + 1}`).join("\n")
    const { container } = render(<CodeViewer code={small} />)

    expect(container.querySelectorAll(".ui-code-line").length).toBe(100)
    expect(container.querySelector(".ui-code-progress")).toBeNull()
  })

  it("renders large files in chunks showing progress", async () => {
    const big = Array.from({ length: 1200 }, (_, index) => `line ${index + 1}`).join("\n")
    const { container } = render(<CodeViewer code={big} />)

    expect(container.querySelector(".ui-code-progress")).not.toBeNull()
    expect(container.querySelectorAll(".ui-code-line").length).toBeLessThan(1200)

    await waitFor(() => expect(container.querySelectorAll(".ui-code-line").length).toBe(1200))
    expect(container.querySelector(".ui-code-progress")).toBeNull()
  })
})
