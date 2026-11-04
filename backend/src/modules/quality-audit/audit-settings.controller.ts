import type { FastifyInstance } from "fastify"
import { AuditSettingsError, type AuditSettingsService } from "./audit-settings.service.js"
import { errorResponses } from "../../infrastructure/openapi/routeSchemas.js"

export function registerAuditSettingsRoutes(app: FastifyInstance, service: AuditSettingsService) {
  const params = { type: "object", required: ["attribute"], properties: {
    attribute: { type: "string", enum: ["maintainability", "security", "functional_adequacy"] },
  } } as const
  const response = { 200: { type: "object", additionalProperties: true }, ...errorResponses([400, 422, 503]) }
  app.get<{ Params: { attribute: string } }>("/api/audit-settings/:attribute", { schema: {
    tags: ["Agent Settings"], summary: "Load audit settings and explicit developer-level schema", params, response,
  } }, async (request, reply) => {
    try { return await service.get(request.params.attribute) }
    catch (error) {
      if (error instanceof AuditSettingsError) return reply.code(error.status).send({ message: error.message })
      throw error
    }
  })
  app.put<{ Params: { attribute: string }, Body: Record<string, unknown> }>("/api/audit-settings/:attribute", { schema: {
    tags: ["Agent Settings"], summary: "Validate and persist audit operating settings for future runs", params,
    body: { type: "object", additionalProperties: true }, response,
  } }, async (request, reply) => {
    try { return await service.save(request.params.attribute, request.body) }
    catch (error) {
      if (error instanceof AuditSettingsError) return reply.code(error.status).send({ message: error.message })
      throw error
    }
  })
}
