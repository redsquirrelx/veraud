/** Incident provenance is supplied by its source, never inferred from error text. */
export interface ExecutionErrorDetail {
  agentId: string | null
  invocationId: string | null
  occurredAt: string | null
  code: string
  exceptionType: string | null
  message: string
}

export const executionErrorDetailSchema = {
  anyOf: [{ type: "null" }, {
    type: "object", additionalProperties: false,
    required: ["agentId", "invocationId", "occurredAt", "code", "exceptionType", "message"],
    properties: {
      agentId: { type: ["string", "null"], maxLength: 128 },
      invocationId: { type: ["string", "null"], maxLength: 128 },
      occurredAt: { type: ["string", "null"], format: "date-time" },
      code: { type: "string", minLength: 1, maxLength: 128 },
      exceptionType: { type: ["string", "null"], maxLength: 128 },
      message: { type: "string", minLength: 1, maxLength: 2000 },
    },
  }],
} as const

/** Explicit allowlist also protects projections of opaque audit envelopes. */
export function readExecutionErrorDetail(value: unknown): ExecutionErrorDetail | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null
  const item = value as Record<string, unknown>
  const agentId = item.agentId ?? item.agent_id ?? null
  const invocationId = item.invocationId ?? item.invocation_id ?? null
  const occurredAt = item.occurredAt ?? item.occurred_at ?? null
  const exceptionType = item.exceptionType ?? item.exception_type ?? null
  const nullableText = (text: unknown) => text === null || typeof text === "string" && text.length <= 128
  if (!nullableText(agentId) || !nullableText(invocationId) || !nullableText(exceptionType)
    || !(occurredAt === null || typeof occurredAt === "string" && /^\d{4}-\d\d-\d\dT.*(?:Z|[+-]\d\d:\d\d)$/i.test(occurredAt) && Number.isFinite(Date.parse(occurredAt)))
    || typeof item.code !== "string" || !item.code.trim() || item.code.length > 128
    || typeof item.message !== "string" || !item.message.trim() || item.message.length > 2000) return null
  return { agentId: agentId as string | null, invocationId: invocationId as string | null,
    occurredAt: occurredAt as string | null, code: item.code, exceptionType: exceptionType as string | null, message: item.message }
}

export function storedExecutionErrorDetail(value: string | null | undefined): ExecutionErrorDetail | null {
  try { return readExecutionErrorDetail(JSON.parse(value ?? "null")) }
  catch { return null }
}

export function executionErrorEvent(detail: ExecutionErrorDetail | null | undefined) {
  return detail ? { ...detail, occurredAt: detail.occurredAt === null ? null : new Date(detail.occurredAt) } : null
}
