import type { FastifyInstance } from "fastify"
import type {
  AgentExecutionEvent,
  RealtimeGateway,
} from "../../infrastructure/realtime-gateway/realtime.gateway.js"
import { logger } from "../../config/logger.js"
import { InvalidDirectInputError } from "../../infrastructure/agent-target/direct-input.guard.js"
import {
  UnknownExecutionTargetError,
  type StoredAgentExecution,
} from "./agent-execution.repository.js"
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

const openDirectBody = {
  type: "object",
  required: ["agentType", "input"],
  properties: {
    agentType: { type: "string", minLength: 1 },
    input: { type: "object", minProperties: 1 },
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
   * The backend calls this when it invokes an agent. The row comes back Waiting
   * and the run continues in the background, so the response does not wait for
   * the agent. The endpoints below stay available for an agent that reports its
   * own progress, and are safe to call after the fact: a finished run is never
   * overwritten.
   */
  app.post("/api/agent-executions", { schema: { body: openBody } }, async (request, reply) => {
    const body = request.body as { agentType: string; evaluationId: number }

    try {
      const execution = await service.open(body.agentType, body.evaluationId)

      logger
        .withTag("agent-execution")
        .info(`Registered agent execution ${execution.id} agentType=${execution.agentType}`)

      return reply.code(201).send(toResponse(execution))
    } catch (error) {
      if (error instanceof UnknownExecutionTargetError) {
        return reply.code(422).send({ error: error.message })
      }

      throw error
    }
  })

  /**
   * Registers a direct invocation with an explicit agent input.
   *
   * No evaluation or project version is created: the row stores
   * evaluationId null and the input goes to the agent as given, except
   * `root_path` which must resolve inside the workspace. Registered before
   * `/:id` for clarity (`:id` only matches digits, so there is no conflict).
   */
  app.post("/api/agent-executions/direct", { schema: { body: openDirectBody } }, async (request, reply) => {
    const body = request.body as { agentType: string; input: Record<string, unknown> }

    try {
      const execution = await service.openDirect(body.agentType, body.input)

      logger
        .withTag("agent-execution")
        .info(`Registered direct agent execution ${execution.id} agentType=${execution.agentType}`)

      return reply.code(201).send(toResponse(execution))
    } catch (error) {
      if (error instanceof UnknownExecutionTargetError || error instanceof InvalidDirectInputError) {
        return reply.code(422).send({ error: error.message })
      }

      throw error
    }
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