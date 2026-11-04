import type { AuditConfigurationHistory } from "./qualityAuditApi.ts"

export interface ExecutedEvidenceAgent { id: string, name: string, invocationId: string }
const executedStatuses = new Set(["running", "completed", "partial", "failed", "cancelled", "timeout"])

/** Saved participants plus actual receipts, never the current global catalog.
 * Legacy audits without a snapshot can still prove participation via receipts. */
export function executedEvidenceAgents(history: AuditConfigurationHistory): ExecutedEvidenceAgent[] {
  const names = new Map<string, string>()
  for (const scope of history.configuration?.scopes ?? []) {
    for (const agent of [...scope.requiredAgents, ...scope.techniques, ...scope.investigators]) names.set(agent.id, agent.name)
    for (const child of scope.subcharacteristics) {
      names.set(child.id, child.name)
      for (const agent of child.investigators) names.set(agent.id, agent.name)
    }
  }
  const agents = new Map<string, ExecutedEvidenceAgent>()
  for (const invocation of history.invocations) {
    if (!executedStatuses.has(invocation.status) || !invocation.id || !invocation.agentId
      || (history.configuration !== null && !names.has(invocation.agentId))) continue
    agents.set(invocation.agentId, { id: invocation.agentId, name: names.get(invocation.agentId) ?? invocation.agentId, invocationId: invocation.id })
  }
  return [...agents.values()]
}
