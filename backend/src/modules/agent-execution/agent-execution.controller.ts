import type { FastifyInstance, FastifyReply } from "fastify"
import { AgentConfigurationError } from "../agent-settings/agent-configuration.js"
import { configurationIssuesSchema } from "../agent-settings/agent-settings.schemas.js"
import { errorResponses } from "../../infrastructure/openapi/routeSchemas.js"
import type {
  AgentExecutionEvent,
  RealtimeGateway,
} from "../../infrastructure/realtime-gateway/realtime.gateway.js"
import { logger } from "../../config/logger.js"
import { monitorExecution } from "./agent-execution.monitor.js"
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
    agentType: { type: "string", minLength: 1, description: "Agent type registered in agent settings.", examples: ["analyzer"] },
    evaluationId: { type: "integer", minimum: 1, description: "Existing evaluation used to resolve the agent input.", examples: [1] },
  },
} as const

const openDirectBody = {
  type: "object",
  required: ["agentType", "input"],
  properties: {
    agentType: { type: "string", minLength: 1, examples: ["analyzer"] },
    input: { type: "object", minProperties: 1, additionalProperties: true, description: "Agent-specific input. root_path, if present, must resolve inside the workspace.", examples: [{ root_path: "project-1-owner-repo" }] },
  },
} as const

const closeBody = {
  type: "object",
  required: ["status"],
  properties: {
    status: { type: "string", enum: ["Completed", "Failed"], examples: ["Completed"] },
    result: { type: ["string", "null"], description: "Opaque serialized agent output. Omitted means null.", examples: ['{"summary":"Analysis completed"}'] },
    error: { type: ["string", "null"], description: "Required to be truthy when failing an open execution. Omitted means null." },
    inputTokens: { type: ["integer", "null"], minimum: 0, examples: [1200] },
    outputTokens: { type: ["integer", "null"], minimum: 0, examples: [180] },
    estimatedTokens: { type: ["integer", "null"], minimum: 0, maximum: 2147483647 },
    interruptionReason: { type: ["string", "null"], minLength: 1 },
  },
} as const

