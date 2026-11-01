import { beforeEach, expect, it, vi } from "vitest"
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { listAgentSettings } from "../../infrastructure/http-client/httpClient.ts"
import { changeLanguage } from "../../shared/i18n/index.ts"
import { QualityAuditResults } from "./QualityAuditResults.tsx"
import { getQualityAudit, type QualityAuditSummary } from "./qualityAuditApi.ts"
import { eventInvocationPaths, loadExecutionEvents, type ExecutionEvent } from "./executionEventsApi.ts"
import userEvent from "@testing-library/user-event"
import { AuditChronologyTab } from "./AuditChronologyTab.tsx"

vi.mock("../../infrastructure/http-client/httpClient.ts", async (original) => ({
  ...await original<typeof import("../../infrastructure/http-client/httpClient.ts")>(), listAgentSettings: vi.fn(),
}))
vi.mock("./qualityAuditApi.ts", async (original) => ({
  ...await original<typeof import("./qualityAuditApi.ts")>(), getQualityAudit: vi.fn(),
}))
vi.mock("./executionEventsApi.ts", async (original) => ({
  ...await original<typeof import("./executionEventsApi.ts")>(), loadExecutionEvents: vi.fn(),
}))

const audit: QualityAuditSummary = { id: 8, evaluationId: 4, branch: "main", commitHash: "a".repeat(40), attributes: ["security"],
  executionStatus: "Completed", auditStatus: "completed", error: null, createdAt: "2026-10-30T10:00:00Z", finishedAt: "2026-10-30T13:00:00Z", reportAvailable: false }
const event = (id: string, overrides: Partial<ExecutionEvent> = {}): ExecutionEvent => ({ eventId: id, streamId: "stream", sequence: 1,
  occurredAt: "2026-10-30T10:00:00Z", receivedAt: "2026-10-30T11:00:00Z", runId: "audit", invocationId: "root",
  parentInvocationId: null, agentId: "security", actionId: id, parentActionId: null, kind: "invocation.started", name: "security", status: "running", metadata: {}, ...overrides })
const events = [event("first"), event("second", { invocationId: "child", parentInvocationId: "root", agentId: "scanner", kind: "tool.started", name: "read_file" }),
  event("third", { invocationId: "child", parentInvocationId: "root", agentId: "scanner", kind: "tool.finished", name: "read_file", status: "failed" })]

beforeEach(async () => {
  vi.resetAllMocks()
  await changeLanguage("es")
  vi.mocked(getQualityAudit).mockResolvedValue(audit)
  vi.mocked(listAgentSettings).mockResolvedValue([
    { agentType: "security", name: "Seguridad", qualityAttributes: [], workflowIds: [], configured: false, configuration: null },
  ])
  vi.mocked(loadExecutionEvents).mockResolvedValue(events)
})

function show(tab = "chronology") {
  return render(<MemoryRouter initialEntries={[`/projects/5/audits/8?tab=${tab}`]}>
    <QualityAuditResults projectId={5} auditId={8} projectName="acme/demo" />
  </MemoryRouter>)
}

it("shows real events with catalog names, parent paths and the event's own state and time", async () => {
  show()
  const panel = screen.getByRole("tabpanel", { name: "Cronología" })
  const items = await within(panel).findAllByRole("listitem")
  expect(items).toHaveLength(2)
  await waitFor(() => expect(items[0].querySelector(".audit-chronology-path")).toHaveTextContent("Seguridad → scanner"))
  const summary = items[0].querySelector("summary")!
  expect(items[0].querySelector("details")).not.toHaveAttribute("open")
  fireEvent.click(summary)
  expect(items[0].querySelector("details")).toHaveAttribute("open")
  expect((await within(items[0]).findAllByRole("article"))[0]).toHaveAttribute("data-state", "failed")
  expect(items[0].querySelector("time")).toHaveAttribute("datetime", events[0].occurredAt)
  expect(within(panel).getByText("Inicio de intento de herramienta: read_file")).toBeVisible()
  expect(panel).not.toHaveTextContent("DEMO")
  expect(loadExecutionEvents).toHaveBeenCalledWith(8, expect.any(AbortSignal))
})

