import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { changeLanguage } from "../i18n/index.ts"
import { AgentExecutionsContext } from "../agent-monitor/useAgentExecutions.ts"
import { EXPLORER_CATALOG, allExecutions } from "./explorerTestFixtures.ts"
import { ExecutionExplorerModal } from "./ExecutionExplorerModal.tsx"
import { ExecutionExplorerProvider, useExecutionExplorer } from "./index.ts"

function stubCatalogFetch() {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(EXPLORER_CATALOG), { status: 200, headers: { "Content-Type": "application/json" } })))
}

function show(executions = allExecutions) {
  return render(
    <AgentExecutionsContext.Provider value={executions}>
      <ExecutionExplorerModal open onClose={() => {}} />
    </AgentExecutionsContext.Provider>,
  )
}

function Trigger({ executionId }: { executionId?: string }) {
  const { openExplorer } = useExecutionExplorer()
  return <button type="button" onClick={() => openExplorer(executionId)}>Open executions</button>
}

function renderedDialog(): HTMLElement {
  const dialog = document.querySelector<HTMLElement>(".execution-explorer-dialog")
  if (!dialog) throw new Error("Missing explorer dialog")
  return dialog
}

/** Queries scoped to the independently scrollable list pane so titles that
 *  also appear in the inspector stay unambiguous. */
function listPane(): ReturnType<typeof within> {
  const pane = document.querySelector<HTMLElement>(".execution-explorer-list-pane")
  if (!pane) throw new Error("Missing execution list pane")
  return within(pane)
}

beforeEach(() => stubCatalogFetch())
afterEach(async () => {
  vi.unstubAllGlobals()
  await changeLanguage("en")
})

