import { createContext, useContext } from "react"
import type { AgentExecution, AuditCancellationResult } from "../../infrastructure/http-client/httpClient.ts"

export const AgentExecutionsContext = createContext<AgentExecution[]>([])
export const AuditExecutionUpdateContext = createContext<(audit: AuditCancellationResult) => void>(() => {})

export function useAgentExecutions(): AgentExecution[] {
  return useContext(AgentExecutionsContext)
}

/** Refetch summaries only for cancellation lifecycle changes, not every phase/token update. */
export function useAuditCancellationRevision(projectId: number, auditId?: number): string {
  return useAgentExecutions().filter((execution) =>
    (auditId === undefined || execution.id === auditId) && execution.monitorContext?.project?.id === projectId
    && (execution.cancellationRequestedAt || execution.interruptionReason === "cancellation_requested" || execution.interruptionReason === "cancelled"),
  ).map((execution) => `${execution.id}:${execution.status}:${execution.cancellationRequestedAt ?? ""}:${execution.interruptionReason ?? ""}`).sort().join("|")
}
