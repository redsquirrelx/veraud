import type { AgentExecution, ExecutionErrorDetail } from "../../infrastructure/http-client/httpClient.ts"
import { readExecutionErrorDetail } from "../../infrastructure/http-client/executionErrorDetail.ts"
import type { QualityAuditSummary } from "./qualityAuditApi.ts"
import { publicErrorText } from "../../infrastructure/http-client/publicErrors.ts"

export interface AuditIncident {
  id: string
  detail: ExecutionErrorDetail | null
  message: string
  agentId: string | null
  invocationId: string | null
  occurredAt: string | null
}

/** Only recorded incidents; failed states alone cannot manufacture an event. */
export function auditIncidents(execution: AgentExecution, audit: QualityAuditSummary): AuditIncident[] {
  const incidents = new Map<string, AuditIncident>()
  function add(owner: string, agentId: string | null, invocationId: string | null, raw: unknown, error: string | null | undefined) {
    const detail = readExecutionErrorDetail(raw)
    const message = detail?.message ?? publicErrorText(error)
    if (!message) return
    const sourceAgent = detail ? detail.agentId : agentId
    const sourceInvocation = detail ? detail.invocationId : invocationId
    const dateKey = detail?.occurredAt ? new Date(detail.occurredAt).toISOString() : null
    const id = detail ? JSON.stringify([sourceAgent, sourceInvocation ?? owner, dateKey, detail.code, message]) : owner
    if (!incidents.has(id)) incidents.set(id, { id, detail, message, agentId: sourceAgent,
      invocationId: sourceInvocation, occurredAt: detail?.occurredAt ?? null })
  }
  const rootDetail = execution.errorDetail ?? audit.errorDetail
  add(`execution:${execution.id}`, execution.agentType, null, rootDetail, execution.error ?? audit.error)
  for (const receipt of execution.invocations ?? []) {
    add(`invocation:${receipt.invocation_id}`, receipt.agent_id, receipt.invocation_id, receipt.error_detail, receipt.error)
  }
  return [...incidents.values()].sort((a, b) => {
    const first = a.occurredAt ? Date.parse(a.occurredAt) : Infinity
    const second = b.occurredAt ? Date.parse(b.occurredAt) : Infinity
    return first === second ? a.id.localeCompare(b.id) : first - second
  })
}
