import { afterEach, expect, it, vi } from "vitest"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { AuditEvidenceBrowser } from "./AuditEvidenceBrowser.tsx"
import { readAgentEvidence } from "./auditAgentEvidence.ts"

afterEach(() => vi.restoreAllMocks())

const annexes = {
  executions: [{ agent_id: "investigator", invocation_id: "inv-1", recorded_results: {
    symbols: [{ id: "symbol:1", qualified_name: "Service.find", kind: "method", path: "src/service.ts", start_line: 8, end_line: 9 }],
  } }],
  evidence_inventory: [{ id: "E-1", kind: "source", source: "src/service.ts", content: "find() {\n  return item\n}",
    start_line: 8, end_line: 10, commit: "historical-commit", commit_verification: "exact", symbol_ids: ["symbol:1"],
    provenance: { agent_id: "investigator", invocation_id: "inv-1" } }],
}
const evidence = readAgentEvidence(annexes, "inv-1")!.evidence

it("keeps recorded symbols in a compact dropdown with their type and source location", async () => {
  const fetch = vi.spyOn(globalThis, "fetch")
  render(<AuditEvidenceBrowser evidence={evidence} projectId={2} recordedOnly auditedCommit="historical-commit" />)
  const symbols = screen.getByRole("combobox", { name: "Code symbols" })
  expect(within(symbols).getByRole("option", { name: "Service.find — Method · Lines 8–9" })).toBeEnabled()
  expect(screen.queryByRole("region", { name: "Code symbols" })).toBeNull()
  await userEvent.selectOptions(symbols, "symbol:1")
  expect(document.querySelector(".audit-evidence-symbol-location")).toHaveTextContent("Lines 8–9")
  expect(document.querySelector(".audit-evidence-symbol-location")).toHaveTextContent("src/service.ts")
  expect(screen.getByRole("region", { name: "Read-only code viewer" })).toHaveTextContent("return item")
  expect(fetch).not.toHaveBeenCalled()
})

it.each(["later-commit", null, ""])("never loads current files or exposes content when the audit commit cannot match: %s", (commit) => {
  const fetch = vi.spyOn(globalThis, "fetch")
  render(<AuditEvidenceBrowser evidence={evidence} projectId={2} recordedOnly auditedCommit={commit} />)
  expect(screen.getByRole("region", { name: "Read-only code viewer" })).not.toHaveTextContent("return item")
  expect(screen.getByText("No matching audited-version content is available.")).toBeVisible()
  expect(screen.queryByRole("button", { name: "Load complete file" })).toBeNull()
  expect(fetch).not.toHaveBeenCalled()
})

it("hides explicitly unverified evidence even if its declared commit matches", () => {
  render(<AuditEvidenceBrowser evidence={[{ ...evidence[0], commitVerification: "unverified" }]} recordedOnly auditedCommit="historical-commit" />)
  expect(screen.getByRole("region", { name: "Read-only code viewer" })).not.toHaveTextContent("return item")
})

it("opens only findings that reference the selected evidence, including multiple links", async () => {
  render(<AuditEvidenceBrowser evidence={evidence} recordedOnly auditedCommit="historical-commit" findingsStatus="loaded"
    qualityResults={{ findings: [
      { id: "F-1", title: "Shared responsibility", description: "Recorded finding description", evidence_ids: ["E-1", "E-2"] },
      { id: "F-2", title: "Repeated dependency", evidence_ids: ["E-1"] },
      { id: "F-other", title: "Unrelated finding", evidence_ids: ["E-2"] },
    ] }} />)
  expect(screen.queryByText(/Unrelated finding/)).toBeNull()
  expect(screen.getByRole("button", { name: "F-2 — Repeated dependency" })).toBeVisible()
  await userEvent.click(screen.getByRole("button", { name: "F-1 — Shared responsibility" }))
  const drawer = within(screen.getByRole("dialog", { name: "Shared responsibility" }))
  expect(drawer.getByText("F-1")).toBeVisible()
  expect(drawer.getByText("Recorded finding description")).toBeVisible()
})

it("does not invent symbol metadata when records are missing or contradictory", () => {
  const unresolved = readAgentEvidence({ ...annexes, executions: [{ ...annexes.executions[0], recorded_results: {
    symbols: [{ id: "symbol:1", name: "First", kind: "class" }, { id: "symbol:1", name: "Second", kind: "function" }],
  } }] }, "inv-1")!.evidence
  expect(unresolved[0].symbols?.[0]).toMatchObject({ id: "symbol:1", name: null, kind: null, startLine: null })
  render(<AuditEvidenceBrowser evidence={unresolved} recordedOnly auditedCommit="historical-commit" findingsStatus="unavailable" />)
  expect(screen.getByRole("option", { name: /symbol:1 — Not recorded.*Location unavailable/ })).toBeEnabled()
  expect(screen.getByText("Finding details are not yet available for this audit.")).toBeVisible()
})

