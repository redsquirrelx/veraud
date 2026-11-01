import { requestJson } from "../../infrastructure/http-client/httpClient.ts"

export interface ExecutionEvent {
  eventId: string
  streamId: string
  sequence: number
  occurredAt: string
  receivedAt: string
  runId: string | null
  invocationId: string | null
  parentInvocationId: string | null
  agentId: string | null
  actionId: string
  parentActionId: string | null
  sourceId?: string | null
  kind: string
  name: string | null
  status: string | null
  metadata: Record<string, number | boolean>
}

export function getExecutionEvents(id: number, offset: number, signal?: AbortSignal) {
  return requestJson<{ total: number, events: ExecutionEvent[] }>(
    `/api/agent-executions/${id}/events?offset=${offset}&limit=200`, "Could not load execution events", { signal }, false)
}

/** Read every page, deduplicating replays without collapsing repeated actions. */
export async function loadExecutionEvents(id: number, signal: AbortSignal) {
  const events = new Map<string, ExecutionEvent>()
  let offset = 0
  let total = Infinity
  while (offset < total) {
    const page = await getExecutionEvents(id, offset, signal)
    if (signal.aborted) throw new DOMException("Aborted", "AbortError")
    total = Math.min(total, page.total)
    if (!page.events.length && offset < total) throw new Error("Incomplete event page")
    for (const event of page.events) events.set(event.eventId, event)
    offset += page.events.length
  }
  return [...events.values()].sort((a, b) => Date.parse(a.occurredAt) - Date.parse(b.occurredAt)
    || a.streamId.localeCompare(b.streamId) || a.sequence - b.sequence || a.eventId.localeCompare(b.eventId))
}

export function eventInvocationPaths(events: ExecutionEvent[], names: Map<string, string>) {
  const invocations = new Map<string, ExecutionEvent>()
  const key = (event: ExecutionEvent, id: string) => `${event.runId ?? event.streamId}:${id}`
  for (const event of events) if (event.invocationId) {
    const id = key(event, event.invocationId)
    const previous = invocations.get(id)
    if (!previous || event.kind === "invocation.started" || !previous.agentId && event.agentId) invocations.set(id, event)
  }
  return events.map((event) => {
    const path: string[] = []
    const seen = new Set<string>()
    let current: ExecutionEvent | undefined = event.invocationId ? invocations.get(key(event, event.invocationId)) : event
    while (current) {
      const id = current.invocationId
      if (id && seen.has(id)) break
      if (id) seen.add(id)
      if (current.agentId) path.unshift(names.get(current.agentId) ?? current.agentId)
      const parent = current.parentInvocationId
      current = parent ? invocations.get(key(event, parent)) : undefined
      if (parent && !current) path.unshift(parent)
    }
    return path.join(" → ")
  })
}
