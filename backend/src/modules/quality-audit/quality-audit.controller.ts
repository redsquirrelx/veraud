import { createReadStream } from "node:fs"
import type { FastifyInstance } from "fastify"
import type { AuditOperatingOptions } from "../../infrastructure/agent-server-client/agent-server.client.js"
import { errorResponses, objectResponse, branchInput } from "../../infrastructure/openapi/routeSchemas.js"
import { AgentConfigurationError } from "../agent-settings/agent-configuration.js"
import { configurationIssuesSchema } from "../agent-settings/agent-settings.schemas.js"
import { UnknownExecutionTargetError } from "../agent-execution/agent-execution.repository.js"
import { executionErrorDetailSchema } from "../agent-execution/execution-error-detail.js"
import { AnalysisAlreadyRunningError, InvalidGitRequestError, ProjectFileError, ProjectNotFoundError, SyncInProgressError, WorkspaceMissingError } from "../project/project.service.js"
import { ArchitectureContextRequiredError, ArchitectureContextUnavailableError, AuditEvidenceUnavailableError, AuditNotFoundError, AuditReportUnavailableError, type QualityAuditService } from "./quality-audit.service.js"
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
  errorDetail: executionErrorDetailSchema,
  startedAt: { type: ["string", "null"], format: "date-time" },
  finishedAt: { type: ["string", "null"], format: "date-time" }, reportAvailable: { type: "boolean" },
  configurationAvailable: { type: "boolean" },
  cancellationRequestedAt: { type: ["string", "null"], format: "date-time" },
})

function failure(error: unknown) {
  if (error instanceof ProjectNotFoundError || error instanceof AuditNotFoundError || error instanceof ArchitectureContextUnavailableError) return 404
  if (error instanceof InvalidGitRequestError) return 400
  if (error instanceof AgentConfigurationError || error instanceof AnalysisAlreadyRunningError
    || error instanceof SyncInProgressError || error instanceof WorkspaceMissingError
     || error instanceof ArchitectureContextRequiredError || error instanceof UnknownExecutionTargetError || error instanceof AuditReportUnavailableError || error instanceof ProjectFileError) return 422
  throw error
}

