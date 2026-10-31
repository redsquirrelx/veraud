import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { changeLanguage } from "../../shared/i18n/index.ts"
import { formatDateTime } from "../../shared/i18n/format.ts"
import { ApiError } from "../../infrastructure/http-client/httpClient.ts"
import { QualityAuditResults } from "./QualityAuditResults.tsx"
import * as api from "./qualityAuditApi.ts"

vi.mock("./qualityAuditApi.ts", () => ({ getQualityAudit: vi.fn(), getQualityAuditReportSection: vi.fn(), listQualityAudits: vi.fn(), getQualityAuditReport: vi.fn(), downloadQualityAuditReport: vi.fn(), getQualityAuditConfiguration: vi.fn() }))
const audit: api.QualityAuditSummary = { id: 8, evaluationId: 4, branch: "original-branch", commitHash: "b".repeat(40), attributes: ["maintainability"],
  executionStatus: "Completed", auditStatus: "partial", runId: "original-run", error: null, createdAt: "2026-10-17T10:00:00Z", startedAt: "2026-10-17T10:05:00Z", finishedAt: "2026-10-17T11:00:00Z", reportAvailable: true }
beforeEach(() => {
  vi.mocked(api.getQualityAudit).mockResolvedValue(audit)
  vi.mocked(api.getQualityAuditReportSection).mockImplementation(async (_project, _id, section) => ({ section, data: section === "executive_summary" ? {
    conclusion: "Original report conclusion.", summary: { text: "Original report content", source_refs: ["source-1", "source-2"] },
  } : null }))
})
afterEach(async () => { cleanup(); vi.resetAllMocks(); await changeLanguage("en") })
function show() { render(<MemoryRouter><QualityAuditResults projectId={5} auditId={8} projectName="acme/Shop" /></MemoryRouter>) }

