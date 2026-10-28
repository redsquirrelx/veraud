import { it } from "node:test"
import assert from "node:assert/strict"
import Fastify from "fastify"
import { QualityAuditService, AuditNotFoundError, AuditEvidenceUnavailableError } from "./quality-audit.service.js"
import { registerQualityAuditRoutes } from "./quality-audit.controller.js"
import { AuditRunUnavailableError } from "../../infrastructure/agent-server-client/agent-server.client.js"
import type { QualityAuditRepository } from "./quality-audit.repository.js"
import type { ProjectService } from "../project/project.service.js"
import type { AgentExecutionService } from "../agent-execution/agent-execution.service.js"

function fixture() {
  const runId = "a".repeat(32)
  const context = { row: { status: "Running" }, projection: { runId: runId as string | null, reportType: null as string | null } }
  const receipt = { invocation_id: "inv-1", agent_id: "responsibility", run_id: runId }
  const item = { id: "E-1", run_id: runId, agent_id: "responsibility", invocation_id: "inv-1", source: "src/a.ts",
    kind: "source", content: "const a = 1", details: { private: "secret" } }
  let snapshotCalls = 0
  let snapshot: Record<string, unknown> = { run_id: runId, status: "running", evidence: [item, { ...item, id: "foreign", run_id: "other" }],
    findings: [{ private: "secret" }], assessments: [{ private: "secret" }] }
  let remoteError: Error | null = null
  const repository = {
    findSummary: async (project: number, id: number) => project === 2 && id === 41 ? context : null,
    findConfiguration: async () => ({ invocationReceipts: JSON.stringify([receipt]) }),
    findReportSection: async () => ({ reportType: "object", data: JSON.stringify({ evidence_inventory: [{ id: "stored" }], executions: [] }) }),
  } as unknown as QualityAuditRepository
  const service = new QualityAuditService(repository, {} as ProjectService, {} as AgentExecutionService, undefined, {
    getAuditSnapshot: async (id) => {
      snapshotCalls++
      assert.equal(id, runId)
      if (remoteError) throw remoteError
      return snapshot
    },
  })
  return { service, context, setSnapshot: (value: Record<string, unknown>) => { snapshot = value },
    setError: (error: Error) => { remoteError = error }, calls: () => snapshotCalls }
}

it("reads published evidence while running with provenance and no private Blackboard details", async () => {
  const f = fixture()
  const result = await f.service.evidence(2, 41)
  assert.equal(result.partial, true)
  assert.equal(result.available, true)
  assert.match(JSON.stringify(result), /E-1|inv-1|const a = 1/)
  assert.doesNotMatch(JSON.stringify(result), /secret|findings|assessments|foreign|details/)
  assert.equal(f.calls(), 1)
})

it("checks project scope before querying agent-server", async () => {
  const f = fixture()
  await assert.rejects(f.service.evidence(3, 41), AuditNotFoundError)
  assert.equal(f.calls(), 0)
})

it("can resolve the live run from recorded invocation receipts before a result is stored", async () => {
  const f = fixture()
  f.context.projection.runId = null
  assert.equal((await f.service.evidence(2, 41)).available, true)
  assert.equal(f.calls(), 1)
})

it("uses the original persisted report after completion even if agent-server is unavailable", async () => {
  const f = fixture()
  f.context.row.status = "Completed"
  f.context.projection.reportType = "object"
  f.setError(new Error("offline"))
  const result = await f.service.evidence(2, 41)
  assert.equal(result.partial, false)
  assert.match(JSON.stringify(result), /stored/)
  assert.equal(f.calls(), 0)
})

it("distinguishes an empty published inventory from an unavailable live run", async () => {
  const f = fixture()
  f.setSnapshot({ run_id: "a".repeat(32), evidence: [] })
  assert.equal((await f.service.evidence(2, 41)).available, true)
  f.setError(new AuditRunUnavailableError("lost run"))
  assert.deepEqual(await f.service.evidence(2, 41), { partial: true, available: false, data: null })
})

it("fails safely on upstream errors and mismatched snapshot identity", async () => {
  const f = fixture()
  f.setSnapshot({ run_id: "other", evidence: [] })
  await assert.rejects(f.service.evidence(2, 41), AuditEvidenceUnavailableError)
  f.setError(new Error("private-upstream-body"))
  await assert.rejects(f.service.evidence(2, 41), (error: unknown) => {
    assert.ok(error instanceof AuditEvidenceUnavailableError)
    assert.doesNotMatch(error.message, /private/)
    return true
  })
})

it("exposes a scoped no-store endpoint with partial data and explicit upstream failure", async () => {
  const f = fixture()
  const app = Fastify()
  for (const $id of ["MessageError", "ValidationError"]) app.addSchema({ $id, type: "object", properties: { message: { type: "string" } } })
  registerQualityAuditRoutes(app, f.service)
  try {
    const response = await app.inject("/api/projects/2/audits/41/evidence")
    assert.equal(response.statusCode, 200)
    assert.equal(response.headers["cache-control"], "no-store")
    assert.equal(response.json().partial, true)
    assert.match(response.body, /E-1/)
    assert.equal((await app.inject("/api/projects/3/audits/41/evidence")).statusCode, 404)
    f.setError(new Error("offline"))
    assert.equal((await app.inject("/api/projects/2/audits/41/evidence")).statusCode, 503)
  } finally { await app.close() }
})
