import { beforeEach, expect, it, vi } from "vitest"
import { act, render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { requestJson } from "../../infrastructure/http-client/httpClient.ts"
import { AuditStatusDisclosure } from "./AuditStatusDisclosure.tsx"
import type { AuditAgentRun, AuditStatusModel } from "./auditStatus.ts"

vi.mock("../../infrastructure/http-client/httpClient.ts", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../infrastructure/http-client/httpClient.ts")>()
  return { ...actual, requestJson: vi.fn() }
})

beforeEach(() => {
  window.localStorage.clear()
  vi.mocked(requestJson).mockReset()
})

const agent = (id: string, agentType: string, parentId?: string): AuditAgentRun => ({
  id, agentType, parentId, state: "partial", phase: null, inputTokens: null, outputTokens: null,
  startedAt: "2026-11-15T15:36:08Z", finishedAt: "2026-11-15T15:48:04Z", error: null,
})
const partial = (changes: Partial<AuditStatusModel> = {}): AuditStatusModel => ({
  id: 152, project: { id: 5, repositoryOwner: "owner", repositoryName: "repo" },
  branch: "main", commitHash: "abc1234", state: "partial",
  createdAt: "2026-11-15T15:36:08Z", finishedAt: "2026-11-15T15:48:04Z", error: null,
  reportAvailable: false,
  pipelines: [{ id: "maintainability", state: "partial", agents: [
    agent("manager-1", "maintainability_manager"),
    agent("testability-1", "testability", "manager-1"),
    agent("investigator-1", "test_controllability", "testability-1"),
  ] }],
  ...changes,
})
const annexes = {
  execution_issues: [
    { agent_id: "testability", status: "partial", termination_reason: "assessment_partial",
      explanation: "Motivo registrado: assessment_partial.", incidents: [], diagnostics: [] },
    { agent_id: "maintainability_manager", status: "partial", termination_reason: "audit_partial",
      explanation: "Motivo registrado: audit_partial.",
      incidents: ["El proveedor informó un límite de cuota (HTTP 429)."],
      diagnostics: ["coordinator-assignment-x/testability: provider_request: GoogleAPIError; http_status=503"] },
    { agent_id: "test_controllability", status: "partial", termination_reason: "provider_daily_quota_exhausted",
      explanation: "Etapa pendiente: se agotó la cuota diaria del proveedor.",
      incidents: ["El proveedor informó un límite de cuota (HTTP 429)."],
      diagnostics: ["investigate: provider_request: GoogleRateLimitError (response unavailable or invalid); http_status=429, quota_id=GenerateRequestsPerDayPerProjectPerModel-FreeTier"] },
  ],
}
const view = (model = partial()) => render(<MemoryRouter><AuditStatusDisclosure audit={model} /></MemoryRouter>)

it("shows the reason button only for project-scoped partial or failed audits", () => {
  view()
  expect(screen.getByRole("button", { name: "View reason" })).toBeInTheDocument()

  view(partial({ id: 153, state: "completed" }))
  expect(screen.queryAllByRole("button", { name: "View reason" })).toHaveLength(1)

  view(partial({ id: 154, project: null }))
  expect(screen.queryAllByRole("button", { name: "View reason" })).toHaveLength(1)
})

it("opens a modal listing the recorded reasons per agent", async () => {
  vi.mocked(requestJson).mockResolvedValue(annexes)
  view()
  await userEvent.click(screen.getByRole("button", { name: "View reason" }))

  const dialog = await screen.findByRole("dialog")
  expect(within(dialog).getByText("maintainability_manager")).toBeVisible()
  expect(within(dialog).getByText("test_controllability")).toBeVisible()
  expect(within(dialog).getByText("provider_daily_quota_exhausted")).toBeVisible()
  // Silent coordinator branches carry no reason and are not listed.
  expect(within(dialog).queryByText("testability")).toBeNull()
  // Technical diagnostics stay collapsed but visible once opened.
  expect(within(dialog).getByText(/quota_id=GenerateRequestsPerDayPerProjectPerModel-FreeTier/, { exact: false })).toBeInTheDocument()
  expect(requestJson).toHaveBeenCalledWith("/api/projects/5/audits/152/execution-issues",
    "Could not load the report detail", { signal: expect.any(AbortSignal) })
})

it("reports an empty outcome when no actionable incidents exist", async () => {
  vi.mocked(requestJson).mockResolvedValue({ execution_issues: [{ agent_id: "testability", status: "partial", termination_reason: "assessment_partial", incidents: [], diagnostics: [] }] })
  view()
  await userEvent.click(screen.getByRole("button", { name: "View reason" }))
  expect(await screen.findByText("The report records no incidents for this run.")).toBeInTheDocument()
})

it("shows a retry action when the report cannot be loaded", async () => {
  vi.mocked(requestJson).mockRejectedValueOnce(new Error("404"))
    .mockResolvedValueOnce(annexes)
  view()
  await userEvent.click(screen.getByRole("button", { name: "View reason" }))
  expect(await screen.findByText("The report detail could not be loaded.")).toBeInTheDocument()
  await userEvent.click(screen.getByRole("button", { name: "Retry" }))
  const dialog = await screen.findByRole("dialog")
  expect(within(dialog).getByText("maintainability_manager")).toBeInTheDocument()
  expect(requestJson).toHaveBeenCalledTimes(2)
})

it("does not load reports before opening and aborts the request when closed", async () => {
  vi.mocked(requestJson).mockImplementation(() => new Promise(() => {}))
  view()
  expect(requestJson).not.toHaveBeenCalled()
  await userEvent.click(screen.getByRole("button", { name: "View reason" }))
  const signal = vi.mocked(requestJson).mock.calls[0]![2]!.signal!
  expect(signal.aborted).toBe(false)
  await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Close" }))
  expect(signal.aborted).toBe(true)
  expect(screen.queryByRole("dialog")).toBeNull()
})

it("leaves the loading state after 15 seconds even if the request never settles", async () => {
  vi.mocked(requestJson).mockImplementation(() => new Promise(() => {}))
  view()
  await userEvent.click(screen.getByRole("button", { name: "View reason" }))
  const signal = vi.mocked(requestJson).mock.calls[0]![2]!.signal!
  // The request timer was installed with real timers, so spy on setTimeout
  // before opening a fresh modal to advance only this wait deterministically.
  await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Close" }))
  expect(signal.aborted).toBe(true)
  vi.useFakeTimers()
  try {
    const button = screen.getByRole("button", { name: "View reason" })
    act(() => button.click())
    await act(async () => { vi.advanceTimersByTime(15_000) })
    expect(screen.getByText("The report detail could not be loaded.")).toBeVisible()
    expect(vi.mocked(requestJson).mock.calls[1]![2]!.signal!.aborted).toBe(true)
  } finally { vi.useRealTimers() }
})
