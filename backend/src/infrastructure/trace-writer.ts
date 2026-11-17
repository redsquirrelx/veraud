import { appendFileSync, mkdirSync } from "node:fs"
import { randomBytes } from "node:crypto"
import { join, resolve } from "node:path"

let traceRoot: string | null = null
export interface TraceEnvelope {
  traceId: string
  executionId: number
  agentType: string
  projectId?: number
  branch?: string | null
  commitHash?: string
  runId?: string
  spanId: string
}

export interface TraceEvent {
  spanId?: string | undefined
  parentSpanId?: string | undefined
  event: string
  status?: "ok" | "error" | "running"
  message?: string | undefined
  errorCode?: string | undefined
  durationMs?: number | undefined
  details?: Record<string, unknown>
}
const SAFE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/

export function configureTraceRoot(root: string): void {
  traceRoot = resolve(root)
}
function now(): string { return new Date().toISOString().replace(/(\.\d{3})Z$/, "$1Z") }
function stamp(): string { return now().replace(/[-:.]/g, "").replace("T", "-").replace("Z", "Z") }
function compact(timestamp: string) { return timestamp.replace(/\D/g, "").slice(0, 17) }
function sanitize(value: string) { return value.replace(/[^A-Za-z0-9._-]/g, "-").slice(0, 128) }
function redact(value: unknown): unknown {
  if (Array.isArray(value)) return value.slice(0, 100).map(redact)
  if (!value || typeof value !== "object") return typeof value === "string" && value.length > 16_384 ? `${value.slice(0, 16_384)}<truncated>` : value
  const blocked = /(?:api[-_]?key|credential|password|secret|authorization|token)/i
  return Object.fromEntries(Object.entries(value as Record<string, unknown>).slice(0, 100).map(([key, item]) => [key, blocked.test(key) ? "[redacted]" : redact(item)]))
}
function eventText(event: TraceEvent) {
  return `${event.status?.toUpperCase() ?? "EVENT"} ${event.event}${event.message ? ` — ${event.message}` : ""}`
}
/** Trace failure is intentionally caught: telemetry must never fail the audit. */
export function writeTraceEvent(envelope: TraceEnvelope, event: TraceEvent): void {
  try {
    if (process.env.VERAUD_TRACE_ENABLED === "0") return
    if (!SAFE.test(envelope.traceId) || envelope.traceId !== sanitize(envelope.traceId)) return
    const root = traceRoot ?? resolve("logs")
    const directory = resolve(root, `${envelope.traceId}-${sanitize(envelope.agentType)}-exec-${envelope.executionId}`)
    if (!directory.startsWith(resolve(root))) return
    mkdirSync(directory, { recursive: true })
    const payload = {
      version: 1, at: now(), traceId: envelope.traceId, executionId: envelope.executionId,
      agentType: envelope.agentType, service: "backend",
      projectId: envelope.projectId ?? null, branch: envelope.branch ?? null, commitHash: envelope.commitHash ?? null,
      spanId: event.spanId ?? envelope.traceId, parentSpanId: event.parentSpanId ?? null,
      event: event.event, status: event.status ?? "running", message: event.message ?? null,
      errorCode: event.errorCode ?? null, durationMs: event.durationMs ?? null, details: redact(event.details ?? {}),
    };
    appendFileSync(join(directory, "trace.ndjson"), `${JSON.stringify(payload)}\n`, "utf8");
    appendFileSync(join(directory, "backend.log"), `${now()} ${eventText(event)}\n`, "utf8");
  } catch { /* trace is best-effort */ }
}
export function createTraceEnvelope(execution: { id: number, agentType: string }, options?: { projectId?: number, branch?: string | null, commitHash?: string, runId?: string }): TraceEnvelope {
  const traceId = `${compact(now())}-${randomBytes(6).toString("hex")}`
  return { traceId, executionId: execution.id, agentType: execution.agentType, spanId: traceId, ...options }
}
export function childSpanId(parent: string | undefined, name: string): string {
  return `${sanitize(parent || "root")}-${sanitize(name)}-${randomBytes(3).toString("hex")}`.slice(0, 128)
}
export function traceFailureDetails(error: unknown): Record<string, unknown> {
  if (!(error instanceof Error)) return { errorType: typeof error }
  const anyError = error as Error & { code?: unknown, status?: unknown };
  return { errorType: error.name, errorCode: typeof anyError.code === "string" ? anyError.code : undefined, status: typeof anyError.status === "number" ? anyError.status : undefined, message: error.message };
}
