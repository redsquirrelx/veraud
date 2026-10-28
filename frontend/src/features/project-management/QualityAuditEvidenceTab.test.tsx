import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, useLocation, useNavigate } from "react-router-dom"
import { auditEvidenceLink } from "./auditEvidenceNavigation.ts"
import { changeLanguage } from "../../shared/i18n/index.ts"
import { QualityAuditResults } from "./QualityAuditResults.tsx"
import { executedEvidenceAgents } from "./auditEvidenceAgents.ts"
import * as api from "./qualityAuditApi.ts"

vi.mock("./qualityAuditApi.ts", () => ({ getQualityAudit: vi.fn(), getQualityAuditReportSection: vi.fn(),
  getQualityAuditConfiguration: vi.fn(), getPublishedAuditEvidence: vi.fn(), readAuditSourceFile: vi.fn(), downloadQualityAuditReport: vi.fn() }))

const commit = "a".repeat(40)
const audit: api.QualityAuditSummary = { id: 41, evaluationId: 1, branch: "audited", commitHash: commit, attributes: ["maintainability"],
  executionStatus: "Completed", auditStatus: "completed", error: null, createdAt: "2026-10-20", finishedAt: null,
  reportAvailable: true, configurationAvailable: true }
const history: api.AuditConfigurationHistory = { configuration: { version: 1, branch: "audited", commitHash: commit, attributes: ["maintainability"],
  scopes: [{ id: "maintainability", requiredAgents: [{ id: "manager", name: "Saved manager" }], techniques: [], investigators: [],
    subcharacteristics: [{ id: "modularity", name: "Saved coordinator", investigators: [
      { id: "responsibility", name: "Saved responsibility" }, { id: "boundary", name: "Saved boundary" },
      { id: "unused", name: "Configured but never executed" }, { id: "skipped", name: "Skipped participant" },
    ] }] }],
}, invocations: [
  { id: "inv-old", agentId: "responsibility", status: "completed" },
  { id: "inv-latest", agentId: "responsibility", status: "completed" },
  { id: "inv-boundary", agentId: "boundary", status: "failed" },
  { id: "inv-skipped", agentId: "skipped", status: "skipped" },
  { id: "inv-unconfigured", agentId: "unconfigured", status: "completed" },
] }
const annexes = { executions: [{ invocation_id: "inv-latest", agent_id: "responsibility" }, { invocation_id: "inv-boundary", agent_id: "boundary" }],
  reference_labels: { "symbol:run": "Service.run — src/service.ts:2–2" }, evidence_inventory: [
    { id: "E-old", source: "Demo/src/service.ts", kind: "source", commit, start_line: 2, end_line: 2, symbol_ids: ["symbol:run"],
      provenance: { invocation_id: "inv-old", agent_id: "responsibility" } },
    { id: "E-new", source: "src/service.ts", kind: "source", commit, start_line: 1, end_line: 1,
      provenance: { invocation_id: "inv-latest", agent_id: "responsibility" } },
    { id: "E-foreign", source: "secret.ts", kind: "source", provenance: { invocation_id: "inv-unconfigured", agent_id: "unconfigured" } },
  ] }
const findings = { findings: [{ id: "F-1", title: "Linked historical finding", description: "Finding details", evidence_ids: ["E-old"] }] }

beforeEach(() => {
  vi.mocked(api.getQualityAudit).mockResolvedValue(audit)
  vi.mocked(api.getQualityAuditConfiguration).mockResolvedValue(history)
  vi.mocked(api.getQualityAuditReportSection).mockImplementation(async (_project, _audit, section) => ({ section,
    data: section === "annexes_and_traceability" ? annexes : section === "quality_results" ? findings : {},
  }))
  vi.mocked(api.readAuditSourceFile).mockImplementation(async (_project, _audit, path) => ({ path, commitHash: commit,
    content: "// audited file\nfunction run() {}", size: 34 }))
})
afterEach(async () => { vi.resetAllMocks(); await changeLanguage("en") })
function Location() {
  const location = useLocation()
  const navigate = useNavigate()
  return <><output aria-label="Current route">{location.pathname}{location.search}</output>
    <button onClick={() => navigate(-1)}>History back</button><button onClick={() => navigate(1)}>History forward</button></>
}
function show(path = "/projects/2/audits/41") { return render(<MemoryRouter initialEntries={[path]}>
  <QualityAuditResults projectId={2} auditId={41} projectName="acme/Demo" repositoryName="Demo" /><Location />
</MemoryRouter>) }

