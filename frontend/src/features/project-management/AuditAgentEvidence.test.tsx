import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { AuditAgentEvidence } from "./AuditAgentEvidence.tsx"
import { getPublishedAuditEvidence, getQualityAudit, getQualityAuditReportSection } from "./qualityAuditApi.ts"
import { readAgentEvidence } from "./auditAgentEvidence.ts"

vi.mock("./qualityAuditApi.ts", () => ({ getPublishedAuditEvidence: vi.fn(), getQualityAudit: vi.fn(), getQualityAuditReportSection: vi.fn(),
  readAuditSourceFile: () => Promise.reject(new Error("Historical file unavailable in this fixture")),
}))
vi.mock("../../infrastructure/http-client/httpClient.ts", async (original) => ({
  ...await original<typeof import("../../infrastructure/http-client/httpClient.ts")>(),
  readProjectFile: () => new Promise(() => {}),
}))
const metadata = { id: 41, evaluationId: 1, branch: "main", commitHash: "abc123", attributes: ["maintainability"],
  executionStatus: "Completed", auditStatus: "completed", error: null, createdAt: "2026-10-20", finishedAt: null, reportAvailable: true }
const evidence = (id: string, invocation = "inv-1", agent = "responsibility") => ({ id, kind: "code", source: "src/service.ts",
  content: "Stored code fragment", start_line: 5, end_line: 7, commit: "abc123", tool_call_id: "tool-1",
  provenance: { agent_id: agent, invocation_id: invocation } })
const annexes = { executions: [{ agent_id: "responsibility", invocation_id: "inv-1" }],
  evidence_inventory: [evidence("E-1"), evidence("E-other-invocation", "inv-2"), evidence("E-other-agent", "inv-1", "other"),
    { ...evidence("E-unattributed"), provenance: null }] }

beforeEach(() => {
  vi.mocked(getQualityAudit).mockResolvedValue(metadata)
  vi.mocked(getPublishedAuditEvidence).mockResolvedValue({ partial: true, available: false, data: null })
  vi.mocked(getQualityAuditReportSection).mockResolvedValue({ section: "annexes_and_traceability", data: annexes })
})
afterEach(() => vi.resetAllMocks())

function show(invocationId = "inv-1") {
  return render(<MemoryRouter initialEntries={["/?agent=wrong&name=Untrusted%20agent"]}>
    <AuditAgentEvidence projectId={2} auditId={41} invocationId={invocationId} projectName="acme/Demo" />
  </MemoryRouter>)
}

it("includes every invocation of the recorded investigator, not URL identity or other agents", async () => {
  show()
  expect(await screen.findByRole("heading", { name: "Registered evidence (2)" }, { timeout: 5000 })).toBeVisible()
  expect(screen.getByText("responsibility")).toBeVisible()
  expect(screen.queryByText("Untrusted agent")).toBeNull()
  expect(screen.getByText("E-1")).toBeVisible()
  expect(screen.getByText("E-other-invocation")).toBeVisible()
  expect(screen.getByText("inv-2")).not.toBeVisible()
  expect(screen.queryByText("E-other-agent")).toBeNull()
  expect(screen.queryByText("E-unattributed")).toBeNull()
  expect(screen.getByRole("region", { name: "Read-only code viewer" })).toHaveTextContent("Stored code fragment")
  expect(screen.getAllByText("Lines 5–7")).toHaveLength(3)
  expect(screen.getAllByText("abc123")).toHaveLength(3)
  expect(getQualityAuditReportSection).toHaveBeenCalledWith(2, 41, "annexes_and_traceability", expect.any(AbortSignal))
})

it("selects real evidence in the viewer without requesting additional data", async () => {
  show()
  await screen.findByText("E-1")
  expect(screen.queryByRole("heading", { name: "Evidence viewer mockup" })).toBeNull()
  await userEvent.click(screen.getByRole("button", { name: /^E-other-invocation/ }))
  expect(screen.getByRole("region", { name: "Read-only code viewer" })).toBeVisible()
  expect(screen.getByText("E-1")).toBeVisible()
  expect(getQualityAudit).toHaveBeenCalledTimes(1)
  expect(getQualityAuditReportSection).toHaveBeenCalledTimes(2)
  expect(getPublishedAuditEvidence).not.toHaveBeenCalled()
  expect(screen.getByRole("button", { name: /^E-other-invocation/ })).toHaveAttribute("aria-pressed", "true")
})

