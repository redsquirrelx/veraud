import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { cleanup, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { changeLanguage } from "../../shared/i18n/index.ts"
import { ApiError, listAgentSettings } from "../../infrastructure/http-client/httpClient.ts"
import { QualityAudits } from "./QualityAudits.tsx"
import { AnalyzeMenu } from "./AnalyzeMenu.tsx"
import * as api from "./qualityAuditApi.ts"

vi.mock("./qualityAuditApi.ts", () => ({
  listQualityAudits: vi.fn(), startQualityAudit: vi.fn(), getQualityAuditReport: vi.fn(), downloadQualityAuditReport: vi.fn(),
  getQualityAuditConfiguration: vi.fn(),
}))

vi.mock("../../infrastructure/http-client/httpClient.ts", async (importOriginal) => ({
  ...await importOriginal<typeof import("../../infrastructure/http-client/httpClient.ts")>(),
  listAgentSettings: vi.fn(),
}))

beforeEach(() => { vi.mocked(listAgentSettings).mockResolvedValue([]) })
afterEach(async () => { cleanup(); vi.resetAllMocks(); await changeLanguage("en") })

function show() {
  render(<MemoryRouter><QualityAudits projectId={5} branch="main" commitHash={"a".repeat(40)} canRun /></MemoryRouter>)
}

async function toggleAttribute(name: string) {
  await userEvent.click(screen.getByRole("button", { name: "Configure audit" }))
  await userEvent.click(screen.getByRole("checkbox", { name: `Enable ${name}` }))
  await userEvent.keyboard("{Escape}")
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
}

describe("project quality audits", () => {
  it("reuses historical selections for the current revision without changing or restarting the original audit", async () => {
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
      ...["modularity", "reusability"].map((agentType) => ({ agentType, qualityAttributes: ["maintainability"], workflowIds: [], configured: false, configuration: null })),
      ...["responsibility", "architecture_boundary"].map((agentType) => ({ agentType, name: agentType, role: "investigator", parentAgentTypes: ["modularity"],
        qualityAttributes: ["maintainability"], workflowIds: [], configured: false, configuration: null })),
    ])
    const user = userEvent.setup()
    show()
    const reuse = await screen.findByRole("button", { name: "Reuse configuration" })
    await waitFor(() => expect(reuse).toBeEnabled())
    await user.click(reuse)
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

  it("restores available scope defaults locally without saving global agent settings or clearing requirements", async () => {
    vi.mocked(api.listQualityAudits).mockResolvedValue([])
    vi.mocked(listAgentSettings).mockResolvedValue([
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
      await user.type(screen.getByRole("textbox", { name: "Functional requirements" }), "Keep this requirement.")
      await user.click(screen.getByRole("button", { name: "Configure audit" }))
      await user.click(screen.getByRole("checkbox", { name: "Reusability" }))
      await user.click(screen.getAllByText("View investigators")[0]!)
      await user.click(screen.getByRole("checkbox", { name: "architecture_boundary" }))
      await user.click(screen.getByRole("checkbox", { name: "Enable Security" }))
      expect(screen.getByText("Partial evaluation")).toBeInTheDocument()

      await user.click(screen.getByRole("button", { name: "Restore defaults" }))

      for (const name of ["Enable Maintainability", "Enable Security", "Modularity", "Reusability", "architecture_boundary", "responsibility"]) {
        expect(screen.getByRole("checkbox", { name })).toBeChecked()
      }
      expect(screen.getByRole("checkbox", { name: "Unavailable" })).toBeDisabled()
      expect(screen.getByRole("checkbox", { name: "Unavailable" })).not.toBeChecked()
      expect(screen.getByRole("checkbox", { name: "Enable Functional adequacy" })).not.toBeChecked()
      expect(screen.queryByText("Partial evaluation")).not.toBeInTheDocument()
      expect(listAgentSettings).toHaveBeenCalledOnce()
      expect(api.startQualityAudit).not.toHaveBeenCalled()
      expect(fetch).not.toHaveBeenCalled()
      await user.click(screen.getByRole("checkbox", { name: "Enable Functional adequacy" }))
      await user.keyboard("{Escape}")
      await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
      expect(screen.getByRole("textbox", { name: "Functional requirements" })).toHaveValue("Keep this requirement.")
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
    expect(screen.getByRole("button", { name: "Expand Functional adequacy" })).toBeDisabled()
    await user.click(screen.getByRole("checkbox", { name: "Enable Functional adequacy" }))
    expect(screen.getByRole("button", { name: "Collapse Functional adequacy" })).toHaveAttribute("aria-expanded", "true")
    expect(api.startQualityAudit).not.toHaveBeenCalled()
  })

  it("disables maintainability when the last subcharacteristic loses its last investigator", async () => {
    vi.mocked(api.listQualityAudits).mockResolvedValue([])
    vi.mocked(api.startQualityAudit).mockResolvedValue({ executionId: 43 })
    vi.mocked(listAgentSettings).mockResolvedValue([
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
    expect(within(drawer).getByRole("heading", { name: "Functional adequacy" })).toBeInTheDocument()
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
    for (const name of ["Maintainability", "Security", "Functional adequacy"]) {
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

  it.each([false, true])("starts functional adequacy with explicit requirements (joint: %s)", async (joint) => {
    vi.mocked(api.listQualityAudits).mockResolvedValue([])
    vi.mocked(api.startQualityAudit).mockResolvedValue({ executionId: 12 })
    show()
    await screen.findByText("No audits recorded.")
    if (!joint) {
      await toggleAttribute("Maintainability")
      await toggleAttribute("Security")
    }
    await toggleAttribute("Functional adequacy")
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
    await toggleAttribute("Security")
    await toggleAttribute("Maintainability")
    expect(screen.getByRole("button", { name: "Start audit" })).toBeDisabled()
    await toggleAttribute("Maintainability")
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
    await toggleAttribute("Maintainability")
    expect(screen.getByRole("region", { name: "Maintainability" })).toHaveTextContent("Disabled")
    await userEvent.click(screen.getByRole("button", { name: "Start audit" }))
    await waitFor(() => expect(api.startQualityAudit).toHaveBeenCalledWith(5, "main", "a".repeat(40), ["security"]))
  })

  it("selects both attributes by default and starts them as one audit request", async () => {
    vi.mocked(api.listQualityAudits).mockResolvedValue([])
    vi.mocked(api.startQualityAudit).mockResolvedValue({ executionId: 10 })
    show()
    await screen.findByText("No audits recorded.")
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument()
    expect(screen.getByRole("region", { name: "Security" })).toHaveTextContent("Enabled")
    expect(screen.getByRole("region", { name: "Maintainability" })).toHaveTextContent("Enabled")
    expect(screen.getByRole("region", { name: "Functional adequacy" })).toHaveTextContent("Disabled")
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
    await toggleAttribute("Functional adequacy")
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
    expect(screen.getByRole("region", { name: "Adecuación funcional" })).toHaveTextContent("Activado")
    expect(screen.getByRole("textbox", { name: "Requisitos funcionales" })).toHaveValue("Requirement one.\nRequirement two.")
    expect(screen.getByText("Original report conclusion.")).toBeInTheDocument()
    expect(screen.getByText("Original report content")).toBeInTheDocument()
    expect(screen.getByText("Referencias de origen (2)")).toBeInTheDocument()
    expect(screen.getAllByText("report-run-id").length).toBeGreaterThanOrEqual(2)
    expect(api.startQualityAudit).not.toHaveBeenCalled()
    expect([vi.mocked(api.listQualityAudits).mock.calls.length, vi.mocked(api.getQualityAuditReport).mock.calls.length]).toEqual(requestCounts)
  })
})
