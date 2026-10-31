import { beforeEach, expect, it, vi } from "vitest"
import { act, render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { getAgentExecution, type AgentExecution, type AgentInvocation } from "../../infrastructure/http-client/httpClient.ts"
import { changeLanguage } from "../../shared/i18n/index.ts"
import { QualityAuditResults } from "./QualityAuditResults.tsx"
import { AuditIncidentsTab } from "./AuditIncidentsTab.tsx"
import { getQualityAudit, type QualityAuditSummary } from "./qualityAuditApi.ts"

vi.mock("../../infrastructure/http-client/httpClient.ts", async (original) => ({
  ...await original<typeof import("../../infrastructure/http-client/httpClient.ts")>(), getAgentExecution: vi.fn(),
}))
vi.mock("./qualityAuditApi.ts", async (original) => ({
  ...await original<typeof import("./qualityAuditApi.ts")>(), getQualityAudit: vi.fn(),
}))

const audit: QualityAuditSummary = { id: 8, evaluationId: 4, branch: "main", commitHash: "a".repeat(40), attributes: ["security"],
  executionStatus: "Completed", auditStatus: "failed", error: null, createdAt: "2026-10-30T10:00:00Z", finishedAt: "2026-10-30T13:00:00Z", reportAvailable: false }
const execution: AgentExecution = { id: 8, evaluationId: 4, agentType: "security", status: "Completed", result: null,
  error: null, inputTokens: 5, outputTokens: 2, createdAt: audit.createdAt, startedAt: null, finishedAt: audit.finishedAt }
const later = { agentId: "late-agent", invocationId: "late", occurredAt: "2026-10-30T12:00:00Z", code: "execution_timeout",
  exceptionType: "TimeoutError", message: "Late child incident" }
const earlier = { ...later, agentId: "early-agent", invocationId: "early", occurredAt: "2026-10-30T11:00:00Z", message: "Early child incident" }
function receipt(id: string): AgentInvocation {
  return { invocation_id: id, parent_invocation_id: null, agent_id: `${id}-agent`, run_id: "audit", status: "failed",
    started_at: audit.createdAt, finished_at: audit.finishedAt, error: null, input_tokens: 3, output_tokens: 1 }
}

beforeEach(async () => {
  vi.resetAllMocks()
  await changeLanguage("es")
  vi.mocked(getQualityAudit).mockResolvedValue(audit)
  vi.mocked(getAgentExecution).mockResolvedValue(execution)
})

function show(tab = "incidents") {
  return render(<MemoryRouter initialEntries={[`/projects/5/audits/8?tab=${tab}`]}>
    <QualityAuditResults projectId={5} auditId={8} projectName="acme/demo" />
  </MemoryRouter>)
}

it("adds Incidents after Evidence, deduplicates inherited causes, sorts chronologically and opens individual details", async () => {
  vi.mocked(getAgentExecution).mockResolvedValue({ ...execution, errorDetail: { ...later, occurredAt: "2026-10-30T12:00:00.000Z" }, invocations: [
    { ...receipt("late"), error_detail: later }, { ...receipt("early"), error_detail: earlier },
    { ...receipt("legacy"), error: "Legacy error" },
  ] })
  show()
  expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual(["Resumen General", "Hallazgos", "Evidencias", "Incidentes"])
  const panel = screen.getByRole("tabpanel", { name: "Incidentes" })
  const articles = await within(panel).findAllByRole("article")
  expect(articles).toHaveLength(3)
  expect(articles.map((article) => article.querySelector("strong")?.textContent)).toEqual(["early-agent", "late-agent", "legacy-agent"])
  expect(articles[2].querySelector("time")).toBeNull()
  expect(within(panel).queryByText(/historial exhaustivo/)).not.toBeInTheDocument()
  expect(within(panel).getAllByText("Fecha")).toHaveLength(2)
  expect(within(articles[2]).getByText("Fecha no registrada")).toBeVisible()
  expect(within(panel).queryByText("#early")).not.toBeInTheDocument()
  expect(within(panel).queryByText("No registrado")).not.toBeInTheDocument()
  await userEvent.click(within(articles[0]).getByRole("button", { name: /Ver error/ }))
  expect(screen.getByRole("dialog")).toHaveTextContent("Early child incident")
  expect(screen.getByRole("dialog").querySelector("time")).toHaveAttribute("datetime", earlier.occurredAt)
  await userEvent.keyboard("{Escape}")
  await userEvent.click(within(articles[2]).getByRole("button", { name: /Ver error/ }))
  expect(screen.getByRole("dialog")).toHaveTextContent("Legacy error")
  expect(screen.getByRole("dialog").querySelector("time")).toBeNull()
})

it("loads only on opening, caches tab revisits and reloads on Refresh", async () => {
  show("general")
  await screen.findByRole("button", { name: "Actualizar" })
  expect(getAgentExecution).not.toHaveBeenCalled()
  await userEvent.click(screen.getByRole("tab", { name: "Incidentes" }))
  expect(await screen.findByText("No hay incidentes registrados para esta auditoría.")).toBeVisible()
  expect(getAgentExecution).toHaveBeenCalledExactlyOnceWith(8, true)
  await userEvent.click(screen.getByRole("tab", { name: "Resumen General" }))
  await userEvent.click(screen.getByRole("tab", { name: "Incidentes" }))
  expect(getAgentExecution).toHaveBeenCalledTimes(1)
  await userEvent.click(screen.getByRole("button", { name: "Actualizar" }))
  await screen.findByText("No hay incidentes registrados para esta auditoría.")
  expect(getAgentExecution).toHaveBeenCalledTimes(2)
})

it("offers retry after a safe loading error and works for unfinished audits without a report", async () => {
  vi.mocked(getQualityAudit).mockResolvedValue({ ...audit, executionStatus: "Running", finishedAt: null })
  vi.mocked(getAgentExecution).mockRejectedValueOnce(new Error("private transport text"))
    .mockResolvedValue({ ...execution, status: "Running", errorDetail: earlier, finishedAt: null })
  show()
  expect(await screen.findByRole("alert")).toHaveTextContent("No se pudieron cargar los incidentes")
  expect(screen.queryByText("private transport text")).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole("button", { name: "Reintentar" }))
  expect(await screen.findByText(/La auditoría sigue activa/)).toBeVisible()
  expect(screen.getByRole("article")).toHaveTextContent("early-agent")
})

