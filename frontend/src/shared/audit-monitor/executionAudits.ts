import type { AgentExecution, AgentSettings } from "../../infrastructure/http-client/httpClient.ts"
import { auditStateFrom, isFinished, type AuditAgentRun, type AuditRunState, type AuditStatusModel } from "./auditStatus.ts"

type RecordValue = Record<string, unknown>
const object = (value: unknown): RecordValue => value !== null && typeof value === "object" && !Array.isArray(value) ? value as RecordValue : {}
const rows = (value: unknown): RecordValue[] => Array.isArray(value) ? value.map(object) : []
const strings = (value: unknown): string[] => Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : []
const text = (value: unknown): string | null => typeof value === "string" ? value : null
const count = (value: unknown): number | null => typeof value === "number" && value >= 0 ? value : null

function resultOf(execution: AgentExecution): RecordValue {
  try { return object(JSON.parse(execution.result ?? "null")) }
  catch { return {} }
}

function combined(states: AuditRunState[]): AuditRunState {
  if (!states.length) return "unknown"
  if (states.includes("running")) return "running"
  if (states.includes("waiting")) return "waiting"
  if (states.includes("failed")) return "failed"
  if (states.includes("partial")) return "partial"
  return states.every((state) => state === "completed") ? "completed" : "unknown"
}

/** Project/evaluation identity groups real rows; catalog membership never creates runs.
 * Final report traces provide retrospective participants, not simulated live events. */
export function executionAudits(executions: AgentExecution[], catalog: AgentSettings[]): AuditStatusModel[] {
  const byAgent = new Map(catalog.map((agent) => [agent.agentType, agent]))
  const groups = new Map<string, AgentExecution[]>()
  for (const execution of executions) {
    const key = execution.evaluationId === null ? `direct:${execution.id}` : `evaluation:${execution.evaluationId}`
    groups.set(key, [...(groups.get(key) ?? []), execution])
  }
  return [...groups.values()].map((group): AuditStatusModel => {
    group.sort((a, b) => a.id - b.id)
    const first = group[0]!
    const context = group.find((item) => item.monitorContext)?.monitorContext
    const pipelines = new Map<string, Map<string | number, AuditAgentRun>>()
    const reportedStates = new Map<string, AuditRunState>()
    const outcomes: string[] = []
    let reportAvailable = false
    const add = (pipeline: string, agent: AuditAgentRun) => {
      if (!pipelines.has(pipeline)) pipelines.set(pipeline, new Map())
      pipelines.get(pipeline)!.set(agent.id, agent)
    }
    for (const execution of group) {
      const result = resultOf(execution)
      const report = object(result.report)
      const selected = strings(result.attributes)
      const metadata = byAgent.get(execution.agentType)
      const attributes = metadata?.qualityAttributes ?? execution.monitorContext?.qualityAttributes ?? []
      const workflows = metadata?.workflowIds ?? execution.monitorContext?.workflowIds ?? []
      const quality = execution.monitorContext?.evaluationType === "QualityAudit" || selected.length > 0
      if (quality) {
        const status = text(result.status)
        if (status) outcomes.push(status)
        reportAvailable ||= Object.keys(report).length > 0
        for (const attribute of selected) if (!pipelines.has(attribute)) pipelines.set(attribute, new Map())
        for (const attribute of rows(object(report.quality_results).attributes)) {
          const id = text(attribute.id)
          if (id && (!selected.length || selected.includes(id))) {
            reportedStates.set(id, auditStateFrom("", text(attribute.status)))
            if (!pipelines.has(id)) pipelines.set(id, new Map())
          }
        }
      }
      const bucket = (id: string): string => {
        const agent = byAgent.get(id)
        const membership = agent?.qualityAttributes ?? (id === execution.agentType ? attributes : [])
        if (membership.length === 1) return membership[0]!
        if (membership.length > 1) return "quality-audit"
        return agent?.workflowIds[0] ?? (id === execution.agentType ? workflows[0] : null) ?? id
      }
      const traces = quality ? rows(object(report.annexes_and_traceability).executions) : []
      for (const trace of traces) {
        const agentType = text(trace.agent_id)
        const invocation = text(trace.invocation_id)
        if (!agentType || !invocation) continue
        const consumption = object(trace.consumption)
        add(bucket(agentType), {
          id: invocation, agentType, state: auditStateFrom(text(trace.status) ?? "", null),
          inputTokens: count(consumption.input_tokens), outputTokens: count(consumption.output_tokens),
          startedAt: null, finishedAt: null, error: null,
        })
      }
      if (!traces.some((trace) => trace.agent_id === execution.agentType && typeof trace.invocation_id === "string")) {
        // One backend row orchestrates a joint audit; its totals are not copied
        // into both attributes. No per-attribute execution state is inferred.
        const pipeline = quality && selected.length > 1 ? "quality-audit" : bucket(execution.agentType)
        add(pipeline, { id: execution.id, agentType: execution.agentType,
          state: auditStateFrom(execution.status, quality ? text(result.status) : null),
          inputTokens: execution.inputTokens, outputTokens: execution.outputTokens,
          startedAt: execution.startedAt, finishedAt: execution.finishedAt, error: execution.error })
      }
    }
    const executionState = combined(group.map((item) => auditStateFrom(item.status, null)))
    const outcome = outcomes.includes("failed") ? "failed" : outcomes.includes("partial") ? "partial"
      : outcomes.length > 0 && outcomes.every((state) => state === "completed") ? "completed" : null
    return {
      id: first.id, project: context?.project ?? null, branch: context?.branch ?? null, commitHash: context?.commitHash ?? null,
      state: outcome ? auditStateFrom("", outcome) : executionState,
      error: group.find((item) => item.error)?.error ?? null,
      createdAt: group.map((item) => item.createdAt).sort()[0]!,
      finishedAt: group.every((item) => isFinished(auditStateFrom(item.status, null)))
        ? group.map((item) => item.finishedAt).filter((date): date is string => date !== null).sort().at(-1) ?? null : null,
      reportAvailable,
      pipelines: [...pipelines].map(([id, agents]) => ({ id,
        state: reportedStates.get(id) ?? combined([...agents.values()].map((agent) => agent.state)), agents: [...agents.values()] })),
    }
  }).sort((a, b) => b.createdAt.localeCompare(a.createdAt) || b.id - a.id)
}
