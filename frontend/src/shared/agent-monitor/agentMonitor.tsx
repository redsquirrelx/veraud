import { useCallback, useEffect, useState, type ReactNode } from "react"
import { backendWsUrl, getAgentExecution, type AgentExecution } from "../../infrastructure/http-client/httpClient.ts"
import { localStorage } from "../../infrastructure/storage/LocalStorage.ts"
import { mergeExecution, mergeInvocations } from "./mergeExecution.ts"
import { AgentExecutionsContext, AuditExecutionUpdateContext } from "./useAgentExecutions.ts"
import type { AuditCancellationResult } from "../../infrastructure/http-client/httpClient.ts"

interface AgentExecutionEvent {
  type: string
  execution: AgentExecution
}

function isAgentEvent(data: unknown): data is AgentExecutionEvent {
  if (typeof data !== "object" || data === null) {
    return false
  }
  const event = data as { type?: unknown; execution?: unknown }
  if (event.type !== "agent-execution.opened" && event.type !== "agent-execution.updated") {
    return false
  }
  const execution = event.execution as { id?: unknown } | null
  return typeof execution?.id === "number"
}

export function AgentExecutionsProvider({ children, retryMs = 3000 }: { children: ReactNode; retryMs?: number }) {
  const [executions, setExecutions] = useState<AgentExecution[]>([])
  const updateAudit = useCallback((audit: AuditCancellationResult) => {
    setExecutions((current) => current.map((execution) => {
      if (execution.id !== audit.id) return execution
      let result: Record<string, unknown> = {}
      try {
        const parsed: unknown = JSON.parse(execution.result ?? "{}")
        if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) result = parsed as typeof result
      } catch { /* Retain the live metadata. */ }
      return mergeExecution(execution, { ...execution, status: audit.executionStatus, error: audit.error,
        finishedAt: audit.finishedAt, cancellationRequestedAt: audit.cancellationRequestedAt,
        interruptionReason: audit.auditStatus === "cancelled" ? "cancelled"
          : audit.cancellationRequestedAt && ["Waiting", "Running"].includes(audit.executionStatus) ? "cancellation_requested" : null,
        result: JSON.stringify({ ...result, status: audit.auditStatus, run_id: audit.runId ?? result.run_id }),
      })
    }))
  }, [])

  useEffect(() => {
    let alive = true
    let socket: WebSocket | null = null
    let retry: ReturnType<typeof setTimeout> | null = null
    const stored = localStorage.get<unknown>("agents.recentExecutionIds", [])
    const knownIds = new Set<number>(Array.isArray(stored) ? stored.filter((id): id is number => Number.isInteger(id) && id > 0).slice(-50) : [])
    const hydrated = new Set<number>()
    const pending = new Set<number>()
    const refreshAgain = new Set<number>()
    const revisions = new Map<number, number>()

    function apply(execution: AgentExecution, snapshotOnly = false) {
      if (!alive) return
      setExecutions((current) => {
        const index = current.findIndex((item) => item.id === execution.id)
        if (index === -1) return [...current, execution].sort((a, b) => a.id - b.id).slice(-50)
        const next = [...current]
        next[index] = snapshotOnly ? {
           ...current[index]!, configuration: execution.configuration ?? current[index]?.configuration ?? null,
            monitorContext: execution.monitorContext ?? current[index]?.monitorContext,
            invocations: mergeInvocations(execution.invocations, current[index]?.invocations),
        } : mergeExecution(current[index], execution)
        return next
      })
    }

    async function refresh(id: number) {
      if (pending.has(id)) { refreshAgain.add(id); return }
      pending.add(id)
      const revision = revisions.get(id) ?? 0
      try {
        const execution = await getAgentExecution(id, true)
        if (execution.id !== id) return
        hydrated.add(id)
        apply(execution, revision !== (revisions.get(id) ?? 0))
      } catch {
        // A later event/reconnect can retry; transient HTTP failures keep the live row.
      } finally {
        pending.delete(id)
        if (alive && refreshAgain.delete(id)) void refresh(id)
      }
    }

    function restore() {
      for (const id of knownIds) void refresh(id)
    }

    function handleMessage(event: MessageEvent) {
      if (!alive) {
        return
      }
      let data: unknown
      try {
        data = JSON.parse(String(event.data))
      } catch {
        return
      }
      if (!isAgentEvent(data)) {
        return
      }
      knownIds.add(data.execution.id)
      if (knownIds.size > 50) knownIds.delete(knownIds.values().next().value!)
      localStorage.set("agents.recentExecutionIds", [...knownIds])
      revisions.set(data.execution.id, (revisions.get(data.execution.id) ?? 0) + 1)
      apply(data.execution)
      if (!hydrated.has(data.execution.id) || data.execution.status === "Completed" || data.execution.status === "Failed") {
        void refresh(data.execution.id)
      }
    }

    function schedule() {
      if (!alive) {
        return
      }
      retry = setTimeout(() => void connect(), retryMs)
    }

    function connect() {
      if (!alive) {
        return
      }
      try {
        socket = new WebSocket(backendWsUrl())
      } catch {
        schedule()
        return
      }
      socket.addEventListener("message", handleMessage)
      socket.addEventListener("open", restore)
      socket.addEventListener("close", schedule)
      socket.addEventListener("error", () => socket?.close())
    }

    connect()
    restore()

    return () => {
      alive = false
      if (retry !== null) {
        clearTimeout(retry)
      }
      const current = socket
      if (current === null) {
        return
      }
      if (current.readyState === WebSocket.CONNECTING) {
        current.addEventListener("open", () => current.close(), { once: true })
      } else {
        current.close()
      }
    }
  }, [retryMs])

  return <AuditExecutionUpdateContext.Provider value={updateAudit}>
    <AgentExecutionsContext.Provider value={executions}>{children}</AgentExecutionsContext.Provider>
  </AuditExecutionUpdateContext.Provider>
}
