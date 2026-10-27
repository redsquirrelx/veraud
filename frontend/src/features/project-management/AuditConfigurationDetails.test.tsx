import { afterEach, describe, expect, it, vi } from "vitest"
import { cleanup, render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { changeLanguage } from "../../shared/i18n/index.ts"
import { AuditConfigurationDetails } from "./AuditConfigurationDetails.tsx"
import { getQualityAuditConfiguration, type AuditConfigurationHistory } from "./qualityAuditApi.ts"

vi.mock("./qualityAuditApi.ts", () => ({ getQualityAuditConfiguration: vi.fn() }))

afterEach(async () => { cleanup(); vi.resetAllMocks(); await changeLanguage("en") })

const history: AuditConfigurationHistory = {
  configuration: { version: 1, branch: "release-original", commitHash: "b".repeat(40), attributes: ["maintainability"], scopes: [{
    id: "maintainability", requiredAgents: [{ id: "maintainability_manager", name: "Original manager" }], techniques: [], investigators: [],
    subcharacteristics: [{ id: "modularity", name: "Original coordinator", investigators: [{ id: "original_investigator", name: "Original investigator" }] }],
  }] },
  invocations: [{ id: "receipt-1", agentId: "original_investigator", status: "completed" }],
}

describe("audit configuration history", () => {
  it("loads the saved revision and participants on demand without exposing editable settings", async () => {
    vi.mocked(getQualityAuditConfiguration).mockResolvedValue(history)
    const user = userEvent.setup()
    render(<AuditConfigurationDetails projectId={5} auditId={8} available />)
    expect(getQualityAuditConfiguration).not.toHaveBeenCalled()
    await user.click(screen.getByRole("button", { name: "View configuration" }))
    const drawer = within(screen.getByRole("dialog", { name: "Audit configuration · #8" }))
    expect(await drawer.findByText("release-original")).toBeInTheDocument()
    expect(drawer.getByText("b".repeat(40))).toBeInTheDocument()
    expect(drawer.getByRole("heading", { name: "Modularity" })).toBeInTheDocument()
    expect(drawer.getAllByText("Original investigator").length).toBeGreaterThan(0)
    expect(drawer.queryByRole("checkbox")).not.toBeInTheDocument()
    expect(getQualityAuditConfiguration).toHaveBeenCalledWith(5, 8, expect.any(AbortSignal))
    await user.click(drawer.getByText("Invoked agents"))
    expect(drawer.getByText("Completed")).toBeVisible()
    await changeLanguage("es")
    expect(screen.getByRole("dialog", { name: "Configuración de auditoría · #8" })).toBeInTheDocument()
    expect(getQualityAuditConfiguration).toHaveBeenCalledOnce()
  })

  it("does not invent configurations for historical runs", () => {
    render(<AuditConfigurationDetails projectId={5} auditId={1} available={false} />)
    expect(screen.getByRole("button", { name: "View configuration" })).toBeDisabled()
    expect(getQualityAuditConfiguration).not.toHaveBeenCalled()
  })

  it("allows retrying a failed history request", async () => {
    vi.mocked(getQualityAuditConfiguration).mockRejectedValueOnce(new Error("offline")).mockResolvedValue(history)
    render(<AuditConfigurationDetails projectId={5} auditId={8} available />)
    await userEvent.click(screen.getByRole("button", { name: "View configuration" }))
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load this audit's configuration.")
    await userEvent.click(screen.getByRole("button", { name: "Retry" }))
    expect(await screen.findByText("release-original")).toBeInTheDocument()
  })
})
