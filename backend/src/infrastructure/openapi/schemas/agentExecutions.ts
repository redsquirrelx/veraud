import { configurationSchema } from "../../../modules/agent-settings/agent-settings.schemas.js"

export const agentExecutionSchema = {
  $id: "AgentExecution",
  type: "object",
  required: ["id", "evaluationId", "agentType", "status", "result", "error", "inputTokens", "outputTokens", "createdAt", "startedAt", "finishedAt"],
  properties: {
    id: { type: "integer" },
    evaluationId: { type: ["integer", "null"] },
    agentType: { type: "string" },
    status: { type: "string", enum: ["Waiting", "Running", "Completed", "Failed"] },
    result: { type: ["string", "null"], description: "Opaque serialized agent output, returned as a string rather than a JSON object." },
    error: { type: ["string", "null"] },
    inputTokens: { type: ["integer", "null"] },
    outputTokens: { type: ["integer", "null"] },
    createdAt: { type: "string", format: "date-time" },
    startedAt: { type: ["string", "null"], format: "date-time" },
    finishedAt: { type: ["string", "null"], format: "date-time" },
    configuration: { ...configurationSchema, description: "Immutable configuration captured at execution start, without API keys. Null for historical executions." },
  },
} as const

export const versionAnalysisSchema = {
  $id: "VersionAnalysis",
  type: "object",
  required: ["id", "branch", "commitHash", "analysisStatus", "analyzedAt", "evaluationId", "execution", "derivedStatus"],
  properties: {
    id: { type: "integer" },
    branch: { type: ["string", "null"] },
    commitHash: { type: ["string", "null"] },
    analysisStatus: { type: "string" },
    analyzedAt: { type: ["string", "null"], format: "date-time" },
    evaluationId: { type: ["integer", "null"] },
    execution: { anyOf: [{ $ref: "AgentExecution#" }, { type: "null" }] },
    executions: { type: "array", items: { $ref: "AgentExecution#" }, description: "All stages of the latest evaluation, one row per pipeline stage." },
    derivedStatus: { type: "string", description: "Execution status, or NeverAnalyzed/Pending when there is no execution." },
  },
} as const
