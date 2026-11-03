import type { FastifyInstance } from "fastify"
import type { AuditOperatingOptions } from "../../infrastructure/agent-server-client/agent-server.client.js"
import { errorResponses, objectResponse, branchInput } from "../../infrastructure/openapi/routeSchemas.js"
import { AgentConfigurationError } from "../agent-settings/agent-configuration.js"
import { configurationIssuesSchema } from "../agent-settings/agent-settings.schemas.js"
import { UnknownExecutionTargetError } from "../agent-execution/agent-execution.repository.js"
import { AnalysisAlreadyRunningError, InvalidGitRequestError, ProjectFileError, ProjectNotFoundError, SyncInProgressError, WorkspaceMissingError } from "../project/project.service.js"
import { AuditEvidenceUnavailableError, AuditNotFoundError, AuditReportUnavailableError, type QualityAuditService } from "./quality-audit.service.js"
import { auditReportSections } from "./audit-report-sections.js"

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
  startedAt: { type: ["string", "null"], format: "date-time" },
  finishedAt: { type: ["string", "null"], format: "date-time" }, reportAvailable: { type: "boolean" },
  configurationAvailable: { type: "boolean" },
  cancellationRequestedAt: { type: ["string", "null"], format: "date-time" },
})

function failure(error: unknown) {
  if (error instanceof ProjectNotFoundError || error instanceof AuditNotFoundError) return 404
  if (error instanceof InvalidGitRequestError) return 400
  if (error instanceof AgentConfigurationError || error instanceof AnalysisAlreadyRunningError
    || error instanceof SyncInProgressError || error instanceof WorkspaceMissingError
    || error instanceof UnknownExecutionTargetError || error instanceof AuditReportUnavailableError || error instanceof ProjectFileError) return 422
  throw error
}