it("embeds real selected-agent evidence without navigation, filtering configured participants by actual executions", async () => {
  show()
  await screen.findByRole("heading", { name: "Audit report · #41" })
  expect(api.getQualityAuditConfiguration).not.toHaveBeenCalled()
  await userEvent.click(screen.getByRole("tab", { name: "Evidence" }))
  const panel = within(screen.getByRole("tabpanel", { name: "Evidence" }))
  const select = await panel.findByRole("combobox", { name: "Executed agent" })
  expect(within(select).getAllByRole("option").map((option) => option.getAttribute("value"))).toEqual(["", "responsibility", "boundary"])
  expect(panel.getByText("Select an executed agent to inspect its evidence here.")).toBeVisible()
  expect(vi.mocked(api.getQualityAuditReportSection).mock.calls.some((call) => call[2] === "annexes_and_traceability")).toBe(false)
  await userEvent.selectOptions(select, "responsibility")
  expect(await panel.findByText("E-old")).toBeVisible()
  expect(panel.getByText("E-new")).toBeVisible()
  expect(panel.queryByText("E-foreign")).toBeNull()
  await waitFor(() => expect(panel.getByRole("region", { name: "Read-only code viewer" })).toHaveTextContent("function run() {}"))
  expect(api.readAuditSourceFile).toHaveBeenCalledWith(2, 41, "src/service.ts", expect.any(AbortSignal))
  await userEvent.selectOptions(panel.getByRole("combobox", { name: "Code symbols" }), "symbol:run")
  await userEvent.click(panel.getByRole("button", { name: "F-1 — Linked historical finding" }))
  expect(await screen.findByRole("dialog", { name: "Linked historical finding" })).toHaveTextContent("Finding details")
  await userEvent.keyboard("{Escape}")
  expect(screen.getByLabelText("Current route")).toHaveTextContent("/projects/2/audits/41")
  expect(panel.queryByRole("link", { name: "Back to audit" })).toBeNull()
  expect(api.getQualityAudit).toHaveBeenCalledTimes(1)
  await userEvent.selectOptions(select, "boundary")
  expect(await panel.findByText("No evidence is registered for this agent in this audit.")).toBeVisible()
  expect(panel.queryByText("E-old")).toBeNull()
  expect(vi.mocked(api.getQualityAuditReportSection).mock.calls.filter((call) => call[2] === "annexes_and_traceability")).toHaveLength(1)
})

it("retains agent selection, source content and section caches when switching tabs", async () => {
  show()
  await userEvent.click(screen.getByRole("tab", { name: "Evidence" }))
  const select = await screen.findByRole("combobox", { name: "Executed agent" })
  await userEvent.selectOptions(select, "responsibility")
  await waitFor(() => expect(screen.getByRole("region", { name: "Read-only code viewer" })).toHaveTextContent("function run() {}"))
  const panel = screen.getByRole("tabpanel", { name: "Evidence" })
  const fileCalls = vi.mocked(api.readAuditSourceFile).mock.calls.length
  await userEvent.click(screen.getByRole("tab", { name: "Findings" }))
  expect(panel).not.toBeVisible()
  await userEvent.click(screen.getByRole("tab", { name: "Evidence" }))
  expect(select).toHaveValue("responsibility")
  expect(panel).toBeVisible()
  expect(api.getQualityAuditConfiguration).toHaveBeenCalledTimes(1)
  expect(api.readAuditSourceFile).toHaveBeenCalledTimes(fileCalls)
  expect(vi.mocked(api.getQualityAuditReportSection).mock.calls.filter((call) => call[2] === "quality_results")).toHaveLength(1)
})

it("supports keyboard navigation and Spanish translations for the new tab and agent selector", async () => {
  await changeLanguage("es")
  show()
  await screen.findByRole("heading", { name: "Informe de auditoría · #41" })
  screen.getByRole("tab", { name: "Resumen General" }).focus()
  await userEvent.keyboard("{End}")
  expect(screen.getByRole("tab", { name: "Evidencias" })).toHaveFocus()
  expect(await screen.findByRole("combobox", { name: "Agente ejecutado" })).toBeVisible()
  await userEvent.keyboard("{ArrowRight}")
  expect(screen.getByRole("tab", { name: "Resumen General" })).toHaveFocus()
})

it("retries configuration failures and distinguishes an audit with no executed participants", async () => {
  vi.mocked(api.getQualityAuditConfiguration).mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValueOnce({ ...history, invocations: [] })
  show()
  await userEvent.click(screen.getByRole("tab", { name: "Evidence" }))
  const panel = within(screen.getByRole("tabpanel", { name: "Evidence" }))
  expect(await panel.findByRole("alert")).toHaveTextContent("Could not load the audit's executed agents.")
  await userEvent.click(panel.getByRole("button", { name: "Retry" }))
  expect(await panel.findByText("No executed agents are recorded within this audit's configuration.")).toBeVisible()
  expect(panel.queryByRole("combobox")).toBeNull()
})

