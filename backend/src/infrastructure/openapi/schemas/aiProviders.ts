export const aiModelSchema = {
  $id: "AiModel",
  type: "object",
  required: ["id", "name", "inUse"],
  properties: {
    id: { type: "integer" },
    name: { type: "string" },
    inUse: { type: "boolean" },
  },
} as const

export const aiCredentialSchema = {
  $id: "AiCredential",
  type: "object",
  required: ["id", "name", "apiKeyPreview", "inUse"],
  properties: {
    id: { type: "integer" },
    name: { type: "string" },
    apiKeyPreview: { type: "string", description: "Masked API key; the full key is never included in this response." },
    inUse: { type: "boolean" },
  },
} as const

export const aiProviderSchema = {
  $id: "AiProvider",
  type: "object",
  required: ["id", "name", "models", "credentials"],
  properties: {
    id: { type: "integer" },
    name: { type: "string" },
    models: { type: "array", items: { $ref: "AiModel#" } },
    credentials: { type: "array", items: { $ref: "AiCredential#" } },
  },
} as const
