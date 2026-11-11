import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { useState } from "react"
import { cleanup, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { changeLanguage } from "../../shared/i18n/index.ts"
import { ApiError, listAgentSettings, type AgentExecution, type AgentSettings } from "../../infrastructure/http-client/httpClient.ts"
import { AgentExecutionsContext } from "../../shared/agent-monitor/useAgentExecutions.ts"
import { QualityAudits } from "./QualityAudits.tsx"
import { SettingsContext, type SettingsContextValue } from "../../app/settingsContext.tsx"
import { AnalyzeMenu } from "./AnalyzeMenu.tsx"
import * as api from "./qualityAuditApi.ts"
import * as operating from "./auditOperatingSettingsApi.ts"
import { getArchitectureContextAvailability } from "./architectureContextApi.ts"

vi.mock("./architectureContextApi.ts", () => ({ getArchitectureContextAvailability: vi.fn() }))

vi.mock("./auditOperatingSettingsApi.ts", async (importOriginal) => ({
  ...await importOriginal<typeof import("./auditOperatingSettingsApi.ts")>(), getAuditSettings: vi.fn(), saveAuditSettings: vi.fn(),
}))

vi.mock("./qualityAuditApi.ts", () => ({
  listQualityAudits: vi.fn(), listQualityAuditPage: vi.fn(), startQualityAudit: vi.fn(), getQualityAuditReport: vi.fn(), downloadQualityAuditReport: vi.fn(),
  getQualityAuditConfiguration: vi.fn(),
  getQualityAudit: vi.fn(),
}))

vi.mock("../../infrastructure/http-client/httpClient.ts", async (importOriginal) => ({
  ...await importOriginal<typeof import("../../infrastructure/http-client/httpClient.ts")>(),
  listAgentSettings: vi.fn(),
}))

const historicalSummary: api.QualityAuditSummary = { id: 8, evaluationId: 4, branch: "main", commitHash: "a".repeat(40), attributes: ["maintainability"],
  executionStatus: "Completed", auditStatus: "partial", runId: "report-run-id", error: null,
  createdAt: "2026-10-17T10:00:00Z", finishedAt: null, reportAvailable: true }
const readyAgents: AgentSettings[] = ["maintainability_manager", "security", "functional_adequacy"].map((agentType) => ({
  agentType, qualityAttributes: [agentType], workflowIds: [], configured: true, configuration: null, availability: "available", requiresModel: true,
}))
beforeEach(() => {
  vi.mocked(getArchitectureContextAvailability).mockImplementation(async (projectId, commitHash) => ({
    projectId, commitHash, available: true, executionId: 41, executionStatus: "partial",
  }))
  vi.mocked(api.listQualityAuditPage).mockImplementation(async (projectId, limit, offset) => {
    const rows = [...await api.listQualityAudits(projectId)].sort((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt) || b.id - a.id)
    const actualOffset = rows.length ? Math.min(offset, Math.floor((rows.length - 1) / limit) * limit) : 0
    return { items: rows.slice(actualOffset, actualOffset + limit), total: rows.length, limit, offset: actualOffset,
      hasRunning: rows.some((row) => ["Waiting", "Running"].includes(row.executionStatus)) }
  })
  vi.mocked(listAgentSettings).mockResolvedValue(readyAgents)
  vi.mocked(api.getQualityAudit).mockResolvedValue(historicalSummary)
  vi.mocked(operating.getAuditSettings).mockImplementation(async (attribute) => ({ schema: { type: "object", properties: {
    [attribute === "security" ? "security_config" : "functional_config"]: { type: "object", properties: {
      [attribute === "security" ? "max_scan_files" : "timeout_seconds"]: { type: "integer", minimum: 1, maximum: 100, default: 5 },
    } },
    audit_budget: { type: "object", properties: { max_total_tokens: { type: "integer" } } },
  } }, values: {} }))
})
afterEach(async () => { cleanup(); vi.resetAllMocks(); await changeLanguage("en") })

function show(settings?: Partial<SettingsContextValue>) {
  const page = <MemoryRouter><QualityAudits projectId={5} branch="main" commitHash={"a".repeat(40)} canRun /></MemoryRouter>
  render(settings ? <SettingsContext.Provider value={{ openSettings: () => {}, ...settings }}>{page}</SettingsContext.Provider> : page)
}

async function toggleAttribute(name: string) {
  await userEvent.click(screen.getByRole("button", { name: "Configure audit" }))
  await userEvent.click(screen.getByRole("checkbox", { name: `Enable ${name === "Functional adequacy" ? "Functional adequacy · exploratory" : name}` }))
  await userEvent.keyboard("{Escape}")
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
}

describe("project quality audits", () => {
  it("removes manual V2 JSON input and leaves saved context resolution to the backend", async () => {
    vi.mocked(api.listQualityAudits).mockResolvedValue([])
    vi.mocked(api.startQualityAudit).mockResolvedValue({ executionId: 44 })
    show()
    await screen.findByText("No audits recorded.")
    await toggleAttribute("Security")
    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: "Configure audit" }))
    expect(screen.queryByRole("textbox", { name: "Maintainability V2 input (optional JSON)" })).not.toBeInTheDocument()
    await user.keyboard("{Escape}")
    await user.click(screen.getByRole("button", { name: "Start audit" }))
    await waitFor(() => expect(api.startQualityAudit).toHaveBeenCalledWith(5, "main", "a".repeat(40), ["maintainability"]))
  })

  it("blocks missing context and keeps security available without silently dropping maintainability", async () => {
    vi.mocked(getArchitectureContextAvailability).mockImplementation(async (projectId, commitHash) => ({
      projectId, commitHash, available: false, executionId: null, executionStatus: null,
    }))
    vi.mocked(api.listQualityAudits).mockResolvedValue([])
    vi.mocked(api.startQualityAudit).mockResolvedValue({ executionId: 44 })
    show()
    await screen.findByText("No audits recorded.")
    expect(screen.getByRole("button", { name: "Start audit" })).toBeDisabled()
    expect(screen.getByRole("region", { name: "Maintainability" })).toHaveAttribute("aria-disabled", "true")
    expect(screen.getAllByText(/Run Analyze to generate architecture context/).length).toBeGreaterThan(0)
    await toggleAttribute("Maintainability")
    await waitFor(() => expect(screen.getByRole("button", { name: "Start audit" })).toBeEnabled())
    await userEvent.click(screen.getByRole("button", { name: "Configure audit" }))
    expect(screen.getByRole("checkbox", { name: "Enable Maintainability" })).toBeDisabled()
    await userEvent.keyboard("{Escape}")
    await userEvent.click(screen.getByRole("button", { name: "Start audit" }))
    await waitFor(() => expect(api.startQualityAudit).toHaveBeenCalledWith(5, "main", "a".repeat(40), ["security"]))
  })

  it("shows a loading indicator before the empty history and while refreshing", async () => {
    let resolve!: (rows: api.QualityAuditSummary[]) => void
    vi.mocked(api.listQualityAudits).mockImplementation(() => new Promise((done) => { resolve = done }))
    render(<MemoryRouter><QualityAudits projectId={5} branch="main" commitHash={"a".repeat(40)} canRun view="history" /></MemoryRouter>)

    expect(screen.getByRole("status", { name: "Loading audits" })).toBeVisible()
    expect(screen.queryByText("No audits recorded.")).toBeNull()
    expect(screen.queryByRole("article")).toBeNull()
    expect(screen.getByRole("button", { name: "Refresh" })).toBeDisabled()
    resolve([])
    await waitFor(() => expect(screen.queryByRole("status", { name: "Loading audits" })).toBeNull())
    expect(screen.getByText("No audits recorded.")).toBeVisible()

    await userEvent.click(screen.getByRole("button", { name: "Refresh" }))
    expect(screen.getByRole("status", { name: "Loading audits" })).toBeVisible()
    expect(screen.queryByText("No audits recorded.")).toBeNull()
    expect(screen.queryByRole("article")).toBeNull()
    resolve([historicalSummary])
    expect(await screen.findByRole("article")).toBeVisible()
    expect(screen.queryByRole("status", { name: "Loading audits" })).toBeNull()

    // Refreshing with an existing row hides it instead of showing old and new together.
    await userEvent.click(screen.getByRole("button", { name: "Refresh" }))
    expect(screen.getByRole("status", { name: "Loading audits" })).toBeVisible()
    expect(screen.queryByRole("article")).toBeNull()
    resolve([historicalSummary])
    expect(await screen.findByRole("article")).toBeVisible()
  })

  it("stops the loading indicator on failure without showing an empty history", async () => {
    vi.mocked(api.listQualityAudits).mockRejectedValue(new Error("offline"))
    render(<MemoryRouter><QualityAudits projectId={5} branch="main" commitHash={"a".repeat(40)} canRun view="history" /></MemoryRouter>)
    expect(await screen.findByRole("alert")).toBeVisible()
    expect(screen.queryByRole("status", { name: "Loading audits" })).toBeNull()
    expect(screen.queryByText("No audits recorded.")).toBeNull()
    expect(screen.getByRole("button", { name: "Refresh" })).toBeEnabled()
  })

  it("refreshes history on confirmed cancellation events without refetching every usage update", async () => {
    vi.mocked(api.listQualityAudits).mockResolvedValueOnce([{ ...historicalSummary, executionStatus: "Running", auditStatus: null }])
      .mockResolvedValue([{ ...historicalSummary, executionStatus: "Completed", auditStatus: "cancelled" }])
    const view = (executions: AgentExecution[]) => <MemoryRouter><AgentExecutionsContext.Provider value={executions}>
      <QualityAudits projectId={5} branch="main" commitHash={"a".repeat(40)} canRun view="history" />
    </AgentExecutionsContext.Provider></MemoryRouter>
    const { rerender } = render(view([]))
    await screen.findByRole("article")
    const cancelled: AgentExecution = { id: historicalSummary.id, evaluationId: 4, agentType: "security", status: "Completed", result: null, error: null,
      inputTokens: 12, outputTokens: 2, createdAt: historicalSummary.createdAt, startedAt: null, finishedAt: "2026-10-30T12:00:00Z",
      interruptionReason: "cancelled", cancellationRequestedAt: "2026-10-30T11:59:00Z",
      monitorContext: { project: { id: 5, repositoryOwner: "acme", repositoryName: "demo" }, branch: "main", commitHash: null,
        evaluationType: "QualityAudit", qualityAttributes: ["security"], workflowIds: [] } }
    rerender(view([cancelled]))
    expect(await screen.findByText("Cancelled")).toBeVisible()
    expect(api.listQualityAudits).toHaveBeenCalledTimes(2)
    rerender(view([{ ...cancelled, inputTokens: 15 }]))
    expect(api.listQualityAudits).toHaveBeenCalledTimes(2)
  })
  it.each([["cancelling", "Running", "Cancelling…"], ["cancelled", "Completed", "Cancelled"]])(
    "shows the server's %s outcome instead of a successful execution label", async (auditStatus, executionStatus, label) => {
      vi.mocked(api.listQualityAudits).mockResolvedValue([{ ...historicalSummary, auditStatus, executionStatus }])
      render(<MemoryRouter><QualityAudits projectId={5} branch="main" commitHash={"a".repeat(40)} canRun view="history" /></MemoryRouter>)
      const article = await screen.findByRole("article")
      expect(within(article).getByText(label)).toBeVisible()
    },
  )
  const paginatedAudits = Array.from({ length: 21 }, (_, index) => ({
    ...historicalSummary, id: 100 - index, reportAvailable: false,
    createdAt: `2026-01-${String(index + 1).padStart(2, "0")}T12:00:00Z`,
  }))

  function showHistory() {
    render(<MemoryRouter><QualityAudits projectId={5} branch="main" commitHash={"a".repeat(40)} canRun view="history" /></MemoryRouter>)
  }

  async function openAuditMenu(container: HTMLElement = document.body) {
    await userEvent.click(within(container).getByRole("button", { name: /More actions for audit/ }))
  }

  it("loads only one summary page without fetching audit details or the agent catalog", async () => {
    vi.mocked(api.listQualityAuditPage).mockResolvedValue({ items: [{ ...historicalSummary, runId: null }], total: 12,
      hasRunning: false, limit: 5, offset: 0 })
    showHistory()
    await screen.findByRole("article")
    expect(api.listQualityAuditPage).toHaveBeenCalledWith(5, 5, 0, expect.any(AbortSignal))
    expect(api.getQualityAudit).not.toHaveBeenCalled()
    expect(api.getQualityAuditReport).not.toHaveBeenCalled()
    expect(api.getQualityAuditConfiguration).not.toHaveBeenCalled()
    expect(listAgentSettings).not.toHaveBeenCalled()
    // Run ID is hidden from the explorer row; Blackboard lives in the menu and is disabled while unavailable.
    expect(screen.queryByRole("button", { name: "View Blackboard" })).toBeNull()
    await openAuditMenu()
    expect(screen.getByRole("button", { name: "View Blackboard" })).toBeDisabled()

    vi.mocked(api.listQualityAuditPage).mockResolvedValue({ items: [{ ...historicalSummary, id: 9 }], total: 12,
      hasRunning: false, limit: 5, offset: 5 })
    await userEvent.click(screen.getAllByRole("button", { name: "Next page" })[0])
    await waitFor(() => expect(screen.getByRole("article")).toHaveTextContent("#9"))
    expect(api.listQualityAuditPage).toHaveBeenLastCalledWith(5, 5, 5, expect.any(AbortSignal))
  })

  it("aborts history requests when leaving the page", async () => {
    vi.mocked(api.listQualityAuditPage).mockImplementation(() => new Promise(() => {}))
    const view = render(<MemoryRouter><QualityAudits projectId={5} branch="main" commitHash={"a".repeat(40)} canRun view="history" /></MemoryRouter>)
    const signal = vi.mocked(api.listQualityAuditPage).mock.calls[0][3]!
    expect(signal.aborted).toBe(false)
    view.unmount()
    expect(signal.aborted).toBe(true)
  })

  it("orders history newest first and starts with five records per page", async () => {
    vi.mocked(api.listQualityAudits).mockResolvedValue(paginatedAudits)
    showHistory()
    await screen.findAllByRole("article")
    expect(screen.getAllByRole("article")).toHaveLength(5)
    const controls = screen.getAllByRole("combobox", { name: "Audits per page" })
    const articles = screen.getAllByRole("article")
    expect(controls[0].compareDocumentPosition(articles[0]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(controls[1].compareDocumentPosition(articles[articles.length - 1]) & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy()
    const headings = screen.getAllByRole("article").map((article) => within(article).getByRole("heading").textContent)
    expect(headings[0]).toContain("#80")
    expect(headings[4]).toContain("#84")
    expect(screen.getAllByRole("combobox", { name: "Audits per page" })).toHaveLength(2)
    screen.getAllByRole("combobox", { name: "Audits per page" }).forEach((select) => expect(select).toHaveValue("5"))
    expect(screen.getAllByText("Page 1 of 5")).toHaveLength(2)
    screen.getAllByRole("button", { name: "Previous page" }).forEach((button) => expect(button).toBeDisabled())
    await userEvent.click(screen.getAllByRole("button", { name: "Next page" })[0])
    expect(screen.getAllByText("Page 2 of 5")).toHaveLength(2)
    expect(within(screen.getAllByRole("article")[0]).getByRole("heading")).toHaveTextContent("#85")
    await userEvent.click(screen.getAllByRole("button", { name: "Previous page" })[1])
    expect(within(screen.getAllByRole("article")[0]).getByRole("heading")).toHaveTextContent("#80")
  })

  it.each([5, 10, 15, 20])("allows %s records per page and resets to the first page", async (size) => {
    vi.mocked(api.listQualityAudits).mockResolvedValue(paginatedAudits)
    showHistory()
    await screen.findAllByRole("article")
    await userEvent.click(screen.getAllByRole("button", { name: "Next page" })[0])
    const selector = screen.getAllByRole("combobox", { name: "Audits per page" })[1]
    expect(within(selector).getAllByRole("option").map((option) => option.textContent)).toEqual(["5", "10", "15", "20"])
    await userEvent.selectOptions(selector, String(size))
    expect(screen.getAllByRole("article")).toHaveLength(size)
    expect(within(screen.getAllByRole("article")[0]).getByRole("heading")).toHaveTextContent("#80")
    expect(screen.getAllByText(`Page 1 of ${Math.ceil(21 / size)}`)).toHaveLength(2)
    screen.getAllByRole("combobox", { name: "Audits per page" }).forEach((select) => expect(select).toHaveValue(String(size)))
  })

  it("handles the final partial page and clamps the page after history shrinks", async () => {
    vi.mocked(api.listQualityAudits).mockResolvedValue(paginatedAudits)
    showHistory()
    await screen.findAllByRole("article")
    await userEvent.selectOptions(screen.getAllByRole("combobox", { name: "Audits per page" })[0], "20")
    await userEvent.click(screen.getAllByRole("button", { name: "Next page" })[1])
    expect(screen.getAllByRole("article")).toHaveLength(1)
    screen.getAllByRole("button", { name: "Next page" }).forEach((button) => expect(button).toBeDisabled())
    vi.mocked(api.listQualityAudits).mockResolvedValue([paginatedAudits[0]])
    await userEvent.click(screen.getByRole("button", { name: "Refresh" }))
    await waitFor(() => expect(screen.queryAllByRole("navigation", { name: "Audit history pages" })).toHaveLength(0))
    expect(screen.getAllByRole("article")).toHaveLength(1)
    screen.getAllByRole("combobox", { name: "Audits per page" }).forEach((select) => expect(select).toHaveValue("20"))
  })

  it("does not show paging controls for an empty history", async () => {
    vi.mocked(api.listQualityAudits).mockResolvedValue([])
    showHistory()
    await screen.findByText("No audits recorded.")
    expect(screen.queryByRole("combobox", { name: "Audits per page" })).toBeNull()
    expect(screen.queryByRole("navigation", { name: "Audit history pages" })).toBeNull()
  })

  it("still blocks starting when a running audit is outside the visible page", async () => {
    vi.mocked(api.listQualityAudits).mockResolvedValue([
      { ...paginatedAudits[0], executionStatus: "Running" }, ...paginatedAudits.slice(1),
    ])
    show()
    await screen.findAllByRole("article")
    expect(screen.getAllByRole("article")).toHaveLength(5)
    expect(screen.getByRole("button", { name: "Start audit" })).toBeDisabled()
    expect(api.startQualityAudit).not.toHaveBeenCalled()
  })

  it("starts audits from the configuration view without rendering history", async () => {
    vi.mocked(api.listQualityAudits).mockResolvedValue([])
    vi.mocked(api.startQualityAudit).mockResolvedValue({ executionId: 8 })
    render(<MemoryRouter><QualityAudits projectId={5} branch="main" commitHash={"a".repeat(40)} canRun view="configuration" /></MemoryRouter>)
    const start = screen.getByRole("button", { name: "Start audit" })
    await waitFor(() => expect(start).toBeEnabled())
    expect(screen.queryByRole("heading", { name: "Project audits" })).toBeNull()
    await userEvent.click(start)
    expect(api.startQualityAudit).toHaveBeenCalledWith(5, "main", "a".repeat(40), ["maintainability", "security"])
  })

  it("keeps history refresh and load errors available without setup controls", async () => {
    vi.mocked(api.listQualityAudits).mockRejectedValueOnce(new Error("offline")).mockResolvedValue([])
    render(<MemoryRouter><QualityAudits projectId={5} branch="main" commitHash={"a".repeat(40)} canRun view="history" /></MemoryRouter>)
    expect(await screen.findByRole("alert")).toBeVisible()
    expect(screen.queryByRole("button", { name: "Start audit" })).toBeNull()
    expect(screen.queryByRole("button", { name: "Configure audit" })).toBeNull()
    await userEvent.click(screen.getByRole("button", { name: "Refresh" }))
    await waitFor(() => expect(api.listQualityAudits).toHaveBeenCalledTimes(2))
  })

  it("groups the audit count with the history title and places refresh in the header", async () => {
    vi.mocked(api.listQualityAudits).mockResolvedValue([historicalSummary])
    render(<MemoryRouter><QualityAudits projectId={5} branch="main" commitHash={"a".repeat(40)} canRun view="history" /></MemoryRouter>)
    await screen.findByRole("article")
    const title = screen.getByRole("heading", { name: "Project audits" })
    expect(within(title.parentElement!).getByText("1").closest(".ui-badge")).toBeInTheDocument()
    const header = title.closest(".quality-audit-heading")!
    expect(within(header as HTMLElement).getByRole("button", { name: "Refresh" })).toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: "Refresh" }))
    await waitFor(() => expect(api.listQualityAudits).toHaveBeenCalledTimes(2))
  })

  it("uses the same secondary button style for the visible history actions and keeps secondary actions in the menu", async () => {
    vi.mocked(api.listQualityAudits).mockResolvedValue([{ ...historicalSummary, configurationAvailable: true }])
    show()
    const article = await screen.findByRole("article")
    const history = within(article)
    // View Details and Reuse Configuration are visible first-hand in the explorer row.
    expect(history.getByRole("link", { name: "View details" })).toHaveClass("ui-button-secondary")
    expect(history.getByRole("button", { name: "Reuse configuration" })).toHaveClass("ui-button-secondary")
    expect(history.queryByRole("link", { name: "View Blackboard" })).not.toBeInTheDocument()
    await openAuditMenu(article)
    for (const name of ["View configuration", "Download Word report"]) {
      expect(history.getByRole("button", { name })).toBeInTheDocument()
    }
    expect(history.getByRole("link", { name: "View Blackboard" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Refresh" })).toHaveClass("ui-button-secondary")
    expect(screen.getByRole("button", { name: "Start audit" })).toHaveClass("ui-button-primary")
  })

  it("blocks an unconfigured selection and allows starting after rechecking the catalog", async () => {
    vi.mocked(api.listQualityAudits).mockResolvedValue([])
    vi.mocked(api.startQualityAudit).mockResolvedValue({ executionId: 8 })
    vi.mocked(listAgentSettings).mockResolvedValueOnce(readyAgents.map((agent) => agent.agentType === "security" ? { ...agent, configured: false } : agent))
      .mockResolvedValue(readyAgents)
    show()
    await waitFor(() => expect(screen.getByRole("button", { name: "Start audit" })).toBeEnabled())
    await toggleAttribute("Security")
    expect(await screen.findByText("Security: Configure a model and compatible credentials before starting.")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Start audit" })).toBeDisabled()
    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: "Check agents again" }))
    await waitFor(() => expect(screen.getByRole("button", { name: "Start audit" })).toBeEnabled())
    await user.click(screen.getByRole("button", { name: "Start audit" }))
    expect(api.startQualityAudit).toHaveBeenCalledWith(5, "main", "a".repeat(40), ["maintainability", "security"])
  })

  it.each(["maintainability_manager", "security"])("starts with only %s ready, without requiring other agents", async (agentType) => {
    vi.mocked(api.listQualityAudits).mockResolvedValue([])
    vi.mocked(api.startQualityAudit).mockResolvedValue({ executionId: 8 })
    vi.mocked(listAgentSettings).mockResolvedValue(readyAgents.map((agent) => ({ ...agent, configured: agent.agentType === agentType })))
    show()
    const start = screen.getByRole("button", { name: "Start audit" })
    await waitFor(() => expect(start).toBeEnabled())
    await userEvent.click(start)
    expect(api.startQualityAudit).toHaveBeenCalledWith(5, "main", "a".repeat(40), [agentType === "security" ? "security" : "maintainability"])
  })

  it("allows a ready selection even when all other agents are absent from the catalog", async () => {
    vi.mocked(api.listQualityAudits).mockResolvedValue([])
    vi.mocked(api.startQualityAudit).mockResolvedValue({ executionId: 8 })
    vi.mocked(listAgentSettings).mockResolvedValue(readyAgents.filter((agent) => agent.agentType === "security"))
    show()
    await waitFor(() => expect(screen.getByRole("button", { name: "Start audit" })).toBeEnabled())
    await userEvent.click(screen.getByRole("button", { name: "Start audit" }))
    expect(api.startQualityAudit).toHaveBeenCalledWith(5, "main", "a".repeat(40), ["security"])
  })

  it("explains when no configured agent can be selected by default", async () => {
    vi.mocked(api.listQualityAudits).mockResolvedValue([])
    vi.mocked(listAgentSettings).mockResolvedValue(readyAgents.map((agent) => ({ ...agent, configured: false })))
    show()
    expect(await screen.findByText(/Select at least one available, configured agent/)).toBeVisible()
    expect(screen.getByRole("button", { name: "Start audit" })).toBeDisabled()
    expect(api.startQualityAudit).not.toHaveBeenCalled()
  })

  it("rechecks readiness when no default agent was initially configured", async () => {
    vi.mocked(api.listQualityAudits).mockResolvedValue([])
    vi.mocked(listAgentSettings).mockResolvedValueOnce(readyAgents.map((agent) => ({ ...agent, configured: false })))
      .mockResolvedValue(readyAgents.filter((agent) => agent.agentType === "security"))
    show()
    await screen.findByText(/Select at least one available, configured agent/)
    await userEvent.click(screen.getByRole("button", { name: "Check agents again" }))
    await waitFor(() => expect(screen.getByRole("button", { name: "Start audit" })).toBeEnabled())
    expect(screen.getByRole("region", { name: "Security" })).toHaveTextContent("Enabled")
  })

  it.each(["Waiting", "Running"])("does not start another audit while an existing audit is %s", async (executionStatus) => {
    vi.mocked(api.listQualityAudits).mockResolvedValue([{ ...historicalSummary, executionStatus }])
    vi.mocked(listAgentSettings).mockResolvedValue(readyAgents.filter((agent) => agent.agentType === "security"))
    show()
    await screen.findByRole("article")
    expect(screen.getByRole("button", { name: "Start audit" })).toBeDisabled()
    expect(api.startQualityAudit).not.toHaveBeenCalled()
  })

  it.each([
    { branch: null, commitHash: null, canRun: true, reason: /Apply a branch and commit/ },
    { branch: "main", commitHash: "a".repeat(40), canRun: false, reason: /project is not ready/ },
  ])("explains the project or revision blocker", async ({ reason, ...props }) => {
    vi.mocked(api.listQualityAudits).mockResolvedValue([])
    render(<MemoryRouter><QualityAudits projectId={5} {...props} /></MemoryRouter>)
    expect(await screen.findByText(reason)).toBeVisible()
    expect(screen.getByRole("button", { name: "Start audit" })).toBeDisabled()
  })

  it("configures security and exploratory time limits without exposing requirements", async () => {
    vi.mocked(api.listQualityAudits).mockResolvedValue([])
    vi.mocked(api.startQualityAudit).mockResolvedValue({ executionId: 8 })
    show()
    await screen.findByText("No audits recorded.")
    const user = userEvent.setup()
    expect(operating.getAuditSettings).not.toHaveBeenCalled()
    await user.click(screen.getByRole("button", { name: "Configure audit" }))
    await user.click(screen.getByRole("checkbox", { name: "Enable Maintainability" }))
    await user.click(screen.getByRole("checkbox", { name: "Enable Functional adequacy · exploratory" }))
    expect(screen.queryByRole("textbox", { name: "Functional requirements" })).not.toBeInTheDocument()
    const security = within(screen.getByRole("button", { name: "Collapse Security" }).closest("section")!)
    const functional = within(screen.getByRole("button", { name: "Collapse Functional adequacy · exploratory" }).closest("section")!)
    await user.click(security.getByRole("button", { name: "Advanced settings for this run (developer)" }))
    const scan = await security.findByRole("spinbutton", { name: "security_config · max_scan_files" })
    await user.type(scan, "25")
    await user.click(functional.getByRole("button", { name: "Advanced settings for this run (developer)" }))
    await user.type(await functional.findByRole("spinbutton", { name: "functional_config · timeout_seconds" }), "3")
    expect(screen.queryByRole("spinbutton", { name: /audit_budget/ })).not.toBeInTheDocument()
    await user.keyboard("{Escape}")
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
    await user.click(screen.getByRole("button", { name: "Configure audit" }))
    expect(screen.getByRole("spinbutton", { name: "security_config · max_scan_files" })).toHaveValue(25)
    expect(screen.getByRole("spinbutton", { name: "functional_config · timeout_seconds" })).toHaveValue(3)
    await user.keyboard("{Escape}")
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
    await user.click(screen.getByRole("button", { name: "Start audit" }))
    expect(api.startQualityAudit).toHaveBeenCalledWith(5, "main", "a".repeat(40), ["security", "functional_adequacy"], {
      functional_requirements: [],
      attribute_options: { security: { security_config: { max_scan_files: 25 } }, functional_adequacy: { functional_config: { timeout_seconds: 3 } } },
    })
    vi.mocked(api.startQualityAudit).mockClear()
    await toggleAttribute("Security")
    await user.click(screen.getByRole("button", { name: "Start audit" }))
    expect(api.startQualityAudit).toHaveBeenCalledWith(5, "main", "a".repeat(40), ["functional_adequacy"], {
      functional_requirements: [],
      attribute_options: { functional_adequacy: { functional_config: { timeout_seconds: 3 } } },
    })
    expect(operating.saveAuditSettings).not.toHaveBeenCalled()
  })

  it.each([false, true])("only exposes exploratory limits even when a functional model is configured (%s)", async (configured) => {
    vi.mocked(api.listQualityAudits).mockResolvedValue([])
    vi.mocked(api.startQualityAudit).mockResolvedValue({ executionId: 8 })
    vi.mocked(listAgentSettings).mockResolvedValue(readyAgents.map((agent) => agent.agentType === "functional_adequacy" ? { ...agent, configured } : agent))
    vi.mocked(operating.getAuditSettings).mockResolvedValue({ schema: { type: "object", properties: {
      agent_defaults: { type: "object", properties: { max_tool_calls: { type: "integer", minimum: 0 } } },
      functional_config: { type: "object", properties: {
        timeout_seconds: { type: "number", exclusiveMinimum: 0 },
        max_wall_time_seconds: { type: "number", exclusiveMinimum: 0 },
        provider_request_timeout_seconds: { type: "number", exclusiveMinimum: 0 },
        max_provider_retries: { type: "integer", minimum: 0, maximum: 8 },
        provider_rate_limits: { type: "object", properties: {
          requests_per_minute: { anyOf: [{ type: "integer", minimum: 1 }, { type: "null" }] },
          tokens_per_minute: { anyOf: [{ type: "integer", minimum: 1 }, { type: "null" }] },
        } },
      } },
    } }, values: { functional_config: { provider_rate_limits: { requests_per_minute: 42, tokens_per_minute: 700000 } } } })
    show()
    await screen.findByText("No audits recorded.")
    await toggleAttribute("Maintainability")
    await toggleAttribute("Security")
    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: "Configure audit" }))
    await user.click(screen.getByRole("checkbox", { name: "Enable Functional adequacy · exploratory" }))
    expect(screen.queryByRole("textbox", { name: "Functional requirements" })).not.toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "Advanced settings for this run (developer)" }))
    const timeout = await screen.findByRole("spinbutton", { name: "functional_config · timeout_seconds" })
    expect(screen.queryByRole("spinbutton", { name: /max_tool_calls/ })).not.toBeInTheDocument()
    await user.type(timeout, "0")
    expect(screen.getByRole("alert")).toHaveTextContent("outside the allowed limits")
    await user.clear(timeout)
    await user.type(timeout, "47")
    await user.type(screen.getByRole("spinbutton", { name: "functional_config · max_wall_time_seconds" }), "88")
    expect(screen.queryByRole("spinbutton", { name: /provider_|max_model_calls|retrieval_top_k|embedding_model/ })).not.toBeInTheDocument()
    await user.keyboard("{Escape}")
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
    await user.click(screen.getByRole("button", { name: "Start audit" }))
    expect(api.startQualityAudit).toHaveBeenCalledWith(5, "main", "a".repeat(40), ["functional_adequacy"], {
      functional_requirements: [],
      attribute_options: { functional_adequacy: { functional_config: { timeout_seconds: 47, max_wall_time_seconds: 88 } } },
    })
    expect(operating.saveAuditSettings).not.toHaveBeenCalled()
  })

  it("blocks invalid run settings and can restore local defaults without saving global options", async () => {
    vi.mocked(api.listQualityAudits).mockResolvedValue([])
    show()
    await screen.findByText("No audits recorded.")
    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: "Configure audit" }))
    await user.click(screen.getByRole("button", { name: "Advanced settings for this run (developer)" }))
    await user.type(await screen.findByRole("spinbutton", { name: "security_config · max_scan_files" }), "101")
    await user.keyboard("{Escape}")
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
    expect(screen.getByRole("button", { name: "Start audit" })).toBeDisabled()
    await user.click(screen.getByRole("button", { name: "Configure audit" }))
    await user.click(screen.getByRole("button", { name: "Restore defaults" }))
    await user.keyboard("{Escape}")
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
    expect(screen.getByRole("button", { name: "Start audit" })).toBeEnabled()
    expect(operating.saveAuditSettings).not.toHaveBeenCalled()
    expect(api.startQualityAudit).not.toHaveBeenCalled()
  })

  it("retries unavailable parameter schemas and leaves inherited settings untouched", async () => {
    vi.mocked(api.listQualityAudits).mockResolvedValue([])
    vi.mocked(operating.getAuditSettings).mockRejectedValueOnce(new Error("offline"))
    show()
    await screen.findByText("No audits recorded.")
    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: "Configure audit" }))
    await user.click(screen.getByRole("button", { name: "Advanced settings for this run (developer)" }))
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load available settings.")
    await user.click(screen.getByRole("button", { name: "Retry" }))
    expect(await screen.findByRole("spinbutton", { name: "security_config · max_scan_files" })).toHaveValue(null)
    expect(operating.getAuditSettings).toHaveBeenCalledTimes(2)
    expect(operating.saveAuditSettings).not.toHaveBeenCalled()
  })

  it.each(["Completed", "Failed"])("offers results for a finalized %s audit without a report", async (executionStatus) => {
    vi.mocked(api.listQualityAudits).mockResolvedValue([{ id: 8, evaluationId: 4, branch: "main", commitHash: "a".repeat(40), attributes: ["maintainability"],
      executionStatus, auditStatus: executionStatus === "Failed" ? "failed" : "partial", error: null,
      createdAt: "2026-10-17T10:00:00Z", finishedAt: null, reportAvailable: false }])
    show()
    const article = await screen.findByRole("article")
    await openAuditMenu(article)
    expect(screen.getByRole("link", { name: "View details" })).toHaveAttribute("href", "/projects/5/audits/8")
  })

  it.each([false, true])("reuses historical selections without changing the original audit (separate views: %s)", async (separateViews) => {
    vi.mocked(api.listQualityAudits).mockResolvedValue([{
      id: 8, evaluationId: 4, branch: "old-branch", commitHash: "b".repeat(40), attributes: ["maintainability"],
      executionStatus: "Completed", auditStatus: "partial", error: null, createdAt: "2026-10-17T10:00:00Z", finishedAt: null,
      reportAvailable: false, configurationAvailable: true,
    }])
    const history: api.AuditConfigurationHistory = { configuration: {
      version: 1, branch: "old-branch", commitHash: "b".repeat(40), attributes: ["maintainability"], scopes: [{
        id: "maintainability", requiredAgents: [], techniques: [], investigators: [], subcharacteristics: [
          { id: "modularity", name: "Modularity", investigators: [{ id: "responsibility", name: "ResponsibilityAgent" }] },
        ],
      }],
    }, invocations: [] }
    const original = JSON.stringify(history)
    vi.mocked(api.getQualityAuditConfiguration).mockResolvedValue(history)
    vi.mocked(api.startQualityAudit).mockResolvedValue({ executionId: 44 })
    vi.mocked(listAgentSettings).mockResolvedValue([
      ...readyAgents,
      ...["modularity", "reusability"].map((agentType) => ({ agentType, qualityAttributes: ["maintainability"], workflowIds: [], configured: false, configuration: null })),
      ...["responsibility", "architecture_boundary"].map((agentType) => ({ agentType, name: agentType, role: "investigator", parentAgentTypes: ["modularity"],
        qualityAttributes: ["maintainability"], workflowIds: [], configured: false, configuration: null })),
    ])
    const user = userEvent.setup()
    const onConfigure = vi.fn()
    function Workspace() {
      const [view, setView] = useState<"all" | "history" | "configuration">(separateViews ? "history" : "all")
      return <QualityAudits projectId={5} branch="main" commitHash={"a".repeat(40)} canRun view={view}
        onConfigure={() => { onConfigure(); setView(separateViews ? "configuration" : "all") }} />
    }
    render(<MemoryRouter><Workspace /></MemoryRouter>)
    await screen.findByRole("article")
    const reuse = await screen.findByRole("button", { name: "Reuse configuration" })
    await waitFor(() => expect(reuse).toBeEnabled())
    await user.click(reuse)
    await waitFor(() => expect(onConfigure).toHaveBeenCalledOnce())
    const drawer = within(await screen.findByRole("dialog", { name: "Configure audit" }))
    expect(drawer.getByRole("checkbox", { name: "Enable Maintainability" })).toBeChecked()
    expect(drawer.getByRole("checkbox", { name: "Enable Security" })).not.toBeChecked()
    expect(drawer.getByRole("checkbox", { name: "Modularity" })).toBeChecked()
    expect(drawer.getByRole("checkbox", { name: "Reusability" })).not.toBeChecked()
    expect(drawer.getByText("Selections loaded. The current branch and commit are unchanged.")).toBeInTheDocument()
    expect(api.startQualityAudit).not.toHaveBeenCalled()
    expect(JSON.stringify(history)).toBe(original)
    await user.keyboard("{Escape}")
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
    await user.click(screen.getByRole("button", { name: "Start audit" }))
    await waitFor(() => expect(api.startQualityAudit).toHaveBeenCalledWith(5, "main", "a".repeat(40), ["maintainability"],
      { maintainability_selection: { modularity: ["responsibility"] } }))
    expect(api.getQualityAuditConfiguration).toHaveBeenCalledWith(5, 8, expect.any(AbortSignal))
    expect(JSON.stringify(history)).toBe(original)
  })

  it("restores ready scope defaults locally without revealing the hidden LLM mode", async () => {
    vi.mocked(api.listQualityAudits).mockResolvedValue([])
    vi.mocked(listAgentSettings).mockResolvedValue([
      ...readyAgents.filter((agent) => agent.agentType !== "security"),
      ...["modularity", "reusability"].map((agentType) => ({ agentType, qualityAttributes: ["maintainability"],
        workflowIds: [], configured: false, configuration: null })),
      ...["architecture_boundary", "responsibility"].map((agentType) => ({ agentType, name: agentType, role: "investigator",
        parentAgentTypes: ["modularity"], qualityAttributes: ["maintainability"], workflowIds: [], configured: false, configuration: null })),
      { agentType: "abstraction", name: "abstraction", role: "investigator", parentAgentTypes: ["reusability"],
        qualityAttributes: ["maintainability"], workflowIds: [], configured: false, configuration: null },
      { agentType: "unavailable", name: "Unavailable", role: "investigator", parentAgentTypes: ["modularity"], availability: "not_executed",
        qualityAttributes: ["maintainability"], workflowIds: [], configured: false, configuration: null },
      { agentType: "security", qualityAttributes: ["security"], workflowIds: [], configured: false, configuration: null },
    ])
    const fetch = vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("Unexpected settings write"))
    try {
      const user = userEvent.setup()
      show()
      await screen.findByText("No audits recorded.")
      await toggleAttribute("Functional adequacy")
      expect(screen.queryByRole("textbox", { name: "Functional requirements" })).not.toBeInTheDocument()
      await user.click(screen.getByRole("button", { name: "Configure audit" }))
      await user.click(screen.getByRole("checkbox", { name: "Reusability" }))
      await user.click(screen.getAllByText("View investigators")[0]!)
      await user.click(screen.getByRole("checkbox", { name: "architecture_boundary" }))
      await user.click(screen.getByRole("checkbox", { name: "Enable Security" }))
      // The partial-evaluation label is no longer surfaced in the configuration drawer.
      expect(screen.queryByText("Partial evaluation")).not.toBeInTheDocument()

      await user.click(screen.getByRole("button", { name: "Restore defaults" }))

      for (const name of ["Enable Maintainability", "Modularity", "Reusability", "architecture_boundary", "responsibility"]) {
        expect(screen.getByRole("checkbox", { name })).toBeChecked()
      }
      expect(screen.getByRole("checkbox", { name: "Enable Security" })).not.toBeChecked()
      expect(screen.getByRole("checkbox", { name: "Unavailable" })).toBeDisabled()
      expect(screen.getByRole("checkbox", { name: "Unavailable" })).not.toBeChecked()
      expect(screen.getByRole("checkbox", { name: "Enable Functional adequacy · exploratory" })).not.toBeChecked()
      expect(screen.queryByText("Partial evaluation")).not.toBeInTheDocument()
      expect(listAgentSettings).toHaveBeenCalledOnce()
      expect(api.startQualityAudit).not.toHaveBeenCalled()
      expect(fetch).not.toHaveBeenCalled()
      await user.click(screen.getByRole("checkbox", { name: "Enable Functional adequacy · exploratory" }))
      await user.keyboard("{Escape}")
      await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
      expect(screen.queryByRole("textbox", { name: "Functional requirements" })).not.toBeInTheDocument()
    } finally { fetch.mockRestore() }
  })

  it("disables restoring defaults when the registered agents cannot be loaded", async () => {
    vi.mocked(api.listQualityAudits).mockResolvedValue([])
    vi.mocked(listAgentSettings).mockRejectedValue(new Error("offline"))
    show()
    await screen.findByText("No audits recorded.")
    await userEvent.click(screen.getByRole("button", { name: "Configure audit" }))
    expect(screen.getByRole("button", { name: "Restore defaults" })).toBeDisabled()
  })

  it("keeps activation controls visible while independently collapsing enabled attribute content", async () => {
    vi.mocked(api.listQualityAudits).mockResolvedValue([])
    vi.mocked(listAgentSettings).mockResolvedValue([
      ...readyAgents,
      { agentType: "modularity", qualityAttributes: ["maintainability"], workflowIds: [], configured: false, configuration: null },
    ])
    const user = userEvent.setup()
    show()
    await screen.findByText("No audits recorded.")
    await user.click(screen.getByRole("button", { name: "Configure audit" }))
    await waitFor(() => expect(screen.getByRole("checkbox", { name: "Modularity" })).toBeEnabled())
    await user.click(screen.getByRole("button", { name: "Collapse Maintainability" }))
    expect(screen.queryByRole("checkbox", { name: "Modularity" })).not.toBeInTheDocument()
    expect(screen.getByRole("checkbox", { name: "Enable Maintainability" })).toBeChecked()
    expect(screen.getByRole("button", { name: "Expand Maintainability" })).toHaveAttribute("aria-expanded", "false")
    await user.click(screen.getByRole("button", { name: "Expand Maintainability" }))
    expect(screen.getByRole("checkbox", { name: "Modularity" })).toBeChecked()
    await user.click(screen.getByRole("checkbox", { name: "Enable Maintainability" }))
    expect(screen.queryByRole("checkbox", { name: "Modularity" })).not.toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Expand Maintainability" })).toBeDisabled()
    expect(screen.getByRole("checkbox", { name: "Enable Maintainability" })).not.toBeChecked()
    await user.click(screen.getByRole("checkbox", { name: "Enable Maintainability" }))
    expect(screen.getByRole("button", { name: "Collapse Maintainability" })).toHaveAttribute("aria-expanded", "true")
    expect(screen.getByRole("checkbox", { name: "Modularity" })).toBeChecked()
    expect(screen.getByRole("button", { name: "Expand Functional adequacy · exploratory" })).toBeDisabled()
    await user.click(screen.getByRole("checkbox", { name: "Enable Functional adequacy · exploratory" }))
    expect(screen.getByRole("button", { name: "Collapse Functional adequacy · exploratory" })).toHaveAttribute("aria-expanded", "true")
    expect(api.startQualityAudit).not.toHaveBeenCalled()
  })

  it("disables maintainability when the last subcharacteristic loses its last investigator", async () => {
    vi.mocked(api.listQualityAudits).mockResolvedValue([])
    vi.mocked(api.startQualityAudit).mockResolvedValue({ executionId: 43 })
    vi.mocked(listAgentSettings).mockResolvedValue([
      ...readyAgents,
      { agentType: "modularity", qualityAttributes: ["maintainability"], workflowIds: [], configured: false, configuration: null },
      { agentType: "responsibility", name: "ResponsibilityAgent", role: "investigator", parentAgentTypes: ["modularity"],
        qualityAttributes: ["maintainability"], workflowIds: [], configured: false, configuration: null },
    ])
    const user = userEvent.setup()
    show()
    await screen.findByText("No audits recorded.")
    await user.click(screen.getByRole("button", { name: "Configure audit" }))
    await waitFor(() => expect(screen.getByRole("checkbox", { name: "Modularity" })).toBeEnabled())
    await user.click(screen.getAllByText("View investigators")[0]!)
    await user.click(screen.getByRole("checkbox", { name: "ResponsibilityAgent" }))
    expect(within(screen.getByRole("dialog")).getByRole("heading", { name: "Maintainability" })).toBeInTheDocument()
    expect(screen.getByRole("checkbox", { name: "Enable Maintainability" })).not.toBeChecked()
    await user.keyboard("{Escape}")
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
    expect(screen.getByRole("region", { name: "Maintainability" })).toHaveTextContent("Disabled")
    await user.click(screen.getByRole("button", { name: "Start audit" }))
    await waitFor(() => expect(api.startQualityAudit).toHaveBeenCalledWith(5, "main", "a".repeat(40), ["security"]))
    await user.click(screen.getByRole("button", { name: "Configure audit" }))
    expect(screen.queryByRole("checkbox", { name: "Modularity" })).not.toBeInTheDocument()
    await user.click(screen.getByRole("checkbox", { name: "Enable Maintainability" }))
    await waitFor(() => expect(screen.getByRole("checkbox", { name: "Modularity" })).toBeChecked())
    expect(screen.getByRole("checkbox", { name: "Enable Maintainability" })).toBeChecked()
  })

  it("preserves hierarchy selections across drawer closes and submits only enabled investigators", async () => {
    vi.mocked(api.listQualityAudits).mockResolvedValue([])
    vi.mocked(api.startQualityAudit).mockResolvedValue({ executionId: 42 })
    vi.mocked(listAgentSettings).mockResolvedValue([
      ...readyAgents,
      ...["modularity", "reusability"].map((agentType) => ({ agentType, role: "coordinator", qualityAttributes: ["maintainability"],
        workflowIds: [], configured: false, configuration: null })),
      ...["architecture_boundary", "responsibility"].map((agentType) => ({ agentType, name: agentType, role: "investigator",
        parentAgentTypes: ["modularity"], qualityAttributes: ["maintainability"], workflowIds: [], configured: false, configuration: null })),
    ])
    const user = userEvent.setup()
    show()
    await screen.findByText("No audits recorded.")
    await toggleAttribute("Security")
    await user.click(screen.getByRole("button", { name: "Configure audit" }))
    const drawer = within(screen.getByRole("dialog"))
    await waitFor(() => expect(drawer.getByRole("checkbox", { name: "Modularity" })).toBeEnabled())
    await user.click(drawer.getByRole("checkbox", { name: "Reusability" }))
    await user.click(drawer.getAllByText("View investigators")[0]!)
    await user.click(drawer.getByRole("checkbox", { name: "architecture_boundary" }))
    await user.keyboard("{Escape}")
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
    await user.click(screen.getByRole("button", { name: "Configure audit" }))
    await waitFor(() => expect(screen.getByRole("checkbox", { name: "Modularity" })).toBeEnabled())
    expect(screen.getByRole("checkbox", { name: "Reusability" })).not.toBeChecked()
    await user.keyboard("{Escape}")
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
    await user.click(screen.getByRole("button", { name: "Start audit" }))
    await waitFor(() => expect(api.startQualityAudit).toHaveBeenCalledWith(5, "main", "a".repeat(40), ["maintainability"],
      { maintainability_selection: { modularity: ["responsibility"] } }))
    const summary = within(screen.getByRole("region", { name: "Maintainability" }))
    expect(summary.getByText("Responsibilities")).toBeInTheDocument()
    expect(summary.queryByText("Architectural boundaries")).not.toBeInTheDocument()
    expect(summary.queryByRole("heading", { name: "Reusability" })).not.toBeInTheDocument()
    expect(listAgentSettings).toHaveBeenCalledOnce()
  })

  it("keeps every attribute section visible and localizes the configuration without starting an audit", async () => {
    vi.mocked(api.listQualityAudits).mockResolvedValue([])
    const user = userEvent.setup()
    show()
    await screen.findByText("No audits recorded.")
    await toggleAttribute("Security")
    await toggleAttribute("Functional adequacy")
    const trigger = screen.getByRole("button", { name: "Configure audit" })
    await user.click(trigger)

    const drawer = screen.getByRole("dialog", { name: "Configure audit" })
    expect(within(drawer).getByRole("heading", { name: "Maintainability" })).toBeInTheDocument()
    expect(within(drawer).getByRole("heading", { name: "Functional adequacy · exploratory" })).toBeInTheDocument()
    expect(within(drawer).getByRole("heading", { name: "Security" })).toBeInTheDocument()
    expect(within(drawer).getByRole("checkbox", { name: "Enable Security" })).not.toBeChecked()
    expect(api.startQualityAudit).not.toHaveBeenCalled()

    await changeLanguage("es")
    expect(screen.getByRole("dialog", { name: "Configurar auditoría" })).toBeInTheDocument()
    await user.keyboard("{Escape}")
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
    await waitFor(() => expect(trigger).toHaveFocus())
  })

  it("keeps configuration sections available when all attributes are disabled", async () => {
    vi.mocked(api.listQualityAudits).mockResolvedValue([])
    const user = userEvent.setup()
    show()
    await screen.findByText("No audits recorded.")
    await toggleAttribute("Maintainability")
    await toggleAttribute("Security")
    await user.click(screen.getByRole("button", { name: "Configure audit" }))

    const drawer = within(screen.getByRole("dialog"))
    expect(drawer.getByText("Enable at least one attribute in this panel to start the audit.")).toBeInTheDocument()
    for (const name of ["Maintainability", "Security", "Functional adequacy · exploratory"]) {
      expect(drawer.getByRole("heading", { name })).toBeInTheDocument()
      expect(drawer.getByRole("checkbox", { name: `Enable ${name}` })).not.toBeChecked()
    }
    expect(api.startQualityAudit).not.toHaveBeenCalled()
  })

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

  it.each([false, true])("always starts exploratory functional adequacy (joint: %s)", async (joint) => {
    vi.mocked(api.listQualityAudits).mockResolvedValue([])
    vi.mocked(api.startQualityAudit).mockResolvedValue({ executionId: 12 })
    show()
    await screen.findByText("No audits recorded.")
    if (!joint) {
      await toggleAttribute("Maintainability")
      await toggleAttribute("Security")
    }
    await toggleAttribute("Functional adequacy")
    expect(screen.getByRole("button", { name: "Start audit" })).toBeEnabled()
    expect(screen.queryByRole("textbox", { name: "Functional requirements" })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: "Start audit" }))
    await waitFor(() => expect(api.startQualityAudit).toHaveBeenCalledWith(5, "main", "a".repeat(40),
      [...(joint ? ["maintainability", "security"] : []), "functional_adequacy"], {
        functional_requirements: [],
      }))
  })
  it("starts exploration without a functional model and never exposes requirements", async () => {
    vi.mocked(api.listQualityAudits).mockResolvedValue([])
    vi.mocked(api.startQualityAudit).mockResolvedValue({ executionId: 12 })
    vi.mocked(listAgentSettings).mockResolvedValue(readyAgents.map((agent) => agent.agentType === "functional_adequacy"
      ? { ...agent, configured: false } : agent))
    show()
    await screen.findByText("No audits recorded.")
    await toggleAttribute("Maintainability")
    await toggleAttribute("Security")
    await toggleAttribute("Functional adequacy")
    const start = screen.getByRole("button", { name: "Start audit" })
    expect(start).toBeEnabled()
    expect(screen.queryByRole("textbox", { name: "Functional requirements" })).not.toBeInTheDocument()
    await userEvent.click(start)
    await waitFor(() => expect(api.startQualityAudit).toHaveBeenCalledWith(5, "main", "a".repeat(40),
      ["functional_adequacy"], { functional_requirements: [] }))
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
    await toggleAttribute("Security")
    await toggleAttribute("Maintainability")
    expect(screen.getByRole("button", { name: "Start audit" })).toBeDisabled()
    await toggleAttribute("Maintainability")
    await userEvent.click(screen.getByRole("button", { name: "Start audit" }))
    await waitFor(() => expect(api.startQualityAudit).toHaveBeenCalledWith(5, "main", "a".repeat(40), ["maintainability"]))
  })

  it("links to dedicated results for a completed partial audit and permits downloading its report", async () => {
    vi.mocked(api.listQualityAudits).mockResolvedValue([{
      id: 8, evaluationId: 4, branch: "main", commitHash: "a".repeat(40), attributes: ["maintainability"],
      executionStatus: "Completed", auditStatus: "partial", error: null, runId: "bdeb6efb73bd45fe9cb193f54710cf60",
      createdAt: "2026-10-17T10:00:00Z", finishedAt: "2026-10-17T10:05:00Z", reportAvailable: true,
    }])
    show()
    expect(await screen.findByText("Partial evaluation")).toBeInTheDocument()
    // The full run ID is kept for the detail page, not the explorer row.
    expect(screen.queryByText("bdeb6efb73bd45fe9cb193f54710cf60")).not.toBeInTheDocument()
    expect(api.getQualityAudit).not.toHaveBeenCalled()
    const article = screen.getByRole("article")
    expect(within(article).getByRole("link", { name: "View details" })).toHaveAttribute("href", "/projects/5/audits/8")
    await openAuditMenu(article)
    expect(screen.getByRole("link", { name: "View Blackboard" })).toBeInTheDocument()
    expect(screen.queryByRole("heading", { name: "Audit report · #8" })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: "Download Word report" }))
    expect(api.downloadQualityAuditReport).toHaveBeenCalledWith(5, 8)
  })

  it("keeps historical functional audits generic instead of relabeling them as exploratory", async () => {
    const historical = { ...historicalSummary, attributes: ["functional_adequacy"] }
    const original = JSON.stringify(historical)
    vi.mocked(api.listQualityAudits).mockResolvedValue([historical])
    render(<MemoryRouter><QualityAudits projectId={5} branch="main" commitHash={"a".repeat(40)} canRun view="history" /></MemoryRouter>)
    const article = await screen.findByRole("article")
    expect(within(article).getByRole("heading", { name: /Functional adequacy · #8/ })).toBeInTheDocument()
    expect(article).not.toHaveTextContent("Functional adequacy · exploratory")
    await openAuditMenu(article)
    expect(screen.getByRole("link", { name: "View details" })).toHaveAttribute("href", "/projects/5/audits/8")
    expect(JSON.stringify(historical)).toBe(original)
    expect(api.getQualityAuditReport).not.toHaveBeenCalled()
  })

  it("starts security independently with the selected revision", async () => {
    vi.mocked(api.listQualityAudits).mockResolvedValue([])
    vi.mocked(api.startQualityAudit).mockResolvedValue({ executionId: 9 })
    show()
    await screen.findByText("No audits recorded.")
    await toggleAttribute("Maintainability")
    expect(screen.getByRole("region", { name: "Maintainability" })).toHaveTextContent("Disabled")
    await userEvent.click(screen.getByRole("button", { name: "Start audit" }))
    await waitFor(() => expect(api.startQualityAudit).toHaveBeenCalledWith(5, "main", "a".repeat(40), ["security"]))
  })

  it("selects both attributes by default and starts them as one audit request", async () => {
    vi.mocked(api.listQualityAudits).mockResolvedValue([])
    vi.mocked(api.startQualityAudit).mockResolvedValue({ executionId: 10 })
    const openSettings = vi.fn()
    show({ openSettings })
    await screen.findByText("No audits recorded.")
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument()
    expect(screen.getByRole("region", { name: "Security" })).toHaveTextContent("Enabled")
    expect(screen.getByRole("region", { name: "Maintainability" })).toHaveTextContent("Enabled")
    expect(screen.getByRole("region", { name: "Functional adequacy · exploratory" })).toHaveTextContent("Disabled")
    const settingsButton = screen.getByRole("button", { name: "Configure agents" })
    expect(settingsButton).toHaveClass("ui-button", "ui-button-secondary")
    await userEvent.click(settingsButton)
    expect(openSettings).toHaveBeenCalledWith("agents")
    await userEvent.click(screen.getByRole("button", { name: "Start audit" }))
    await waitFor(() => expect(api.startQualityAudit).toHaveBeenCalledWith(5, "main", "a".repeat(40), ["maintainability", "security"]))
    expect(api.startQualityAudit).toHaveBeenCalledOnce()
  })

  it("keeps View Details and Reuse Configuration visible while the audit is still running", async () => {
    vi.mocked(api.listQualityAudits).mockResolvedValue([{
      id: 9, evaluationId: 4, runId: "c".repeat(32), branch: "main", commitHash: "a".repeat(40),
      attributes: ["maintainability"], executionStatus: "Running", auditStatus: null, error: null,
      createdAt: "2026-10-17T10:00:00Z", finishedAt: null, reportAvailable: false,
    }])
    show()
    // The full run ID stays out of the explorer row.
    expect(screen.queryByText("c".repeat(32))).not.toBeInTheDocument()
    const article = await screen.findByRole("article")
    expect(within(article).getByRole("link", { name: "View details" })).toHaveAttribute("href", "/projects/5/audits/9")
    expect(within(article).getByRole("button", { name: "Reuse configuration" })).toBeInTheDocument()
    // A running audit has no report yet, so no extra request is made for it.
    expect(api.getQualityAuditReport).not.toHaveBeenCalled()
    await openAuditMenu(article)
    expect((screen.getByRole("link", { name: "View Blackboard" })).getAttribute("href"))
      .toBe(`http://localhost:7502/blackboard?run_id=${"c".repeat(32)}`)
    expect(screen.queryByRole("button", { name: "Download Word report" })).not.toBeInTheDocument()
  })

  it("disables the Blackboard menu action while the run id is still starting", async () => {
    vi.mocked(api.listQualityAudits).mockResolvedValue([{
      id: 10, evaluationId: 4, runId: null, branch: "main", commitHash: "a".repeat(40),
      attributes: ["maintainability"], executionStatus: "Running", auditStatus: null, error: null,
      createdAt: "2026-10-17T10:00:00Z", finishedAt: null, reportAvailable: false,
    }])
    show()
    await screen.findByRole("article")
    await openAuditMenu()
    expect(screen.getByRole("button", { name: "View Blackboard" })).toBeDisabled()
  })

  it("translates history links and the exploratory label without revealing LLM mode or making requests", async () => {
    vi.mocked(api.listQualityAudits).mockResolvedValue([{
      id: 8, evaluationId: 4, branch: "main", commitHash: "a".repeat(40), attributes: ["maintainability"],
      executionStatus: "Completed", auditStatus: "partial", error: null, runId: "report-run-id",
      createdAt: "2026-10-17T10:00:00Z", finishedAt: "2026-10-17T10:05:00Z", reportAvailable: true,
    }])
    vi.mocked(api.getQualityAudit).mockResolvedValue(historicalSummary)
    show()
    expect(await screen.findByText("Partial evaluation")).toBeInTheDocument()
    await toggleAttribute("Functional adequacy")
    expect(screen.queryByRole("textbox", { name: "Functional requirements" })).not.toBeInTheDocument()
    await openAuditMenu()
    expect(screen.getByRole("link", { name: "View details" })).toHaveAttribute("href", "/projects/5/audits/8")
    expect(api.getQualityAudit).not.toHaveBeenCalled()
    const requestCounts = [vi.mocked(api.listQualityAudits).mock.calls.length, vi.mocked(api.getQualityAudit).mock.calls.length]

    await changeLanguage("es")

    expect(screen.getByRole("heading", { name: "Auditoría de calidad" })).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Ver detalles" })).toHaveAttribute("href", "/projects/5/audits/8")
    expect(screen.getByRole("heading", { name: "Auditorías del proyecto" })).toBeInTheDocument()
    expect(screen.getByRole("region", { name: "Adecuación funcional · exploratoria" })).toHaveTextContent("Activado")
    expect(screen.queryByRole("textbox", { name: "Requisitos funcionales" })).not.toBeInTheDocument()
    // The full run ID is not exposed in the explorer row; the Blackboard target carries it.
    expect(screen.queryByText("report-run-id")).not.toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Ver Blackboard" })).toHaveAttribute("href", expect.stringContaining("run_id=report-run-id"))
    expect(api.startQualityAudit).not.toHaveBeenCalled()
    expect([vi.mocked(api.listQualityAudits).mock.calls.length, vi.mocked(api.getQualityAudit).mock.calls.length]).toEqual(requestCounts)
    expect(api.getQualityAuditReport).not.toHaveBeenCalled()
  })

  it("filters evaluation runs by status before paginating and resets to the first page", async () => {
    const make = (id: number, executionStatus: string, auditStatus: string | null): api.QualityAuditSummary => ({
      id, evaluationId: 4, branch: "main", commitHash: "a".repeat(40), attributes: ["maintainability"],
      executionStatus, auditStatus, error: null, runId: `run-${id}`,
      createdAt: `2026-02-${String(id).padStart(2, "0")}T12:00:00Z`, finishedAt: null, reportAvailable: false,
    })
    vi.mocked(api.listQualityAudits).mockResolvedValue([
      make(1, "Completed", "completed"), make(2, "Completed", "partial"), make(3, "Failed", "failed"),
      make(4, "Running", null), make(5, "Completed", "completed"), make(6, "Completed", "partial"),
      make(7, "Failed", "failed"),
    ])
    const user = userEvent.setup()
    showHistory()
    await screen.findAllByRole("article")
    // Defaults to the unfiltered, newest-first explorer.
    expect(screen.getByRole("tab", { name: "All" })).toHaveAttribute("aria-selected", "true")
    await user.click(screen.getAllByRole("button", { name: "Next page" })[0])
    expect(within(screen.getAllByRole("article")[0]).getByRole("heading")).toHaveTextContent("#2")
    expect(screen.getAllByText("Page 2 of 2")).toHaveLength(2)
    // Switching the filter resets pagination and applies the filter before slicing.
    await user.click(screen.getByRole("tab", { name: "Partial" }))
    expect(screen.getByRole("tab", { name: "Partial" })).toHaveAttribute("aria-selected", "true")
    await waitFor(() => expect(screen.getAllByRole("article")).toHaveLength(2))
    expect(screen.getAllByRole("article").map((article) => within(article).getByRole("heading").textContent)).toEqual(
      ["Maintainability · #2", "Maintainability · #6"])
    // The filtered set fits on one page, so the shared pager renders no page nav.
    expect(screen.queryByRole("navigation", { name: "Audit history pages" })).toBeNull()
    // A filter with no matches shows the filtered empty state, not the generic one.
    await user.click(screen.getByRole("tab", { name: "Failed" }))
    await waitFor(() => expect(screen.getAllByRole("article")).toHaveLength(2))
    await user.click(screen.getByRole("tab", { name: "Completed" }))
    await waitFor(() => expect(screen.getAllByRole("article")).toHaveLength(2))
    expect(screen.getAllByRole("article").map((article) => within(article).getByRole("heading").textContent)).toEqual(
      ["Maintainability · #1", "Maintainability · #5"])
  })

  it("shows an empty state when a status filter has no matching runs", async () => {
    vi.mocked(api.listQualityAudits).mockResolvedValue([{
      id: 8, evaluationId: 4, branch: "main", commitHash: "a".repeat(40), attributes: ["maintainability"],
      executionStatus: "Completed", auditStatus: "completed", error: null, runId: "run-8",
      createdAt: "2026-10-17T10:00:00Z", finishedAt: null, reportAvailable: false,
    }])
    showHistory()
    await screen.findByRole("article")
    await userEvent.click(screen.getByRole("tab", { name: "Failed" }))
    expect(await screen.findByText("No audits recorded for this filter.")).toBeVisible()
    expect(screen.queryByRole("combobox", { name: "Audits per page" })).toBeNull()
  })

  it("keeps the row menu keyboard accessible with the secondary actions", async () => {
    vi.mocked(api.listQualityAudits).mockResolvedValue([{ ...historicalSummary, configurationAvailable: true }])
    show()
    const user = userEvent.setup()
    await screen.findByRole("article")
    const trigger = screen.getByRole("button", { name: /More actions for audit #8/ })
    trigger.focus()
    await user.keyboard("{Enter}")
    expect(await screen.findByRole("button", { name: "View configuration" })).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "View details" })).toBeInTheDocument()
    await user.keyboard("{Escape}")
    await waitFor(() => expect(screen.queryByRole("button", { name: "View configuration" })).not.toBeInTheDocument())
    await waitFor(() => expect(trigger).toHaveFocus())
  })
})