it("keeps legacy receipts usable without borrowing names or participants from today's catalog", () => {
  expect(executedEvidenceAgents({ configuration: null, invocations: [
    { id: "old-1", agentId: "historical-agent", status: "completed" },
    { id: "never-started", agentId: "waiting-agent", status: "waiting" },
  ] })).toEqual([{ id: "historical-agent", name: "historical-agent", invocationId: "old-1" }])
})

it("shows published evidence for the selected executed agent while the audit is running", async () => {
  vi.mocked(api.getQualityAudit).mockResolvedValue({ ...audit, executionStatus: "Running", reportAvailable: false })
  vi.mocked(api.getPublishedAuditEvidence).mockResolvedValue({ partial: true, available: true, data: annexes })
  show()
  await userEvent.click(screen.getByRole("tab", { name: "Evidence" }))
  const panel = within(screen.getByRole("tabpanel", { name: "Evidence" }))
  const select = await panel.findByRole("combobox", { name: "Executed agent" })
  expect(api.getPublishedAuditEvidence).not.toHaveBeenCalled()
  await userEvent.selectOptions(select, "responsibility")
  expect(await panel.findByText("E-old")).toBeVisible()
  expect(panel.getByText("E-new")).toBeVisible()
  expect(panel.getByText(/these records are partial/)).toBeVisible()
  expect(api.getPublishedAuditEvidence).toHaveBeenCalledWith(2, 41, expect.any(AbortSignal))
  expect(api.getQualityAuditReportSection).not.toHaveBeenCalled()
  await userEvent.click(screen.getByRole("tab", { name: "General Overview" }))
  const signal = vi.mocked(api.getPublishedAuditEvidence).mock.calls[0][2]
  expect(signal?.aborted).toBe(true)
})

it("transitions from published evidence to persisted evidence when completion is observed", async () => {
  vi.mocked(api.getQualityAudit).mockResolvedValueOnce({ ...audit, executionStatus: "Running", reportAvailable: false }).mockResolvedValue(audit)
  vi.mocked(api.getPublishedAuditEvidence).mockResolvedValue({ partial: false, available: true, data: annexes })
  show()
  await userEvent.click(screen.getByRole("tab", { name: "Evidence" }))
  await userEvent.selectOptions(await screen.findByRole("combobox", { name: "Executed agent" }), "responsibility")
  await waitFor(() => expect(vi.mocked(api.getQualityAuditReportSection).mock.calls.some((call) => call[2] === "annexes_and_traceability")).toBe(true))
  expect(await screen.findByText("E-old")).toBeVisible()
  expect(screen.getByRole("combobox", { name: "Executed agent" })).toHaveValue("responsibility")
  expect(screen.queryByText(/these records are partial/)).toBeNull()
  expect(api.getQualityAudit).toHaveBeenCalledTimes(2)
})

it("links finding evidence to the exact evidence tab selection using inventory ownership, not the detecting agent", async () => {
  vi.mocked(api.getQualityAuditReportSection).mockImplementation(async (_project, _audit, section) => ({ section,
    data: section === "annexes_and_traceability" ? annexes : section === "quality_results" ? { findings: [{
      id: "F-target", title: "Finding with evidence links", evidence_ids: ["E-new", "E-old"],
      source_refs: [{ record_type: "finding", record_id: "F-target", agent_id: "boundary" }],
    }] } : {},
  }))
  show("/projects/2/audits/41?tab=findings")
  await userEvent.click(await screen.findByRole("button", { name: "Finding with evidence links" }))
  const drawer = within(screen.getByRole("dialog", { name: "Finding with evidence links" }))
  const link = drawer.getByRole("link", { name: "View evidence E-new" })
  expect(link).toHaveClass("ui-button", "ui-button-secondary", "quality-audit-evidence-link")
  expect(link).toHaveAttribute("href", "/projects/2/audits/41?tab=evidence&evidence=E-new")
  expect(drawer.getByRole("link", { name: "View evidence E-old" })).toBeVisible()
  await userEvent.click(link)
  expect(screen.getByRole("tab", { name: "Evidence" })).toHaveAttribute("aria-selected", "true")
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
  const panel = within(screen.getByRole("tabpanel", { name: "Evidence" }))
  await waitFor(() => expect(panel.getByRole("combobox", { name: "Executed agent" })).toHaveValue("responsibility"))
  expect(panel.getByRole("button", { name: /^E-new/ })).toHaveAttribute("aria-pressed", "true")
  expect(panel.getByRole("button", { name: /^E-old/ })).toHaveAttribute("aria-pressed", "false")
  await waitFor(() => expect(panel.getByRole("region", { name: "Read-only code viewer" })).toHaveTextContent("function run() {}"))
  expect(screen.getByRole("tabpanel", { name: "Evidence" }).querySelector('.ui-code-line-info[data-line="1"]')).not.toBeNull()
  expect(panel.getByRole("button", { name: "F-target — Finding with evidence links" })).toBeVisible()
  await userEvent.click(screen.getByRole("button", { name: "History back" }))
  expect(screen.getByRole("tab", { name: "Findings" })).toHaveAttribute("aria-selected", "true")
  await userEvent.click(screen.getByRole("button", { name: "History forward" }))
  await waitFor(() => expect(screen.getByRole("button", { name: /^E-new/ })).toHaveAttribute("aria-pressed", "true"))
})

