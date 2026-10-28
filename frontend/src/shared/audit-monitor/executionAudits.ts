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

/** One visible row per agent, retaining the latest invocation's own data.
 * Historical parent IDs resolve to the parent's current row, including children
 * reused by a coordinator continuation. First appearance determines row order. */
function latestAgents(pipelines: Map<string, Map<string | number, AuditAgentRun>>) {
  const latest = new Map<string, { pipeline: string, agent: AuditAgentRun }>()
  const typesById = new Map<string | number, string>()
  for (const [pipeline, agents] of pipelines) {
    for (const agent of agents.values()) {
      typesById.set(agent.id, agent.agentType)
      const prior = latest.get(agent.agentType)?.agent
      const started = Date.parse(agent.startedAt ?? "")
      const previous = Date.parse(prior?.startedAt ?? "")
      if (!prior || (Number.isNaN(started) ? Number.isNaN(previous) : Number.isNaN(previous) || started >= previous)) {
        latest.set(agent.agentType, { pipeline, agent })
      }
    }
  }
  const result = new Map([...pipelines.keys()].map((id) => [id, [] as AuditAgentRun[]]))
  for (const { pipeline, agent } of latest.values()) {
    const parentType = typesById.get(agent.parentId ?? "")
    const parent = parentType ? latest.get(parentType) : undefined
    result.get(pipeline)!.push({ ...agent,
      parentId: parent?.pipeline === pipeline && parentType !== agent.agentType ? parent.agent.id : null })
  }
  return result
}

/** Project/evaluation identity groups real rows; catalog membership never creates runs. */
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
      const quality = execution.monitorContext?.evaluationType === "QualityAudit" || selected.length > 0 || (execution.invocations?.length ?? 0) > 0
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
        // These roots own a specific attribute even when their catalog context
        // or the audit selection includes both quality attributes.
        if (id === "maintainability_manager") return "maintainability"
        if (id === "security") return "security"
        if (id === "functional_adequacy") return "functional_adequacy"
        const agent = byAgent.get(id)
        const membership = agent?.qualityAttributes ?? (id === execution.agentType ? attributes : [])
        if (membership.length === 1) return membership[0]!
        if (membership.length > 1) return "quality-audit"
        return agent?.workflowIds[0] ?? (id === execution.agentType ? workflows[0] : null) ?? id
      }
      const receipts = new Map<string, RecordValue>((execution.invocations ?? []).map((receipt) => [receipt.invocation_id, {
        ...receipt, consumption: { input_tokens: receipt.input_tokens, output_tokens: receipt.output_tokens },
      }]))
      for (const trace of quality ? rows(object(report.annexes_and_traceability).executions) : []) {
        const id = text(trace.invocation_id)
        if (!id) continue
        const live = receipts.get(id)
        const usage = object(trace.consumption)
        const priorUsage = object(live?.consumption)
        receipts.set(id, { ...live, ...trace, parent_invocation_id: trace.parent_invocation_id ?? live?.parent_invocation_id,
          consumption: { input_tokens: count(usage.input_tokens) ?? count(priorUsage.input_tokens),
            output_tokens: count(usage.output_tokens) ?? count(priorUsage.output_tokens) } })
      }
      const traces = [...receipts.values()]
      const byInvocation = new Map(traces.filter((trace) => typeof trace.invocation_id === "string")
        .map((trace) => [String(trace.invocation_id), trace]))
      for (const trace of traces) {
        const agentType = text(trace.agent_id)
        const invocation = text(trace.invocation_id)
        if (!agentType || !invocation) continue
        let root = trace
        const visited = new Set([invocation])
        while (typeof root.parent_invocation_id === "string") {
          const parent = byInvocation.get(root.parent_invocation_id)
          if (!parent || visited.has(String(parent.invocation_id))) break
          visited.add(String(parent.invocation_id))
          root = parent
        }
        const consumption = object(trace.consumption)
        add(bucket(text(root.agent_id) ?? agentType), {
          role: byAgent.get(agentType)?.role, name: byAgent.get(agentType)?.name,
          id: invocation, agentType, state: auditStateFrom(text(trace.status) ?? "", null),
          runId: text(trace.run_id) ?? text(result.run_id),
          phase: trace.status === "running" ? text(trace.phase) : null,
          configuration: agentType === execution.agentType ? execution.configuration : null,
          parentId: text(trace.parent_invocation_id),
          inputTokens: count(consumption.input_tokens), outputTokens: count(consumption.output_tokens),
          startedAt: text(trace.started_at), finishedAt: text(trace.finished_at), error: text(trace.error),
        })
      }
      if (!traces.some((trace) => trace.agent_id === execution.agentType && typeof trace.invocation_id === "string")) {
        // One backend row orchestrates a joint audit; its totals are not copied
        // into both attributes. No per-attribute execution state is inferred.
        const pipeline = bucket(execution.agentType)
        add(pipeline, { id: execution.id, agentType: execution.agentType,
          role: metadata?.role, name: metadata?.name,
          configuration: execution.configuration, estimatedTokens: execution.estimatedTokens,
          interruptionReason: execution.interruptionReason,
          state: auditStateFrom(execution.status, quality ? text(result.status) : null),
          inputTokens: execution.inputTokens, outputTokens: execution.outputTokens,
          startedAt: execution.startedAt, finishedAt: execution.finishedAt, error: execution.error })
      }
    }
    const executionState = combined(group.map((item) => auditStateFrom(item.status, null)))
    const visible = latestAgents(pipelines)
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
      pipelines: [...visible].map(([id, agents]) => ({ id,
        state: reportedStates.get(id) ?? combined(agents.map((agent) => agent.state)), agents })),
    }
  }).sort((a, b) => b.createdAt.localeCompare(a.createdAt) || b.id - a.id)
}
