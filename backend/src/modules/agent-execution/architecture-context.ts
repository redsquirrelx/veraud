export class InvalidArchitectureContextError extends Error {}

/** Storage-boundary checks. The canonical, full contract lives in agent-server. */
export function architectureContextResult(raw: string | null, commitHash: string | null): {
  schemaVersion: string; executionStatus: string; result: string
} {
  let value: Record<string, unknown>
  try {
    const parsed: unknown = JSON.parse(raw ?? "null")
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error()
    value = parsed as Record<string, unknown>
  } catch {
    throw new InvalidArchitectureContextError("Invalid architecture context output")
  }
  const index = value.document_index as Record<string, unknown> | null
  if (value.schema_version !== "1" || !["complete", "partial", "failed"].includes(String(value.execution_status))
    || !Array.isArray(value.knowledge) || !Array.isArray(value.knowledge_issues)
    || !Array.isArray(value.validation_errors) || !Array.isArray(value.pending_categories)
    || !Array.isArray(value.covered_categories) || typeof value.finalization_reason !== "string"
    || !index || index.commit !== commitHash) {
    throw new InvalidArchitectureContextError("Architecture context output does not match its project version")
  }
  return { schemaVersion: "1", executionStatus: String(value.execution_status), result: raw! }
}