it("resolves a shared direct link after loading metadata and allows choosing another agent afterwards", async () => {
  show("/projects/2/audits/41?tab=evidence&evidence=E-new")
  const select = await screen.findByRole("combobox", { name: "Executed agent" })
  await waitFor(() => expect(select).toHaveValue("responsibility"))
  expect(screen.getByRole("button", { name: /^E-new/ })).toHaveAttribute("aria-pressed", "true")
  await userEvent.selectOptions(select, "boundary")
  expect(select).toHaveValue("boundary")
  expect(screen.getByLabelText("Current route")).not.toHaveTextContent("evidence=E-new")
  expect(await screen.findByText("No evidence is registered for this agent in this audit.")).toBeVisible()
})

it.each(["missing-evidence", "E-foreign"])("does not substitute unrelated evidence for an unavailable or disallowed target: %s", async (id) => {
  show(auditEvidenceLink("/projects/2/audits/41", id))
  expect(await screen.findByRole("alert")).toHaveTextContent(`Evidence ${id} is not available for an executed agent in this audit.`)
  expect(screen.queryByRole("region", { name: "Read-only code viewer" })).toBeNull()
  expect(api.readAuditSourceFile).not.toHaveBeenCalled()
})

it("encodes evidence identifiers as URL query values rather than route or parameter fragments", () => {
  const id = "evidence:/path?a=1&b=2 #symbol"
  const url = new URL(auditEvidenceLink("/projects/2/audits/41", id), "https://example.test")
  expect(url.pathname).toBe("/projects/2/audits/41")
  expect(url.searchParams.get("tab")).toBe("evidence")
  expect(url.searchParams.get("evidence")).toBe(id)
  expect(url.hash).toBe("")
})

it("opens evidence links from the General Overview finding drawer and closes that drawer", async () => {
  show()
  await userEvent.click(await screen.findByText("6. Quality results"))
  await userEvent.click(await screen.findByRole("button", { name: "Linked historical finding" }))
  await userEvent.click(within(screen.getByRole("dialog", { name: "Linked historical finding" })).getByRole("link", { name: "View evidence E-old" }))
  expect(screen.getByRole("tab", { name: "Evidence" })).toHaveAttribute("aria-selected", "true")
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
  await waitFor(() => expect(screen.getByRole("button", { name: /^E-old/ })).toHaveAttribute("aria-pressed", "true"))
})

it("restores exact evidence selections with browser back/forward without rereading the same source file", async () => {
  show("/projects/2/audits/41?tab=evidence&evidence=E-old")
  await waitFor(() => expect(screen.getByRole("region", { name: "Read-only code viewer" })).toHaveTextContent("function run() {}"))
  expect(screen.getByRole("button", { name: /^E-old/ })).toHaveAttribute("aria-pressed", "true")
  await userEvent.click(screen.getByRole("button", { name: /^E-new/ }))
  expect(screen.getByRole("button", { name: /^E-new/ })).toHaveAttribute("aria-pressed", "true")
  await userEvent.click(screen.getByRole("button", { name: "History back" }))
  expect(screen.getByRole("button", { name: /^E-old/ })).toHaveAttribute("aria-pressed", "true")
  await userEvent.click(screen.getByRole("button", { name: "History forward" }))
  expect(screen.getByRole("button", { name: /^E-new/ })).toHaveAttribute("aria-pressed", "true")
  expect(api.readAuditSourceFile).toHaveBeenCalledTimes(1)
})

it("distinguishes findings without evidence references instead of inventing evidence links", async () => {
  vi.mocked(api.getQualityAuditReportSection).mockImplementation(async (_project, _audit, section) => ({ section,
    data: section === "quality_results" ? { findings: [{ id: "F-empty", title: "Finding without evidence", evidence_ids: [] }] } : {},
  }))
  show("/projects/2/audits/41?tab=findings")
  await userEvent.click(await screen.findByRole("button", { name: "Finding without evidence" }))
  const drawer = within(screen.getByRole("dialog", { name: "Finding without evidence" }))
  expect(drawer.getByText("This finding has no recorded evidence references.")).toBeVisible()
  expect(drawer.queryByRole("link")).toBeNull()
})
