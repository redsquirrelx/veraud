import { publicErrorCode, publicErrorMessages, publicExceptionType, publicIdentifier } from "./publicErrors.ts"

/** Incident metadata supplied by the server; lifecycle dates are not substitutes. */
export interface ExecutionErrorDetail {
  agentId: string | null
  invocationId: string | null
  occurredAt: string | null
  code: string
  exceptionType: string | null
  message: string
}

/** Raw retained snapshots may use Python names; the public API uses camelCase. */
export function readExecutionErrorDetail(value: unknown): ExecutionErrorDetail | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null
  const item = value as Record<string, unknown>
  if (typeof item.code !== "string" || !item.code.trim() || typeof item.message !== "string" || !item.message.trim()) return null
  const text = (value: unknown) => typeof value === "string" && value.trim() ? value : null
  const date = text(item.occurredAt ?? item.occurred_at)
  const code = publicErrorCode(item.code)
  return { agentId: publicIdentifier(text(item.agentId ?? item.agent_id)), invocationId: publicIdentifier(text(item.invocationId ?? item.invocation_id)),
    occurredAt: date && Number.isFinite(Date.parse(date)) ? date : null,
    code, exceptionType: publicExceptionType(text(item.exceptionType ?? item.exception_type)), message: publicErrorMessages[code] }
}