it("loads only when the tab is opened and refreshes from the beginning", async () => {
  show("general")
  await screen.findByText("Actualizar")
  expect(loadExecutionEvents).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole("tab", { name: "Cronología" }))
  await screen.findAllByRole("listitem")
  fireEvent.click(screen.getByRole("button", { name: "Actualizar eventos" }))
  await waitFor(() => expect(loadExecutionEvents).toHaveBeenCalledTimes(2))
})

it("offers retry on failure instead of presenting an empty or successful history", async () => {
  vi.mocked(loadExecutionEvents).mockRejectedValueOnce(new Error("private error"))
  show()
  expect(await screen.findByRole("alert")).toHaveTextContent("No se pudo cargar la cronología")
  expect(screen.queryByText("private error")).toBeNull()
  fireEvent.click(screen.getByRole("button", { name: "Reintentar" }))
  expect(await screen.findAllByRole("listitem")).toHaveLength(2)
})

it("shows an honest empty state for older audits and supports English", async () => {
  await changeLanguage("en")
  vi.mocked(loadExecutionEvents).mockResolvedValue([])
  show()
  expect(await screen.findByText("No events are recorded for this audit.")).toBeVisible()
  expect(screen.getByRole("note")).toHaveTextContent("older audits are not backfilled")
})

it("builds paths without mixing audits and handles cycles", () => {
  expect(eventInvocationPaths(events, new Map())[1]).toBe("security → scanner")
  expect(eventInvocationPaths([event("other", { runId: "other", parentInvocationId: "root" })], new Map())[0]).toBe("security")
  expect(eventInvocationPaths([events[0], event("other", { runId: "other", invocationId: "child", parentInvocationId: "root", agentId: "scanner" })], new Map())[1]).toBe("root → scanner")
})

it("uses incident-style pagination above and below with synchronized page sizes", async () => {
  vi.mocked(loadExecutionEvents).mockResolvedValue(Array.from({ length: 21 }, (_, i) => event(`event-${i}`, { invocationId: `run-${i}`, agentId: `agent-${i}` })))
  show()
  expect(await screen.findAllByRole("listitem")).toHaveLength(5)
  expect(screen.getAllByRole("navigation", { name: "Páginas de rutas de ejecución" })).toHaveLength(2)
  fireEvent.click(screen.getAllByRole("button", { name: "Página siguiente" })[0])
  expect(screen.getAllByRole("listitem")[0].querySelector("summary")).toHaveTextContent("agent-15")
  fireEvent.change(screen.getAllByLabelText("Bloques por página")[1], { target: { value: "20" } })
  expect(screen.getAllByRole("listitem")).toHaveLength(20)
  expect(screen.getAllByLabelText("Bloques por página")[0]).toHaveValue("20")
  expect(screen.getAllByRole("listitem")[0].querySelector("summary")).toHaveTextContent("agent-20")
  fireEvent.click(screen.getAllByRole("button", { name: "Página siguiente" })[1])
  expect(screen.getAllByRole("listitem")).toHaveLength(1)
  expect(screen.getByRole("listitem").querySelector("summary")).toHaveTextContent("agent-0")
})

it("orders the entire history before pagination and resets the page without refetching", async () => {
  vi.mocked(loadExecutionEvents).mockResolvedValue(Array.from({ length: 12 }, (_, i) => event(`event-${i}`, {
    occurredAt: `2026-10-30T10:00:${String(i).padStart(2, "0")}Z`, sequence: i + 1, invocationId: `run-${i}`, agentId: `agent-${i}`,
  })))
  show()
  await screen.findAllByRole("listitem")
  expect(screen.getAllByLabelText("Orden cronológico")[0]).toHaveValue("newest")
  expect(screen.getAllByLabelText("Orden cronológico")[0].closest(".quality-audit-pagination")).not.toBeNull()
  expect(screen.getAllByRole("listitem")[0].querySelector("summary")).toHaveTextContent("agent-11")
  fireEvent.click(screen.getAllByRole("button", { name: "Página siguiente" })[0])
  fireEvent.change(screen.getAllByLabelText("Orden cronológico")[0], { target: { value: "oldest" } })
  expect(screen.getAllByRole("listitem")[0].querySelector("summary")).toHaveTextContent("agent-0")
  fireEvent.click(screen.getAllByRole("button", { name: "Página siguiente" })[1])
  expect(screen.getAllByRole("listitem")[0].querySelector("summary")).toHaveTextContent("agent-5")
  fireEvent.change(screen.getAllByLabelText("Orden cronológico")[1], { target: { value: "newest" } })
  expect(screen.getAllByLabelText("Orden cronológico")[0]).toHaveValue("newest")
  expect(screen.getAllByRole("listitem")[0].querySelector("summary")).toHaveTextContent("agent-11")
  expect(loadExecutionEvents).toHaveBeenCalledOnce()
})