it("does not request or display final report artifacts while the audit is running", async () => {
  vi.mocked(getQualityAudit).mockResolvedValue({ ...metadata, executionStatus: "Running" })
  show()
  expect(await screen.findByText(/The audit has not finished yet/)).toBeVisible()
  expect(getQualityAuditReportSection).not.toHaveBeenCalled()
  expect(screen.queryByRole("article")).toBeNull()
})

it("shows published evidence before the audit finishes without generating a report", async () => {
  vi.mocked(getQualityAudit).mockResolvedValue({ ...metadata, executionStatus: "Running", reportAvailable: false })
  vi.mocked(getPublishedAuditEvidence).mockResolvedValue({ partial: true, available: true, data: annexes })
  show()
  expect(await screen.findByText("E-1")).toBeVisible()
  expect(screen.getByText("E-other-invocation")).toBeVisible()
  expect(screen.getByText(/these records are partial/)).toBeVisible()
  expect(getQualityAuditReportSection).not.toHaveBeenCalled()
})

it("switches to persisted report evidence when the live endpoint observes completion", async () => {
  vi.mocked(getQualityAudit).mockResolvedValueOnce({ ...metadata, executionStatus: "Running", reportAvailable: false })
    .mockResolvedValue(metadata)
  vi.mocked(getPublishedAuditEvidence).mockResolvedValue({ partial: false, available: true, data: annexes })
  show()
  await waitFor(() => {
    expect(getQualityAudit).toHaveBeenCalledTimes(2)
    expect(getQualityAuditReportSection).toHaveBeenCalledTimes(2)
    expect(screen.queryByText(/these records are partial/)).toBeNull()
    expect(screen.getByText("E-1")).toBeVisible()
  })
})

it("does not request an unavailable report", async () => {
  vi.mocked(getQualityAudit).mockResolvedValue({ ...metadata, reportAvailable: false })
  show()
  expect(await screen.findByText(/This audit has no available report/)).toBeVisible()
  expect(getQualityAuditReportSection).not.toHaveBeenCalled()
})

it.each([
  [{ executions: annexes.executions, evidence_inventory: [] }, "No evidence is registered for this agent in this audit."],
  [{ executions: [], evidence_inventory: [] }, "This execution is not recorded in the report traceability."],
  [null, "This report does not contain an available evidence inventory."],
  [{ executions: annexes.executions }, "This report does not contain an available evidence inventory."],
])("distinguishes missing traceability, empty evidence and unavailable inventory (%#)", async (data, message) => {
  vi.mocked(getQualityAuditReportSection).mockResolvedValue({ section: "annexes_and_traceability", data })
  show()
  expect(await screen.findByText(message)).toBeVisible()
})

it("retains an explicit empty state when no historical content is recorded", async () => {
  vi.mocked(getQualityAuditReportSection).mockResolvedValue({ section: "annexes_and_traceability", data: {
    evidence_inventory: [{ ...evidence("E-1"), content: null, start_line: null, end_line: null }],
  } })
  show()
  expect(await screen.findByText("The report records this evidence but does not include its content.", { selector: "p" })).toBeVisible()
  expect(screen.getByText("E-1")).toBeVisible()
  expect(screen.queryByText(/Lines/)).toBeNull()
})

it("retries section failures independently", async () => {
  vi.mocked(getQualityAuditReportSection).mockRejectedValueOnce(new Error("unavailable"))
  show()
  expect(await screen.findByRole("alert")).toHaveTextContent("Could not load the audit evidence.")
  await userEvent.click(screen.getByRole("button", { name: "Retry" }))
  expect(await screen.findByText("E-1")).toBeVisible()
  expect(getQualityAudit).toHaveBeenCalledTimes(1)
  expect(getQualityAuditReportSection).toHaveBeenCalledTimes(3)
})

