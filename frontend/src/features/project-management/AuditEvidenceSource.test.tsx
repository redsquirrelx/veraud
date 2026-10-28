import { StrictMode } from "react"
import { afterEach, expect, it, vi } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { AuditEvidenceBrowser } from "./AuditEvidenceBrowser.tsx"
import { readAgentEvidence } from "./auditAgentEvidence.ts"

afterEach(() => vi.restoreAllMocks())
const commit = "a".repeat(40)
const content = Array.from({ length: 50 }, (_, index) => `// audited line ${index + 1}`).join("\n")
const response = (path = "src/service.ts", code = content, revision = commit) => new Response(JSON.stringify({ path, content: code,
  size: code.length, commitHash: revision }), { status: 200 })
const evidence = readAgentEvidence({ executions: [{ invocation_id: "inv-1", agent_id: "responsibility", recorded_results: {
  symbols: [{ id: "symbol:run", name: "run", kind: "function", path: "src/service.ts", start_line: 20, end_line: 22 }],
} }], evidence_inventory: [
  { id: "E-1", kind: "source", source: "Demo/src/service.ts", commit, content: null, start_line: 10, end_line: 12, symbol_ids: ["symbol:run"],
    provenance: { invocation_id: "inv-1", agent_id: "responsibility" } },
  { id: "E-2", kind: "source", source: "src/service.ts", commit, content: null, start_line: 30, end_line: 31,
    provenance: { invocation_id: "inv-1", agent_id: "responsibility" } },
] }, "inv-1")!.evidence

it("automatically loads audited full source even when evidence has no content, marks source lines and navigates symbols", async () => {
  const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(response())
  const { container } = render(<StrictMode><AuditEvidenceBrowser evidence={evidence.map((item, index) => index === 0 ? { ...item, commit: null } : item)} projectId={2} auditId={41}
    repositoryName="Demo" recordedOnly auditedCommit={commit} /></StrictMode>)
  await waitFor(() => expect(screen.getByRole("region", { name: "Read-only code viewer" })).toHaveTextContent("audited line 50"))
  expect(fetch).toHaveBeenCalledTimes(1)
  expect(String(fetch.mock.calls[0][0])).toContain("/api/projects/2/audits/41/file")
  expect(fetch.mock.calls[0][1]).toMatchObject({ method: "POST", body: JSON.stringify({ path: "src/service.ts" }) })
  const marked = () => Array.from(container.querySelectorAll(".ui-code-line-info"), (row) => row.getAttribute("data-line"))
  expect(marked()).toEqual(["10", "11", "12"])
  const viewport = container.querySelector<HTMLPreElement>(".ui-code-body")!
  viewport.scrollTo = vi.fn()
  await userEvent.selectOptions(screen.getByRole("combobox", { name: "Code symbols" }), "symbol:run")
  expect(marked()).toEqual(["20", "21", "22"])
  await waitFor(() => expect(viewport.scrollTo).toHaveBeenCalled())
  await userEvent.click(screen.getByRole("button", { name: /^E-2/ }))
  expect(marked()).toEqual(["30", "31"])
  expect(fetch).toHaveBeenCalledTimes(1)
})

it("reuses an in-flight historical read for another evidence at the same normalized path", async () => {
  let finish!: (value: Response) => void
  const fetch = vi.spyOn(globalThis, "fetch").mockImplementationOnce(() => new Promise((resolve) => { finish = resolve }))
  render(<AuditEvidenceBrowser evidence={evidence} projectId={2} auditId={41} repositoryName="Demo" recordedOnly auditedCommit={commit} />)
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1))
  await userEvent.click(screen.getByRole("button", { name: /^E-2/ }))
  finish(response())
  await waitFor(() => expect(screen.getByRole("region", { name: "Read-only code viewer" })).toHaveTextContent("audited line 50"))
  expect(fetch).toHaveBeenCalledTimes(1)
})

