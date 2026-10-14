import type { FastifyInstance } from "fastify"
import { errorResponses } from "../../infrastructure/openapi/routeSchemas.js"
import { AiCredentialNotFoundError, AiInUseError, AiModelNotFoundError, AiProviderNotFoundError, DuplicateAiError, InvalidAiRequestError, type AiProviderService } from "./ai-provider.service.js"

const providerParams = {
  type: "object",
  required: ["id"],
  properties: {
    id: { type: "string", pattern: "^[0-9]+$" },
  },
} as const

const nestedParams = {
  type: "object",
  required: ["id", "nestedId"],
  properties: {
    id: { type: "string", pattern: "^[0-9]+$" },
    nestedId: { type: "string", pattern: "^[0-9]+$" },
  },
} as const

const modelNameInput = { type: "string", description: "Trimmed, 1ΓÇô128 characters, starts with a letter/number; allows letters/numbers and ._/:-, but no .. . Unique within the provider.", examples: ["gpt-4o"] } as const
const credentialNameInput = { type: "string", description: "Trimmed, 1ΓÇô100 characters, starts with a letter/number; allows letters/numbers, spaces, underscore and dash. Unique within the provider.", examples: ["development"] } as const
const apiKeyInput = { type: "string", description: "Trimmed non-empty token, up to 2000 characters, no internal whitespace. Never returned in full.", examples: ["example-key-1234"] } as const