export function registerQualityAuditRoutes(app: FastifyInstance, service: QualityAuditService) {
  app.get("/api/projects/:id/architecture-context", { schema: {
    tags: ["Projects"], summary: "Check saved architecture context for a project revision",
    description: "Reports whether a saved architecture context execution exists for the project revision without starting work.", params,
    querystring: { type: "object", additionalProperties: false, required: ["commitHash"], properties: {
      commitHash: { type: "string", pattern: "^[a-fA-F0-9]{40}$" },
    } },
    response: { 200: objectResponse({ projectId: { type: "integer" }, commitHash: { type: "string" }, available: { type: "boolean" },
      executionId: { type: ["integer", "null"] }, executionStatus: { type: ["string", "null"], enum: ["complete", "partial", null] } }),
      ...errorResponses([400, 404, 422]) },
  } }, async (request, reply) => {
    reply.header("Cache-Control", "no-store")
    try { return await service.architectureContext(Number((request.params as { id: string }).id), (request.query as { commitHash: string }).commitHash) }
    catch (error) { return reply.code(failure(error)).send({ message: (error as Error).message }) }
  })
  app.get("/api/projects/:id/architecture-context/content", { schema: {
    tags: ["Projects"], summary: "Read saved architecture context content for a project revision",
    description: "Returns the stored architecture context document for the project revision without running agents.", params,
    querystring: { type: "object", additionalProperties: false, required: ["commitHash"], properties: {
      commitHash: { type: "string", pattern: "^[a-fA-F0-9]{40}$" },
    } },
    response: { 200: objectResponse({ projectId: { type: "integer" }, commitHash: { type: "string" },
      executionId: { type: "integer" }, executionStatus: { type: "string", enum: ["complete", "partial"] },
      schemaVersion: { type: "string" }, createdAt: { type: "string", format: "date-time" },
      data: { type: "object", additionalProperties: true } }),
      ...errorResponses([400, 404, 422]) },
  } }, async (request, reply) => {
    reply.header("Cache-Control", "no-store")
    try { return await service.architectureContextContent(Number((request.params as { id: string }).id), (request.query as { commitHash: string }).commitHash) }
    catch (error) { return reply.code(failure(error)).send({ message: (error as Error).message }) }
  })
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
     description: "Run maintainability, security and functional adequacy independently or together. Maintainability requires a saved usable architecture context for the exact project/commit; the backend injects it automatically and rejects manual request input. Functional adequacy without functional_requirements is exploratory and needs no model. Optional operating patches are validated against agent-server's catalog.",
    params,
    body: { type: "object", additionalProperties: false, required: ["branch", "commitHash", "attributes"], properties: {
      branch: branchInput, commitHash: { type: "string", pattern: "^[a-fA-F0-9]{40}$" },
      attributes: { type: "array", minItems: 1, maxItems: 3, uniqueItems: true, items: { type: "string", enum: ["maintainability", "security", "functional_adequacy"] } },
      maintainability_selection: { type: "object", minProperties: 1, maxProperties: 12,
        additionalProperties: { type: "array", maxItems: 12, uniqueItems: true, items: { type: "string", minLength: 1 } } },
       request: { not: {}, description: "Server-owned: maintainability loads the saved architecture context for this version. Manual request input is not accepted." },
      functional_requirements: { type: "array", maxItems: 100, items: {
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

  app.post("/api/projects/:id/audits/:auditId/finding-resolution", { schema: {
    tags: ["Projects"], summary: "Revalidate the audit findings against the audited revision",
    description: "Starts the standalone finding_resolution agent over the report findings stored for a completed or failed audit. It produces a new FindingResolution execution for the same project version; it is independent of the quality-audit pipeline. Optional findingIds select a subset.",
    params: { ...params, required: ["id", "auditId"] },
    body: { type: "object", additionalProperties: false, required: ["commitHash"], properties: {
      commitHash: { type: "string", pattern: "^[a-fA-F0-9]{40}$" },
      findingIds: { type: "array", maxItems: 500, uniqueItems: true, items: { type: "string", minLength: 1, maxLength: 256 } },
    } },
    response: { 202: { type: "object", additionalProperties: true }, ...errorResponses([400, 404, 422]) },
  } }, async (request, reply) => {
    const { id, auditId } = request.params as { id: string, auditId: string }
    const body = request.body as { commitHash: string, findingIds?: string[] }
    try {
      return reply.code(202).send(await service.startFindingResolution(Number(id), Number(auditId), body.commitHash, body.findingIds))
    } catch (error) { return reply.code(failure(error)).send({ message: (error as Error).message, ...(error instanceof AgentConfigurationError ? { agents: error.agents } : {}) }) }
  })

  app.get("/api/projects/:id/audits", { schema: {
    tags: ["Projects"], summary: "List persisted quality audits", params,
    description: "Returns lightweight summaries, newest first. Supply limit and offset for a paginated response. Report, configuration and Word artifacts are not materialized in Node.",
    querystring: { type: "object", additionalProperties: false, properties: {
      limit: { type: "integer", minimum: 1, maximum: 100 }, offset: { type: "integer", minimum: 0, maximum: 2147483647 },
    } },
    response: { 200: { anyOf: [{ type: "array", items: summary }, objectResponse({
      items: { type: "array", items: summary }, total: { type: "integer" }, hasRunning: { type: "boolean" },
      limit: { type: "integer" }, offset: { type: "integer" },
    })] }, ...errorResponses([400, 404, 422]) },
  } }, async (request, reply) => {
    const query = request.query as { limit?: number, offset?: number }
    const pagination = query.limit !== undefined || query.offset !== undefined
      ? { limit: query.limit ?? 5, offset: query.offset ?? 0 } : undefined
    try { return await service.list(Number((request.params as { id: string }).id), pagination) }
    catch (error) { return reply.code(failure(error)).send({ message: (error as Error).message }) }
  })

  app.get("/api/projects/:id/audits/:auditId", { schema: {
    tags: ["Projects"], summary: "Read one audit without loading report artifacts or the project history",
    description: "Returns the audit summary and lifecycle state without report artifacts or project history.",
    params: { ...params, required: ["id", "auditId"] },
    response: { 200: summary, ...errorResponses([400, 404, 422]) },
  } }, async (request, reply) => {
    const { id, auditId } = request.params as { id: string, auditId: string }
    try { return await service.detail(Number(id), Number(auditId)) }
    catch (error) { return reply.code(failure(error)).send({ message: (error as Error).message }) }
  })

  app.get("/api/projects/:id/audits/:auditId/report/sections/:section", { schema: {
    tags: ["Projects"], summary: "Read one stored audit report section without other sections or artifacts",
    description: "Returns a single persisted report section without materializing the remaining sections or artifacts.",
    params: { type: "object", required: ["id", "auditId", "section"], properties: { ...params.properties,
      section: { type: "string", enum: auditReportSections } } },
    response: { 200: objectResponse({ section: { type: "string", enum: auditReportSections }, data: {} }), ...errorResponses([400, 404, 422]) },
  } }, async (request, reply) => {
    const { id, auditId, section } = request.params as { id: string, auditId: string, section: string }
    try { return await service.reportSection(Number(id), Number(auditId), section) }
    catch (error) { return reply.code(failure(error)).send({ message: (error as Error).message }) }
  })

  app.get("/api/projects/:id/audits/:auditId/execution-issues", { schema: {
    tags: ["Projects"], summary: "Read compact audit execution incidents without loading evidence",
    description: "Returns only recorded execution incidents from the project-owned audit, without transferring the evidence inventory or full report annexes.",
    params: { ...params, required: ["id", "auditId"] },
    response: { 200: objectResponse({ execution_issues: { type: "array", items: { type: "object", additionalProperties: true } } }),
      ...errorResponses([400, 404, 422]) },
  } }, async (request, reply) => {
    const { id, auditId } = request.params as { id: string, auditId: string }
    try { return await service.executionIssues(Number(id), Number(auditId)) }
    catch (error) { return reply.code(failure(error)).send({ message: (error as Error).message }) }
  })

  app.get("/api/projects/:id/audits/:auditId/evidence", { schema: {
    tags: ["Projects"], summary: "Read currently published audit evidence without running agents or building reports",
    description: "Returns evidence already published for the audit; it never runs agents or builds reports.",
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
    description: "Reads a text file at the audited commit without mutating the working checkout.",
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
    description: "Returns the immutable audit configuration and its recorded invocation receipts.",
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
    try {
      const reportFile = await service.reportFile(Number(id), Number(auditId))
      if (reportFile !== null) return reply.type("application/json").send(createReadStream(reportFile))
      return await service.report(Number(id), Number(auditId))
    } catch (error) { return reply.code(failure(error)).send({ message: (error as Error).message }) }
  })

  app.get("/api/projects/:id/audits/:auditId/report.docx", { schema: {
    tags: ["Projects"], summary: "Download the original persisted Word audit report", params: { ...params, required: ["id", "auditId"] },
    description: "Downloads the same DOCX produced by agent-server's audit report renderer. Stored bytes remain available after agent-server restarts or is offline. The audit ID must belong to this project.",
    response: { 200: { type: "string", format: "binary" }, ...errorResponses([400, 404, 422]) },
  } }, async (request, reply) => {
    const { id, auditId } = request.params as { id: string, auditId: string }
    try {
      const documentFile = await service.documentFile(Number(id), Number(auditId))
      const content = documentFile === null ? await service.document(Number(id), Number(auditId)) : createReadStream(documentFile)
      return reply.type("application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        .header("Content-Disposition", `attachment; filename="informe-auditoria-${auditId}.docx"`)
        .send(content)
    } catch (error) { return reply.code(failure(error)).send({ message: (error as Error).message }) }
  })

  app.get("/api/projects/:id/audits/:auditId/verification-commits", { schema: {
    tags: ["Projects"], summary: "List strict descendants of the audited baseline on its recorded branch",
    description: "Returns the commits that descend from the audited baseline commit on the audited branch, newest first, excluding the baseline itself. Used to pick a target revision for a verification-suite execution; status codes follow the same rules as the other audit routes.",
    params: { ...params, required: ["id", "auditId"] },
    querystring: { type: "object", properties: { limit: { type: "integer", minimum: 1, maximum: 100, default: 30 }, offset: { type: "integer", minimum: 0, default: 0 } } },
    response: { 200: { type: "object", additionalProperties: true }, ...errorResponses([400, 404, 422]) },
  } }, async (request, reply) => {
    const { id, auditId } = request.params as { id: string, auditId: string }
    const query = request.query as { limit?: number, offset?: number }
    try { return await service.verificationCommits(Number(id), Number(auditId), query.limit, query.offset) }
    catch (error) { return reply.code(failure(error)).send({ message: (error as Error).message }) }
  })

  app.post("/api/projects/:id/audits/:auditId/verification-suite", { schema: {
    tags: ["Projects"], summary: "Start a verification-suite build or validation for an audit", params: { ...params, required: ["id", "auditId"] },
    description: "Starts the verification pipeline in the background against the audited repository (or runs the already-built portable suite for action=execute against a checkout, optionally a green-control path or a single verification group via 'group'). Returns immediately with status=building; poll the GET route for progress.",
    response: { 202: { type: "object", additionalProperties: true }, ...errorResponses([400, 404, 422]) },
  } }, async (request, reply) => {
    const { id, auditId } = request.params as { id: string, auditId: string }
    const rawBody = request.body as { action?: unknown, greenControl?: unknown, targetCommit?: unknown, group?: unknown } | null | undefined
    const body: { action?: "create" | "execute", greenControl?: string, targetCommit?: string, group?: string } = {}
    if (rawBody !== null && rawBody !== undefined) {
      if (typeof rawBody !== "object" || Array.isArray(rawBody)) {
        return reply.code(400).send({ message: "body must be an object" })
      }
      if (rawBody.action !== undefined && rawBody.action !== "create" && rawBody.action !== "execute") {
        return reply.code(400).send({ message: "action must be 'create' or 'execute'" })
      }
      body.action = rawBody.action as "create" | "execute" | undefined
      if (rawBody.greenControl !== undefined && rawBody.greenControl !== null && typeof rawBody.greenControl !== "string") {
        return reply.code(400).send({ message: "greenControl must be a string path" })
      }
      body.greenControl = (rawBody.greenControl ?? undefined) as string | undefined
      if (rawBody.targetCommit !== undefined) {
        if (typeof rawBody.targetCommit !== "string" || !/^[a-f0-9]{40}$/i.test(rawBody.targetCommit) || body.action !== "execute") {
          return reply.code(400).send({ message: "targetCommit must be a full Git hash for action=execute" })
        }
        body.targetCommit = rawBody.targetCommit.toLowerCase()
      }
      if (rawBody.group !== undefined) {
        if (typeof rawBody.group !== "string" || !/^[A-Za-z0-9_-]{1,32}$/.test(rawBody.group)) {
          return reply.code(400).send({ message: "group must be a short identifier matching [A-Za-z0-9_-], 1..32 characters" })
        }
        if (body.action === "create") {
          return reply.code(400).send({ message: "group is only valid for action=execute; use the unified suite's --only flag to run subsets" })
        }
        body.group = rawBody.group.toLowerCase()
      }
    }
    try { return await reply.code(202).send(await service.verificationSuite(Number(id), Number(auditId), body)) }
    catch (error) { return reply.code(failure(error)).send({ message: (error as Error).message }) }
  })

  app.get("/api/projects/:id/audits/:auditId/verification-suite", { schema: {
    tags: ["Projects"], summary: "Read the verification-suite build state for an audit", params: { ...params, required: ["id", "auditId"] },
    description: "Returns building while work runs, recovering when communication is interrupted and the outcome is uncertain, failed for terminal errors, ready with the matching attempt summary, or not_built when no suite exists. Status reads never regenerate a suite. Pass ?group=<name> to read the state of a grouped execute.",
    response: { 200: { type: "object", additionalProperties: true }, ...errorResponses([400, 404, 422]) },
  } }, async (request, reply) => {
    const { id, auditId } = request.params as { id: string, auditId: string }
    const query = (request.query ?? {}) as { action?: "create" | "execute", group?: string }
    if (query.action !== undefined && !["create", "execute"].includes(query.action)) {
      return reply.code(400).send({ message: "action must be 'create' or 'execute'" })
    }
    if (query.group !== undefined && !/^[A-Za-z0-9_-]{1,32}$/.test(query.group)) {
      return reply.code(400).send({ message: "group must be a short identifier matching [A-Za-z0-9_-], 1..32 characters" })
    }
    const group = query.action === "execute" && query.group ? query.group.toLowerCase() : undefined
    try { return await service.verificationSuiteStatus(Number(id), Number(auditId), query.action, group) }
    catch (error) { return reply.code(failure(error)).send({ message: (error as Error).message }) }
  })

  app.get("/api/projects/:id/audits/:auditId/verification-suite.zip", { schema: {
    tags: ["Projects"], summary: "Download the verification-suite ZIP built for an audit", params: { ...params, required: ["id", "auditId"] },
    description: "Downloads the suite ZIP produced by the verification-suite build. Returns 404 when the suite has not been built yet.",
    response: { 200: { type: "string", format: "binary" }, ...errorResponses([400, 404, 422]) },
  } }, async (request, reply) => {
    const { id, auditId } = request.params as { id: string, auditId: string }
    try {
      const zip = await service.verificationSuiteZip(Number(id), Number(auditId))
      if (zip === null) return reply.code(404).send({ message: "Verification suite has not been built yet" })
      return reply.type("application/zip")
        .header("Content-Disposition", `attachment; filename="verification-suite-${auditId}.zip"`)
        .send(zip)
    } catch (error) { return reply.code(failure(error)).send({ message: (error as Error).message }) }
  })
}