describe("ExecutionExplorerModal", () => {
  it("renders nothing when closed", () => {
    render(<AgentExecutionsContext.Provider value={[]}><ExecutionExplorerModal open={false} onClose={() => {}} /></AgentExecutionsContext.Provider>)

    expect(screen.queryByRole("dialog")).toBeNull()
  })

  it("opens through the provider, closes with the cross and restores focus to the trigger", async () => {
    const user = userEvent.setup()
    render(<AgentExecutionsContext.Provider value={[]}><ExecutionExplorerProvider><Trigger /></ExecutionExplorerProvider></AgentExecutionsContext.Provider>)

    const trigger = screen.getByRole("button", { name: "Open executions" })
    await user.click(trigger)

    const dialog = screen.getByRole("dialog", { name: "Execution Explorer" })
    expect(dialog).toBeInTheDocument()
    expect(dialog).toHaveAttribute("aria-modal", "true")
    expect(within(dialog).getByRole("button", { name: "Close" })).toHaveFocus()

    await user.click(within(dialog).getByRole("button", { name: "Close" }))

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })

  it("closes on Escape", async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    render(<AgentExecutionsContext.Provider value={[]}><ExecutionExplorerModal open onClose={onClose} /></AgentExecutionsContext.Provider>)

    await user.keyboard("{Escape}")

    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it("preselects the audit requested by the provider", async () => {
    const user = userEvent.setup()
    render(<AgentExecutionsContext.Provider value={allExecutions}><ExecutionExplorerProvider><Trigger executionId="104" /></ExecutionExplorerProvider></AgentExecutionsContext.Provider>)

    await user.click(screen.getByRole("button", { name: "Open executions" }))

    const dialog = screen.getByRole("dialog", { name: "Execution Explorer" })
    expect(within(dialog).getByRole("heading", { name: "Maintainability · #104" })).toBeInTheDocument()
  })

  it("lists audits and architecture context runs, never other evaluation types", async () => {
    show()

    await waitFor(() => expect(listPane().getByRole("button", { name: /Maintainability · #101/ })).toBeInTheDocument())

    // Audits stay visible.
    expect(listPane().getByRole("button", { name: /Maintainability · #101/ })).toBeInTheDocument()
    expect(listPane().getByRole("button", { name: /Maintainability \+ Security · #102/ })).toBeInTheDocument()
    expect(listPane().getByRole("button", { name: /Maintainability · #104/ })).toBeInTheDocument()
    expect(listPane().getByRole("button", { name: /Maintainability · #105/ })).toBeInTheDocument()
    // Architecture context runs appear as standalone agents.
    expect(listPane().getByRole("button", { name: /Architecture Context · #201/ })).toBeInTheDocument()
    expect(listPane().getByRole("button", { name: /Architecture Context · #202/ })).toBeInTheDocument()
    // The verification-suite generation run appears as a standalone agent.
    expect(listPane().getByRole("button", { name: /Verification Suite · #501/ })).toBeInTheDocument()
    // Analysis pipeline and finding resolution never appear.
    expect(listPane().queryByRole("button", { name: /301|302/ })).toBeNull()
    expect(listPane().queryByRole("button", { name: /401/ })).toBeNull()
  })

  it("narrows the list to audits or standalone agents with the type filter", async () => {
    const user = userEvent.setup()
    show()

    await waitFor(() => expect(listPane().getByRole("button", { name: /Maintainability · #101/ })).toBeInTheDocument())

    await user.click(screen.getByRole("tab", { name: /^Audits/ }))

    expect(listPane().getByRole("button", { name: /Maintainability · #101/ })).toBeInTheDocument()
    expect(listPane().queryByRole("button", { name: /Architecture Context · #201/ })).toBeNull()
    expect(listPane().queryByRole("button", { name: /Architecture Context · #202/ })).toBeNull()

    await user.click(screen.getByRole("tab", { name: /^Standalone agents/ }))

    expect(listPane().getByRole("button", { name: /Architecture Context · #201/ })).toBeInTheDocument()
    expect(listPane().getByRole("button", { name: /Architecture Context · #202/ })).toBeInTheDocument()
    expect(listPane().getByRole("button", { name: /Verification Suite · #501/ })).toBeInTheDocument()
    expect(listPane().queryByRole("button", { name: /Maintainability · #101/ })).toBeNull()
  })

  it("renders the cancel action only for running quality audits", async () => {
    const user = userEvent.setup()
    show()

    // #101 is a running quality audit with a positive project id → cancel button present.
    await user.click(await listPane().findByRole("button", { name: /Maintainability · #101/ }))
    const dialog = renderedDialog()
    expect(within(dialog).getByRole("button", { name: "Cancel audit" })).toBeInTheDocument()

    // Agents are never cancellable.
    await user.click(listPane().getByRole("button", { name: /Architecture Context · #201/ }))
    expect(within(renderedDialog()).queryByRole("button", { name: "Cancel audit" })).toBeNull()
  })

  it("shows standalone agents without a hierarchy and with their own detail", async () => {
    const user = userEvent.setup()
    show()

    await user.click(await listPane().findByRole("button", { name: /Architecture Context · #201/ }))

    const dialog = renderedDialog()
    expect(within(dialog).getByRole("heading", { name: "Architecture Context · #201" })).toBeInTheDocument()
    expect(within(dialog).queryByRole("button", { name: /^Toggle / })).toBeNull()
    expect(within(dialog).getByLabelText("Execution")).toBeInTheDocument()
  })

  it("expands the verification suite's generator receipts with their token usage", async () => {
    const user = userEvent.setup()
    show()

    await user.click(await listPane().findByRole("button", { name: /Verification Suite · #501/ }))

    const dialog = renderedDialog()
    expect(within(dialog).getByRole("heading", { name: "Verification Suite · #501" })).toBeInTheDocument()
    expect(within(dialog).getByRole("button", { name: /^Finding test generation/ })).toBeInTheDocument()
    expect(within(dialog).getByRole("button", { name: /^Testability probe/ })).toBeInTheDocument()
  })

  it("shows joint audits as a single grouped row with both attributes", async () => {
    show()

    expect(await listPane().findByRole("button", { name: /Maintainability \+ Security · #102/ })).toBeInTheDocument()
    expect(listPane().queryByRole("button", { name: /Maintainability · #103/ })).toBeNull()
  })

  it("filters audits by status, keeping the completed ones under their tab", async () => {
    const user = userEvent.setup()
    show()

    await waitFor(() => expect(listPane().getByRole("button", { name: /Maintainability · #101/ })).toBeInTheDocument())

    await user.click(screen.getByRole("tab", { name: /^Completed/ }))

    expect(listPane().getByRole("button", { name: /Maintainability \+ Security · #102/ })).toBeInTheDocument()
    expect(listPane().queryByRole("button", { name: /Maintainability · #101/ })).toBeNull()

    await user.click(screen.getByRole("tab", { name: /^Failed/ }))

    expect(listPane().getByRole("button", { name: /Maintainability · #104/ })).toBeInTheDocument()
    expect(listPane().queryByRole("button", { name: /Maintainability \+ Security · #102/ })).toBeNull()
  })

  it("filters audits by free text and reports an empty result", async () => {
    const user = userEvent.setup()
    show()

    const search = screen.getByRole("searchbox", { name: "Search executions" })
    await user.type(search, "security")

    expect(listPane().getByRole("button", { name: /Maintainability \+ Security · #102/ })).toBeInTheDocument()
    expect(listPane().queryByRole("button", { name: /Maintainability · #101/ })).toBeNull()

    await user.clear(search)
    await user.type(search, "nothing-matches-this")

    expect(screen.getByText("No executions match the current filters.")).toBeInTheDocument()
  })

  it("selects an audit in the list and renders its agent hierarchy", async () => {
    const user = userEvent.setup()
    show()

    await user.click(await listPane().findByRole("button", { name: /Maintainability · #101/ }))

    const dialog = renderedDialog()
    expect(within(dialog).getByRole("heading", { name: "Maintainability · #101" })).toBeInTheDocument()
    expect(within(dialog).getByRole("button", { name: /Modularity investigator/ })).toBeInTheDocument()
  })

  it("collapses and expands the audit tree branches", async () => {
    const user = userEvent.setup()
    show()

    await user.click(await listPane().findByRole("button", { name: /Maintainability · #101/ }))
    const managerToggle = screen.getByRole("button", { name: "Toggle Maintainability manager" })
    expect(managerToggle).toHaveAttribute("aria-expanded", "true")

    await user.click(managerToggle)

    expect(managerToggle).toHaveAttribute("aria-expanded", "false")
    expect(screen.queryByRole("button", { name: /Modularity investigator/ })).toBeNull()
    expect(screen.queryByRole("button", { name: /Maintainability coordinator/i })).toBeNull()

    await user.click(managerToggle)

    expect(screen.getByRole("button", { name: /Modularity investigator/ })).toBeInTheDocument()
  })

  it("shows joint audits with one root per attribute", async () => {
    const user = userEvent.setup()
    show()

    await user.click(await listPane().findByRole("button", { name: /Maintainability \+ Security · #102/ }))

    const dialog = renderedDialog()
    expect(within(dialog).getByRole("button", { name: /^Security/ })).toBeInTheDocument()
    expect(within(dialog).getByRole("button", { name: /^Maintainability manager/ })).toBeInTheDocument()
  })

  it("reserves events, traces and results as disabled tabs", () => {
    show()

    for (const name of ["Events", "Traces", "Results"]) {
      expect(screen.getByRole("tab", { name })).toBeDisabled()
    }
  })

  it("switches between list and detail panes for the small-screen navigation", async () => {
    const user = userEvent.setup()
    show()

    await waitFor(() => expect(renderedDialog()).toHaveAttribute("data-mobile-view", "list"))

    await user.click(listPane().getByRole("button", { name: /Maintainability · #101/ }))

    expect(renderedDialog()).toHaveAttribute("data-mobile-view", "detail")

    await user.click(screen.getByRole("button", { name: "Back to list" }))

    expect(renderedDialog()).toHaveAttribute("data-mobile-view", "list")
  })

  it("localizes the chrome in Spanish", async () => {
    await changeLanguage("es")
    show()

    expect(screen.getByRole("dialog", { name: "Explorador de ejecuciones" })).toBeInTheDocument()
    expect(screen.getByRole("searchbox", { name: "Buscar ejecuciones" })).toBeInTheDocument()
  })
})
