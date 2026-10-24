import { afterEach, describe, expect, it, vi } from "vitest"
import { cleanup, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { changeLanguage } from "../../shared/i18n/index.ts"
import { ApiError } from "../../infrastructure/http-client/httpClient.ts"
import { QualityAudits } from "./QualityAudits.tsx"
import { AnalyzeMenu } from "./AnalyzeMenu.tsx"
import * as api from "./qualityAuditApi.ts"

vi.mock("./qualityAuditApi.ts", () => ({
  listQualityAudits: vi.fn(), startQualityAudit: vi.fn(), getQualityAuditReport: vi.fn(), downloadQualityAuditReport: vi.fn(),
}))

afterEach(async () => { cleanup(); vi.resetAllMocks(); await changeLanguage("en") })

function show() {
  render(<MemoryRouter><QualityAudits projectId={5} branch="main" commitHash={"a".repeat(40)} canRun /></MemoryRouter>)
}

describe("project quality audits", () => {
  it.each([
    ["client", "Could not load audits", "No se pudieron cargar las auditorías"],
    ["server", "Backend diagnostic", "Backend diagnostic"],
  ] as const)("relocalizes client errors but preserves server messages (%s)", async (source, english, spanish) => {
    vi.mocked(api.listQualityAudits).mockRejectedValue(new ApiError(503, "Backend diagnostic", source))
    show()
    expect(await screen.findByRole("alert")).toHaveTextContent(english)
    const calls = vi.mocked(api.listQualityAudits).mock.calls.length

    await changeLanguage("es")

    expect(screen.getByRole("alert")).toHaveTextContent(spanish)
    expect(api.listQualityAudits).toHaveBeenCalledTimes(calls)
  })

  it.each([false, true])("starts functional adequacy with explicit requirements (joint: %s)", async (joint) => {
    vi.mocked(api.listQualityAudits).mockResolvedValue([])
    vi.mocked(api.startQualityAudit).mockResolvedValue({ executionId: 12 })
    show()
    await screen.findByText("No audits recorded.")
    if (!joint) {
      await userEvent.click(screen.getByRole("checkbox", { name: /^Maintainability/ }))
      await userEvent.click(screen.getByRole("checkbox", { name: /^Security/ }))
    }
    await userEvent.click(screen.getByRole("checkbox", { name: "Functional adequacy" }))
    expect(screen.getByRole("button", { name: "Start audit" })).toBeDisabled()
    await userEvent.type(screen.getByRole("textbox", { name: "Functional requirements" }), "Allow sign in.\nValidate the password.")
    await userEvent.click(screen.getByRole("button", { name: "Start audit" }))
    await waitFor(() => expect(api.startQualityAudit).toHaveBeenCalledWith(5, "main", "a".repeat(40),
      [...(joint ? ["maintainability", "security"] : []), "functional_adequacy"], {
        functional_requirements: [
          { requirement_id: "REQ-001", description: "Allow sign in." },
          { requirement_id: "REQ-002", description: "Validate the password." },
        ],
      }))
  })
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
    await screen.findByText("No audits recorded.")
    await userEvent.click(screen.getByRole("checkbox", { name: /^Security/ }))
    await userEvent.click(screen.getByRole("checkbox", { name: /^Maintainability/ }))
    expect(screen.getByRole("button", { name: "Start audit" })).toBeDisabled()
    await userEvent.click(screen.getByRole("checkbox", { name: /^Maintainability/ }))
    await userEvent.click(screen.getByRole("button", { name: "Start audit" }))
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
    expect(await screen.findByText("Partial evaluation")).toBeInTheDocument()
    expect(await screen.findByText("bdeb6efb73bd45fe9cb193f54710cf60")).toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: "View report" }))
    expect(await screen.findByText(/la ausencia de hallazgos no demuestra conformidad/)).toBeInTheDocument()
    expect(screen.getAllByText("bdeb6efb73bd45fe9cb193f54710cf60").length).toBeGreaterThanOrEqual(2)
    await userEvent.click(screen.getByRole("button", { name: "Download Word report" }))
    expect(api.downloadQualityAuditReport).toHaveBeenCalledWith(5, 8)
    expect(screen.getAllByText(/^\d+\. /)).toHaveLength(10)
  })

  it("starts security independently with the selected revision", async () => {
    vi.mocked(api.listQualityAudits).mockResolvedValue([])
    vi.mocked(api.startQualityAudit).mockResolvedValue({ executionId: 9 })
    show()
    await screen.findByText("No audits recorded.")
    await userEvent.click(screen.getByRole("checkbox", { name: /^Maintainability/ }))
    expect(screen.getByRole("checkbox", { name: /^Maintainability/ })).not.toBeChecked()
    await userEvent.click(screen.getByRole("button", { name: "Start audit" }))
    await waitFor(() => expect(api.startQualityAudit).toHaveBeenCalledWith(5, "main", "a".repeat(40), ["security"]))
  })

  it("selects both attributes by default and starts them as one audit request", async () => {
    vi.mocked(api.listQualityAudits).mockResolvedValue([])
    vi.mocked(api.startQualityAudit).mockResolvedValue({ executionId: 10 })
    show()
    await screen.findByText("No audits recorded.")
    expect(screen.getByRole("checkbox", { name: /^Security/ })).toBeChecked()
    expect(screen.getByRole("checkbox", { name: /^Maintainability/ })).toBeChecked()
    await userEvent.click(screen.getByRole("button", { name: "Start audit" }))
    await waitFor(() => expect(api.startQualityAudit).toHaveBeenCalledWith(5, "main", "a".repeat(40), ["maintainability", "security"]))
    expect(api.startQualityAudit).toHaveBeenCalledOnce()
  })

  it("shows the run id and its Blackboard link while the audit is still running", async () => {
    vi.mocked(api.listQualityAudits).mockResolvedValue([{
      id: 9, evaluationId: 4, runId: "c".repeat(32), branch: "main", commitHash: "a".repeat(40),
      attributes: ["maintainability"], executionStatus: "Running", auditStatus: null, error: null,
      createdAt: "2026-10-17T10:00:00Z", finishedAt: null, reportAvailable: false,
    }])
    show()
    expect(await screen.findByText("c".repeat(32))).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "View Blackboard" }).getAttribute("href"))
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
    expect(await screen.findByText("Initializing…")).toBeInTheDocument()
  })

  it("translates an open report without changing selections, requirements, or API activity", async () => {
    vi.mocked(api.listQualityAudits).mockResolvedValue([{
      id: 8, evaluationId: 4, branch: "main", commitHash: "a".repeat(40), attributes: ["maintainability"],
      executionStatus: "Completed", auditStatus: "partial", error: null,
      createdAt: "2026-10-17T10:00:00Z", finishedAt: "2026-10-17T10:05:00Z", reportAvailable: true,
    }])
    vi.mocked(api.getQualityAuditReport).mockResolvedValue({
      identification: { audit_id: "report-run-id" },
      executive_summary: {
        conclusion: "Original report conclusion.",
        summary: { text: "Original report content", source_refs: ["source-1", "source-2"] },
      },
    })
    show()
    expect(await screen.findByText("Partial evaluation")).toBeInTheDocument()
    await userEvent.click(screen.getByRole("checkbox", { name: "Functional adequacy" }))
    const requirements = screen.getByRole("textbox", { name: "Functional requirements" })
    await userEvent.type(requirements, "Requirement one.\nRequirement two.")
    await userEvent.click(screen.getByRole("button", { name: "View report" }))
    expect(await screen.findByRole("heading", { name: "Audit report · #8" })).toBeInTheDocument()
    expect(screen.getByText("Original report conclusion.")).toBeInTheDocument()
    expect(screen.getByText("Original report content")).toBeInTheDocument()
    expect(screen.getByText("Source references (2)")).toBeInTheDocument()
    await waitFor(() => expect(api.getQualityAuditReport).toHaveBeenCalledTimes(2))
    const requestCounts = [vi.mocked(api.listQualityAudits).mock.calls.length, vi.mocked(api.getQualityAuditReport).mock.calls.length]

    await changeLanguage("es")

    expect(screen.getByRole("heading", { name: "Auditoría de calidad" })).toBeInTheDocument()
    expect(screen.getByRole("heading", { name: "Informe de auditoría · #8" })).toBeInTheDocument()
    expect(screen.getByRole("heading", { name: "Auditorías del proyecto" })).toBeInTheDocument()
    expect(screen.getByRole("checkbox", { name: "Adecuación funcional" })).toBeChecked()
    expect(screen.getByRole("textbox", { name: "Requisitos funcionales" })).toHaveValue("Requirement one.\nRequirement two.")
    expect(screen.getByText("Original report conclusion.")).toBeInTheDocument()
    expect(screen.getByText("Original report content")).toBeInTheDocument()
    expect(screen.getByText("Referencias de origen (2)")).toBeInTheDocument()
    expect(screen.getAllByText("report-run-id").length).toBeGreaterThanOrEqual(2)
    expect(api.startQualityAudit).not.toHaveBeenCalled()
    expect([vi.mocked(api.listQualityAudits).mock.calls.length, vi.mocked(api.getQualityAuditReport).mock.calls.length]).toEqual(requestCounts)
  })
})