export function registerAiProviderRoutes(app: FastifyInstance, service: AiProviderService): void {
  app.get("/api/ai-providers", { schema: {
    tags: ["AI Providers"], summary: "List AI providers",
    description: "Lists seeded OpenAI, Anthropic, Google and Groq providers with models and masked credentials. Providers themselves are read-only.",
    response: { 200: { type: "array", items: { $ref: "AiProvider#" } } },
  } }, async () => {
    return service.listProviders()
  })

  app.get("/api/ai-providers/:id", {
    schema: { params: providerParams, tags: ["AI Providers"], summary: "Get an AI provider",
      description: "Returns models and masked credentials for one provider, including whether each is assigned to an agent.",
      response: { 200: { $ref: "AiProvider#" }, ...errorResponses([400, 404], "MessageError", false) } },
  }, async (request, reply) => {
    const params = request.params as { id: string }

    try {
      return reply.code(200).send(await service.getProvider(Number(params.id)))
    } catch (error) {
      if (error instanceof AiProviderNotFoundError) {
        return reply.code(404).send({ message: error.message })
      }

      throw error
    }
  })

  app.post("/api/ai-providers/:id/models", {
    schema: {
      tags: ["AI Providers"], summary: "Create an AI model",
      description: "Creates a model scoped to the provider. Duplicate names return 409; a new model has inUse false.",
      response: { 201: { $ref: "AiModel#" }, ...errorResponses([400, 404, 409]) },
      params: providerParams,
      body: {
        type: "object",
        required: ["name"],
        properties: {
          name: modelNameInput,
        },
      },
    },
  }, async (request, reply) => {
    const params = request.params as { id: string }
    const body = request.body as { name: string }

    try {
      const model = await service.createModel(Number(params.id), body.name)
      return reply.code(201).send(model)
    } catch (error) {
      return reply.code(aiErrorCode(error)).send({ message: aiErrorMessage(error) })
    }
  })

  app.patch("/api/ai-providers/:id/models/:nestedId", {
    schema: {
      tags: ["AI Providers"], summary: "Rename an AI model",
      description: "Allows editing models assigned to agents. The provider stays fixed; retaining the current name is allowed. Foreign model IDs return 404.",
      response: { 200: { $ref: "AiModel#" }, ...errorResponses([400, 404, 409]) },
      params: nestedParams,
      body: {
        type: "object",
        required: ["name"],
        properties: { name: modelNameInput },
      },
    },
  }, async (request, reply) => {
    const params = request.params as { id: string, nestedId: string }
    const body = request.body as { name: string }

    try {
      return reply.code(200).send(await service.updateModel(Number(params.id), Number(params.nestedId), body.name))
    } catch (error) {
      return reply.code(aiErrorCode(error)).send({ message: aiErrorMessage(error) })
    }
  })

  app.delete("/api/ai-providers/:id/models/:nestedId", {
    schema: { params: nestedParams, tags: ["AI Providers"], summary: "Delete an AI model",
      description: "Deletes a model belonging to this provider. Models assigned to agents return 409. Success has no response body.",
      response: { 204: { type: "null", description: "Deleted; no content." }, ...errorResponses([400, 404, 409], "MessageError", false) } },
  }, async (request, reply) => {
    const params = request.params as { id: string, nestedId: string }

    try {
      await service.deleteModel(Number(params.id), Number(params.nestedId))
      return reply.code(204).send()
    } catch (error) {
      return reply.code(aiErrorCode(error)).send({ message: aiErrorMessage(error) })
    }
  })

  app.post("/api/ai-providers/:id/credentials", {
    schema: {
      tags: ["AI Providers"], summary: "Create an AI credential",
      description: "Stores a provider-scoped credential and returns only its masked key preview. A new credential has inUse false.",
      response: { 201: { $ref: "AiCredential#" }, ...errorResponses([400, 404, 409]) },
      params: providerParams,
      body: {
        type: "object",
        required: ["name", "apiKey"],
        properties: {
          name: credentialNameInput,
          apiKey: apiKeyInput,
        },
      },
    },
  }, async (request, reply) => {
    const params = request.params as { id: string }
    const body = request.body as { name: string, apiKey: string }

    try {
      const credential = await service.createCredential(Number(params.id), body.name, body.apiKey)
      return reply.code(201).send(credential)
    } catch (error) {
      return reply.code(aiErrorCode(error)).send({ message: aiErrorMessage(error) })
    }
  })

  app.patch("/api/ai-providers/:id/credentials/:nestedId", {
    schema: {
      tags: ["AI Providers"], summary: "Update an AI credential",
      description: "Renames the credential and optionally replaces its key, including credentials in use. Omit apiKey to preserve it; sending an empty key returns 400. Provider stays fixed.",
      response: { 200: { $ref: "AiCredential#" }, ...errorResponses([400, 404, 409]) },
      params: nestedParams,
      body: {
        type: "object",
        required: ["name"],
        properties: { name: credentialNameInput, apiKey: apiKeyInput },
      },
    },
  }, async (request, reply) => {
    const params = request.params as { id: string, nestedId: string }
    const body = request.body as { name: string, apiKey?: string }

    try {
      return reply.code(200).send(await service.updateCredential(Number(params.id), Number(params.nestedId), body.name, body.apiKey))
    } catch (error) {
      return reply.code(aiErrorCode(error)).send({ message: aiErrorMessage(error) })
    }
  })

  app.delete("/api/ai-providers/:id/credentials/:nestedId", {
    schema: { params: nestedParams, tags: ["AI Providers"], summary: "Delete an AI credential",
      description: "Deletes a credential belonging to this provider. Credentials assigned to agents return 409. Success has no response body.",
      response: { 204: { type: "null", description: "Deleted; no content." }, ...errorResponses([400, 404, 409], "MessageError", false) } },
  }, async (request, reply) => {
    const params = request.params as { id: string, nestedId: string }

    try {
      await service.deleteCredential(Number(params.id), Number(params.nestedId))
      return reply.code(204).send()
    } catch (error) {
      return reply.code(aiErrorCode(error)).send({ message: aiErrorMessage(error) })
    }
  })
}

function aiErrorCode(error: unknown): 400 | 404 | 409 {
  if (error instanceof AiProviderNotFoundError || error instanceof AiModelNotFoundError || error instanceof AiCredentialNotFoundError) {
    return 404
  }

  if (error instanceof InvalidAiRequestError) {
    return 400
  }

  if (error instanceof DuplicateAiError || error instanceof AiInUseError) {
    return 409
  }

  throw error
}

function aiErrorMessage(error: unknown): string {
  if (error instanceof AiProviderNotFoundError || error instanceof AiModelNotFoundError || error instanceof AiCredentialNotFoundError || error instanceof InvalidAiRequestError || error instanceof DuplicateAiError || error instanceof AiInUseError) {
    return error.message
  }

  throw error
}