it("retains a valid recorded excerpt on historical read failure and supports retry without requesting current files", async () => {
  const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(new Response(JSON.stringify({ message: "History unavailable" }), { status: 422 }))
    .mockResolvedValueOnce(response())
  render(<AuditEvidenceBrowser evidence={[{ ...evidence[0], content: "// recorded excerpt" }]} projectId={2} auditId={41}
    repositoryName="Demo" recordedOnly auditedCommit={commit} />)
  expect(await screen.findByRole("alert")).toHaveTextContent("Could not read the file at the audited commit")
  expect(screen.getByRole("region", { name: "Read-only code viewer" })).toHaveTextContent("recorded excerpt")
  await userEvent.click(screen.getByRole("button", { name: "Retry" }))
  await waitFor(() => expect(screen.getByRole("region", { name: "Read-only code viewer" })).toHaveTextContent("audited line 50"))
  expect(fetch.mock.calls.every(([url]) => String(url).includes("/audits/41/file"))).toBe(true)
})

it("rejects a response for a different commit and ignores an obsolete audit response", async () => {
  let finish!: (value: Response) => void
  const fetch = vi.spyOn(globalThis, "fetch").mockImplementationOnce(() => new Promise((resolve) => { finish = resolve }))
    .mockResolvedValueOnce(response("src/service.ts", "wrong revision content", commit))
  const { rerender } = render(<AuditEvidenceBrowser evidence={evidence} projectId={2} auditId={41} repositoryName="Demo" recordedOnly auditedCommit={commit} />)
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1))
  const signal = fetch.mock.calls[0][1]?.signal
  rerender(<AuditEvidenceBrowser evidence={evidence} projectId={2} auditId={42} repositoryName="Demo" recordedOnly auditedCommit={"b".repeat(40)} />)
  expect(await screen.findByRole("alert")).toBeVisible()
  finish(response())
  expect(signal?.aborted).toBe(true)
  await waitFor(() => expect(screen.getByRole("region", { name: "Read-only code viewer" })).not.toHaveTextContent("audited line 50"))
  expect(screen.getByRole("region", { name: "Read-only code viewer" })).not.toHaveTextContent("wrong revision content")
})

it("shows the historical file but never applies evidence ranges explicitly attributed to another version", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(response())
  const { container } = render(<AuditEvidenceBrowser evidence={[{ ...evidence[0], commit: "b".repeat(40) }]}
    projectId={2} auditId={41} repositoryName="Demo" recordedOnly auditedCommit={commit} />)
  await waitFor(() => expect(screen.getByRole("region", { name: "Read-only code viewer" })).toHaveTextContent("audited line 50"))
  expect(container.querySelector(".ui-code-line-info")).toBeNull()
  expect(screen.getByText(/Evidence and symbol ranges are not highlighted/)).toBeVisible()
})

it("resolves report reference labels and navigates symbols despite an invalid evidence range", async () => {
  const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(response())
  const recorded = readAgentEvidence({ executions: [{ invocation_id: "inv-1", agent_id: "responsibility" }],
    reference_labels: { "symbol:run": "Service.run — src/service.ts:20–22" },
    evidence_inventory: [{ id: "E-label", kind: "source", source: "src/service.ts", commit,
      start_line: 10, end_line: 500, symbol_ids: ["symbol:run"],
      provenance: { invocation_id: "inv-1", agent_id: "responsibility" } }],
  }, "inv-1")!.evidence
  const { container } = render(<AuditEvidenceBrowser evidence={recorded} projectId={2} auditId={41} recordedOnly auditedCommit={commit} />)
  await waitFor(() => expect(screen.getByRole("region", { name: "Read-only code viewer" })).toHaveTextContent("audited line 50"))
  expect(screen.getByText(/The recorded range cannot be reliably mapped/)).toBeVisible()
  const viewport = container.querySelector<HTMLPreElement>(".ui-code-body")!
  viewport.scrollTo = vi.fn()
  await userEvent.selectOptions(screen.getByRole("combobox", { name: "Code symbols" }), "symbol:run")
  expect(Array.from(container.querySelectorAll(".ui-code-line-info"), (row) => row.getAttribute("data-line"))).toEqual(["20", "21", "22"])
  await waitFor(() => expect(viewport.scrollTo).toHaveBeenCalled())
  expect(fetch).toHaveBeenCalledTimes(1)
})
