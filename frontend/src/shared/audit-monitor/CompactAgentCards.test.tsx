import { beforeEach, expect, it } from "vitest"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { AuditStatusView } from "./AuditStatusView.tsx"
import { AuditStatusDrawer } from "./AuditStatusDrawer.tsx"
import type { AuditAgentRun, AuditStatusModel } from "./auditStatus.ts"

beforeEach(() => window.localStorage.clear())

const agent = (id: string, agentType: string, parentId?: string): AuditAgentRun => ({
  id, agentType, parentId, state: "running", phase: "investigate", inputTokens: 100, outputTokens: 20,
  startedAt: "2026-10-29T10:00:00Z", finishedAt: null, error: null,
})
const audit: AuditStatusModel = {
  id: 88, project: null, branch: null, commitHash: null, state: "running", createdAt: "2026-10-29T10:00:00Z",
  finishedAt: null, error: null, reportAvailable: false,
  pipelines: [{ id: "maintainability", state: "running", agents: [
    agent("manager-1", "maintainability_manager"), agent("mod-1", "modularity", "manager-1"),
    agent("investigator-1", "responsibility", "mod-1"),
  ] }],
}
const view = (model = audit) => <MemoryRouter><AuditStatusView audit={model} /></MemoryRouter>

it("starts with compact headers and exposes independent details and branch controls", async () => {
  render(view())
  const root = screen.getByRole("button", { name: "maintainability_manager run #manager-1" })
  const row = root.closest("li")!
  expect(within(root).getByText("maintainability_manager")).toBeVisible()
  expect(within(root).getByText("Running")).toBeVisible()
  expect(within(root).getByRole("img", { name: "Investigation" })).toBeVisible()
  expect(root.querySelector(".ui-badge")).toBeNull()
  expect(within(row).getByText("maintainability_manager run #manager-1")).not.toBeVisible()
  const tokens = within(row).getAllByText("120 tokens")
  expect(tokens.every((token) => token.closest("[hidden]"))).toBe(true)
  const details = screen.getByRole("button", { name: "Execution details · maintainability_manager run #manager-1" })
  await userEvent.click(details)
  expect(tokens[0]).toBeVisible()
  expect(tokens[1]).not.toBeVisible()
  expect(screen.getByRole("button", { name: "responsibility run #investigator-1" })).toBeVisible()
  await userEvent.click(details)
  expect(tokens[0]).not.toBeVisible()
  expect(screen.getByRole("button", { name: "responsibility run #investigator-1" })).toBeVisible()
  await userEvent.click(root)
  expect(screen.queryByRole("button", { name: "responsibility run #investigator-1" })).toBeNull()
  expect(within(root).getByText("Running")).toBeVisible()
  expect(within(root).getByRole("img", { name: "Investigation" })).toBeVisible()
  // The details button also works from a fully folded branch.
  await userEvent.click(details)
  expect(tokens[0]).toBeVisible()
  expect(screen.getByRole("button", { name: "responsibility run #investigator-1" })).toBeVisible()
})

it("preserves both choices on remount and across new invocation IDs", async () => {
  const { unmount } = render(view())
  await userEvent.click(screen.getByRole("button", { name: "Execution details · modularity run #mod-1" }))
  await userEvent.click(screen.getByRole("button", { name: "maintainability_manager run #manager-1" }))
  unmount()
  const restarted = structuredClone(audit)
  restarted.pipelines[0]!.agents[0]!.id = "manager-2"
  restarted.pipelines[0]!.agents[1]!.parentId = "manager-2"
  render(view(restarted))
  const root = screen.getByRole("button", { name: "maintainability_manager run #manager-2" })
  expect(root).toHaveAttribute("aria-expanded", "false")
  await userEvent.click(root)
  expect(screen.getByRole("button", { name: "Execution details · modularity run #mod-1" })).toHaveAttribute("aria-expanded", "true")
  expect(screen.getByRole("button", { name: "Execution details · maintainability_manager run #manager-2" })).toHaveAttribute("aria-expanded", "false")
})

