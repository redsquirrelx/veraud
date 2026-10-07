import type { FastifyInstance } from "fastify"
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

export function registerAiProviderRoutes(app: FastifyInstance, service: AiProviderService): void {
  app.get("/api/ai-providers", async () => {
    return service.listProviders()
  })

  app.get("/api/ai-providers/:id", {
    schema: { params: providerParams },
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
      params: providerParams,
      body: {
        type: "object",
        required: ["name"],
        properties: {
          name: { type: "string" },
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

  app.delete("/api/ai-providers/:id/models/:nestedId", {
    schema: { params: nestedParams },
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
      params: providerParams,
      body: {
        type: "object",
        required: ["name", "apiKey"],
        properties: {
          name: { type: "string" },
          apiKey: { type: "string" },
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

  app.delete("/api/ai-providers/:id/credentials/:nestedId", {
    schema: { params: nestedParams },
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

function aiErrorCode(error: unknown): number {
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
