import { expect, it } from "vitest"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { AuditStatusView } from "./AuditStatusView.tsx"
import type { AuditAgentRun, AuditStatusModel } from "./auditStatus.ts"
import type { AgentExecution } from "../../infrastructure/http-client/httpClient.ts"
import { executionAudits } from "./executionAudits.ts"

it("updates a restarted agent in place while preserving collapsed branches", async () => {
  const receipt = (invocation_id: string, agent_id: string, parent_invocation_id: string | null,
    started_at = "2026-10-20T10:00:00Z"): NonNullable<AgentExecution["invocations"]>[number] => ({
    invocation_id, agent_id, parent_invocation_id, started_at, run_id: "audit",
    status: "completed", finished_at: "2026-10-20T10:01:00Z", input_tokens: 100, output_tokens: 10, error: null,
  })
  const execution: AgentExecution = { id: 1, evaluationId: 1, agentType: "maintainability_manager", status: "Running",
    result: null, error: null, inputTokens: null, outputTokens: null, createdAt: "2026-10-20T10:00:00Z", startedAt: null, finishedAt: null,
    invocations: [receipt("manager-1", "maintainability_manager", null), receipt("mod-1", "modularity", "manager-1"),
      receipt("boundary-1", "architecture_boundary", "mod-1")] }
  const view = (value: AgentExecution) => <MemoryRouter><AuditStatusView audit={executionAudits([value], [])[0]!} /></MemoryRouter>
  const { rerender } = render(view(execution))
  const coordinator = screen.getByRole("button", { name: "modularity run #mod-1" })
  const originalRow = coordinator.closest("li")
  await userEvent.click(coordinator)
  const manager = screen.getByRole("button", { name: "maintainability_manager run #manager-1" })
  await userEvent.click(manager)
  rerender(view({ ...execution, invocations: [...execution.invocations!,
    { ...receipt("manager-2", "maintainability_manager", null, "2026-10-20T10:02:00Z"), status: "running", finished_at: null },
    { ...receipt("mod-2", "modularity", "manager-2", "2026-10-20T10:02:01Z"), status: "running", finished_at: null, input_tokens: 2 },
  ] }))
  const nextManager = screen.getByRole("button", { name: "maintainability_manager run #manager-2" })
  expect(nextManager).toBe(manager)
  expect(nextManager).toHaveAttribute("aria-expanded", "false")
  expect(nextManager.closest("li")).toHaveAttribute("data-state", "running")
  await userEvent.click(nextManager)
  const nextCoordinator = screen.getByRole("button", { name: "modularity run #mod-2" })
  expect(nextCoordinator.closest("li")).toBe(originalRow)
  expect(nextCoordinator).toHaveAttribute("aria-expanded", "false")
  expect(within(originalRow!).getByText("12 tokens")).toBeVisible()
  expect(screen.getByText("architecture_boundary run #boundary-1")).not.toBeVisible()
  expect(screen.queryByText("modularity run #mod-1")).toBeNull()
  expect(screen.queryByText("maintainability_manager run #manager-1")).toBeNull()
})

it("renders manager, coordinators and investigators as independently collapsible branches", async () => {
  const run = (id: string, parentId?: string): AuditAgentRun => ({ id, agentType: id === "manager" ? "maintainability_manager" : id, parentId,
    state: "completed", inputTokens: null, outputTokens: null, startedAt: null, finishedAt: null, error: null })
  const audit: AuditStatusModel = { id: 1, project: null, branch: null, commitHash: null, state: "completed",
    createdAt: "2026-10-20", finishedAt: null, error: null, reportAvailable: true,
    pipelines: [{ id: "maintainability", state: "completed", agents: [run("manager"), run("modularity", "manager"),
      run("boundary", "modularity"), run("reusability", "manager"), run("reuse-investigator", "reusability")] }] }
  render(<MemoryRouter><AuditStatusView audit={audit} /></MemoryRouter>)
  expect(screen.queryByText("Maintainability")).toBeNull()
  expect(screen.getAllByText("maintainability_manager run #manager")).toHaveLength(1)
  const manager = screen.getByText("maintainability_manager run #manager").closest("li")!
  const modularity = within(manager).getByText("modularity run #modularity").closest("li")!
  expect(within(modularity).getByText("boundary run #boundary")).toBeVisible()
  await userEvent.click(within(modularity).getByRole("button", { name: "modularity run #modularity" }))
  expect(within(modularity).getByText("boundary run #boundary")).not.toBeVisible()
  expect(within(manager).getByText("reuse-investigator run #reuse-investigator")).toBeVisible()
  await userEvent.click(within(manager).getByRole("button", { name: "maintainability_manager run #manager" }))
  expect(within(manager).getByText("reusability run #reusability")).not.toBeVisible()
})

it("uses the root as the group header before children arrive and for security", async () => {
  const root: AuditAgentRun = { id: 3, agentType: "maintainability_manager", state: "running", inputTokens: 10,
    outputTokens: 2, startedAt: null, finishedAt: null, error: null }
  const model: AuditStatusModel = { id: 1, project: null, branch: null, commitHash: null, state: "running",
    createdAt: "2026-10-20", finishedAt: null, error: null, reportAvailable: false,
    pipelines: [{ id: "maintainability", state: "running", agents: [root] }] }
  const { rerender } = render(<MemoryRouter><AuditStatusView audit={model} /></MemoryRouter>)
  expect(screen.queryByText("Maintainability")).toBeNull()
  const header = screen.getByRole("button", { name: "maintainability_manager run #3" })
  expect(header).toHaveAttribute("aria-expanded", "true")
  await userEvent.click(header)
  expect(header).toHaveAttribute("aria-expanded", "false")
  expect(screen.getByText("12 tokens")).toBeVisible()
  rerender(<MemoryRouter><AuditStatusView audit={{ ...model, pipelines: [{ id: "security", state: "running",
    agents: [{ ...root, agentType: "security" }] }] }} /></MemoryRouter>)
  expect(screen.queryByText("Security")).toBeNull()
  expect(screen.getByRole("button", { name: "security run #3" })).toBeVisible()
})
