import type { FastifyInstance } from "fastify"
import type { AuditOperatingOptions } from "../../infrastructure/agent-server-client/agent-server.client.js"
import { errorResponses, objectResponse, branchInput } from "../../infrastructure/openapi/routeSchemas.js"
import { AgentConfigurationError } from "../agent-settings/agent-configuration.js"
import { configurationIssuesSchema } from "../agent-settings/agent-settings.schemas.js"
import { UnknownExecutionTargetError } from "../agent-execution/agent-execution.repository.js"
import { AnalysisAlreadyRunningError, InvalidGitRequestError, ProjectNotFoundError, SyncInProgressError, WorkspaceMissingError } from "../project/project.service.js"
import { AuditNotFoundError, AuditReportUnavailableError, type QualityAuditService } from "./quality-audit.service.js"

const params = {
  type: "object", required: ["id"], properties: {
    id: { type: "string", pattern: "^[0-9]+$" },
    auditId: { type: "string", pattern: "^[0-9]+$" },
  },
} as const

const summary = objectResponse({
  id: { type: "integer" }, evaluationId: { type: ["integer", "null"] },
  branch: { type: ["string", "null"] }, commitHash: { type: ["string", "null"] },
  attributes: { type: "array", items: { type: "string" } },
  executionStatus: { type: "string" }, auditStatus: { type: ["string", "null"] }, runId: { type: ["string", "null"] },
  error: { type: ["string", "null"] }, createdAt: { type: "string", format: "date-time" },
  finishedAt: { type: ["string", "null"], format: "date-time" }, reportAvailable: { type: "boolean" },
})

function failure(error: unknown) {
  if (error instanceof ProjectNotFoundError || error instanceof AuditNotFoundError) return 404
  if (error instanceof InvalidGitRequestError) return 400
  if (error instanceof AgentConfigurationError || error instanceof AnalysisAlreadyRunningError
    || error instanceof SyncInProgressError || error instanceof WorkspaceMissingError
    || error instanceof UnknownExecutionTargetError || error instanceof AuditReportUnavailableError) return 422
  throw error
}

export function registerQualityAuditRoutes(app: FastifyInstance, service: QualityAuditService) {
  app.post("/api/projects/:id/audits", { schema: {
    tags: ["Projects"], summary: "Start a quality audit for a project revision",
    description: "Run maintainability, security or both with one report. Configure model access for each selected attribute first. Optional operating patches are validated against agent-server's catalog; security_config overrides common agent_defaults for security. Developer controls are not exposed as user-panel settings.",
    params,
    body: { type: "object", additionalProperties: false, required: ["branch", "commitHash", "attributes"], properties: {
      branch: branchInput, commitHash: { type: "string", pattern: "^[a-fA-F0-9]{40}$" },
      attributes: { type: "array", minItems: 1, maxItems: 2, uniqueItems: true, items: { type: "string", enum: ["maintainability", "security"] } },
      agent_defaults: { type: "object", additionalProperties: true, description: "Developer-level common overrides; validated by agent-server." },
      security_config: { type: "object", additionalProperties: true, description: "Developer-level security overrides; validated by agent-server." },
      audit_budget: { type: "object", additionalProperties: true },
      call_limits: { type: "object", additionalProperties: true, description: "Developer-level maintainability call envelopes; validated by agent-server." },
    } },
    response: { 202: objectResponse({ versionId: { type: "integer" }, evaluationId: { type: "integer" }, executionId: { type: "integer" } }),
      ...errorResponses([400, 404]), 422: { type: "object", required: ["message"], properties: { message: { type: "string" }, agents: configurationIssuesSchema } } },
  } }, async (request, reply) => {
    const { id } = request.params as { id: string }
    const { branch, commitHash, attributes, ...options } = request.body as AuditOperatingOptions & {
      branch: string, commitHash: string, attributes: string[] }
    try {
      return reply.code(202).send(await service.start(Number(id), branch, commitHash, attributes, options))
    } catch (error) {
      return reply.code(failure(error)).send({ message: (error as Error).message, ...(error instanceof AgentConfigurationError ? { agents: error.agents } : {}) })
    }
  })

  app.get("/api/projects/:id/audits", { schema: {
    tags: ["Projects"], summary: "List persisted quality audits", params,
    description: "Returns audit runs for all project revisions, newest first, with execution and evaluation states kept separate. Report artifacts are fetched separately.",
    response: { 200: { type: "array", items: summary }, ...errorResponses([400, 404, 422]) },
  } }, async (request, reply) => {
    try { return await service.list(Number((request.params as { id: string }).id)) }
    catch (error) { return reply.code(failure(error)).send({ message: (error as Error).message }) }
  })

  app.get("/api/projects/:id/audits/:auditId/report", { schema: {
    tags: ["Projects"], summary: "Read the canonical persisted audit report", params: { ...params, required: ["id", "auditId"] },
    description: "Returns the original SoftwareAuditReport JSON produced from this audit's Blackboard. Available after pipeline completion, including partial evaluations; does not invoke agents.",
    response: { 200: { type: "object", additionalProperties: true }, ...errorResponses([400, 404, 422]) },
  } }, async (request, reply) => {
    const { id, auditId } = request.params as { id: string, auditId: string }
    try { return await service.report(Number(id), Number(auditId)) }
    catch (error) { return reply.code(failure(error)).send({ message: (error as Error).message }) }
  })

  app.get("/api/projects/:id/audits/:auditId/report.docx", { schema: {
    tags: ["Projects"], summary: "Download the original persisted Word audit report", params: { ...params, required: ["id", "auditId"] },
    description: "Downloads the same DOCX produced by agent-server's audit report renderer. Stored bytes remain available after agent-server restarts or is offline. The audit ID must belong to this project.",
    response: { 200: { type: "string", format: "binary" }, ...errorResponses([400, 404, 422]) },
  } }, async (request, reply) => {
    const { id, auditId } = request.params as { id: string, auditId: string }
    try {
      const content = await service.document(Number(id), Number(auditId))
      return reply.type("application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        .header("Content-Disposition", `attachment; filename="informe-auditoria-${auditId}.docx"`)
        .send(content)
    } catch (error) { return reply.code(failure(error)).send({ message: (error as Error).message }) }
  })
}
