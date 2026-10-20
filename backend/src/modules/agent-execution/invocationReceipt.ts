export const invocationReceiptSchema = {
  type: "object", additionalProperties: false,
  required: ["invocation_id", "parent_invocation_id", "agent_id", "run_id", "status", "started_at", "finished_at", "input_tokens", "output_tokens", "error"],
  properties: {
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
  },
} as const

export interface InvocationReceipt {
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
    finished_at: receipt.finished_at === null ? null : new Date(receipt.finished_at) }))
}