it("aborts history requests when leaving the tab", async () => {
  vi.mocked(loadExecutionEvents).mockImplementation(() => new Promise(() => {}))
  show()
  await waitFor(() => expect(loadExecutionEvents).toHaveBeenCalledOnce())
  const signal = vi.mocked(loadExecutionEvents).mock.calls[0][1]
  fireEvent.click(screen.getByRole("tab", { name: "Resumen General" }))
  expect(signal.aborted).toBe(true)
})

it("groups consecutive same-path events with different timestamps into a time interval", async () => {
  vi.mocked(loadExecutionEvents).mockResolvedValue([
    event("first", { invocationId: "invocation-1", occurredAt: "2026-10-30T10:00:00Z" }),
    event("second", { invocationId: "invocation-2", occurredAt: "2026-10-30T11:00:00Z" }),
  ])
  show()
  const items = await screen.findAllByRole("listitem")
  expect(items).toHaveLength(1)
  expect(items[0].querySelector("summary")).toHaveTextContent("2 eventos")
  expect([...items[0].querySelectorAll("summary time")].map((time) => time.getAttribute("datetime")))
    .toEqual(["2026-10-30T11:00:00Z", "2026-10-30T10:00:00Z"])
  expect(screen.queryByRole("article")).toBeNull()
  fireEvent.click(items[0].querySelector("summary")!)
  const articles = await within(items[0]).findAllByRole("article")
  expect(articles.map((article) => article.getAttribute("aria-label"))).toEqual(["invocation.started · second", "invocation.started · first"])
  fireEvent.change(screen.getAllByLabelText("Orden cronológico")[0], { target: { value: "oldest" } })
  expect(within(items[0]).getAllByRole("article").map((article) => article.getAttribute("aria-label")))
    .toEqual(["invocation.started · first", "invocation.started · second"])
})

it("never merges a route across intervening routes, even at the same timestamp", async () => {
  vi.mocked(loadExecutionEvents).mockResolvedValue([
    event("early", { occurredAt: "2026-10-30T10:00:00Z" }),
    event("middle", { agentId: "scanner", invocationId: "scanner", occurredAt: "2026-10-30T10:01:00Z" }),
    event("late", { occurredAt: "2026-10-30T10:02:00Z" }),
    event("same-time-other-route", { agentId: "scanner", invocationId: "scanner", occurredAt: "2026-10-30T10:02:00Z" }),
    event("same-time-original-route", { occurredAt: "2026-10-30T10:02:00Z" }),
  ])
  show()
  await screen.findAllByRole("listitem")
  const summaries = () => [...screen.getByRole("tabpanel", { name: "Cronología" }).querySelectorAll("summary")]
  expect(summaries()).toHaveLength(5)
  for (const summary of summaries()) fireEvent.click(summary)
  await waitFor(() => expect(screen.getAllByRole("article")).toHaveLength(5))
  expect(screen.getAllByRole("article").map((article) => article.getAttribute("aria-label"))).toEqual([
    "invocation.started · same-time-original-route", "invocation.started · same-time-other-route", "invocation.started · late",
    "invocation.started · middle", "invocation.started · early",
  ])
  fireEvent.change(screen.getAllByLabelText("Orden cronológico")[0], { target: { value: "oldest" } })
  expect(screen.getAllByRole("article").map((article) => article.getAttribute("aria-label"))).toEqual([
    "invocation.started · early", "invocation.started · middle", "invocation.started · late",
    "invocation.started · same-time-other-route", "invocation.started · same-time-original-route",
  ])
})

