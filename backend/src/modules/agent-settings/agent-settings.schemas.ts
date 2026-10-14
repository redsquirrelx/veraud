const selectionSchema = {
  type: "object", required: ["id", "name", "providerId", "providerName"],
  properties: { id: { type: "integer" }, name: { type: "string" }, providerId: { type: "integer" }, providerName: { type: "string" } },
} as const

export const configurationSchema = {
  anyOf: [{ type: "null" }, {
    type: "object", required: ["model", "credential", "temperature", "maxTokens"],
    properties: {
      model: selectionSchema, credential: selectionSchema,
      temperature: { type: ["number", "null"] }, maxTokens: { type: ["integer", "null"] },
      tokenBudget: { type: ["integer", "null"], minimum: 1 },
      absoluteTokenLimit: { type: ["integer", "null"], minimum: 1 },
    },
  }],
} as const

export const configurationIssuesSchema = {
  type: "array", items: { type: "object", required: ["agentType", "reason"], properties: { agentType: { type: "string" }, reason: { type: "string" } } },
} as const
