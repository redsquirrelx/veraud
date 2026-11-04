import { afterEach, expect, it, vi } from "vitest"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { AuditEvidenceBrowser } from "./AuditEvidenceBrowser.tsx"
import { evidenceCodeLocation, readAgentEvidence } from "./auditAgentEvidence.ts"

const records = [
  { id: "E-file", kind: "file", source: "src/service.ts", start_line: 3, end_line: 4,
    content: "import type { Project } from './project'\n\nexport function findProject() {\n  return 1\n}\n" },
  { id: "E-symbol", kind: "source", source: "src/check.py", start_line: 20, end_line: 22,
    symbol_ids: ["check"], content: "def check(value):\n    return value > 0\n# done" },
  { id: "E-empty", kind: "metadata", source: null, content: null },
]
const data = (items = records) => readAgentEvidence({ evidence_inventory: items.map((item) => ({ ...item,
  provenance: { agent_id: "responsibility", invocation_id: "inv-1" } })) }, "inv-1")!.evidence
afterEach(() => vi.restoreAllMocks())

it("displays stored file content and highlights the recorded range without fetching anything", () => {
  const fetch = vi.spyOn(globalThis, "fetch")
  render(<AuditEvidenceBrowser evidence={data()} />)
  const viewer = screen.getByRole("region", { name: "Read-only code viewer" })
  expect(viewer).toHaveTextContent("import type { Project }")
  expect(Array.from(viewer.querySelectorAll(".ui-code-number"), (item) => item.textContent)).toEqual(["1", "2", "3", "4", "5"])
  expect(Array.from(viewer.querySelectorAll(".ui-code-line-info .ui-code-number"), (item) => item.textContent)).toEqual(["3", "4"])
  expect(viewer.querySelector(".hljs-keyword")).not.toBeNull()
  expect(screen.queryByRole("textbox")).toBeNull()
  expect(fetch).not.toHaveBeenCalled()
})

it("selects stored symbol excerpts with original numbering and the matching language", async () => {
  const { rerender } = render(<AuditEvidenceBrowser evidence={data()} />)
  await userEvent.click(screen.getByRole("button", { name: /^E-symbol/ }))
  const viewer = screen.getByRole("region", { name: "Read-only code viewer" })
  expect(within(viewer).getByText("Symbol", { selector: ".ui-badge-content" })).toBeVisible()
  expect(viewer).toHaveTextContent("Python")
  expect(viewer).toHaveTextContent("def check(value)")
  expect(Array.from(viewer.querySelectorAll(".ui-code-line-info .ui-code-number"), (item) => item.textContent)).toEqual(["20", "21", "22"])
  expect(screen.getByText("check", { selector: ".hljs-title" })).toBeVisible()
  rerender(<AuditEvidenceBrowser evidence={data().map((item) => item.id === "E-symbol" ? { ...item, content: "def updated():\n    return True\n# done" } : item)} />)
  expect(screen.getByRole("button", { name: /^E-symbol/ })).toHaveAttribute("aria-pressed", "true")
  expect(viewer).toHaveTextContent("def updated()")
})

it("does not retain the previous evidence content when selecting a record without content", async () => {
  render(<AuditEvidenceBrowser evidence={data()} />)
  await userEvent.click(screen.getByRole("button", { name: /^E-empty/ }))
  const viewer = screen.getByRole("region", { name: "Read-only code viewer" })
  expect(viewer).toHaveTextContent("does not include its content")
  expect(viewer.querySelector(".ui-code-viewer")).not.toBeNull()
  expect(viewer).not.toHaveTextContent("import type")
})

it("keeps unsupported evidence kinds explicit instead of labelling them as code files", () => {
  render(<AuditEvidenceBrowser evidence={data()} />)
  expect(screen.getByRole("button", { name: /^E-empty/ })).toHaveTextContent("metadata")
})

it("does not invent source positions when the content cannot be mapped reliably", () => {
  const item = { ...data()[1], content: "one\ntwo\nthree\nfour" }
  render(<AuditEvidenceBrowser evidence={[item]} />)
  expect(screen.getByText(/Numbering is local/)).toBeVisible()
  expect(document.querySelector(".ui-code-line-info")).toBeNull()
})

it("preserves an explicitly empty source file instead of treating it as missing content", () => {
  render(<AuditEvidenceBrowser evidence={[{ ...data()[0], content: "", startLine: null, endLine: null }]} />)
  expect(document.querySelector(".ui-code-viewer")).not.toBeNull()
  expect(screen.queryByText(/does not include its content/)).toBeNull()
})

it("does not mark an invalid or out-of-bounds source range", () => {
  expect(evidenceCodeLocation({ ...data()[0], startLine: 7, endLine: 3 }).range).toBeNull()
  expect(evidenceCodeLocation({ ...data()[0], endLine: 99 }).range).toBeNull()
})

it("initially selects evidence with code instead of the first metadata-only record", () => {
  const items = data()
  render(<AuditEvidenceBrowser evidence={[items[2], items[1], items[0]]} />)
  expect(screen.getByRole("button", { name: /^E-symbol/ })).toHaveAttribute("aria-pressed", "true")
  expect(screen.getByRole("region", { name: "Read-only code viewer" })).toHaveTextContent("def check(value)")
})

it("keeps the read-only viewer visible even when no record includes source content", () => {
  render(<AuditEvidenceBrowser evidence={[data()[2]]} />)
  const viewer = screen.getByRole("region", { name: "Read-only code viewer" })
  expect(viewer.querySelector(".ui-code-viewer")).not.toBeNull()
  expect(viewer).toHaveTextContent("Read-only")
  expect(viewer).toHaveTextContent("does not include its content")
})

it("independently collapses metadata without hiding the evidence or viewer and preserves it on updates", async () => {
  const { rerender } = render(<AuditEvidenceBrowser evidence={data()} />)
  const button = screen.getByRole("button", { name: "Show details E-symbol" })
  const details = document.getElementById(button.getAttribute("aria-controls")!)!
  expect(details).not.toBeVisible()
  expect(screen.getByRole("button", { name: "Show details E-symbol" })).toHaveAttribute("aria-expanded", "false")
  expect(screen.getByRole("button", { name: /E-symbol.*Symbol/ })).toBeVisible()
  expect(screen.getByRole("button", { name: "Show details E-file" })).toHaveAttribute("aria-expanded", "false")
  await userEvent.click(button)
  expect(details).toBeVisible()
  rerender(<AuditEvidenceBrowser evidence={data().map((item) => ({ ...item }))} />)
  expect(details).toBeVisible()
  await userEvent.click(screen.getByRole("button", { name: "Hide details E-symbol" }))
  expect(details).not.toBeVisible()
})
