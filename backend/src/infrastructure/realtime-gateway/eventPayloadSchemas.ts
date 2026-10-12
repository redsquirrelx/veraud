import type { JSONSchema } from "json-schema-to-ts"

export const taskPayloadSchema = {
  $id: "TaskEventPayload",
  type: "object",
  additionalProperties: false,
  required: ["id", "projectId", "description", "command", "status", "kind", "exitCode"],
  properties: {
    id: { type: "integer", description: "Task identifier." },
    projectId: { type: "integer", description: "Owning project identifier." },
    description: { type: ["string", "null"], description: "Task description." },
    command: {
      type: ["string", "null"],
      description: "Readable executable/argument representation, not a shell script. Null when unavailable.",
    },
    status: { type: "string", description: "Runner states: Queued, Running, Succeded (existing spelling), Failed." },
    kind: { type: "string", description: "Git command kind; older rows can contain unknown." },
    exitCode: { type: ["integer", "null"], description: "Null before completion; runner writes 0 on success and 1 on failure." },
  },
} as const satisfies JSONSchema

export const agentExecutionPayloadSchema = {
  $id: "AgentExecutionEventPayload",
  type: "object",
  additionalProperties: false,
  required: ["id", "evaluationId", "agentType", "status", "result", "error", "inputTokens", "outputTokens", "createdAt", "startedAt", "finishedAt"],
  properties: {
    id: { type: "integer", description: "Execution identifier." },
    evaluationId: { type: ["integer", "null"], description: "Evaluation identifier; null for direct executions." },
    agentType: { type: "string", description: "Agent name." },
    status: { type: "string", description: "Lifecycle states: Waiting, Running, Completed, Failed." },
    result: { type: ["string", "null"], description: "Opaque serialized agent output. It remains a string, not a nested object." },
    error: { type: ["string", "null"], description: "Failure message." },
    inputTokens: { type: ["integer", "null"], description: "Optional input token usage." },
    outputTokens: { type: ["integer", "null"], description: "Optional output token usage." },
    createdAt: { type: "string", format: "date-time", description: "Creation timestamp, serialized from a Date." },
    startedAt: {
      anyOf: [{ type: "string", format: "date-time" }, { type: "null" }],
      description: "Start timestamp, or null before running.",
    },
    finishedAt: {
      anyOf: [{ type: "string", format: "date-time" }, { type: "null" }],
      description: "Finish timestamp, or null before completion.",
    },
  },
} as const satisfies JSONSchema

export const eventPayloadSchemas = [taskPayloadSchema, agentExecutionPayloadSchema] as const
