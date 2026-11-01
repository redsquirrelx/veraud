import { beforeEach, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import { changeLanguage } from "../../shared/i18n/index.ts"
import { ExecutionEventDescription } from "./ExecutionEventDescription.tsx"
import type { ExecutionEvent } from "./executionEventsApi.ts"
import { executionEventPresentation } from "./executionEventPresentation.ts"

const event: ExecutionEvent = { eventId: "event-1", streamId: "stream-1", sequence: 3, occurredAt: "2026-10-31T10:00:00Z",
  receivedAt: "2026-10-31T10:01:00Z", runId: "audit", invocationId: "invocation-1", parentInvocationId: null,
  agentId: "scanner", actionId: "action-1", parentActionId: "parent-1", sourceId: "tool-call-1",
  kind: "tool.finished", name: "get_source_excerpt", status: "rejected", metadata: { seconds: 0.125, cache_hit: false } }

beforeEach(async () => { await changeLanguage("es") })

it("keeps the row compact with three priority metrics and no inline disclosure", () => {
  const { container } = render(<ExecutionEventDescription event={{ ...event, metadata: {
    seconds: 0.125, cache_hit: true, attempt: 2, http_status: 429, input_tokens: 100,
  } }} names={new Map()} />)
  expect(screen.getByText("Fin de intento de herramienta: Leer fragmento de código")).toBeVisible()
  expect(screen.getByText("Estado HTTP: 429")).toBeVisible()
  expect(screen.getByText("Intento: 2")).toBeVisible()
  expect(screen.getByText("Duración (s): 0,125")).toBeVisible()
  expect(screen.queryByText(/Tokens de entrada/)).toBeNull()
  expect(screen.queryByText(/Un rechazo no significa/)).toBeNull()
  expect(container.querySelector("details")).toBeNull()
})

it("explains provider recovery and includes only allowlisted recorded metrics in detailed mode", () => {
  render(<ExecutionEventDescription detailed event={{ ...event, kind: "provider.retry", name: "provider_backoff",
    metadata: { retry: 2, delay_seconds: 5, http_status: 429, private_metric: 123456 } }} names={new Map()} />)
  expect(screen.getByText(/no confirma que el reintento haya terminado/)).toBeVisible()
  expect(screen.getByText("Estado HTTP")).toBeVisible()
  expect(screen.getByText("429")).toBeVisible()
  expect(screen.getByText("Referencias técnicas")).toBeVisible()
  expect(screen.queryByText("123456")).toBeNull()
})

it("uses catalog names and translates phases and publication types", () => {
  const names = new Map([["scanner", "Configured scanner"]])
  expect(executionEventPresentation({ ...event, kind: "invocation.started", name: "scanner" }, "en", names).title)
    .toBe("Agent invocation started: Configured scanner")
  expect(executionEventPresentation({ ...event, kind: "phase.changed", name: "evaluate_evidence" }, "es", names).title)
    .toBe("Entrada en fase: Evaluar evidencia")
  expect(executionEventPresentation({ ...event, kind: "publication.created", name: "Evidence" }, "es", names).title)
    .toBe("Registro publicado: Evidencia")
})

it("preserves unknown identifiers without inventing information", async () => {
  await changeLanguage("en")
  render(<ExecutionEventDescription detailed event={{ ...event, kind: "future.event", name: "custom_operation", metadata: {} }} names={new Map()} />)
  expect(screen.getByText("No description is available for this event type.")).toBeVisible()
  expect(screen.getByText("custom_operation")).toBeVisible()
})
