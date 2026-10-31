/** Independent display barrier: no credential values are sent to the browser. */
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
const allowedMessages = new Set<string>([...Object.values(publicErrorMessages), hiddenErrorMessage])
const exceptions = new Set(["Error", "CancelledError", "ValueError", "RuntimeError", "TimeoutError", "ValidationError", "TypeError",
  "AgentTransportError", "AgentInvocationError", "AuditRunUnavailableError", "InvalidConfigError"])

export function publicErrorCode(value: string): keyof typeof publicErrorMessages {
  return Object.hasOwn(publicErrorMessages, value) ? value as keyof typeof publicErrorMessages : "execution_failed"
}
export function publicExceptionType(value: string | null): string | null {
  return value && exceptions.has(value) ? value : null
}
export function publicErrorText(value: string | null | undefined): string | null {
  if (["CancelledError", "asyncio.CancelledError", "concurrent.futures.CancelledError"].includes(value?.trim() ?? "")) {
    return publicErrorMessages.execution_cancelled
  }
  return value?.trim() ? allowedMessages.has(value) ? value : hiddenErrorMessage : null
}
export function publicIdentifier(value: string | null): string | null {
  return value && /^[a-zA-Z0-9_.:-]{1,128}$/.test(value) && !/^(?:sk-|AIza|gh[pousr]_|github_pat_|AKIA|eyJ)/.test(value) ? value : null
}
