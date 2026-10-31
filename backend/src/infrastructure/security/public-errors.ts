/** Public errors are reconstructed, never certified by scanning arbitrary text. */
export const publicErrorMessages = {
  execution_cancelled: "La ejecución fue cancelada.",
  execution_failed: "The execution failed. Additional internal details are not public.",
  execution_timeout: "The execution exceeded its allowed time.",
  child_execution_error: "An agent could not complete its execution.",
  result_contract_invalid: "The received response did not satisfy the expected contract.",
  backend_dispatch_failed: "The backend could not dispatch or finalize the execution.",
  audit_outcome_unconfirmed: "Communication was interrupted; the audit outcome is unconfirmed, not a confirmed agent failure.",
} as const

export const hiddenErrorMessage = "Error details withheld because their safety could not be verified."
const safeMessages = new Set<string>([hiddenErrorMessage, ...Object.values(publicErrorMessages)])
const safeExceptions = new Set(["Error", "CancelledError", "ValueError", "RuntimeError", "TimeoutError", "ValidationError", "TypeError",
  "AgentTransportError", "AgentInvocationError", "AuditRunUnavailableError", "InvalidConfigError"])

export function publicErrorCode(value: unknown): keyof typeof publicErrorMessages {
  return typeof value === "string" && Object.hasOwn(publicErrorMessages, value) ? value as keyof typeof publicErrorMessages : "execution_failed"
}

export function publicExceptionType(value: unknown): string | null {
  return typeof value === "string" && safeExceptions.has(value) ? value : null
}

export function publicErrorText(value: string | null | undefined): string | null {
  if (["CancelledError", "asyncio.CancelledError", "concurrent.futures.CancelledError"].includes(value?.trim() ?? "")) {
    return publicErrorMessages.execution_cancelled
  }
  if (!value?.trim()) return null
  return safeMessages.has(value) ? value : hiddenErrorMessage
}

/** Secondary pattern protection for operational identifiers, not for certifying messages. */
export function publicIdentifier(value: string | null): string | null {
  if (value === null) return null
  return /^[a-zA-Z0-9_.:-]{1,128}$/.test(value) && !/^(?:sk-|AIza|gh[pousr]_|github_pat_|AKIA|eyJ)/.test(value) ? value : null
}

export function publicErrorResult(result: string | null): string | null {
  if (result === null) return null
  let parsed: unknown
  try { parsed = JSON.parse(result) }
  catch { return result } // Opaque non-JSON output is not an error message contract.
  try { return JSON.stringify(publicErrorFields(parsed)) }
  catch { return null } // Never fall back to unsanitized JSON if projection fails.
}

/** Preserve evidence/artifacts; remove untrusted text only in error-bearing fields. */
export function publicErrorFields(value: unknown): unknown {
  if (value instanceof Date) return value
  if (Array.isArray(value)) return value.map(publicErrorFields)
  if (!value || typeof value !== "object") return value
  const result: Record<string, unknown> = {}
  for (const [key, item] of Object.entries(value)) {
    if (key === "error" && typeof item === "string") result[key] = publicErrorText(item)
    else if (key === "error" && item && typeof item === "object") result[key] = { message: hiddenErrorMessage }
    else if (key === "result" && typeof item === "string") result[key] = publicErrorResult(item)
    else if (key === "execution_issues" && Array.isArray(item)) result[key] = item.map((issue) => {
      const diagnostic = issue && typeof issue === "object" ? issue as Record<string, unknown> : {}
      const code = publicErrorCode(diagnostic.termination_reason)
      const identity = Object.fromEntries(["id", "agent_id", "invocation_id", "stage", "category", "status"].flatMap((name) =>
        typeof diagnostic[name] === "string" ? [[name, publicIdentifier(diagnostic[name]) ?? "unknown"]] : []))
      return { ...identity, termination_reason: code, explanation: publicErrorMessages[code],
        source_record_ids: Array.isArray(diagnostic.source_record_ids) ? diagnostic.source_record_ids
          .filter((id): id is string => typeof id === "string").map(publicIdentifier).filter((id) => id !== null) : [],
        ...(typeof diagnostic.message === "string" ? { message: publicErrorMessages[code] } : {}), diagnostics: [], incidents: [] }
    })
    else if ((key === "errorDetail" || key === "error_detail") && item && typeof item === "object") {
      const detail = item as Record<string, unknown>
      const code = publicErrorCode(detail.code)
      result[key] = { agentId: publicIdentifier(typeof (detail.agentId ?? detail.agent_id) === "string" ? String(detail.agentId ?? detail.agent_id) : null),
        invocationId: publicIdentifier(typeof (detail.invocationId ?? detail.invocation_id) === "string" ? String(detail.invocationId ?? detail.invocation_id) : null),
        occurredAt: (() => { const date = detail.occurredAt ?? detail.occurred_at
          return date instanceof Date ? date : typeof date === "string" && Number.isFinite(Date.parse(date)) ? new Date(date).toISOString() : null })(), code,
        exceptionType: publicExceptionType(detail.exceptionType ?? detail.exception_type), message: publicErrorMessages[code] }
    } else if (key === "failure" && item && typeof item === "object") {
      const failure = item as Record<string, unknown>
      const code = publicErrorCode(failure.code)
      result[key] = { code, summary: publicErrorMessages[code], diagnostics: [],
        stage: ["execute", "invoke_child", "validate_result", "publish_result", "reserve_invocation"].includes(String(failure.stage)) ? failure.stage : "execute",
        resources: Array.isArray(failure.resources) ? failure.resources.map((resource) => {
          const r = resource && typeof resource === "object" ? resource as Record<string, unknown> : {}
          return { resource: ["tokens", "calls", "tools", "time", "seconds"].includes(String(r.resource)) ? r.resource : "resource",
            available: typeof r.available === "number" ? r.available : null, required: typeof r.required === "number" ? r.required : null }
        }) : [], exception_type: publicExceptionType(failure.exception_type) }
    } else result[key] = publicErrorFields(item)
  }
  return result
}