it("scrolls internally and changes highlighting without remounting or requesting source files", async () => {
  const fetch = vi.spyOn(globalThis, "fetch")
  const second = { ...evidence[0].symbols![0], id: "symbol:2", name: "Service.item", startLine: 9, endLine: 9 }
  const { container } = render(<AuditEvidenceBrowser evidence={[{ ...evidence[0], symbolIds: ["symbol:1", "symbol:2"],
    symbols: [...evidence[0].symbols!, second] }]} projectId={2} recordedOnly auditedCommit="historical-commit" />)
  const viewport = container.querySelector<HTMLPreElement>(".ui-code-body")!
  const scroll = vi.fn()
  viewport.scrollTo = scroll
  viewport.getBoundingClientRect = () => ({ top: 100 }) as DOMRect
  container.querySelector<HTMLElement>('[data-line="9"]')!.getBoundingClientRect = () => ({ top: 140 }) as DOMRect
  await waitFor(() => expect(scroll).toHaveBeenCalledTimes(1))
  scroll.mockClear()
  const select = screen.getByRole("combobox", { name: "Code symbols" })
  // The first symbol starts at the same line as the evidence: it must still scroll.
  await userEvent.selectOptions(select, "symbol:1")
  await waitFor(() => expect(scroll).toHaveBeenCalledTimes(1))
  await userEvent.selectOptions(select, "symbol:2")
  await waitFor(() => expect(scroll).toHaveBeenLastCalledWith({ top: 40, behavior: "smooth" }))
  expect(Array.from(container.querySelectorAll(".ui-code-line-info"), (row) => row.getAttribute("data-line"))).toEqual(["9"])
  expect(container.querySelector(".ui-code-body")).toBe(viewport)
  await userEvent.selectOptions(select, "")
  expect(Array.from(container.querySelectorAll(".ui-code-line-info"), (row) => row.getAttribute("data-line"))).toEqual(["8", "9", "10"])
  expect(fetch).not.toHaveBeenCalled()
})

it("allows selecting unavailable symbols without highlighting unrelated evidence lines", async () => {
  const symbols = [
    { ...evidence[0].symbols![0], id: "outside", startLine: 100, endLine: 120 },
    { ...evidence[0].symbols![0], id: "other-file", source: "src/other.ts" },
    { ...evidence[0].symbols![0], id: "no-location", startLine: null, endLine: null },
  ]
  const { container } = render(<AuditEvidenceBrowser evidence={[{ ...evidence[0], symbolIds: symbols.map((symbol) => symbol.id), symbols }]}
    recordedOnly auditedCommit="historical-commit" />)
  expect(screen.getAllByRole("option").slice(1)).toHaveLength(3)
  for (const option of screen.getAllByRole("option").slice(1)) expect(option).toBeEnabled()
  for (const symbol of symbols) {
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Code symbols" }), symbol.id)
    expect(screen.getByText(/This symbol is selected, but its location cannot be resolved/)).toBeVisible()
    expect(container.querySelector(".ui-code-line-info")).toBeNull()
  }
})

it("resets symbol selection when another evidence reuses the same source file", async () => {
  render(<AuditEvidenceBrowser evidence={[...evidence, { ...evidence[0], id: "E-2" }]} recordedOnly auditedCommit="historical-commit" />)
  await userEvent.selectOptions(screen.getByRole("combobox", { name: "Code symbols" }), "symbol:1")
  await userEvent.click(screen.getByRole("button", { name: /^E-2/ }))
  expect(screen.getByRole("combobox", { name: "Code symbols" })).toHaveValue("")
})

it("highlights only the recorded portion when a symbol extends beyond the excerpt", async () => {
  const { container } = render(<AuditEvidenceBrowser evidence={[{ ...evidence[0],
    symbols: [{ ...evidence[0].symbols![0], startLine: 9, endLine: 50 }],
  }]} recordedOnly auditedCommit="historical-commit" />)
  await userEvent.selectOptions(screen.getByRole("combobox", { name: "Code symbols" }), "symbol:1")
  expect(screen.getByText("(only the recorded portion is highlighted)")).toBeVisible()
  expect(Array.from(container.querySelectorAll(".ui-code-line-info"), (row) => row.getAttribute("data-line"))).toEqual(["9", "10"])
})
