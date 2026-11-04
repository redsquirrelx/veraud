import type { StoredAgentExecution } from "./agent-execution.repository.js"

const object = (value: unknown): Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value)
  ? value as Record<string, unknown> : {}
const rows = (value: unknown): Record<string, unknown>[] => Array.isArray(value) ? value.map(object) : []

/** Retained reports contain actual assignments, including repeated invocations.
 * Catalog parent types cannot identify which invocation launched a child. */
function invocationParents(raw: Record<string, unknown>): Map<string, string> {
  const parents = new Map<string, string>()
  const visit = (report: Record<string, unknown>, parent: string) => {
    for (const child of [...rows(report.invocations), ...rows(report.assessments)]) {
      const assignment = object(child.assignment)
      const id = assignment.invocation_id
      if (typeof id !== "string" || id === parent) continue
      parents.set(id, parent)
      visit(object(child.result), id)
    }
  }
  const board = object(raw.blackboard)
  for (const record of rows(board.assessments)) {
    if (typeof record.invocation_id === "string") visit(object(object(record.details).report), record.invocation_id)
  }
  for (const record of [...rows(board.evidence), ...rows(board.findings)]) {
    if (typeof record.invocation_id === "string") visit(object(object(record.details).investigation), record.invocation_id)
  }
  return parents
}

/** A monitor needs states and receipts, never snapshots, evidence text or DOCX. */
export function monitorExecution(execution: StoredAgentExecution): StoredAgentExecution {
  if (execution.monitorContext?.evaluationType !== "QualityAudit" || !execution.result) return execution
  let raw: Record<string, unknown>
  try { raw = object(JSON.parse(execution.result)) }
  catch { return { ...execution, result: null } }
  const report = object(raw.report)
  const parents = invocationParents(raw)
  const result: Record<string, unknown> = { attributes: raw.attributes, status: raw.status, run_id: raw.run_id }
  if (Object.keys(report).length) {
    result.report = {
      quality_results: { attributes: rows(object(report.quality_results).attributes).map((attribute) => ({ id: attribute.id, status: attribute.status })) },
      annexes_and_traceability: { executions: rows(object(report.annexes_and_traceability).executions).map((trace) => ({
        agent_id: trace.agent_id, invocation_id: trace.invocation_id, status: trace.status,
        parent_invocation_id: typeof trace.parent_invocation_id === "string" ? trace.parent_invocation_id
          : parents.get(String(trace.invocation_id)) ?? null,
        consumption: { input_tokens: object(trace.consumption).input_tokens, output_tokens: object(trace.consumption).output_tokens },
      })) },
    }
  }
  return { ...execution, result: JSON.stringify(result) }
}
