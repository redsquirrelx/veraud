import { it } from "node:test"
import assert from "node:assert/strict"
import Fastify from "fastify"
import { QualityAuditService, AuditNotFoundError } from "./quality-audit.service.js"
import { registerQualityAuditRoutes } from "./quality-audit.controller.js"
import type { QualityAuditRepository } from "./quality-audit.repository.js"
import { ProjectFileError, type ProjectService } from "../project/project.service.js"
import type { AgentExecutionService } from "../agent-execution/agent-execution.service.js"

it("scopes historical reads to the audit and immutable configuration, and rejects client-supplied revisions", async () => {
  const commit = "a".repeat(40)
  const calls: unknown[][] = []
  let fail = false
  const repository = { findSummary: async (projectId: number, auditId: number) => projectId === 2 && auditId === 41 ? {
    row: { id: 41, evaluation: { projectVersion: { branch: "later", commitHash: "b".repeat(40) } },
      configurationSnapshot: JSON.stringify({ auditConfiguration: { version: 1, branch: "audited", commitHash: commit, attributes: [] } }) },
    projection: { runId: null, auditStatus: null, attributes: null, reportType: null },
  } : null } as unknown as QualityAuditRepository
  const service = new QualityAuditService(repository, { readFileAtCommit: async (...args: unknown[]) => {
    calls.push(args)
    if (fail) throw new ProjectFileError("History unavailable")
    return { path: "src/service.ts", content: "audited content", size: 15, commitHash: commit }
  } } as unknown as ProjectService, {} as AgentExecutionService)
  await assert.rejects(service.file(3, 41, "src/service.ts"), AuditNotFoundError)
  assert.equal(calls.length, 0)
  const app = Fastify({ ajv: { customOptions: { removeAdditional: false } } })
  for (const $id of ["MessageError", "ValidationError"]) app.addSchema({ $id, type: "object", properties: { message: { type: "string" } } })
  registerQualityAuditRoutes(app, service)
  try {
    const response = await app.inject({ method: "POST", url: "/api/projects/2/audits/41/file", payload: { path: "src/service.ts" } })
    assert.equal(response.statusCode, 200)
    assert.equal(response.headers["cache-control"], "no-store")
    assert.equal(response.json().commitHash, commit)
    assert.deepEqual(calls[0], [2, "src/service.ts", commit])
    assert.equal((await app.inject({ method: "POST", url: "/api/projects/3/audits/41/file", payload: { path: "src/service.ts" } })).statusCode, 404)
    assert.equal((await app.inject({ method: "POST", url: "/api/projects/2/audits/41/file", payload: { path: "src/service.ts", commitHash: "b".repeat(40) } })).statusCode, 400)
    fail = true
    assert.equal((await app.inject({ method: "POST", url: "/api/projects/2/audits/41/file", payload: { path: "src/service.ts" } })).statusCode, 422)
  } finally { await app.close() }
})
