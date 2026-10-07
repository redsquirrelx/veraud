import type { FastifyInstance } from "fastify"
import type {
  AgentExecutionEvent,
  RealtimeGateway,
} from "../../infrastructure/realtime-gateway/realtime.gateway.js"
import { logger } from "../../config/logger.js"
import type { StoredAgentExecution } from "./agent-execution.repository.js"
import {
  AgentExecutionNotFoundError,
  AgentExecutionService,
  InvalidCompletionError,
} from "./agent-execution.service.js"

const idParams = {
  type: "object",
  required: ["id"],
  properties: {
    id: { type: "string", pattern: "^[0-9]+$" },
  },
} as const

const openBody = {
  type: "object",
  required: ["agentType", "evaluationId"],
  properties: {
    agentType: { type: "string", minLength: 1 },
    evaluationId: { type: "integer", minimum: 1 },
  },
} as const

const closeBody = {
  type: "object",
  required: ["status"],
  properties: {
    status: { type: "string", enum: ["Completed", "Failed"] },
    result: { type: ["string", "null"] },
    error: { type: ["string", "null"] },
    inputTokens: { type: ["integer", "null"], minimum: 0 },
    outputTokens: { type: ["integer", "null"], minimum: 0 },
  },
} as const

export function registerAgentExecutionRoutes(
  app: FastifyInstance,
  service: AgentExecutionService,
  gateway: RealtimeGateway,
): void {
  /**
   * Registers an agent invocation and returns its id.
   *
   * The backend calls this when it invokes an agent, then passes the id to the
   * agent-server. The agent never creates rows: it only reports progress by
   * calling the endpoints below.
   */
  app.post("/api/agent-executions", { schema: { body: openBody } }, async (request, reply) => {
    const body = request.body as { agentType: string; evaluationId: number }

    const execution = await service.open(body.agentType, body.evaluationId)

    logger
      .withTag("agent-execution")
      .info(`Registered agent execution ${execution.id} agentType=${execution.agentType}`)

    broadcast(gateway, "agent-execution.opened", execution)

    return reply.code(201).send(toResponse(execution))
  })

  app.get("/api/agent-executions/:id", { schema: { params: idParams } }, async (request, reply) => {
    const { id } = request.params as { id: string }

    try {
      return toResponse(await service.findById(Number(id)))
    } catch (error) {
      return notFoundOrRethrow(error, reply)
    }
  })

  /** Called by the agent-server once the run actually starts. Optional. */
  app.post("/api/agent-executions/:id/running", { schema: { params: idParams } }, async (request, reply) => {
    const { id } = request.params as { id: string }

    try {
      const execution = await service.markRunning(Number(id))

      broadcast(gateway, "agent-execution.updated", execution)

      return toResponse(execution)
    } catch (error) {
      return notFoundOrRethrow(error, reply)
    }
  })

  /** Called by the agent-server when the run finishes, successfully or not. */
  app.post(
    "/api/agent-executions/:id/completion",
    { schema: { params: idParams, body: closeBody } },
    async (request, reply) => {
      const { id } = request.params as { id: string }
      const body = request.body as {
        status: "Completed" | "Failed"
        result?: string | null
        error?: string | null
        inputTokens?: number | null
        outputTokens?: number | null
      }

      try {
        const execution = await service.complete(Number(id), {
          status: body.status,
          result: body.result ?? null,
          error: body.error ?? null,
          inputTokens: body.inputTokens ?? null,
          outputTokens: body.outputTokens ?? null,
        })

        logger
          .withTag("agent-execution")
          .info(`Closed agent execution ${execution.id} status=${execution.status}`)

        broadcast(gateway, "agent-execution.updated", execution)

        return toResponse(execution)
      } catch (error) {
        return notFoundOrRethrow(error, reply)
      }
    },
  )
}

function toResponse(execution: StoredAgentExecution) {
  return {
    id: execution.id,
    evaluationId: execution.evaluationId,
    agentType: execution.agentType,
    status: execution.status,
    result: execution.result,
    error: execution.error,
    inputTokens: execution.inputTokens,
    outputTokens: execution.outputTokens,
    createdAt: execution.createdAt,
    startedAt: execution.startedAt,
    finishedAt: execution.finishedAt,
  }
}

function notFoundOrRethrow(error: unknown, reply: { code: (n: number) => { send: (b: unknown) => unknown } }) {
  if (error instanceof AgentExecutionNotFoundError) {
    return reply.code(404).send({ error: error.message })
  }

  if (error instanceof InvalidCompletionError) {
    return reply.code(422).send({ error: error.message })
  }

  throw error
}

function broadcast(
  gateway: RealtimeGateway,
  type: AgentExecutionEvent["type"],
  execution: StoredAgentExecution,
): void {
  gateway.broadcast({ type, execution: toResponse(execution) })
}