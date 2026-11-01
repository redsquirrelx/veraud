import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, Route, Routes, useParams } from "react-router-dom"
import { AuditAgentEvidence } from "../../features/project-management/AuditAgentEvidence.tsx"
import { initializeI18n } from "../i18n/index.ts"
import { AuditStatusDrawer } from "./AuditStatusDrawer.tsx"
import { executionAudits } from "./executionAudits.ts"
import type { AuditAgentRun, AuditStatusModel } from "./auditStatus.ts"
import type { AgentExecution } from "../../infrastructure/http-client/httpClient.ts"
vi.mock("../../infrastructure/http-client/httpClient.ts", async (original) => ({
  ...await original<typeof import("../../infrastructure/http-client/httpClient.ts")>(),
  readProjectFile: () => new Promise(() => {}),
}))
import { getQualityAudit, getQualityAuditReportSection } from "../../features/project-management/qualityAuditApi.ts"

vi.mock("../../features/project-management/qualityAuditApi.ts", () => ({
  getQualityAudit: vi.fn(), getQualityAuditReportSection: vi.fn(),
  readAuditSourceFile: () => Promise.reject(new Error("Historical file unavailable in this fixture")),
}))
beforeEach(() => {
  window.localStorage.clear()
  vi.mocked(getQualityAudit).mockResolvedValue({ id: 41, evaluationId: 1, branch: "main", commitHash: "audited-commit",
    attributes: ["maintainability"], executionStatus: "Completed", auditStatus: "completed", error: null,
    createdAt: "2026-10-20", finishedAt: null, reportAvailable: true })
  vi.mocked(getQualityAuditReportSection).mockResolvedValue({ section: "annexes_and_traceability", data: {
    executions: [{ agent_id: "responsibility", invocation_id: "investigator-1" },
      { agent_id: "architecture_boundary", invocation_id: "investigator-2" }],
    evidence_inventory: [{ id: "E-1", kind: "code", source: "src/service.ts", content: "export const value = 1", commit: "audited-commit",
      provenance: { agent_id: "responsibility", invocation_id: "investigator-1" } }],
  } })
})

const agent = (id: string, agentType: string, role: string, parentId?: string): AuditAgentRun => ({
  id, agentType, role, parentId, name: `${agentType} agent`, state: "completed",
  inputTokens: null, outputTokens: null, startedAt: null, finishedAt: null, error: null,
})
const audit: AuditStatusModel = {
  id: 41, project: { id: 2, repositoryOwner: "acme", repositoryName: "Demo" },
  branch: "main", commitHash: null, state: "running", error: null,
  createdAt: "2026-10-20", finishedAt: null, reportAvailable: false,
  pipelines: [{ id: "maintainability", state: "running", agents: [
    agent("manager-1", "maintainability_manager", "manager"),
    agent("mod-1", "modularity", "coordinator", "manager-1"),
    agent("investigator-1", "responsibility", "investigator", "mod-1"),
    agent("investigator-2", "architecture_boundary", "investigator", "mod-1"),
  ] }],
}

function EvidenceRoute() {
  const { invocationId } = useParams()
  return <AuditAgentEvidence projectId={2} auditId={41} invocationId={invocationId!} projectName="acme/Demo" />
}

function show(model = audit) {
  return render(<MemoryRouter initialEntries={["/projects/2/audits/41"]}>
    <AuditStatusDrawer audits={[model]} />
    <main><Routes>
      <Route path="/projects/:id/audits/:auditId" element={<h2>Audit results</h2>} />
      <Route path="/projects/:id/audits/:auditId/evidence/:invocationId" element={<EvidenceRoute />} />
    </Routes></main>
  </MemoryRouter>)
}

afterEach(async () => { vi.restoreAllMocks(); await initializeI18n("en") })

it("opens registered evidence in the main area while preserving the open audit menu", async () => {
  const fetch = vi.spyOn(globalThis, "fetch")
  show()
  await userEvent.click(screen.getByRole("button", { name: "1 audit" }))
  const panel = screen.getByRole("region", { name: "Audit statuses" })
  for (const button of within(panel).getAllByRole("button", { name: /^Execution details · (responsibility|architecture_boundary)/ })) {
    await userEvent.click(button)
  }
  const links = within(panel).getAllByRole("link", { name: "View evidence" })
  expect(links).toHaveLength(2)
  await userEvent.click(links[0])
  const main = within(screen.getByRole("main"))
  expect(main.getByRole("heading", { name: "Agent evidence" })).toBeVisible()
  expect(await main.findByText("responsibility agent")).toBeVisible()
  expect(main.getAllByText("investigator-1")).toHaveLength(2)
  expect(main.getByRole("link", { name: "Audit #41" })).toBeVisible()
  expect(main.getByRole("region", { name: "Read-only code viewer" })).toHaveTextContent("export const value = 1")
  expect(main.getAllByRole("article")).toHaveLength(1)
  expect(panel).toBeVisible()
  expect(screen.getByRole("button", { name: "1 audit" })).toHaveAttribute("aria-expanded", "true")
  await userEvent.click(within(panel).getAllByRole("link", { name: "View evidence" })[1])
  expect(main.getByText("architecture_boundary agent")).toBeVisible()
  expect(main.getByText("investigator-2")).toBeVisible()
  expect(main.getByText("No evidence is registered for this agent in this audit.")).toBeVisible()
  expect(main.queryByText("export const value = 1")).toBeNull()
  await userEvent.click(main.getByRole("link", { name: "Back to audit" }))
  expect(main.getByRole("heading", { name: "Audit results" })).toBeVisible()
  expect(panel).toBeVisible()
  expect(fetch).not.toHaveBeenCalled()
})

it("translates the registered evidence and action into Spanish", async () => {
  await initializeI18n("es")
  show()
  await userEvent.click(screen.getByRole("button", { name: "1 auditoría" }))
  await userEvent.click(screen.getByRole("button", { name: /^Detalles de ejecución · Ejecución de responsibility/ }))
  await userEvent.click(screen.getAllByRole("link", { name: "Ver evidencias" })[0])
  expect(screen.getByRole("heading", { name: "Evidencias del agente" })).toBeVisible()
  expect(await screen.findByRole("heading", { name: "Evidencias registradas (1)" })).toBeVisible()
})

it("does not offer project evidence navigation without a project context", async () => {
  show({ ...audit, project: null })
  await userEvent.click(screen.getByRole("button", { name: "1 audit" }))
  expect(screen.queryByRole("link", { name: "View evidence" })).toBeNull()
})

it("keeps catalog investigator identity on the invocation used by evidence links", () => {
  const execution: AgentExecution = {
    id: 41, evaluationId: 1, agentType: "maintainability_manager", status: "Running", result: null,
    error: null, inputTokens: null, outputTokens: null, createdAt: "2026-10-20", startedAt: null, finishedAt: null,
    invocations: [{ invocation_id: "investigator-1", parent_invocation_id: null, agent_id: "responsibility",
      run_id: "run-1", status: "completed", started_at: "2026-10-20", finished_at: null,
      input_tokens: null, output_tokens: null, error: null }],
  }
  const models = executionAudits([execution], [{ agentType: "responsibility", name: "Responsibility investigator",
    role: "investigator", configured: false, configuration: null, qualityAttributes: ["maintainability"], workflowIds: [] }])
  expect(models[0].pipelines.flatMap((pipeline) => pipeline.agents).find((item) => item.id === "investigator-1"))
    .toMatchObject({ role: "investigator", name: "Responsibility investigator" })
})