describe("dedicated audit results", () => {
  it("shows the explicit empty result while retaining metadata and the zero-count summary", async () => {
    await changeLanguage("es")
    vi.mocked(api.getQualityAudit).mockResolvedValue({ ...audit, auditStatus: "completed" })
    vi.mocked(api.getQualityAuditReportSection).mockImplementation(async (_project, _audit, section) => ({ section,
      data: section === "executive_summary" ? { findings: { total: 0, by_attribute: {}, by_severity: {} }, conclusion: "Sin hallazgos registrados." }
        : { findings: [] },
    }))
    show()
    expect(await screen.findByText("No se identificaron hallazgos en esta auditoría")).toBeVisible()
    expect(screen.getByRole("region", { name: "Resumen de hallazgos" })).toBeVisible()
    expect(within(screen.getByRole("region", { name: "Resumen de hallazgos" })).getAllByText("0")).toHaveLength(9)
    expect(within(screen.getByLabelText("Datos de la auditoría")).getByText("original-branch")).toBeVisible()
    expect(screen.getByRole("heading", { name: "Informe de auditoría · #8" })).toBeVisible()
    await userEvent.click(screen.getByRole("tab", { name: "Hallazgos" }))
    expect(await within(screen.getByRole("tabpanel", { name: "Hallazgos" })).findByText("No se identificaron hallazgos en esta auditoría")).toBeVisible()
    expect(within(screen.getByLabelText("Datos de la auditoría")).getByText("b".repeat(40))).toBeVisible()
    expect(api.getQualityAuditReport).not.toHaveBeenCalled()
  })

  it.each([["Waiting", false], ["Running", true]] as const)("does not present unfinished %s audit artifacts as final results", async (executionStatus, reportAvailable) => {
    vi.mocked(api.getQualityAudit).mockResolvedValue({ ...audit, executionStatus, reportAvailable, auditStatus: "completed", finishedAt: null })
    show()
    expect(await screen.findByText("The audit has not finished yet")).toBeVisible()
    const header = within(screen.getByLabelText("Audit details"))
    expect(header.queryByText("Final status")).not.toBeInTheDocument()
    expect(header.getByText("original-branch")).toBeVisible()
    expect(screen.queryByRole("heading", { name: "Audit report · #8" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Download Word report" })).not.toBeInTheDocument()
    expect(screen.queryByText("No findings were identified in this audit")).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole("tab", { name: "Findings" }))
    expect(screen.getByText("The audit has not finished yet")).toBeVisible()
    expect(api.getQualityAuditReportSection).not.toHaveBeenCalled()
    await changeLanguage("es")
    expect(screen.getByText("La auditoría aún no ha finalizado")).toBeVisible()
    expect(within(screen.getByLabelText("Datos de la auditoría")).queryByText("Estado final")).not.toBeInTheDocument()
  })

  it("reveals results after refreshing an audit that has finished, keeping the selected tab", async () => {
    vi.mocked(api.getQualityAudit).mockResolvedValueOnce({ ...audit, executionStatus: "Running", finishedAt: null }).mockResolvedValue(audit)
    vi.mocked(api.getQualityAuditReportSection).mockImplementation(async (_project, _audit, section) => ({ section,
      data: section === "quality_results" ? { findings: [] } : { findings: { total: 0 } },
    }))
    show()
    await screen.findByText("The audit has not finished yet")
    const user = userEvent.setup()
    await user.click(screen.getByRole("tab", { name: "Findings" }))
    expect(api.getQualityAuditReportSection).not.toHaveBeenCalled()
    await user.click(screen.getByRole("button", { name: "Refresh" }))
    expect(await within(screen.getByRole("tabpanel", { name: "Findings" })).findByText("No findings were identified in this audit")).toBeVisible()
    expect(screen.queryByText("The audit has not finished yet")).not.toBeInTheDocument()
    expect(screen.getByRole("tab", { name: "Findings" })).toHaveAttribute("aria-selected", "true")
    expect(api.getQualityAudit).toHaveBeenCalledTimes(2)
  })

  it("retries metadata errors from the findings tab without navigating away", async () => {
    await changeLanguage("es")
    vi.mocked(api.getQualityAudit).mockRejectedValueOnce(new Error("offline"))
      .mockRejectedValueOnce(new ApiError(503, "Servicio de resultados no disponible", "server")).mockResolvedValue(audit)
    vi.mocked(api.getQualityAuditReportSection).mockImplementation(async (_project, _audit, section) => ({ section,
      data: section === "quality_results" ? { findings: [] } : {},
    }))
    show()
    await screen.findByRole("alert")
    const user = userEvent.setup()
    await user.click(screen.getByRole("tab", { name: "Hallazgos" }))
    await user.click(screen.getByRole("button", { name: "Reintentar" }))
    expect(await screen.findByRole("alert")).toHaveTextContent("Servicio de resultados no disponible")
    await user.click(screen.getByRole("button", { name: "Reintentar" }))
    expect(await within(screen.getByRole("tabpanel", { name: "Hallazgos" })).findByText("No se identificaron hallazgos en esta auditoría")).toBeVisible()
    await waitFor(() => expect(api.getQualityAudit).toHaveBeenCalledTimes(3))
    expect(screen.getByRole("tab", { name: "Hallazgos" })).toHaveAttribute("aria-selected", "true")
    expect(screen.queryByRole("alert")).not.toBeInTheDocument()
    expect(within(screen.getByLabelText("Datos de la auditoría")).getByText("original-branch")).toBeVisible()
    expect(api.getQualityAuditReport).not.toHaveBeenCalled()
  })

  it("paginates cached findings by severity without downloading another report or section", async () => {
    vi.mocked(api.getQualityAuditReportSection).mockImplementation(async (_project, _audit, section) => ({ section,
      data: section === "quality_results" ? { findings: [
        ...Array.from({ length: 11 }, (_, index) => ({ id: `L${index}`, title: `Low ${index}`, severity: "low", quality_attribute: "maintainability" })),
        { id: "C1", title: "Critical finding", severity: "critical", quality_attribute: "security" },
      ] } : {},
    }))
    show()
    await screen.findByRole("region", { name: "Findings summary" })
    const user = userEvent.setup()
    await user.click(screen.getByRole("tab", { name: "Findings" }))
    const panel = within(screen.getByRole("tabpanel", { name: "Findings" }))
    await panel.findByRole("heading", { name: "Critical finding" })
    expect(panel.getAllByRole("heading", { level: 5 })).toHaveLength(10)
    expect(panel.getAllByRole("heading", { level: 5 })[0]).toHaveTextContent("Critical finding")
    await user.click(panel.getByRole("button", { name: "Next page" }))
    expect(panel.getAllByRole("heading", { level: 5 }).map((item) => item.textContent)).toEqual(["Low 9", "Low 10"])
    await user.click(panel.getByRole("button", { name: "Previous page" }))
    expect(panel.getAllByRole("heading", { level: 5 })).toHaveLength(10)
    await user.selectOptions(panel.getByRole("combobox", { name: "Findings per page" }), "20")
    expect(panel.getAllByRole("heading", { level: 5 })).toHaveLength(12)
    await user.selectOptions(panel.getByRole("combobox", { name: "Severity order" }), "ascending")
    expect(panel.getAllByRole("heading", { level: 5 }).at(-1)).toHaveTextContent("Critical finding")
    expect(api.getQualityAudit).toHaveBeenCalledOnce()
    expect(api.getQualityAuditReportSection).toHaveBeenCalledTimes(2)
    expect(api.getQualityAuditReport).not.toHaveBeenCalled()
  })

  it("defaults to General Overview and shows findings directly in their own tab, sharing the section cache", async () => {
    vi.mocked(api.getQualityAuditReportSection).mockImplementation(async (_project, _audit, section) => ({ section,
      data: section === "quality_results" ? { findings: [{
        id: "M1", title: "Grouped finding", description: "Brief description", quality_attribute: "maintainability",
        subcharacteristic: "testability", verification_status: "inconclusive",
        severity: "medium", components: ["service"], source_refs: [{ record_type: "finding", record_id: "M1", agent_id: "detector" }],
      }] } : {},
    }))
    const user = userEvent.setup()
    show()
    await screen.findByRole("region", { name: "Findings summary" })
    expect(screen.getByRole("tab", { name: "General Overview" })).toHaveAttribute("aria-selected", "true")
    expect(screen.getAllByRole("tab")).toHaveLength(4)
    expect(api.getQualityAuditReportSection).toHaveBeenCalledOnce()
    await user.click(screen.getByRole("tab", { name: "Findings" }))
    const panel = within(screen.getByRole("tabpanel", { name: "Findings" }))
    expect(await panel.findByRole("heading", { name: "Grouped finding" })).toBeVisible()
    expect(panel.getByText("Severity: Medium")).toBeInTheDocument()
    expect(panel.getByText("Attribute: Maintainability")).toBeInTheDocument()
    expect(panel.getByText("Subcharacteristic: Testability")).toBeInTheDocument()
    expect(panel.getByText("Validation: Inconclusive")).toBeInTheDocument()
    expect(panel.queryByText("service")).not.toBeInTheDocument()
    await user.click(panel.getByRole("button", { name: "Grouped finding" }))
    const drawer = within(await screen.findByRole("dialog", { name: "Grouped finding" }))
    expect(drawer.getByText("M1")).toBeInTheDocument()
    expect(drawer.getByText("service")).toBeInTheDocument()
    expect(drawer.getByText("detector")).toBeInTheDocument()
    expect(api.getQualityAuditReportSection).toHaveBeenCalledTimes(2)
    await user.keyboard("{Escape}")
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
    expect(screen.queryByRole("heading", { name: "Audit report · #8" })).not.toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Back to audits" })).toBeVisible()
    await user.click(screen.getByRole("tab", { name: "General Overview" }))
    expect(screen.getByRole("heading", { name: "Audit report · #8" })).toBeVisible()
    await user.click(screen.getByText("6. Quality results"))
    expect(await screen.findByRole("heading", { name: "Grouped finding" })).toBeVisible()
    await user.click(screen.getByRole("tab", { name: "Findings" }))
    expect(within(screen.getByRole("tabpanel", { name: "Findings" })).getByRole("heading", { name: "Grouped finding" })).toBeVisible()
    expect(api.getQualityAuditReportSection).toHaveBeenCalledTimes(2)
    expect(api.getQualityAuditReport).not.toHaveBeenCalled()
    await changeLanguage("es")
    expect(screen.getByRole("tab", { name: "Resumen General" })).toBeInTheDocument()
    expect(screen.getByRole("tab", { name: "Hallazgos" })).toHaveAttribute("aria-selected", "true")
  })

  it("supports keyboard tab navigation and retries findings independently", async () => {
    let attempts = 0
    vi.mocked(api.getQualityAuditReportSection).mockImplementation(async (_project, _audit, section) => {
      if (section === "quality_results" && attempts++ === 0) throw new Error("offline")
      return { section, data: section === "quality_results" ? { findings: [] } : {} }
    })
    const user = userEvent.setup()
    show()
    await screen.findByRole("region", { name: "Findings summary" })
    screen.getByRole("tab", { name: "General Overview" }).focus()
    await user.keyboard("{ArrowRight}")
    expect(screen.getByRole("tab", { name: "Findings" })).toHaveFocus()
    const panel = within(screen.getByRole("tabpanel", { name: "Findings" }))
    expect(await panel.findByRole("alert")).toHaveTextContent("Could not load this section.")
    await user.click(panel.getByRole("button", { name: "Retry" }))
    expect(await panel.findByText("No findings were identified in this audit")).toBeVisible()
    expect(api.getQualityAudit).toHaveBeenCalledOnce()
    expect(api.getQualityAuditReportSection).toHaveBeenCalledTimes(3)
    screen.getByRole("tab", { name: "Findings" }).focus()
    await user.keyboard("{Home}")
    expect(screen.getByRole("tab", { name: "General Overview" })).toHaveFocus()
    expect(screen.getByRole("tabpanel", { name: "General Overview" })).toBeVisible()
  })

  it("does not request findings when the audit has no report", async () => {
    vi.mocked(api.getQualityAudit).mockResolvedValue({ ...audit, reportAvailable: false })
    show()
    await screen.findByText("This audit did not produce a report.")
    await userEvent.click(screen.getByRole("tab", { name: "Findings" }))
    expect(within(screen.getByRole("tabpanel", { name: "Findings" })).getByText("This audit did not produce a report.")).toBeVisible()
    expect(api.getQualityAuditReportSection).not.toHaveBeenCalled()
  })

  it("loads grouped findings only when quality results are expanded and keeps the original details available", async () => {
    vi.mocked(api.getQualityAuditReportSection).mockImplementation(async (_project, _audit, section) => ({ section,
      data: section === "quality_results" ? { attributes: [], findings: [{
        id: "SEC-1", title: "Unvalidated input", description: "Input reaches the query without validation.",
        quality_attribute: "security", severity: "high", components: ["query-service"],
        source_refs: [{ record_type: "finding", record_id: "SEC-1", agent_id: "input-validator" }],
        justification: "Original justification", verification_status: "inconclusive",
      }] } : {},
    }))
    show()
    await screen.findByRole("region", { name: "Findings summary" })
    expect(screen.queryByText("Unvalidated input")).not.toBeInTheDocument()
    expect(api.getQualityAuditReportSection).toHaveBeenCalledOnce()
    await userEvent.click(screen.getByText("6. Quality results"))
    const list = within(await screen.findByRole("region", { name: "Findings by quality attribute" }))
    expect(list.getByRole("heading", { name: "Security (1)" })).toBeInTheDocument()
    expect(list.getByText("Input reaches the query without validation.")).toBeInTheDocument()
    expect(list.getByText("Severity: High")).toBeInTheDocument()
    expect(list.queryByText("query-service")).not.toBeInTheDocument()
    expect(list.queryByText("input-validator")).not.toBeInTheDocument()
    expect(list.queryByText("Original justification")).not.toBeInTheDocument()
    await userEvent.click(list.getByRole("button", { name: "Unvalidated input" }))
    const drawer = within(await screen.findByRole("dialog", { name: "Unvalidated input" }))
    expect(drawer.getByText("query-service")).toBeInTheDocument()
    expect(drawer.getByText("input-validator")).toBeInTheDocument()
    await userEvent.click(drawer.getByText("View original details"))
    expect(await drawer.findByText("Original justification")).toBeInTheDocument()
    expect(drawer.getByText("inconclusive")).toBeInTheDocument()
    expect(api.getQualityAuditReportSection).toHaveBeenCalledTimes(2)
    expect(api.getQualityAuditReport).not.toHaveBeenCalled()
  })

  it("summarizes original findings by attribute and severity without fetching another section", async () => {
    vi.mocked(api.getQualityAuditReportSection).mockResolvedValue({ section: "executive_summary", data: {
      findings: { total: 15, by_attribute: { maintainability: 6, security: 5, performance_efficiency: 4 },
        by_severity: { critical: 1, high: 2, medium: 3, low: 4, info: 5 } },
    } })
    show()
    const summary = within(await screen.findByRole("region", { name: "Findings summary" }))
    expect(screen.getByRole("region", { name: "Findings summary" }).compareDocumentPosition(
      screen.getByRole("heading", { name: "Audit report · #8" }),
    ) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    const expectCount = (label: string, value: string) => {
      expect(summary.getByText(label).closest("div")).toHaveTextContent(new RegExp(`${label}\\s*${value}$`))
    }
    expectCount("Total findings detected", "15")
    expectCount("Maintainability", "6")
    expectCount("Security", "5")
    expectCount("Performance", "4")
    expectCount("Critical", "1")
    expectCount("High", "2")
    expectCount("Medium", "3")
    expectCount("Low", "4")
    expectCount("Informational", "5")
    await userEvent.click(screen.getByText("2. Executive summary"))
    expect(screen.getByRole("region", { name: "Findings summary" })).toBeVisible()
    expect(api.getQualityAuditReportSection).toHaveBeenCalledOnce()
    expect(api.getQualityAuditReport).not.toHaveBeenCalled()
    await changeLanguage("es")
    const translated = within(screen.getByRole("region", { name: "Resumen de hallazgos" }))
    for (const label of ["Mantenibilidad", "Seguridad", "Rendimiento", "Crítica", "Alta", "Media", "Baja", "Informativa"]) {
      expect(translated.getByText(label)).toBeInTheDocument()
    }
  })

  it("shows zero for absent counter categories and preserves other attributes and undetermined severity", async () => {
    vi.mocked(api.getQualityAuditReportSection).mockResolvedValue({ section: "executive_summary", data: {
      findings: { total: 2, by_attribute: { functional_adequacy: 2 }, by_severity: { undetermined: 2 } },
    } })
    show()
    const summary = within(await screen.findByRole("region", { name: "Findings summary" }))
    expect(summary.getByText("Maintainability").closest("div")).toHaveTextContent("Maintainability0")
    expect(summary.getByText("Performance").closest("div")).toHaveTextContent("Performance0")
    expect(summary.getByText("Critical").closest("div")).toHaveTextContent("Critical0")
    expect(summary.getByText("Other attributes").closest("div")).toHaveTextContent("Other attributes2")
    expect(summary.getByText("Undetermined / other severity").closest("div")).toHaveTextContent("Undetermined / other severity2")
  })

  it("does not invent zero counts when a historical report has no finding statistics", async () => {
    show()
    const summary = within(await screen.findByRole("region", { name: "Findings summary" }))
    expect(summary.getAllByText("Not recorded")).toHaveLength(9)
    expect(summary.queryByText("0")).not.toBeInTheDocument()
  })

  it("shows the stored revision, partial report and traceability, and downloads the same audit", async () => {
    show()
    expect(await screen.findByRole("heading", { name: "Audit report · #8" })).toBeInTheDocument()
    const header = within(screen.getByLabelText("Audit details"))
    expect(header.getByRole("heading", { name: "Audit results · #8" })).toBeInTheDocument()
    expect(header.getByText("acme/Shop")).toBeInTheDocument()
    expect(header.getByText("original-branch")).toBeInTheDocument()
    expect(header.getByText("b".repeat(40))).toBeInTheDocument()
    expect(header.getByText("original-run")).toBeInTheDocument()
    expect(header.getByText("Partial evaluation")).toBeInTheDocument()
    expect(header.getByText(formatDateTime(audit.startedAt!))).toHaveAttribute("datetime", audit.startedAt)
    expect(await screen.findByText("Original report conclusion.")).toBeInTheDocument()
    expect(screen.getByText("Original report content")).toBeInTheDocument()
    expect(screen.getAllByText("original-run").length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText("Source references (2)")).toBeInTheDocument()
    expect(screen.getAllByText(/^\d+\. /)).toHaveLength(10)
    expect(screen.getByRole("link", { name: "Back to audits" })).toHaveAttribute("href", "/projects/5/audits")
    await userEvent.click(screen.getByRole("button", { name: "Download Word report" }))
    expect(api.downloadQualityAuditReport).toHaveBeenCalledWith(5, 8)
    await changeLanguage("es")
    expect(screen.getByRole("heading", { name: "Resultados de auditoría · #8" })).toBeInTheDocument()
    expect(screen.getByRole("heading", { name: "Informe de auditoría · #8" })).toBeInTheDocument()
    expect(within(screen.getByLabelText("Datos de la auditoría")).getByText("Fecha de ejecución")).toBeInTheDocument()
    expect(screen.getByText("Referencias de origen (2)")).toBeInTheDocument()
    expect(screen.getByText("Original report content")).toBeInTheDocument()
    expect(api.getQualityAudit).toHaveBeenCalledOnce()
    expect(api.getQualityAuditReportSection).toHaveBeenCalledOnce()
    expect(api.getQualityAuditReportSection).toHaveBeenCalledWith(5, 8, "executive_summary", expect.any(AbortSignal))
    expect(api.listQualityAudits).not.toHaveBeenCalled()
    expect(api.getQualityAuditReport).not.toHaveBeenCalled()
  })

  it("shows failed audits even when no report was produced", async () => {
    vi.mocked(api.getQualityAudit).mockResolvedValue({ ...audit, executionStatus: "Failed", auditStatus: "failed", reportAvailable: false, error: "Audit stopped" })
    show()
    expect(await screen.findByRole("alert")).toHaveTextContent("Audit stopped")
    expect(screen.getByText("This audit did not produce a report.")).toBeInTheDocument()
    expect(api.getQualityAuditReport).not.toHaveBeenCalled()
    expect(api.getQualityAuditReportSection).not.toHaveBeenCalled()
    expect(screen.queryByRole("button", { name: "Download Word report" })).not.toBeInTheDocument()
  })

  it("uses the available historical execution date when the start date was not recorded", async () => {
    vi.mocked(api.getQualityAudit).mockResolvedValue({ ...audit, startedAt: null, reportAvailable: false })
    show()
    const date = await screen.findByText(formatDateTime(audit.finishedAt!))
    expect(date).toHaveAttribute("datetime", audit.finishedAt)
  })

  it("does not present the creation date as execution when no execution timestamp exists", async () => {
    vi.mocked(api.getQualityAudit).mockResolvedValue({ ...audit, startedAt: null, finishedAt: null, reportAvailable: false })
    show()
    await screen.findByText("This audit did not produce a report.")
    expect(within(screen.getByLabelText("Audit details")).getByText("Not recorded")).toBeInTheDocument()
  })

  it("does not fetch a report for an audit outside this project", async () => {
    vi.mocked(api.getQualityAudit).mockRejectedValue(new ApiError(404, "Not found", "server"))
    show()
    expect(await screen.findByRole("alert")).toHaveTextContent("This audit does not exist in the project.")
    expect(api.getQualityAuditReport).not.toHaveBeenCalled()
  })

  it("allows retrying a failed request", async () => {
    vi.mocked(api.getQualityAudit).mockRejectedValueOnce(new Error("offline")).mockResolvedValue(audit)
    show()
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load the audit results.")
    await userEvent.click(screen.getByRole("button", { name: "Retry" }))
    expect(await screen.findByRole("heading", { name: "Audit report · #8" })).toBeInTheDocument()
  })

  it("shows metadata while sections load independently, caches them, and renders long lists in batches", async () => {
    let finishSummary!: (value: { section: "executive_summary", data: unknown }) => void
    vi.mocked(api.getQualityAuditReportSection).mockImplementation(async (_project, _id, section) => {
      if (section === "executive_summary") return new Promise((resolve) => { finishSummary = resolve })
      return { section, data: Array.from({ length: 55 }, (_, index) => `Finding ${index + 1}`) }
    })
    const user = userEvent.setup()
    show()
    expect(await screen.findByText("Partial evaluation")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Download Word report" })).toBeEnabled()
    await waitFor(() => expect(api.getQualityAuditReportSection).toHaveBeenCalledTimes(1))
    await user.click(screen.getByText("6. Quality results"))
    expect(await screen.findByText("Finding 1")).toBeInTheDocument()
    expect(screen.queryByText("Finding 55")).not.toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "Show more (5 remaining)" }))
    expect(screen.getByText("Finding 55")).toBeInTheDocument()
    await user.click(screen.getByText("6. Quality results"))
    await user.click(screen.getByText("6. Quality results"))
    expect(await screen.findByText("Finding 1")).toBeInTheDocument()
    expect(vi.mocked(api.getQualityAuditReportSection).mock.calls.filter((call) => call[2] === "quality_results")).toHaveLength(1)
    await act(async () => { finishSummary({ section: "executive_summary", data: { conclusion: "Summary finished" } }) })
    expect(await screen.findByText("Summary finished")).toBeInTheDocument()
    expect(api.listQualityAudits).not.toHaveBeenCalled()
    expect(api.getQualityAuditReport).not.toHaveBeenCalled()
  })

  it("retries a failed section without reloading metadata or the complete report", async () => {
    vi.mocked(api.getQualityAuditReportSection).mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValue({ section: "executive_summary", data: { conclusion: "Recovered section" } })
    show()
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load this section.")
    await userEvent.click(screen.getByRole("button", { name: "Retry" }))
    expect(await screen.findByText("Recovered section")).toBeInTheDocument()
    expect(api.getQualityAudit).toHaveBeenCalledOnce()
    await waitFor(() => expect(api.getQualityAuditReportSection).toHaveBeenCalledTimes(2))
  })

  it("cancels an unfinished section when it is collapsed and ignores its late response", async () => {
    const finish: Array<(value: { section: "executive_summary", data: unknown }) => void> = []
    vi.mocked(api.getQualityAuditReportSection).mockImplementation(() => new Promise((resolve) => { finish.push(resolve) }))
    const user = userEvent.setup()
    show()
    await screen.findByRole("heading", { name: "Audit report · #8" })
    await waitFor(() => expect(api.getQualityAuditReportSection).toHaveBeenCalledTimes(1))
    const signal = vi.mocked(api.getQualityAuditReportSection).mock.calls[0]![3]!
    await user.click(screen.getByText("2. Executive summary"))
    await waitFor(() => expect(signal.aborted).toBe(true))
    await user.click(screen.getByText("2. Executive summary"))
    await waitFor(() => expect(api.getQualityAuditReportSection).toHaveBeenCalledTimes(2))
    await act(async () => {
      finish[0]!({ section: "executive_summary", data: { conclusion: "Stale response" } })
      finish[1]!({ section: "executive_summary", data: { conclusion: "Current response" } })
    })
    expect(await screen.findByText("Current response")).toBeInTheDocument()
    expect(screen.queryByText("Stale response")).not.toBeInTheDocument()
  })
})
