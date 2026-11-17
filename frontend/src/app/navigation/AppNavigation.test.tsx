import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, useLocation } from "react-router-dom"
import { afterEach, describe, expect, it, vi } from "vitest"
import { ToastProvider } from "../toasts.tsx"
import { SettingsProvider } from "../settingsContext.tsx"
import { AppMainNavigation } from "./AppNavigation.tsx"
import { ExecutionExplorerProvider } from "../../shared/execution-explorer/index.ts"
import { AgentExecutionsContext } from "../../shared/agent-monitor/useAgentExecutions.ts"
import type { AgentExecution } from "../../infrastructure/http-client/httpClient.ts"

afterEach(() => vi.unstubAllGlobals())

function Location() {
  return <p data-testid="location">{useLocation().pathname}</p>
}

describe("settings navigation", () => {
  it("opens settings without navigating and closes only with the X", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("[]", { status: 200 })))
    const user = userEvent.setup()
    render(<MemoryRouter><ToastProvider>
      <SettingsProvider>
        <AppMainNavigation />
        <Location />
      </SettingsProvider>
    </ToastProvider></MemoryRouter>)
    await user.click(screen.getByRole("button", { name: "Settings" }))
    const dialog = screen.getByRole("dialog", { name: "Settings" })
    expect(within(dialog).getByRole("tab", { name: "Models & credentials" })).toBeInTheDocument()
    expect(screen.getByTestId("location")).toHaveTextContent("/")
    await user.click(dialog.closest(".ui-modal-overlay")!)
    await user.keyboard("{Escape}")
    expect(dialog).toBeInTheDocument()
    await user.click(within(dialog).getByRole("button", { name: "Close" }))
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  })
})

describe("executions navigation", () => {
  const runningExecution: AgentExecution = {
    id: 1, evaluationId: null, agentType: "security", status: "Running", result: null, error: null,
    inputTokens: null, outputTokens: null, createdAt: "2026-11-16T08:00:00Z", startedAt: "2026-11-16T08:00:05Z", finishedAt: null,
  }

  it("opens the global Execution Explorer without navigating", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("[]", { status: 200 })))
    const user = userEvent.setup()
    render(<MemoryRouter><ToastProvider>
      <ExecutionExplorerProvider>
        <SettingsProvider>
          <AppMainNavigation />
          <Location />
        </SettingsProvider>
      </ExecutionExplorerProvider>
    </ToastProvider></MemoryRouter>)

    await user.click(screen.getByRole("button", { name: "Executions" }))

    const dialog = screen.getByRole("dialog", { name: "Execution Explorer" })
    expect(dialog).toBeInTheDocument()
    expect(screen.getByTestId("location")).toHaveTextContent("/")

    await user.click(within(dialog).getByRole("button", { name: "Close" }))

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  })

  it("shows the active-execution counter only when executions are live", () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("[]", { status: 200 })))
    const { unmount } = render(<MemoryRouter><ToastProvider>
      <AgentExecutionsContext.Provider value={[runningExecution]}>
        <ExecutionExplorerProvider>
          <SettingsProvider>
            <AppMainNavigation />
          </SettingsProvider>
        </ExecutionExplorerProvider>
      </AgentExecutionsContext.Provider>
    </ToastProvider></MemoryRouter>)

    expect(screen.getByRole("button", { name: "1 active execution" })).toHaveTextContent("1")

    unmount()

    render(<MemoryRouter><ToastProvider>
      <AgentExecutionsContext.Provider value={[]}>
        <ExecutionExplorerProvider>
          <SettingsProvider>
            <AppMainNavigation />
          </SettingsProvider>
        </ExecutionExplorerProvider>
      </AgentExecutionsContext.Provider>
    </ToastProvider></MemoryRouter>)

    expect(screen.getByRole("button", { name: "Executions" })).toBeInTheDocument()
  })
})