it("retries metadata failures before requesting evidence", async () => {
  vi.mocked(getQualityAudit).mockRejectedValueOnce(new Error("unavailable"))
  show()
  await screen.findByRole("alert")
  expect(getQualityAuditReportSection).not.toHaveBeenCalled()
  await userEvent.click(screen.getByRole("button", { name: "Retry" }))
  expect(await screen.findByText("E-1")).toBeVisible()
})

it("keeps all investigator evidence when switching between its invocations without refetching", async () => {
  const { rerender } = show()
  await screen.findByText("E-1")
  rerender(<MemoryRouter><AuditAgentEvidence projectId={2} auditId={41} invocationId="inv-2" projectName="acme/Demo" /></MemoryRouter>)
  expect(screen.getByText("E-1")).toBeVisible()
  expect(screen.getByText("E-other-invocation")).toBeVisible()
  await waitFor(() => expect(getQualityAuditReportSection).toHaveBeenCalledTimes(2))
})

it("finds earlier evidence even when the selected latest invocation produced none", () => {
  const result = readAgentEvidence({ executions: [{ agent_id: "responsibility", invocation_id: "inv-latest" }],
    evidence_inventory: [evidence("E-earlier", "inv-earlier"), evidence("E-other", "inv-other", "other")] }, "inv-latest")
  expect(result).toMatchObject({ agentId: "responsibility", evidence: [{ id: "E-earlier", invocationId: "inv-earlier" }] })
})

it("replaces the list when selecting a different investigator", async () => {
  vi.mocked(getQualityAuditReportSection).mockResolvedValue({ section: "annexes_and_traceability", data: {
    executions: [...annexes.executions, { agent_id: "other", invocation_id: "inv-other" }],
    evidence_inventory: [...annexes.evidence_inventory, evidence("E-different-investigator", "inv-other", "other")],
  } })
  const { rerender } = show()
  await screen.findByText("E-1")
  rerender(<MemoryRouter><AuditAgentEvidence projectId={2} auditId={41} invocationId="inv-other" projectName="acme/Demo" /></MemoryRouter>)
  expect(screen.queryByText("E-1")).toBeNull()
  expect(screen.queryByText("E-other-invocation")).toBeNull()
  expect(screen.getByText("E-different-investigator")).toBeVisible()
})

it("uses a recorded live identity when the latest invocation is absent from the report", () => {
  expect(readAgentEvidence({ evidence_inventory: [evidence("E-earlier", "inv-earlier")] }, "inv-latest", "responsibility"))
    .toMatchObject({ agentId: "responsibility", evidence: [{ id: "E-earlier", invocationId: "inv-earlier" }] })
})

it("ignores malformed inventory entries without inventing provenance or locations", () => {
  expect(readAgentEvidence({ evidence_inventory: [null, "bad", {}, { ...evidence("E-1"), start_line: -1, end_line: "7" }] }, "inv-1"))
    .toMatchObject({ found: true, evidence: [{ id: "E-1", startLine: null, endLine: null }] })
})

it("aborts an obsolete section request and never replaces the newly selected audit with its data", async () => {
  let resolveOld!: (value: Awaited<ReturnType<typeof getQualityAuditReportSection>>) => void
  vi.mocked(getQualityAuditReportSection).mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve }))
  const { rerender } = show()
  await waitFor(() => expect(getQualityAuditReportSection).toHaveBeenCalledTimes(2))
  const oldSignal = vi.mocked(getQualityAuditReportSection).mock.calls[0][3]
  rerender(<MemoryRouter><AuditAgentEvidence projectId={2} auditId={42} invocationId="inv-1" projectName="acme/Demo" /></MemoryRouter>)
  expect(await screen.findByText("E-1")).toBeVisible()
  expect(oldSignal?.aborted).toBe(true)
  resolveOld({ section: "annexes_and_traceability", data: { evidence_inventory: [evidence("STALE")] } })
  await waitFor(() => expect(screen.queryByText("STALE")).toBeNull())
  expect(screen.getByText("E-1")).toBeVisible()
})