it("opens event details in the shared modal, traps focus and closes with Escape", async () => {
  const user = userEvent.setup()
  vi.mocked(loadExecutionEvents).mockResolvedValue([event("finished", {
    kind: "tool.finished", name: "get_source_excerpt", status: "rejected", metadata: { seconds: 0.125, cache_hit: false },
  })])
  show()
  const item = (await screen.findAllByRole("listitem"))[0]
  await user.click(item.querySelector("summary")!)
  const row = await screen.findByRole("button", { name: "Fin de intento de herramienta: Leer fragmento de código" })
  expect(item.querySelector(".audit-chronology-list details")).toBeNull()
  await user.click(row)
  const modal = screen.getByRole("dialog", { name: "Detalles del evento" })
  expect(within(modal).getByText("Rechazado")).toBeVisible()
  expect(within(modal).getByText("0,125 s")).toBeVisible()
  expect(within(modal).getByText(/Un rechazo no significa/)).toBeVisible()
  expect(within(modal).getByText(/No se registró un mensaje asociado/)).toBeVisible()
  const close = within(modal).getByRole("button", { name: "Cerrar" })
  expect(close).toHaveFocus()
  await user.tab()
  expect(close).toHaveFocus()
  await user.keyboard("{Escape}")
  expect(screen.queryByRole("dialog")).toBeNull()
  expect(row).toHaveFocus()
  await user.keyboard("{Enter}")
  expect(screen.getByRole("dialog")).toBeVisible()
  await user.click(screen.getByRole("button", { name: "Cerrar" }))
  expect(screen.queryByRole("dialog")).toBeNull()
  expect(row).toHaveFocus()
})

it("shows unrecorded duration rather than assuming zero in the event modal", async () => {
  show()
  const item = (await screen.findAllByRole("listitem"))[0]
  fireEvent.click(item.querySelector("summary")!)
  const row = await within(item).findByRole("button", { name: "Fin de intento de herramienta: read_file" })
  fireEvent.click(row)
  const modal = screen.getByRole("dialog")
  expect(within(modal).getByText("No registrado")).toBeVisible()
  expect(within(modal).queryByText("0 s")).toBeNull()
})

it("polls active history, reads late events after completion, then keeps the final history without polling", async () => {
  vi.useFakeTimers()
  let view: ReturnType<typeof render> | undefined
  try {
    vi.mocked(loadExecutionEvents).mockResolvedValueOnce([event("first")]).mockResolvedValue(events)
    const running = { ...audit, executionStatus: "Running", finishedAt: null }
    await act(async () => { view = render(<AuditChronologyTab active audit={running} revision={0} />) })
    expect(loadExecutionEvents).toHaveBeenCalledTimes(1)
    expect(screen.getByRole("status")).toHaveTextContent("automáticamente")
    await act(async () => { await vi.advanceTimersByTimeAsync(3000) })
    expect(loadExecutionEvents).toHaveBeenCalledTimes(2)
    expect(screen.getAllByRole("listitem")).toHaveLength(2)
    await act(async () => { view!.rerender(<AuditChronologyTab active audit={audit} revision={0} />) })
    expect(loadExecutionEvents).toHaveBeenCalledTimes(3)
    await act(async () => { await vi.advanceTimersByTimeAsync(6000) })
    expect(loadExecutionEvents).toHaveBeenCalledTimes(5)
    await act(async () => { await vi.advanceTimersByTimeAsync(30000) })
    expect(loadExecutionEvents).toHaveBeenCalledTimes(5)
    expect(screen.getAllByRole("listitem")).toHaveLength(2)
    expect(screen.queryByRole("status")).toBeNull()
  } finally { view?.unmount(); vi.useRealTimers() }
})

