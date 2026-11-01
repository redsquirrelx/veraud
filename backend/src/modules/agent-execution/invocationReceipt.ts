import { executionErrorDetailSchema, executionErrorEvent, type ExecutionErrorDetail } from "./execution-error-detail.js"

export const invocationReceiptSchema = {
  type: "object", additionalProperties: false,
  required: ["invocation_id", "parent_invocation_id", "agent_id", "run_id", "status", "started_at", "finished_at", "input_tokens", "output_tokens", "error"],
  properties: {
    phase: { type: ["string", "null"], minLength: 1, maxLength: 128 },
    phase_sequence: { type: "integer", minimum: 0, maximum: 2147483647 },
    invocation_id: { type: "string", minLength: 1, maxLength: 128 },
    parent_invocation_id: { type: ["string", "null"], minLength: 1, maxLength: 128 },
    agent_id: { type: "string", minLength: 1, maxLength: 128 },
    run_id: { type: "string", minLength: 1, maxLength: 128 },
    status: { type: "string", enum: ["running", "completed", "partial", "failed", "cancelled", "timeout"] },
    started_at: { type: "string", format: "date-time" },
    finished_at: { type: ["string", "null"], format: "date-time" },
    input_tokens: { type: ["integer", "null"], minimum: 0, maximum: 2147483647 },
    output_tokens: { type: ["integer", "null"], minimum: 0, maximum: 2147483647 },
    error: { type: ["string", "null"], maxLength: 2000 },
    error_detail: executionErrorDetailSchema,
  },
} as const

export interface InvocationReceipt {
  error_detail?: ExecutionErrorDetail | null
  phase?: string | null
  phase_sequence?: number
  invocation_id: string
  parent_invocation_id: string | null
  agent_id: string
  run_id: string
  status: "running" | "completed" | "partial" | "failed" | "cancelled" | "timeout"
  started_at: string
  finished_at: string | null
  input_tokens: number | null
  output_tokens: number | null
  error: string | null
}

export function invocationEvents(receipts: InvocationReceipt[] = []) {
  return receipts.map((receipt) => ({ ...receipt, started_at: new Date(receipt.started_at),
    error_detail: executionErrorEvent(receipt.error_detail),
    finished_at: receipt.finished_at === null ? null : new Date(receipt.finished_at) }))
}
