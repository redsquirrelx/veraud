import { afterEach, expect, it, vi } from "vitest"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { useAgentExecutions } from "../agent-monitor/useAgentExecutions.ts"
import { listAgentSettings, type AgentExecution } from "../../infrastructure/http-client/httpClient.ts"
import { LiveAuditMonitor } from "./LiveAuditMonitor.tsx"

vi.mock("../agent-monitor/useAgentExecutions.ts", async (original) => ({
  ...await original<typeof import("../agent-monitor/useAgentExecutions.ts")>(), useAgentExecutions: vi.fn(),
}))
vi.mock("../../infrastructure/http-client/httpClient.ts", async (original) => ({
  ...await original<typeof import("../../infrastructure/http-client/httpClient.ts")>(), listAgentSettings: vi.fn(),
}))
afterEach(() => vi.resetAllMocks())

it("drives the shared drawer with live rows, preserves direct executions and updates finished status", async () => {
  const user = userEvent.setup()
  const execution: AgentExecution = { id: 17, evaluationId: null, agentType: "dummy", status: "Running", result: null,
    inputTokens: null, outputTokens: null, error: null, createdAt: "2026-10-18T10:00:00Z", startedAt: null, finishedAt: null }
  vi.mocked(useAgentExecutions).mockReturnValue([execution])
  vi.mocked(listAgentSettings).mockResolvedValue([{ agentType: "dummy", qualityAttributes: [], workflowIds: [], configured: false, configuration: null }])
  const { rerender, container } = render(<MemoryRouter><LiveAuditMonitor /></MemoryRouter>)
  await waitFor(() => expect(listAgentSettings).toHaveBeenCalledOnce())
  await user.click(screen.getByRole("button", { name: "2 audits" }))
  const panel = screen.getByRole("region", { name: "Audit statuses" })
  expect(within(panel).getByText("dummy run #17")).toBeInTheDocument()
  expect(within(panel).queryByRole("link")).toBeNull()
  expect(within(panel).getByText("DEMO/DEMO")).toBeVisible()
  expect(within(panel).queryByRole("button", { name: "Cancel audit" })).toBeNull()
  expect(within(panel).getByText("Audit #-2").closest(".audit-disclosure")).toHaveAttribute("data-state", "failed")
  expect(panel).toHaveAttribute("aria-hidden", "false")
  expect(container.querySelector(".agent-menu")).toBeNull()
  vi.mocked(useAgentExecutions).mockReturnValue([{ ...execution, status: "Failed", error: "Selected model unavailable" }])
  rerender(<MemoryRouter><LiveAuditMonitor /></MemoryRouter>)
  expect(within(panel).getAllByRole("img", { name: "Execution error" }).length).toBeGreaterThan(0)
  expect(within(panel).getByText("dummy run #17").closest("li")).toHaveAttribute("data-state", "failed")
})
