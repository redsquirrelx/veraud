import type { FastifyInstance } from "fastify"
import type { AgentSettingsService } from "./agent-settings.service.js"
import { InvalidAgentAssignmentError, UnknownAgentTypeError } from "./agent-settings.errors.js"
import { errorResponses } from "../../infrastructure/openapi/routeSchemas.js"
import type { AgentExecutionOptions } from "./agent-settings.repository.js"
import { AgentConfigurationError } from "./agent-configuration.js"
import { configurationSchema, configurationIssuesSchema } from "./agent-settings.schemas.js"

const agentSettingsSchema = {
  type: "object",
  required: ["agentType", "configured", "configuration", "verification"],
  properties: {
    agentType: { type: "string" },
    configured: { type: "boolean" },
    configuration: configurationSchema,
    verification: {
      type: "object", required: ["status", "checkedAt", "message"],
      properties: {
        status: { type: "string", enum: ["not_verified", "verified", "failed"] },
        checkedAt: { type: ["string", "null"], format: "date-time" },
        message: { type: ["string", "null"] },
      },
    },
  },
} as const

export function registerAgentSettingsRoutes(app: FastifyInstance, service: AgentSettingsService): void {
  app.get("/api/agent-settings", { schema: {
    tags: ["Agent Settings"],
    summary: "List backend agent types and their saved configuration",
    description: "Lists backend-declared agent types and saved settings, including unconfigured agents with configuration null. Does not contact the agent-server. configured indicates model/credential provider consistency; verification separately reports the last access check for the current configuration. Execution starts check live access again. Credentials expose names and IDs only, never API keys.",
    response: {
      200: {
        type: "array",
        items: agentSettingsSchema,
      },
    },
  } }, async () => service.list())

  app.post<{ Params: { agentType: string } }>("/api/agent-settings/:agentType/verify", { schema: {
    tags: ["Agent Settings"], summary: "Verify saved credential access to the selected model",
    description: "Performs a minimal provider generation through the agent-server (may incur usage). Returns verified/failed state with check time and controlled error. Changed selections, parameters or credential/model revisions invalidate previous checks. Execution starts always repeat this check.",
    params: { type: "object", required: ["agentType"], properties: { agentType: { type: "string", minLength: 1 } } },
    response: { 200: agentSettingsSchema, 422: { type: "object", required: ["message", "agents"], properties: { message: { type: "string" }, agents: configurationIssuesSchema } } },
  } }, async (request, reply) => {
    try { return await service.verify(request.params.agentType) }
    catch (error) {
      if (error instanceof AgentConfigurationError) return reply.code(422).send({ message: error.message, agents: error.agents })
      throw error
    }
  })

  app.put<{ Params: { agentType: string }, Body: { modelId: number, credentialId: number } & AgentExecutionOptions }>("/api/agent-settings/:agentType", { schema: {
    tags: ["Agent Settings"],
    summary: "Assign a model and credential to a backend agent",
    description: "Stores an existing model and credential belonging to the same provider. Only backend-declared agent types can be configured. Optional temperature (0ΓÇô2) and maximum tokens (positive integer) are preserved when omitted and cleared when null. Returns the saved configuration without API keys. Does not verify provider access or change an in-progress execution.",
    params: { type: "object", required: ["agentType"], properties: { agentType: { type: "string", minLength: 1 } } },
    body: {
      type: "object", required: ["modelId", "credentialId"], additionalProperties: false,
      properties: {
        modelId: { type: "integer", minimum: 1 }, credentialId: { type: "integer", minimum: 1 },
        temperature: { type: ["number", "null"], minimum: 0, maximum: 2 },
        maxTokens: { type: ["integer", "null"], minimum: 1, maximum: 2147483647 },
        tokenBudget: { type: ["integer", "null"], minimum: 1, maximum: 2147483647 },
        absoluteTokenLimit: { type: ["integer", "null"], minimum: 1, maximum: 2147483647 },
      },
    },
    response: { 200: agentSettingsSchema, ...errorResponses([400, 404, 422]) },
  } }, async (request, reply) => {
    try {
      const { modelId, credentialId, ...options } = request.body
      return await service.save(request.params.agentType, modelId, credentialId, options)
    } catch (error) {
      if (error instanceof UnknownAgentTypeError) return reply.code(404).send({ message: error.message })
      if (error instanceof InvalidAgentAssignmentError) return reply.code(422).send({ message: error.message })
      throw error
    }
  })
}
