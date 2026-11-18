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
      { ...agent("testability"), childAgentTypes: ["test_isolation"] },
      { ...agent("architecture_boundary"), role: "investigator", name: "ArchitectureBoundaryAgent" },
      { ...agent("responsibility"), role: "investigator", name: "ResponsibilityAgent" },
      { ...agent("blocked", "not_executed"), role: "investigator", name: "BlockedAgent" },
      { ...agent("abstraction"), role: "investigator", name: "AbstractionAgent", parentAgentTypes: ["reusability"] },
      { ...agent("test_isolation"), role: "investigator", name: "TestIsolationAgent", parentAgentTypes: ["testability"] },
      { ...agent("unrelated"), role: "investigator", name: "UnrelatedAgent" },
    ])
    const user = userEvent.setup()
    render(<MaintainabilityConfiguration />)
    await waitFor(() => expect(screen.getByRole("checkbox", { name: "Modularity" })).toBeEnabled())
    expect(screen.getAllByText("View investigators")).toHaveLength(3)
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
    // Partial-evaluation labels are no longer surfaced in the configuration.
    expect(screen.queryByText("Partial evaluation")).not.toBeInTheDocument()
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
    expect(screen.getAllByText("Ver investigadores")).toHaveLength(3)
    expect(screen.queryByText("Evaluación parcial")).not.toBeInTheDocument()
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

  it("selects only registered, available subcharacteristics by default and hides unimplemented ones", async () => {
    vi.mocked(listAgentSettings).mockResolvedValue([
      agent("modularity"), agent("reusability"), agent("testability", "not_implemented"),
      { ...agent("test_isolation"), role: "investigator", name: "TestIsolationAgent", parentAgentTypes: ["testability"] },
    ])
    render(<MaintainabilityConfiguration />)

    await waitFor(() => expect(screen.getByRole("checkbox", { name: "Modularity" })).toBeEnabled())
    expect(screen.getAllByRole("checkbox")).toHaveLength(4)
    expect(screen.queryByRole("checkbox", { name: "Analyzability" })).toBeNull()
    expect(screen.queryByRole("checkbox", { name: "Modifiability" })).toBeNull()
    for (const name of ["Modularity", "Reusability"]) expect(screen.getByRole("checkbox", { name })).toBeChecked()
    expect(screen.getByRole("checkbox", { name: "Testability" })).toBeDisabled()
    expect(screen.getByRole("checkbox", { name: "Testability" })).not.toBeChecked()
    await userEvent.click(screen.getByRole("checkbox", { name: "Modularity" }))
    expect(screen.getByRole("checkbox", { name: "Modularity" })).not.toBeChecked()
    await changeLanguage("es")
    expect(screen.getByRole("checkbox", { name: "Reusabilidad" })).toBeChecked()
    expect(listAgentSettings).toHaveBeenCalledOnce()
  })

  it("renders testability as available with its registered investigators once registered", async () => {
    vi.mocked(listAgentSettings).mockResolvedValue([
      agent("modularity"), agent("reusability"),
      { ...agent("testability"), childAgentTypes: ["test_isolation", "test_controllability"] },
      { ...agent("test_isolation"), role: "investigator", name: "TestIsolationAgent", parentAgentTypes: ["testability"] },
      { ...agent("test_controllability"), role: "investigator", name: "TestControllabilityAgent", parentAgentTypes: ["testability"] },
    ])
    const user = userEvent.setup()
    render(<MaintainabilityConfiguration />)
    await waitFor(() => expect(screen.getByRole("checkbox", { name: "Testability" })).toBeEnabled())
    expect(screen.getByRole("checkbox", { name: "Testability" })).toBeChecked()
    await user.click(screen.getAllByText("View investigators")[2]!)
    expect(screen.getByRole("checkbox", { name: "TestIsolationAgent" })).toBeChecked()
    expect(screen.getByText("Evaluates whether dependencies can be substituted or their effects controlled for independent testing.", { exact: false })).toBeInTheDocument()
    expect(screen.getByRole("checkbox", { name: "TestControllabilityAgent" })).toBeChecked()
    expect(screen.getByText("Evaluates whether the entries, states, dependencies and conditions needed to test documented behaviors can be controlled.", { exact: false })).toBeInTheDocument()
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