it("does not manufacture incidents from failed states or cancellation without a recorded error", async () => {
  vi.mocked(getAgentExecution).mockResolvedValue({ ...execution, status: "Failed", invocations: [
    receipt("failed-without-message"), { ...receipt("cancelled"), status: "cancelled", error: null },
  ] })
  show()
  expect(await screen.findByText("No hay incidentes registrados para esta auditoría.")).toBeVisible()
  expect(screen.queryByRole("article")).not.toBeInTheDocument()
})

it("shows recorded root and child errors even when cancellation is confirmed", async () => {
  vi.mocked(getAgentExecution).mockResolvedValue({ ...execution, interruptionReason: "cancelled",
    error: "Cancellation cleanup failed", invocations: [
      { ...receipt("cancelled"), status: "cancelled", error: "CancelledError" },
    ] })
  show()
  const articles = await screen.findAllByRole("article")
  expect(articles).toHaveLength(2)
  expect(screen.queryByText("Cancellation cleanup failed")).not.toBeInTheDocument()
  await userEvent.click(within(articles.find((article) => article.textContent?.includes("cancelled-agent"))!).getByRole("button", { name: /Ver error/ }))
  expect(screen.getByRole("dialog")).toHaveTextContent("CancelledError")
  expect(screen.getByRole("dialog").querySelector("time")).toBeNull()
})

it("rejects a mismatched execution and ignores responses for a previously selected audit", async () => {
  let resolve!: (execution: AgentExecution) => void
  vi.mocked(getAgentExecution).mockReturnValueOnce(new Promise((finish) => { resolve = finish }))
    .mockResolvedValue({ ...execution, id: 9, errorDetail: later })
  const { rerender } = render(<AuditIncidentsTab projectId={5} audit={audit} active revision={0} />)
  rerender(<AuditIncidentsTab projectId={5} audit={{ ...audit, id: 9 }} active revision={0} />)
  expect(await screen.findByRole("article")).toHaveTextContent("late-agent")
  await act(async () => { resolve({ ...execution, errorDetail: earlier }) })
  expect(screen.queryByText("early-agent")).not.toBeInTheDocument()
  vi.mocked(getAgentExecution).mockResolvedValue({ ...execution, evaluationId: 999 })
  rerender(<AuditIncidentsTab projectId={5} audit={audit} active revision={1} />)
  expect(await screen.findByRole("alert")).toBeVisible()
})

it("synchronizes top and bottom pagination with 5, 10 and 20 items without refetching", async () => {
  await changeLanguage("en")
  vi.mocked(getAgentExecution).mockResolvedValue({ ...execution, invocations: Array.from({ length: 12 }, (_, index) => {
    const id = String(index).padStart(2, "0")
    return { ...receipt(id), error: `Incident ${id}` }
  }) })
  show()
  await screen.findAllByRole("article")
  const controls = screen.getAllByRole("combobox", { name: "Incidents per page" })
  expect(controls).toHaveLength(2)
  controls.forEach((control) => {
    expect(control).toHaveValue("5")
    expect(within(control).getAllByRole("option").map((option) => option.textContent)).toEqual(["5", "10", "20"])
  })
  expect(screen.getAllByRole("article")).toHaveLength(5)
  screen.getAllByRole("button", { name: "Previous page" }).forEach((button) => expect(button).toBeDisabled())
  await userEvent.click(screen.getAllByRole("button", { name: "Next page" })[0])
  expect(screen.getAllByText("Page 2 of 3")).toHaveLength(2)
  expect(screen.getAllByRole("article")[0]).toHaveTextContent("05-agent")
  await userEvent.click(screen.getAllByRole("button", { name: "Next page" })[1])
  expect(screen.getAllByRole("article")).toHaveLength(2)
  screen.getAllByRole("button", { name: "Next page" }).forEach((button) => expect(button).toBeDisabled())
  await userEvent.selectOptions(controls[1], "10")
  expect(screen.getAllByRole("article")).toHaveLength(10)
  expect(screen.getAllByText("Page 1 of 2")).toHaveLength(2)
  controls.forEach((control) => expect(control).toHaveValue("10"))
  await userEvent.selectOptions(controls[0], "20")
  expect(screen.getAllByRole("article")).toHaveLength(12)
  controls.forEach((control) => expect(control).toHaveValue("20"))
  expect(getAgentExecution).toHaveBeenCalledTimes(1)
})