it("retains the visible history on polling failures, recovers and stops requests when the tab is hidden", async () => {
  vi.useFakeTimers()
  let view: ReturnType<typeof render> | undefined
  try {
    vi.mocked(loadExecutionEvents).mockResolvedValueOnce(events).mockRejectedValueOnce(new Error("private error")).mockResolvedValue(events)
    const running = { ...audit, executionStatus: "Running" }
    await act(async () => { view = render(<AuditChronologyTab active audit={running} revision={0} />) })
    await act(async () => { await vi.advanceTimersByTimeAsync(3000) })
    expect(screen.getAllByRole("listitem")).toHaveLength(2)
    expect(screen.getByRole("alert")).toHaveTextContent("últimos eventos cargados")
    expect(screen.queryByText("private error")).toBeNull()
    await act(async () => { await vi.advanceTimersByTimeAsync(3000) })
    expect(screen.queryByRole("alert")).toBeNull()
    await act(async () => { view!.rerender(<AuditChronologyTab active={false} audit={running} revision={0} />) })
    const count = vi.mocked(loadExecutionEvents).mock.calls.length
    const signal = vi.mocked(loadExecutionEvents).mock.calls.at(-1)![1]
    expect(signal.aborted).toBe(true)
    await act(async () => { await vi.advanceTimersByTimeAsync(30000) })
    expect(loadExecutionEvents).toHaveBeenCalledTimes(count)
  } finally { view?.unmount(); vi.useRealTimers() }
})

it("keeps an existing route mounted when newer events have lexically smaller IDs", async () => {
  vi.useFakeTimers()
  let view: ReturnType<typeof render> | undefined
  try {
    const first = event("z-first")
    vi.mocked(loadExecutionEvents).mockResolvedValueOnce([first]).mockResolvedValue([
      first, event("a-newer", { occurredAt: "2026-10-30T10:01:00Z" }),
    ])
    await act(async () => { view = render(<AuditChronologyTab active audit={{ ...audit, executionStatus: "Running" }} revision={0} />) })
    const summary = screen.getByRole("listitem").querySelector("summary")!
    const block = summary.closest("details")!
    await act(async () => { fireEvent.click(summary); await vi.advanceTimersByTimeAsync(0) })
    expect(block).toHaveAttribute("open")
    await act(async () => { await vi.advanceTimersByTimeAsync(3000) })
    expect(document.querySelector(".audit-chronology-group")).toBe(block)
    expect(block).toHaveAttribute("open")
    expect(summary).toHaveTextContent("2 eventos")
  } finally { view?.unmount(); vi.useRealTimers() }
})

it("reveals a route's events in batches of 20 and resets the batch when changing order", async () => {
  const user = userEvent.setup()
  vi.mocked(loadExecutionEvents).mockResolvedValue(Array.from({ length: 45 }, (_, i) => event(`event-${i}`, {
    sequence: i + 1, occurredAt: `2026-10-30T10:00:${String(i).padStart(2, "0")}Z`,
  })))
  show()
  const item = (await screen.findAllByRole("listitem"))[0]
  await user.click(item.querySelector("summary")!)
  expect(await screen.findAllByRole("article")).toHaveLength(20)
  expect(screen.getAllByRole("article")[0]).toHaveAttribute("aria-label", "invocation.started · event-44")
  expect(screen.getAllByRole("article")[19]).toHaveAttribute("aria-label", "invocation.started · event-25")
  const more = screen.getByRole("button", { name: "Mostrar siguientes 20 eventos" })
  expect(more).toHaveTextContent("…")
  await user.click(more)
  expect(screen.getAllByRole("article")).toHaveLength(40)
  await user.click(more)
  expect(screen.getAllByRole("article")).toHaveLength(45)
  expect(screen.queryByRole("button", { name: "Mostrar siguientes 20 eventos" })).toBeNull()
  expect(loadExecutionEvents).toHaveBeenCalledOnce()
  fireEvent.change(screen.getAllByLabelText("Orden cronológico")[0], { target: { value: "oldest" } })
  expect(screen.getAllByRole("article")).toHaveLength(20)
  expect(screen.getAllByRole("article")[0]).toHaveAttribute("aria-label", "invocation.started · event-0")
  expect(screen.getByRole("button", { name: "Mostrar siguientes 20 eventos" })).toBeVisible()
})
