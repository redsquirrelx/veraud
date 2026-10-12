import type { FastifyInstance } from "fastify"
import { agentExecutionSchema, versionAnalysisSchema } from "./schemas/agentExecutions.js"
import { aiCredentialSchema, aiModelSchema, aiProviderSchema } from "./schemas/aiProviders.js"
import { executionErrorSchema, messageErrorSchema, validationErrorSchema } from "./schemas/errors.js"
import { projectSummarySchema, registeredProjectSchema } from "./schemas/projects.js"
import { taskSchema } from "./schemas/tasks.js"

export const API_SCHEMAS = [
  messageErrorSchema,
  executionErrorSchema,
  validationErrorSchema,
  projectSummarySchema,
  registeredProjectSchema,
  agentExecutionSchema,
  versionAnalysisSchema,
  aiModelSchema,
  aiCredentialSchema,
  aiProviderSchema,
  taskSchema,
] as const

/** Register public response contracts in the scope shared by all controllers. */
export function registerApiSchemas(app: FastifyInstance): void {
  for (const schema of API_SCHEMAS) app.addSchema(schema)
}
