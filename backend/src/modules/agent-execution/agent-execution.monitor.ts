import type { StoredAgentExecution } from "./agent-execution.repository.js"

const object = (value: unknown): Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value)
  ? value as Record<string, unknown> : {}
const rows = (value: unknown): Record<string, unknown>[] => Array.isArray(value) ? value.map(object) : []

/** A monitor needs states and receipts, never snapshots, evidence text or DOCX. */
export function monitorExecution(execution: StoredAgentExecution): StoredAgentExecution {
  if (execution.monitorContext?.evaluationType !== "QualityAudit" || !execution.result) return execution
  let raw: Record<string, unknown>
  try { raw = object(JSON.parse(execution.result)) }
  catch { return { ...execution, result: null } }
  const report = object(raw.report)
  const result: Record<string, unknown> = { attributes: raw.attributes, status: raw.status, run_id: raw.run_id }
  if (Object.keys(report).length) {
    result.report = {
      quality_results: { attributes: rows(object(report.quality_results).attributes).map((attribute) => ({ id: attribute.id, status: attribute.status })) },
      annexes_and_traceability: { executions: rows(object(report.annexes_and_traceability).executions).map((trace) => ({
        agent_id: trace.agent_id, invocation_id: trace.invocation_id, status: trace.status,
        consumption: { input_tokens: object(trace.consumption).input_tokens, output_tokens: object(trace.consumption).output_tokens },
      })) },
    }
  }
  return { ...execution, result: JSON.stringify(result) }
}
