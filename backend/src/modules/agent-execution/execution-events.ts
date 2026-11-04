import type { FastifyInstance } from "fastify"
import { Prisma, type PrismaClient } from "../../generated/prisma/client.js"
import { publicIdentifier } from "../../infrastructure/security/public-errors.js"
import { errorResponses } from "../../infrastructure/openapi/routeSchemas.js"

export const eventKinds = ["execution.started", "execution.finished", "invocation.started", "invocation.finished", "phase.changed",
  "node.started", "node.finished", "tool.started", "tool.finished", "model.started", "model.finished",
  "provider.request", "provider.retry", "provider.wait", "provider.error", "provider.retry_skipped",
  "activity.started", "activity.finished", "wait.started", "wait.finished", "publication.created", "audit.state_changed"] as const
const statuses = ["running", "completed", "partial", "failed", "cancelling", "cancelled", "timeout", "rejected", "waiting"] as const
const metrics = ["seconds", "wait_seconds", "attempt", "attempts", "retry", "delay_seconds", "http_status", "input_tokens", "output_tokens", "estimated_tokens", "cache_hit", "phase_sequence"] as const
type Metadata = Partial<Record<typeof metrics[number], number | boolean>>
export interface ExecutionEventInput {
  eventId: string; streamId: string; sequence: number; occurredAt: string
  runId: string | null; invocationId: string | null; parentInvocationId: string | null; agentId: string | null
  actionId: string; parentActionId: string | null; kind: typeof eventKinds[number]
  sourceId?: string | null
  name: string | null; status: typeof statuses[number] | null; metadata: Metadata
}
const identifier = { type: ["string", "null"], minLength: 1, maxLength: 128 } as const
export const executionEventSchema = {
  type: "object", additionalProperties: false,
  required: ["eventId", "streamId", "sequence", "occurredAt", "runId", "invocationId", "parentInvocationId", "agentId", "actionId", "parentActionId", "kind", "name", "status", "metadata"],
  properties: {
    eventId: { type: "string", format: "uuid" }, streamId: { type: "string", format: "uuid" },
    sequence: { type: "integer", minimum: 1, maximum: 2147483647 }, occurredAt: { type: "string", format: "date-time" },
    runId: identifier, invocationId: identifier, parentInvocationId: identifier, agentId: identifier,
    actionId: { type: "string", minLength: 1, maxLength: 128 }, parentActionId: identifier, sourceId: identifier, name: identifier,
    kind: { type: "string", enum: eventKinds }, status: { type: ["string", "null"], enum: [...statuses, null] },
    metadata: { type: "object", additionalProperties: false, properties: Object.fromEntries(metrics.map((key) =>
      [key, key === "cache_hit" ? { type: "boolean" } : { type: "number", minimum: 0, maximum: Number.MAX_SAFE_INTEGER }])) },
  },
} as const

export class ExecutionEventConflict extends Error {}
export class ExecutionEventExecutionNotFound extends Error {}

/** Append-only events, deliberately separate from mutable lifecycle receipts. */
export class ExecutionEventRepository {
  constructor(private db: PrismaClient) {}

  async append(executionId: number, events: ExecutionEventInput[]) {
    return this.db.$transaction(async (tx) => {
      const execution = await tx.agentExecution.findUnique({ where: { id: executionId } })
      if (!execution) throw new ExecutionEventExecutionNotFound()
      let knownRun: string | undefined
      try { knownRun = (JSON.parse(execution.result ?? "{}") as { run_id?: string }).run_id } catch { /* Opaque historical output. */ }
      const receipts = JSON.parse(execution.invocationReceipts) as { run_id: string }[]
      knownRun ??= receipts[0]?.run_id
      knownRun ??= (await tx.executionEventStream.findFirst({ where: { executionId, runId: { not: null } } }))?.runId ?? undefined
      for (const event of events) {
        const safeRun = publicIdentifier(event.runId)
        if (knownRun && safeRun && knownRun !== safeRun) throw new ExecutionEventConflict("Event does not belong to the execution's audit")
        knownRun ??= safeRun ?? undefined
        const stream = await tx.executionEventStream.upsert({ where: { id: event.streamId },
          create: { id: event.streamId, executionId, runId: safeRun }, update: {} })
        if (stream.executionId !== executionId || stream.runId && safeRun && stream.runId !== safeRun) {
          throw new ExecutionEventConflict("Event stream identity cannot change")
        }
        if (!stream.runId && safeRun) await tx.executionEventStream.update({ where: { id: stream.id }, data: { runId: safeRun } })
        const data = { ...event, occurredAt: new Date(event.occurredAt),
          runId: publicIdentifier(event.runId), invocationId: publicIdentifier(event.invocationId),
          parentInvocationId: publicIdentifier(event.parentInvocationId), agentId: publicIdentifier(event.agentId),
          name: publicIdentifier(event.name), parentActionId: publicIdentifier(event.parentActionId), sourceId: publicIdentifier(event.sourceId ?? null),
          actionId: publicIdentifier(event.actionId) ?? "unknown", metadata: JSON.stringify(Object.fromEntries(metrics
            .filter((key) => key === "cache_hit" ? typeof event.metadata[key] === "boolean"
              : typeof event.metadata[key] === "number" && Number.isFinite(event.metadata[key]) && Number(event.metadata[key]) >= 0 && Number(event.metadata[key]) <= Number.MAX_SAFE_INTEGER)
            .map((key) => [key, event.metadata[key]]))) }
        const previous = await tx.executionEvent.findFirst({ where: { OR: [{ eventId: event.eventId }, { streamId: event.streamId, sequence: event.sequence }] } })
        if (previous) {
          if (Object.entries(data).some(([key, value]) => {
            const old = previous[key as keyof typeof previous]
            return value instanceof Date ? !(old instanceof Date) || old.getTime() !== value.getTime() : old !== value
          })) throw new ExecutionEventConflict("An event cannot be overwritten")
        } else await tx.executionEvent.create({ data })
      }
      return { acknowledged: true }
    })
  }

