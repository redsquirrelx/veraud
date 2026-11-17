/** Derive the user-facing reasons for a partial/failed audit from the published
 * report annexes. The live monitor only carries invocation receipts, which do
 * not record why a stage was deferred; the report is the only artifact that
 * keeps it. Never throws: a missing or malformed section yields no issues. */
export interface AuditIssue {
  agentId: string
  invocationId: string | null
  status: string | null
  terminationReason: string | null
  explanation: string | null
  incidents: string[]
  diagnostics: string[]
}

type RecordValue = Record<string, unknown>
const object = (value: unknown): RecordValue => value !== null && typeof value === "object" && !Array.isArray(value)
  ? value as RecordValue : {}
const rows = (value: unknown): RecordValue[] => Array.isArray(value) ? value.map(object) : []
const text = (value: unknown): string | null => typeof value === "string" ? value : null
const strings = (value: unknown): string[] => Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : []

/** Keep only issues that carry actionable detail; silent branch outcomes
 * (completed stages with no incidents) are not reasons for a partial audit. */
export function auditIssuesFromReport(section: unknown): AuditIssue[] {
  const annexes = object(section)
  return rows(annexes.execution_issues).flatMap((issue) => {
    const incidents = strings(issue.incidents)
    const diagnostics = strings(issue.diagnostics)
    if (incidents.length === 0 && diagnostics.length === 0) return []
    return [{
      agentId: text(issue.agent_id) ?? "unknown",
      invocationId: text(issue.invocation_id),
      status: text(issue.status),
      terminationReason: text(issue.termination_reason),
      explanation: text(issue.explanation),
      incidents,
      diagnostics,
    }]
  })
}
