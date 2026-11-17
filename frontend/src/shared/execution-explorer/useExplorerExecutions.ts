import { useEffect, useMemo, useState } from "react"
import { useAgentExecutions } from "../agent-monitor/useAgentExecutions.ts"
import { executionAudits } from "../audit-monitor/executionAudits.ts"
import { listAgentSettings, type AgentExecution, type AgentSettings } from "../../infrastructure/http-client/httpClient.ts"
import type { AuditStatusModel } from "../audit-monitor/auditStatus.ts"

/** Root agent types that identify a quality-audit group before the row is
 *  hydrated with `monitorContext.evaluationType === "QualityAudit"`. */
const AUDIT_ROOT_AGENTS = new Set(["maintainability_manager", "security", "functional_adequacy"])
/** Root agent types that identify an architecture-context group for the same reason. */
const ARCHITECTURE_CONTEXT_AGENTS = new Set(["architecture_context"])
/** Verification-suite generation rows (the suite runner itself; the two
 *  generator agents are reported as invocation receipts under it). */
const VERIFICATION_SUITE_AGENTS = new Set(["verification_suite"])

export type ExplorerRowKind = "audit" | "agent"

export interface ExplorerRow {
  kind: ExplorerRowKind
  model: AuditStatusModel
}

function groupKey(execution: AgentExecution) {
  return execution.evaluationId === null ? `direct:${execution.id}` : `evaluation:${execution.evaluationId}`
}

function classifyGroup(group: AgentExecution[]): ExplorerRowKind | null {
  if (group.some((item) => item.monitorContext?.evaluationType === "QualityAudit") || group.some((item) => AUDIT_ROOT_AGENTS.has(item.agentType))) {
    return "audit"
  }
  if (group.some((item) => item.monitorContext?.evaluationType === "ArchitectureContext") || group.some((item) => ARCHITECTURE_CONTEXT_AGENTS.has(item.agentType))) {
    return "agent"
  }
  if (group.some((item) => item.monitorContext?.evaluationType === "VerificationSuite") || group.some((item) => VERIFICATION_SUITE_AGENTS.has(item.agentType))) {
    return "agent"
  }
  return null
}

/** Live executions for the Execution Explorer: same WS/HTTP feed, grouping and
 *  semantics as the audit monitor. Read-only — no filters, actions or polling
 *  are added here. Only quality audits and architecture-context runs are
 *  visible; everything else (analysis pipeline, finding resolution, direct
 *  runs) never reaches the UI. */
export function useExplorerExecutions(): ExplorerRow[] {
  const executions = useAgentExecutions()
  const hasExecutions = executions.length > 0
  const [catalog, setCatalog] = useState<AgentSettings[]>([])

  useEffect(() => {
    if (!hasExecutions) return
    const controller = new AbortController()
    listAgentSettings(controller.signal)
      .then((agents) => { if (!controller.signal.aborted) setCatalog(agents) })
      .catch(() => { /* HTTP execution context stays usable while the catalog is unavailable. */ })
    return () => controller.abort()
  }, [hasExecutions])

  return useMemo(() => {
    if (executions.length === 0) return []
    const groups = new Map<string, AgentExecution[]>()
    for (const execution of executions) {
      groups.set(groupKey(execution), [...(groups.get(groupKey(execution)) ?? []), execution])
    }
    const kept = new Map<string, ExplorerRowKind>()
    for (const [key, group] of groups) {
      const kind = classifyGroup(group)
      if (kind) kept.set(key, kind)
    }
    // executionAudits groups the same way and tags models with their first id,
    // so the kind travels with the model unchanged.
    const kindById = new Map<number, ExplorerRowKind>()
    for (const execution of executions) {
      const kind = kept.get(groupKey(execution))
      if (!kind) continue
      kindById.set(execution.id, kind)
    }
    return executionAudits(executions.filter((item) => kept.has(groupKey(item))), catalog).map((model) => ({
      kind: kindById.get(model.id) ?? "audit",
      model,
    }))
  }, [executions, catalog])
}