it("opens leaf details from the agent name using the keyboard", async () => {
  render(view())
  const leaf = screen.getByRole("button", { name: "responsibility run #investigator-1" })
  expect(leaf).toHaveAttribute("aria-expanded", "false")
  leaf.focus()
  await userEvent.keyboard("{Enter}")
  expect(leaf).toHaveAttribute("aria-expanded", "true")
  expect(within(leaf.closest("li")!).getByText("120 tokens")).toBeVisible()
  await userEvent.keyboard(" ")
  expect(leaf).toHaveAttribute("aria-expanded", "false")
  expect(within(leaf.closest("li")!).getByText("120 tokens")).not.toBeVisible()
})

it("groups execution identity, dates and tokens into separate labelled sections", async () => {
  render(view())
  await userEvent.click(screen.getByRole("button", { name: "Execution details · responsibility run #investigator-1" }))
  const row = screen.getByRole("button", { name: "responsibility run #investigator-1" }).closest("li")!
  expect(within(within(row).getByRole("region", { name: "Execution" })).getByText("responsibility run #investigator-1")).toBeVisible()
  const dates = within(row).getByRole("region", { name: "Timeline" })
  expect(within(dates).getByText("Started")).toBeVisible()
  expect(dates.querySelector("time")).toHaveAttribute("datetime", "2026-10-29T10:00:00Z")
  expect(within(dates).getByText("Finished")).toBeVisible()
  expect(within(dates).getByText("Not recorded")).toBeVisible()
  expect(within(within(row).getByRole("region", { name: "Token usage" })).getByText("120 tokens")).toBeVisible()
})

it("keeps errors in their own section and preserves missing-date information", async () => {
  const failed = structuredClone(audit)
  const run = failed.pipelines[0]!.agents[2]!
  run.state = "failed"
  run.startedAt = null
  run.error = "Provider unavailable"
  render(view(failed))
  await userEvent.click(screen.getByRole("button", { name: "Execution details · responsibility run #investigator-1" }))
  const row = screen.getByRole("button", { name: "responsibility run #investigator-1" }).closest("li")!
  const errors = within(row).getByRole("region", { name: "Execution error" })
  expect(screen.queryByText("Provider unavailable")).toBeNull()
  await userEvent.click(within(errors).getByText("View error"))
  expect(screen.getByRole("dialog")).toHaveTextContent("Provider unavailable")
  expect(within(within(row).getByRole("region", { name: "Timeline" })).getAllByText("Not recorded")).toHaveLength(2)
})

it("updates phase and state while the entire branch is folded", async () => {
  const { rerender } = render(view())
  const root = screen.getByRole("button", { name: "maintainability_manager run #manager-1" })
  await userEvent.click(root)
  const changed = structuredClone(audit)
  changed.pipelines[0]!.agents[0]!.phase = "review_findings"
  rerender(view(changed))
  expect(root).toHaveAttribute("aria-expanded", "false")
  expect(within(root).getByRole("img", { name: "Review" })).toHaveAttribute("data-highlighted", "true")
  changed.pipelines[0]!.agents[0]!.state = "failed"
  rerender(view(structuredClone(changed)))
  expect(root.closest("li")).toHaveAttribute("data-state", "failed")
  expect(within(root).getByText("Failed")).toBeVisible()
})

it("shows separate state-border and graph-phase colour legends above the audits", async () => {
  render(<MemoryRouter><AuditStatusDrawer audits={[audit]} /></MemoryRouter>)
  await userEvent.click(screen.getByRole("button", { name: "1 audit" }))
  const states = screen.getByRole("group", { name: "Execution states" })
  expect(within(states).getAllByRole("listitem")).toHaveLength(7)
  expect(within(states).getByText("Cancelling…")).toHaveAttribute("data-state", "cancelling")
  expect(within(states).getByText("Cancelled")).toHaveAttribute("data-state", "cancelled")
  expect(within(states).getByText("Failed")).toHaveAttribute("data-state", "failed")
  const phases = screen.getByRole("group", { name: "Graph phases" })
  expect(within(phases).getAllByRole("listitem")).toHaveLength(5)
  expect(phases.querySelector('[data-phase="investigate"]')).toBeInTheDocument()
})
