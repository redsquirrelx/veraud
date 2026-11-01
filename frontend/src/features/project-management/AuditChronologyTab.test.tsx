import { beforeEach, expect, it, vi } from "vitest"
import { render, screen, within } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { getAgentExecution, type AgentExecution } from "../../infrastructure/http-client/httpClient.ts"
import { changeLanguage } from "../../shared/i18n/index.ts"
import { QualityAuditResults } from "./QualityAuditResults.tsx"
import { getQualityAudit, type QualityAuditSummary } from "./qualityAuditApi.ts"
import { demoChronologyPipelines } from "./auditChronologyDemo.ts"
import { chronologyExecutions } from "./auditChronology.ts"
import { auditAgentName } from "../../shared/audit-monitor/auditStatus.ts"

vi.mock("../../infrastructure/http-client/httpClient.ts", async (original) => ({
  ...await original<typeof import("../../infrastructure/http-client/httpClient.ts")>(), getAgentExecution: vi.fn(),
}))
vi.mock("./qualityAuditApi.ts", async (original) => ({
  ...await original<typeof import("./qualityAuditApi.ts")>(), getQualityAudit: vi.fn(),
}))

const audit: QualityAuditSummary = { id: 8, evaluationId: 4, branch: "main", commitHash: "a".repeat(40), attributes: ["security"],
  executionStatus: "Completed", auditStatus: "completed", error: null, createdAt: "2026-10-30T10:00:00Z", finishedAt: "2026-10-30T13:00:00Z", reportAvailable: false }
const execution: AgentExecution = { id: 8, evaluationId: 4, agentType: "security", status: "Completed", result: null,
  error: null, inputTokens: 5, outputTokens: 2, createdAt: audit.createdAt, startedAt: null, finishedAt: audit.finishedAt }

beforeEach(async () => {
  vi.resetAllMocks()
  await changeLanguage("es")
  vi.mocked(getQualityAudit).mockResolvedValue(audit)
  vi.mocked(getAgentExecution).mockResolvedValue(execution)
})

function show(tab = "chronology") {
  return render(<MemoryRouter initialEntries={[`/projects/5/audits/8?tab=${tab}`]}>
    <QualityAuditResults projectId={5} auditId={8} projectName="acme/demo" />
  </MemoryRouter>)
}

it("lists monitor invocations chronologically, preserving parents, parallel branches and repeated agents", async () => {
  show()
  expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual(["Resumen General", "Hallazgos", "Evidencias", "Incidentes", "Cronología"])
  expect(screen.getByRole("tab", { name: "Cronología" })).toHaveAttribute("aria-selected", "true")
  const panel = screen.getByRole("tabpanel", { name: "Cronología" })
  expect(await within(panel).findByRole("note")).toHaveTextContent("DEMO:")
  expect(getAgentExecution).not.toHaveBeenCalled()
  const items = within(panel).getAllByRole("listitem")
  expect(items).toHaveLength(8)
  expect(items.map((item) => item.querySelector("article")?.getAttribute("aria-label"))).toEqual([
    "Gestor de mantenibilidad · #demo-manager", "Coordinador de modularidad · #demo-modularity", "Coordinador de seguridad · #demo-security",
    "Investigador de responsabilidades · #demo-responsibility-1", "Investigador de impacto de dependencias · #demo-dependency",
    "Investigador de responsabilidades · #demo-responsibility-2", "Coordinador de capacidad de prueba · #demo-testability", "Investigador de aislamiento de pruebas · #demo-pending",
  ])
  expect(items[3].querySelector(".audit-chronology-path")).toHaveTextContent("Gestor de mantenibilidad → Coordinador de modularidad → Investigador de responsabilidades")
  expect(items[5].querySelector(".audit-chronology-path")).toHaveTextContent("Gestor de mantenibilidad → Coordinador de modularidad → Investigador de responsabilidades")
  expect(items[7].querySelector(".audit-chronology-path")).toHaveTextContent("Gestor de mantenibilidad → Coordinador de capacidad de prueba → Investigador de aislamiento de pruebas")
  expect(items[0].querySelector("article")).toHaveAttribute("data-state", "running")
  expect(items[3].querySelector("article")).toHaveAttribute("data-state", "partial")
  expect(items[7].querySelector("article")).toHaveAttribute("data-state", "waiting")
  expect(items[0].querySelector(".audit-run-dot")).toBeInTheDocument()
  expect(items[0].querySelector("time")).toHaveAttribute("datetime", "2026-10-30T10:00:00Z")
  expect(items[7].querySelector("time")).toBeNull()
  expect(within(items[7]).getByText("En espera")).toBeVisible()
  expect(panel.querySelector("details")).toBeNull()
  expect(getAgentExecution).not.toHaveBeenCalled()
})

it("translates the chronology to English", async () => {
  await changeLanguage("en")
  show()
  expect(screen.getByRole("tab", { name: "Chronology" })).toBeVisible()
  const panel = screen.getByRole("tabpanel", { name: "Chronology" })
  expect(await within(panel).findByRole("note")).toHaveTextContent("DEMO: agent executions")
  expect(within(panel).getByText("Execution path")).toBeInTheDocument()
  expect(within(panel).getByText("Waiting")).toBeVisible()
})

it("sorts unsorted monitor data globally without collapsing repeated invocations", () => {
  const shuffled = demoChronologyPipelines.map((pipeline) => ({ ...pipeline, agents: [...pipeline.agents].reverse() })).reverse()
  const rows = chronologyExecutions(shuffled)
  expect(rows.map((row) => row.agent.id)).toEqual([
    "demo-manager", "demo-modularity", "demo-security", "demo-responsibility-1", "demo-dependency",
    "demo-responsibility-2", "demo-testability", "demo-pending",
  ])
  expect(rows[5].parent?.id).toBe("demo-modularity")
  expect(rows[5].depth).toBe(2)
  expect(rows[5].path.map((agent) => agent.id)).toEqual(["demo-manager", "demo-modularity", "demo-responsibility-2"])
})

it("uses the same catalog name and identifier fallback as the execution monitor", () => {
  expect(auditAgentName({ agentType: "responsibility", name: "Configured investigator" })).toBe("Configured investigator")
  expect(auditAgentName({ agentType: "responsibility" })).toBe("responsibility")
})