export function registerQualityAuditRoutes(app: FastifyInstance, service: QualityAuditService) {
  app.post("/api/projects/:id/audits/:auditId/cancel", { schema: {
    tags: ["Projects"], summary: "Request cancellation of a project audit",
    description: "Persists an idempotent cancellation request. Pending dispatch is blocked; active runs are cancelled by agent-server. A request alone does not confirm cancellation.",
    params: { ...params, required: ["id", "auditId"] },
    response: { 202: summary, ...errorResponses([400, 404, 422]) },
  } }, async (request, reply) => {
    const { id, auditId } = request.params as { id: string, auditId: string }
    try {
      reply.header("Cache-Control", "no-store")
      return reply.code(202).send(await service.cancel(Number(id), Number(auditId)))
    } catch (error) { return reply.code(failure(error)).send({ message: (error as Error).message }) }
  })

  app.post("/api/projects/:id/audits", { schema: {
    tags: ["Projects"], summary: "Start a quality audit for a project revision",
    description: "Run maintainability, security and functional adequacy, independently or together, with one report. Functional adequacy requires explicit functional_requirements. Configure model access for each selected attribute first. Optional operating patches are validated against agent-server's catalog.",
    params,
    body: { type: "object", additionalProperties: false, required: ["branch", "commitHash", "attributes"], properties: {
      branch: branchInput, commitHash: { type: "string", pattern: "^[a-fA-F0-9]{40}$" },
      attributes: { type: "array", minItems: 1, maxItems: 3, uniqueItems: true, items: { type: "string", enum: ["maintainability", "security", "functional_adequacy"] } },
      maintainability_selection: { type: "object", minProperties: 1, maxProperties: 12,
        additionalProperties: { type: "array", maxItems: 12, uniqueItems: true, items: { type: "string", minLength: 1 } } },
      functional_requirements: { type: "array", minItems: 1, maxItems: 100, items: {
        type: "object", additionalProperties: false, required: ["requirement_id", "description"], properties: {
          requirement_id: { type: "string", minLength: 1, maxLength: 128, pattern: "\\S" },
          description: { type: "string", minLength: 1, maxLength: 10000, pattern: "\\S" },
        },
      } },
      agent_defaults: { type: "object", additionalProperties: true, description: "Developer-level common overrides; validated by agent-server." },
      security_config: { type: "object", additionalProperties: true, description: "Developer-level security overrides; validated by agent-server." },
      functional_config: { type: "object", additionalProperties: true },
      attribute_options: { type: "object", additionalProperties: { type: "object", additionalProperties: true } },
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

  app.get("/api/projects/:id/audits/:auditId", { schema: {
    tags: ["Projects"], summary: "Read one audit without loading report artifacts or the project history",
    params: { ...params, required: ["id", "auditId"] },
    response: { 200: summary, ...errorResponses([400, 404, 422]) },
  } }, async (request, reply) => {
    const { id, auditId } = request.params as { id: string, auditId: string }
    try { return await service.detail(Number(id), Number(auditId)) }
    catch (error) { return reply.code(failure(error)).send({ message: (error as Error).message }) }
  })

  app.get("/api/projects/:id/audits/:auditId/report/sections/:section", { schema: {
    tags: ["Projects"], summary: "Read one stored audit report section without other sections or artifacts",
    params: { type: "object", required: ["id", "auditId", "section"], properties: { ...params.properties,
      section: { type: "string", enum: auditReportSections } } },
    response: { 200: objectResponse({ section: { type: "string", enum: auditReportSections }, data: {} }), ...errorResponses([400, 404, 422]) },
  } }, async (request, reply) => {
    const { id, auditId, section } = request.params as { id: string, auditId: string, section: string }
    try { return await service.reportSection(Number(id), Number(auditId), section) }
    catch (error) { return reply.code(failure(error)).send({ message: (error as Error).message }) }
  })

  app.get("/api/projects/:id/audits/:auditId/evidence", { schema: {
    tags: ["Projects"], summary: "Read currently published audit evidence without running agents or building reports",
    params: { ...params, required: ["id", "auditId"] },
    response: { 200: objectResponse({ partial: { type: "boolean" }, available: { type: "boolean" }, data: {} }),
      ...errorResponses([400, 404, 422, 503]) },
  } }, async (request, reply) => {
    const { id, auditId } = request.params as { id: string, auditId: string }
    reply.header("Cache-Control", "no-store")
    try { return await service.evidence(Number(id), Number(auditId)) }
    catch (error) { return reply.code(error instanceof AuditEvidenceUnavailableError ? 503 : failure(error)).send({ message: (error as Error).message }) }
  })

  app.post("/api/projects/:id/audits/:auditId/file", { schema: {
    tags: ["Projects"], summary: "Read a text file at the immutable audited commit without changing the checkout",
    params: { ...params, required: ["id", "auditId"] },
    body: { type: "object", additionalProperties: false, required: ["path"], properties: {
      path: { type: "string", minLength: 1, maxLength: 1024 },
    } },
    response: { 200: objectResponse({ path: { type: "string" }, content: { type: "string" }, size: { type: "integer" }, commitHash: { type: "string" } }),
      ...errorResponses([400, 404, 422]) },
  } }, async (request, reply) => {
    const { id, auditId } = request.params as { id: string, auditId: string }
    reply.header("Cache-Control", "no-store")
    try { return await service.file(Number(id), Number(auditId), (request.body as { path: string }).path) }
    catch (error) { return reply.code(failure(error)).send({ message: (error as Error).message }) }
  })

  app.get("/api/projects/:id/audits/:auditId/configuration", { schema: {
    tags: ["Projects"], summary: "Read the immutable audit scope and recorded invocations",
    params: { ...params, required: ["id", "auditId"] },
    response: { 200: objectResponse({
      configuration: { anyOf: [{ type: "null" }, { type: "object", additionalProperties: true }] },
      invocations: { type: "array", items: objectResponse({ id: { type: "string" }, agentId: { type: "string" }, status: { type: "string" } }) },
    }), ...errorResponses([400, 404, 422]) },
  } }, async (request, reply) => {
    const { id, auditId } = request.params as { id: string, auditId: string }
    try { return await service.configuration(Number(id), Number(auditId)) }
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
