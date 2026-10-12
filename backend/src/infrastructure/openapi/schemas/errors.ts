export const messageErrorSchema = {
  $id: "MessageError",
  type: "object",
  required: ["message"],
  properties: { message: { type: "string" } },
} as const

export const executionErrorSchema = {
  $id: "ExecutionError",
  type: "object",
  required: ["error"],
  properties: { error: { type: "string" } },
} as const

export const validationErrorSchema = {
  $id: "ValidationError",
  description: "Fastify request validation error, distinct from domain errors.",
  type: "object",
  required: ["statusCode", "code", "error", "message"],
  properties: {
    statusCode: { type: "integer" },
    code: { type: "string" },
    error: { type: "string" },
    message: { type: "string" },
  },
} as const
