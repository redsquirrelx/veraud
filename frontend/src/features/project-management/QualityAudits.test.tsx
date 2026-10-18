import { afterEach, describe, expect, it, vi } from "vitest"
import { cleanup, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { QualityAudits } from "./QualityAudits.tsx"
import { AnalyzeMenu } from "./AnalyzeMenu.tsx"
import * as api from "./qualityAuditApi.ts"

vi.mock("./qualityAuditApi.ts", () => ({
  listQualityAudits: vi.fn(), startQualityAudit: vi.fn(), getQualityAuditReport: vi.fn(), downloadQualityAuditReport: vi.fn(),
}))

afterEach(() => { cleanup(); vi.resetAllMocks() })

function show() {
  render(<MemoryRouter><QualityAudits projectId={5} branch="main" commitHash={"a".repeat(40)} canRun /></MemoryRouter>)
}

describe("project quality audits", () => {
  it("offers quality audits separately from Project Architecture in the Analyze menu", async () => {
    const onAnalyze = vi.fn()
    const onAudit = vi.fn()
    render(<AnalyzeMenu canAnalyze analyzing={false} onAnalyze={onAnalyze} onAudit={onAudit} />)
    await userEvent.click(screen.getByRole("button", { name: "Analyze" }))
    expect(screen.getByText("Project architecture")).toBeInTheDocument()
    await userEvent.click(screen.getByText("Quality audit"))
    expect(onAudit).toHaveBeenCalledOnce()
    expect(onAnalyze).not.toHaveBeenCalled()
  })
  it("starts maintainability independently using the selected revision and attribute list", async () => {
    vi.mocked(api.listQualityAudits).mockResolvedValue([])
    vi.mocked(api.startQualityAudit).mockResolvedValue({ executionId: 8 })
    show()
    await screen.findByText("No hay auditorías registradas.")
    await userEvent.click(screen.getByRole("checkbox", { name: "Mantenibilidad" }))
    expect(screen.getByRole("button", { name: "Iniciar auditoría" })).toBeDisabled()
    await userEvent.click(screen.getByRole("checkbox", { name: "Mantenibilidad" }))
    await userEvent.click(screen.getByRole("button", { name: "Iniciar auditoría" }))
    await waitFor(() => expect(api.startQualityAudit).toHaveBeenCalledWith(5, "main", "a".repeat(40), ["maintainability"]))
  })

  it("shows the original partial report and permits downloading it", async () => {
    vi.mocked(api.listQualityAudits).mockResolvedValue([{
      id: 8, evaluationId: 4, branch: "main", commitHash: "a".repeat(40), attributes: ["maintainability"],
      executionStatus: "Completed", auditStatus: "partial", error: null,
      createdAt: "2026-10-17T10:00:00Z", finishedAt: "2026-10-17T10:05:00Z", reportAvailable: true,
    }])
    vi.mocked(api.getQualityAuditReport).mockResolvedValue({
      identification: { audit_id: "bdeb6efb73bd45fe9cb193f54710cf60" },
      executive_summary: { conclusion: "Evaluación parcial; la ausencia de hallazgos no demuestra conformidad." },
    })
    show()
    expect(await screen.findByText("Evaluación parcial")).toBeInTheDocument()
    expect(await screen.findByText("bdeb6efb73bd45fe9cb193f54710cf60")).toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: "Ver informe" }))
    expect(await screen.findByText(/la ausencia de hallazgos no demuestra conformidad/)).toBeInTheDocument()
    expect(screen.getAllByText("bdeb6efb73bd45fe9cb193f54710cf60").length).toBeGreaterThanOrEqual(2)
    await userEvent.click(screen.getByRole("button", { name: "Descargar informe Word" }))
    expect(api.downloadQualityAuditReport).toHaveBeenCalledWith(5, 8)
    expect(screen.getAllByText(/^\d+\. /)).toHaveLength(10)
  })

  it("starts security independently with the selected revision", async () => {
    vi.mocked(api.listQualityAudits).mockResolvedValue([])
    vi.mocked(api.startQualityAudit).mockResolvedValue({ executionId: 9 })
    show()
    await screen.findByText("No hay auditorías registradas.")
    await userEvent.click(screen.getByRole("checkbox", { name: "Seguridad" }))
    expect(screen.getByRole("checkbox", { name: "Mantenibilidad" })).not.toBeChecked()
    await userEvent.click(screen.getByRole("button", { name: "Iniciar auditoría" }))
    await waitFor(() => expect(api.startQualityAudit).toHaveBeenCalledWith(5, "main", "a".repeat(40), ["security"]))
  })

  it("shows the run id and its Blackboard link while the audit is still running", async () => {
    vi.mocked(api.listQualityAudits).mockResolvedValue([{
      id: 9, evaluationId: 4, runId: "c".repeat(32), branch: "main", commitHash: "a".repeat(40),
      attributes: ["maintainability"], executionStatus: "Running", auditStatus: null, error: null,
      createdAt: "2026-10-17T10:00:00Z", finishedAt: null, reportAvailable: false,
    }])
    show()
    expect(await screen.findByText("c".repeat(32))).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Ver Blackboard" }).getAttribute("href"))
      .toBe(`http://localhost:7502/blackboard?run_id=${"c".repeat(32)}`)
    // A running audit has no report yet, so no extra request is made for it.
    expect(api.getQualityAuditReport).not.toHaveBeenCalled()
  })

  it("waits for the run id while the audit is starting", async () => {
    vi.mocked(api.listQualityAudits).mockResolvedValue([{
      id: 10, evaluationId: 4, runId: null, branch: "main", commitHash: "a".repeat(40),
      attributes: ["maintainability"], executionStatus: "Running", auditStatus: null, error: null,
      createdAt: "2026-10-17T10:00:00Z", finishedAt: null, reportAvailable: false,
    }])
    show()
    expect(await screen.findByText("Inicializando…")).toBeInTheDocument()
  })
})