const progressBody = {
  type: "object", required: ["inputTokens", "outputTokens"], additionalProperties: false,
  properties: {
    inputTokens: { type: ["integer", "null"], minimum: 0, maximum: 2147483647 },
    outputTokens: { type: ["integer", "null"], minimum: 0, maximum: 2147483647 },
    estimatedTokens: { type: "integer", minimum: 0, maximum: 2147483647, default: 0 },
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
  app.post("/api/agent-executions", { schema: { body: openBody,
    tags: ["Agent Executions"], summary: "Start an agent execution for an evaluation",
    description: "Checks saved model/credential provider consistency and live model access before creating an execution; failures return 422 with affected agents. Captures an immutable configuration without API keys, then returns Waiting and dispatches with that configuration. Input is resolved from the evaluation. Later dispatch failures update the execution; they do not change this initial HTTP response.",
    response: { 201: { $ref: "AgentExecution#" }, ...errorResponses([400], "ExecutionError", false), 422: { type: "object", required: ["error"], properties: { error: { type: "string" }, agents: configurationIssuesSchema } } },
  } }, async (request, reply) => {
    const body = request.body as { agentType: string; evaluationId: number }

    try {
      const execution = await service.open(body.agentType, body.evaluationId)

      logger
        .withTag("agent-execution")
        .info(`Registered agent execution ${execution.id} agentType=${execution.agentType}`)

      return reply.code(201).send(toResponse(execution))
    } catch (error) {
      if (error instanceof AgentConfigurationError) return reply.code(422).send({ error: error.message, agents: error.agents })
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
  app.post("/api/agent-executions/direct", { schema: { body: openDirectBody,
    tags: ["Agent Executions"], summary: "Start an agent with explicit input",
    description: "Checks saved model/credential provider consistency and live model access before creating an execution; failures return 422 with affected agents. Captures the saved configuration for this run. Creates no evaluation/version and returns evaluationId null. Workspace traversal is rejected before creation; an absent checkout fails the execution in the background. Other input fields pass through to the agent.",
    response: { 201: { $ref: "AgentExecution#" }, ...errorResponses([400], "ExecutionError", false), 422: { type: "object", required: ["error"], properties: { error: { type: "string" }, agents: configurationIssuesSchema } } },
  } }, async (request, reply) => {
    const body = request.body as { agentType: string; input: Record<string, unknown> }

    try {
      const execution = await service.openDirect(body.agentType, body.input)

      logger
        .withTag("agent-execution")
        .info(`Registered direct agent execution ${execution.id} agentType=${execution.agentType}`)

      return reply.code(201).send(toResponse(execution))
    } catch (error) {
      if (error instanceof AgentConfigurationError) return reply.code(422).send({ error: error.message, agents: error.agents })
      if (error instanceof UnknownExecutionTargetError || error instanceof InvalidDirectInputError) {
        return reply.code(422).send({ error: error.message })
      }

      throw error
    }
  })

  app.get("/api/agent-executions/:id", { schema: { params: idParams,
    querystring: { type: "object", properties: { monitor: { type: "boolean" } } },
    tags: ["Agent Executions"], summary: "Get an agent execution",
    description: "Returns execution state, usage, lifecycle dates and HTTP monitor context. With monitor=true, quality-audit result is a compact state/receipt projection excluding evidence, snapshots and Word bytes. The default returns the original result.",
    response: { 200: { $ref: "AgentExecution#" }, ...errorResponses([400, 404], "ExecutionError", false) },
  } }, async (request, reply) => {
    const { id } = request.params as { id: string }

    try {
      const execution = await service.findById(Number(id))
      return toResponse((request.query as { monitor?: boolean }).monitor ? monitorExecution(execution) : execution)
    } catch (error) {
      return notFoundOrRethrow(error, reply)
    }
  })

  /** Called by the agent-server once the run actually starts. Optional. */
  app.post("/api/agent-executions/:id/running", { schema: { params: idParams,
    body: { type: ["object", "null"], properties: { runId: { type: "string", pattern: "^[a-f0-9]{32}$" } }, additionalProperties: false },
    tags: ["Agent Executions"], summary: "Report that an agent execution started",
    description: "Optional agent-server callback. Marks an open execution Running and publishes an update. Finished executions are not overwritten. No body is required.",
    response: { 200: { $ref: "AgentExecution#" }, ...errorResponses([400, 404], "ExecutionError", false) },
  } }, async (request, reply) => {
    const { id } = request.params as { id: string }

    try {
      const execution = await service.markRunning(Number(id), (request.body as { runId?: string } | undefined)?.runId)

      broadcast(gateway, "agent-execution.updated", execution)

      return toResponse(execution)
    } catch (error) {
      return notFoundOrRethrow(error, reply)
    }
  })

  app.post("/api/agent-executions/:id/progress", { schema: {
    params: idParams, body: progressBody,
    tags: ["Agent Executions"], summary: "Report cumulative agent token usage",
    description: "Stores provider-reported input/output counts and separate estimates while Running. Counts are cumulative, not deltas. Duplicate, stale and post-completion progress cannot reduce usage or reopen an execution.",
    response: { 200: { $ref: "AgentExecution#" }, ...errorResponses([400, 404], "ExecutionError", false) },
  } }, async (request, reply) => {
    const { id } = request.params as { id: string }
    const body = request.body as { inputTokens: number | null, outputTokens: number | null, estimatedTokens?: number }
    try {
      const execution = await service.updateUsage(Number(id), { ...body, estimatedTokens: body.estimatedTokens ?? 0 })
      broadcast(gateway, "agent-execution.updated", execution)
      return toResponse(execution)
    } catch (error) { return notFoundOrRethrow(error, reply) }
  })

  /** Called by the agent-server when the run finishes, successfully or not. */
  app.post(
    "/api/agent-executions/:id/completion",
    { schema: { params: idParams, body: closeBody,
      tags: ["Agent Executions"], summary: "Report an agent execution result",
      description: "Agent-server callback. Missing optional fields become null. Failed requires an error for open executions; callbacks on already-finished executions return the stored row unchanged.",
      response: { 200: { $ref: "AgentExecution#" }, ...errorResponses([400, 404, 422], "ExecutionError", false) },
    } },
    async (request, reply) => {
      const { id } = request.params as { id: string }
      const body = request.body as {
        status: "Completed" | "Failed"
        result?: string | null
        error?: string | null
        inputTokens?: number | null
        outputTokens?: number | null
        estimatedTokens?: number | null
        interruptionReason?: string | null
      }

      try {
        const execution = await service.complete(Number(id), {
          status: body.status,
          result: body.result ?? null,
          error: body.error ?? null,
          inputTokens: body.inputTokens ?? null,
          outputTokens: body.outputTokens ?? null,
          ...(body.estimatedTokens === undefined ? {} : { estimatedTokens: body.estimatedTokens }),
          ...(body.interruptionReason === undefined ? {} : { interruptionReason: body.interruptionReason }),
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

function toResponse(execution: StoredAgentExecution, includeContext = true) {
  return {
    id: execution.id,
    evaluationId: execution.evaluationId,
    agentType: execution.agentType,
    status: execution.status,
    result: execution.result,
    error: execution.error,
    inputTokens: execution.inputTokens,
    outputTokens: execution.outputTokens,
    estimatedTokens: execution.estimatedTokens,
    interruptionReason: execution.interruptionReason,
    createdAt: execution.createdAt,
    startedAt: execution.startedAt,
    finishedAt: execution.finishedAt,
    configuration: execution.configuration ?? null,
    ...(!includeContext || execution.monitorContext === undefined ? {} : { monitorContext: execution.monitorContext }),
  }
}

function notFoundOrRethrow(error: unknown, reply: FastifyReply) {
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
  gateway.broadcast({ type, execution: toResponse(execution, false) })
}