  async list(executionId: number, offset: number, limit: number) {
    if (!await this.db.agentExecution.findUnique({ where: { id: executionId }, select: { id: true } })) throw new ExecutionEventExecutionNotFound()
    const where = { stream: { executionId } }
    const [total, events] = await this.db.$transaction([
      this.db.executionEvent.count({ where }),
      this.db.executionEvent.findMany({ where, orderBy: [{ occurredAt: "asc" }, { streamId: "asc" }, { sequence: "asc" }], skip: offset, take: limit }),
    ])
    return { total, offset, limit, events: events.map((row) => ({
      eventId: row.eventId, streamId: row.streamId, sequence: row.sequence, runId: row.runId,
      invocationId: row.invocationId, parentInvocationId: row.parentInvocationId, agentId: row.agentId,
      actionId: row.actionId, parentActionId: row.parentActionId, sourceId: row.sourceId, kind: row.kind, name: row.name, status: row.status,
      occurredAt: row.occurredAt.toISOString(), receivedAt: row.receivedAt.toISOString(), metadata: JSON.parse(row.metadata) as Metadata,
    })) }
  }
}

export function registerExecutionEventRoutes(app: FastifyInstance, repository: ExecutionEventRepository) {
  const params = { type: "object", required: ["id"], properties: { id: { type: "string", pattern: "^[1-9][0-9]*$" } } } as const
  const errors = errorResponses([400, 404, 422], "ExecutionError", false)
  function failure(error: unknown, reply: import("fastify").FastifyReply) {
    if (error instanceof ExecutionEventExecutionNotFound) return reply.code(404).send({ error: "Agent execution not found" })
    if (error instanceof ExecutionEventConflict || error instanceof Prisma.PrismaClientKnownRequestError && error.code === "P2002") {
      return reply.code(422).send({ error: "Conflicting execution event identity" })
    }
    throw error
  }
  app.post<{ Params: { id: string }, Body: { events: ExecutionEventInput[] } }>("/api/agent-executions/:id/events", { schema: {
    params, tags: ["Agent Executions"], summary: "Append immutable execution events (idempotent batch)",
    body: { type: "object", additionalProperties: false, required: ["events"], properties: { events: { type: "array", minItems: 1, maxItems: 100, items: executionEventSchema } } },
    response: { 200: { type: "object", required: ["acknowledged"], properties: { acknowledged: { type: "boolean" } } }, ...errors },
  } }, async (request, reply) => {
    try { return await repository.append(Number(request.params.id), request.body.events) }
    catch (error) { return failure(error, reply) }
  })
  app.get<{ Params: { id: string }, Querystring: { offset?: number, limit?: number } }>("/api/agent-executions/:id/events", { schema: {
    params, tags: ["Agent Executions"], summary: "Read execution chronology, ordered by occurrence time",
    querystring: { type: "object", additionalProperties: false, properties: { offset: { type: "integer", minimum: 0, default: 0 }, limit: { type: "integer", minimum: 1, maximum: 200, default: 100 } } },
    response: { 200: { type: "object", required: ["total", "offset", "limit", "events"], properties: {
      total: { type: "integer" }, offset: { type: "integer" }, limit: { type: "integer" }, events: { type: "array", items: { ...executionEventSchema,
        properties: { ...executionEventSchema.properties, receivedAt: { type: "string", format: "date-time" } } } },
    } }, ...errors },
  } }, async (request, reply) => {
    try { return await repository.list(Number(request.params.id), request.query.offset ?? 0, request.query.limit ?? 100) }
    catch (error) { return failure(error, reply) }
  })
}
