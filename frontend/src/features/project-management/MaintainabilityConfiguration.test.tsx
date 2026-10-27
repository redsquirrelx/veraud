import { afterEach, describe, expect, it, vi } from "vitest"
import { cleanup, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { listAgentSettings, type AgentSettings } from "../../infrastructure/http-client/httpClient.ts"
import { changeLanguage } from "../../shared/i18n/index.ts"
import { MaintainabilityConfiguration } from "./MaintainabilityConfiguration.tsx"

vi.mock("../../infrastructure/http-client/httpClient.ts", () => ({ listAgentSettings: vi.fn() }))

afterEach(async () => { cleanup(); vi.resetAllMocks(); await changeLanguage("en") })

function agent(agentType: string, availability = "available"): AgentSettings {
  return { agentType, availability, qualityAttributes: ["maintainability"], workflowIds: ["quality-audit"], configured: false, configuration: null }
}

describe("maintainability configuration", () => {
  it("discovers investigators from catalog relationships and toggles them independently", async () => {
    vi.mocked(listAgentSettings).mockResolvedValue([
      { ...agent("modularity"), childAgentTypes: ["architecture_boundary", "responsibility", "blocked"] },
      agent("reusability"),
      { ...agent("architecture_boundary"), role: "investigator", name: "ArchitectureBoundaryAgent" },
      { ...agent("responsibility"), role: "investigator", name: "ResponsibilityAgent" },
      { ...agent("blocked", "not_executed"), role: "investigator", name: "BlockedAgent" },
      { ...agent("abstraction"), role: "investigator", name: "AbstractionAgent", parentAgentTypes: ["reusability"] },
      { ...agent("unrelated"), role: "investigator", name: "UnrelatedAgent" },
    ])
    const user = userEvent.setup()
    render(<MaintainabilityConfiguration />)
    await waitFor(() => expect(screen.getByRole("checkbox", { name: "Modularity" })).toBeEnabled())
    expect(screen.getAllByText("View investigators")).toHaveLength(5)
    expect(screen.queryByRole("status")).not.toBeInTheDocument()
    await user.click(screen.getAllByText("View investigators")[0]!)
    const boundary = screen.getByRole("checkbox", { name: "ArchitectureBoundaryAgent" })
    expect(boundary).toBeChecked()
    expect(screen.getByText("Evaluates whether dependencies respect architectural boundaries and design principles.")).toBeVisible()
    expect(screen.getByRole("checkbox", { name: "BlockedAgent" })).toBeDisabled()
    expect(screen.getByRole("checkbox", { name: "BlockedAgent" })).not.toBeChecked()
    const modularityDetails = screen.getAllByText("View investigators")[0]!.closest("details")!
    expect(within(modularityDetails).queryByRole("checkbox", { name: "AbstractionAgent" })).not.toBeInTheDocument()
    expect(screen.queryByRole("checkbox", { name: "UnrelatedAgent" })).not.toBeInTheDocument()
    await user.click(boundary)
    expect(boundary).not.toBeChecked()
    expect(screen.getByText("Partial evaluation")).toBeInTheDocument()
    expect(screen.getByRole("status")).toHaveTextContent("The audit result will be partial because not all available investigators are selected.")
    await user.click(boundary)
    expect(screen.queryByRole("status")).not.toBeInTheDocument()
    expect(screen.queryByText("Partial evaluation")).not.toBeInTheDocument()
    await user.click(boundary)
    expect(screen.getByRole("checkbox", { name: "ResponsibilityAgent" })).toBeChecked()
    await user.click(screen.getByRole("checkbox", { name: "Modularity" }))
    expect(boundary).toBeDisabled()
    await user.click(screen.getByRole("checkbox", { name: "Modularity" }))
    expect(boundary).toBeEnabled()
    expect(boundary).not.toBeChecked()
    await user.click(screen.getAllByText("View investigators")[1]!)
    expect(screen.getByRole("checkbox", { name: "AbstractionAgent" })).toBeChecked()
    await changeLanguage("es")
    expect(screen.getAllByText("Ver investigadores")).toHaveLength(5)
    expect(screen.getByRole("status")).toHaveTextContent("El resultado de la auditoría será parcial porque no están seleccionados todos los investigadores disponibles.")
    expect(screen.getByText("Evaluación parcial")).toBeInTheDocument()
    expect(listAgentSettings).toHaveBeenCalledOnce()
  })

  it("deselects a subcharacteristic when its last investigator is disabled and restores defaults when reselected", async () => {
    vi.mocked(listAgentSettings).mockResolvedValue([
      agent("modularity"), agent("reusability"),
      { ...agent("responsibility"), role: "investigator", name: "ResponsibilityAgent", parentAgentTypes: ["modularity"] },
      { ...agent("abstraction"), role: "investigator", name: "AbstractionAgent", parentAgentTypes: ["reusability"] },
    ])
    const onChange = vi.fn()
    const user = userEvent.setup()
    render(<MaintainabilityConfiguration onChange={onChange} />)
    await waitFor(() => expect(screen.getByRole("checkbox", { name: "Modularity" })).toBeEnabled())
    await user.click(screen.getAllByText("View investigators")[0]!)
    await user.click(screen.getByRole("checkbox", { name: "ResponsibilityAgent" }))
    expect(screen.getByRole("checkbox", { name: "Modularity" })).not.toBeChecked()
    expect(onChange).toHaveBeenLastCalledWith({ reusability: ["abstraction"] })
    await user.click(screen.getByRole("checkbox", { name: "Modularity" }))
    expect(screen.getByRole("checkbox", { name: "ResponsibilityAgent" })).toBeChecked()
    await user.click(screen.getByRole("checkbox", { name: "Modularity" }))
    await user.click(screen.getByRole("checkbox", { name: "Reusability" }))
    expect(onChange).toHaveBeenLastCalledWith({})
  })

  it("selects only registered, available subcharacteristics by default regardless of model configuration", async () => {
    vi.mocked(listAgentSettings).mockResolvedValue([
      agent("modularity"), agent("reusability"), agent("testability", "not_implemented"),
      { ...agent("modifiability"), qualityAttributes: ["security"] },
    ])
    render(<MaintainabilityConfiguration />)

    await waitFor(() => expect(screen.getByRole("checkbox", { name: "Modularity" })).toBeEnabled())
    expect(screen.getAllByRole("checkbox")).toHaveLength(5)
    for (const name of ["Modularity", "Reusability"]) expect(screen.getByRole("checkbox", { name })).toBeChecked()
    for (const name of ["Analyzability", "Modifiability", "Testability"]) {
      expect(screen.getByRole("checkbox", { name })).toBeDisabled()
      expect(screen.getByRole("checkbox", { name })).not.toBeChecked()
    }
    await userEvent.click(screen.getByRole("checkbox", { name: "Modularity" }))
    expect(screen.getByRole("checkbox", { name: "Modularity" })).not.toBeChecked()
    await changeLanguage("es")
    expect(screen.getByRole("checkbox", { name: "Reusabilidad" })).toBeChecked()
    expect(listAgentSettings).toHaveBeenCalledOnce()
  })

  it("does not assume availability while loading or after a failure and allows retrying", async () => {
    let reject!: (reason: Error) => void
    vi.mocked(listAgentSettings).mockReturnValueOnce(new Promise((_, fail) => { reject = fail }))
    render(<MaintainabilityConfiguration />)
    for (const checkbox of screen.getAllByRole("checkbox")) expect(checkbox).toBeDisabled()

    reject(new Error("offline"))
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not check agent availability.")
    vi.mocked(listAgentSettings).mockResolvedValue([agent("testability")])
    await userEvent.click(screen.getByRole("button", { name: "Retry" }))
    await waitFor(() => expect(screen.getByRole("checkbox", { name: "Testability" })).toBeChecked())
    expect(screen.queryByRole("alert")).not.toBeInTheDocument()
  })
})
