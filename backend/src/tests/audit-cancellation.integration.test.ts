import { test } from "node:test"
import assert from "node:assert/strict"
import { execSync } from "node:child_process"
import { mkdtempSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { buildApp } from "../app.js"
import { makeQualityAuditCatalogSource } from "./helpers/agentCatalog.js"
import { auditResponseSerialization } from "./helpers/responseSerializationAudit.js"
import { AgentExecutionRepository } from "../modules/agent-execution/agent-execution.repository.js"
import { AgentSettingsRepository } from "../modules/agent-settings/agent-settings.repository.js"
import type { AgentInvoker } from "../infrastructure/agent-server-client/agent-server.client.js"

async function setup(invoker: AgentInvoker) {
  const directory = mkdtempSync(join(tmpdir(), "veraud-cancel-"))
  const databaseUrl = `file:${join(directory, "test.db")}`
  execSync("pnpm prisma migrate deploy", {
    cwd: fileURLToPath(new URL("../../", import.meta.url)), env: { ...process.env, DATABASE_URL: databaseUrl }, stdio: "ignore",
  })
  const options = { databaseUrl, workspaceDir: join(directory, "workspace"), silent: true,
    makeAgentCatalogSource: makeQualityAuditCatalogSource, makeAgentInvoker: () => invoker }
  const { app, db } = await buildApp(options)
  auditResponseSerialization(app)
  const project = await db.project.create({ data: { githubRepositoryId: 123n, repositoryOwner: "acme", repositoryName: "demo", status: "READY" } })
  const version = await db.projectVersion.create({ data: { projectId: project.id, branch: "main", commitHash: "a".repeat(40), analysisStatus: "Completed" } })
  const evaluation = await db.evaluation.create({ data: { projectVersionId: version.id, type: "QualityAudit" } })
  await db.agentSettings.upsert({ where: { agentType: "security" }, create: { agentType: "security" }, update: {} })
  const execution = await db.agentExecution.create({ data: { evaluationId: evaluation.id, agentType: "security", status: "Running",
    startedAt: new Date(), dispatchStartedAt: new Date(), inputTokens: 123, outputTokens: 45,
    result: JSON.stringify({ run_id: "b".repeat(32), attributes: ["security"] }) } })
  return { app, db, options, project, evaluation, execution, url: `/api/projects/${project.id}/audits/${execution.id}/cancel` }
}

test("project cancellation validates ownership, persists one request and broadcasts without claiming termination", async () => {
  let sends = 0
  const h = await setup({ run: async () => ({}), cancelAudit: async (runId) => { sends++; return { run_id: runId, status: "cancelling" } },
    getAuditSnapshot: async (runId) => ({ run_id: runId, status: "cancelling" }) })
  try {
    await h.app.ready()
    const socket = await h.app.injectWS("/ws")
    const messages: string[] = []
    socket.on("message", (message) => messages.push(String(message)))
    try {
      assert.equal((await h.app.inject({ method: "POST", url: h.url.replace(`/projects/${h.project.id}/`, "/projects/99999/") })).statusCode, 404)
      assert.equal(sends, 0)
      const response = await h.app.inject({ method: "POST", url: h.url })
      assert.equal(response.statusCode, 202)
      assert.equal(response.json().auditStatus, "cancelling")
      const requested = response.json().cancellationRequestedAt
      assert.ok(requested)
      const repeated = await h.app.inject({ method: "POST", url: h.url })
      assert.equal(repeated.json().cancellationRequestedAt, requested)
      for (let attempt = 0; !messages.length && attempt < 20; attempt++) await new Promise((resolve) => setTimeout(resolve, 10))
      const event = JSON.parse(messages[0]!)
      assert.equal(event.type, "agent-execution.updated")
      assert.equal(event.execution.status, "Running")
      assert.equal(event.execution.cancellationRequestedAt, requested)
      assert.equal(event.execution.interruptionReason, "cancellation_requested")
      assert.equal(event.execution.result, null)
      const stored = await h.db.agentExecution.findUniqueOrThrow({ where: { id: h.execution.id } })
      assert.equal(stored.status, "Running")
      assert.equal(stored.finishedAt, null)
      assert.equal(stored.inputTokens, 123)
      assert.equal(sends, 1)
    } finally { socket.terminate() }
  } finally { await h.app.close(); await h.db.$disconnect() }
})

test("persisted requests resume after restart and finish only after agent-server confirms cancellation", async () => {
  let state = "cancelling"
  let sends = 0
  const h = await setup({ run: async () => ({}), cancelAudit: async (runId) => { sends++; return { run_id: runId, status: "cancelling" } },
    getAuditSnapshot: async (runId) => ({ run_id: runId, status: state, evidence: [{ id: "retained" }] }) })
  await h.app.inject({ method: "POST", url: h.url })
  await h.app.close()
  await h.db.$disconnect()
  state = "cancelled"
  const restarted = await buildApp(h.options)
  try {
    await restarted.app.ready()
    let stored = await restarted.db.agentExecution.findUniqueOrThrow({ where: { id: h.execution.id } })
    for (let attempt = 0; stored.status !== "Completed" && attempt < 100; attempt++) {
      await new Promise((resolve) => setTimeout(resolve, 10))
      stored = await restarted.db.agentExecution.findUniqueOrThrow({ where: { id: h.execution.id } })
    }
    assert.equal(stored.status, "Completed")
    assert.equal(stored.interruptionReason, "cancelled")
    assert.equal(stored.inputTokens, 123)
    assert.deepEqual(JSON.parse(stored.result!).blackboard.evidence, [{ id: "retained" }])
    assert.ok(sends >= 1)
  } finally { await restarted.app.close(); await restarted.db.$disconnect() }
})

test("persistent dispatch admission cannot win after cancellation and terminal runs remain unchanged", async () => {
  const h = await setup({ run: async () => ({}) })
  try {
    const repository = new AgentExecutionRepository(h.db, new AgentSettingsRepository(h.db))
    const queued = await h.db.agentExecution.create({ data: { evaluationId: h.evaluation.id, agentType: "security", status: "Waiting" } })
    const requested = await repository.requestAuditCancellation(queued.id)
    assert.ok(requested.cancellationRequestedAt)
    assert.equal(await repository.claimAuditDispatch(queued.id), false)
    assert.ok((await repository.pendingAuditCancellations()).includes(queued.id))
    const finished = await h.db.agentExecution.create({ data: { evaluationId: h.evaluation.id, agentType: "security", status: "Completed",
      result: '{"status":"completed","report":{"original":true}}', finishedAt: new Date() } })
    const response = await h.app.inject({ method: "POST", url: `/api/projects/${h.project.id}/audits/${finished.id}/cancel` })
    assert.equal(response.statusCode, 202)
    const unchanged = await h.db.agentExecution.findUniqueOrThrow({ where: { id: finished.id } })
    assert.equal(unchanged.cancellationRequestedAt, null)
    assert.equal(unchanged.result, finished.result)
  } finally { await h.app.close(); await h.db.$disconnect() }
})

test("a persisted request without run_id is delivered after a late running callback, including after restart", async () => {
  let sends = 0
  const h = await setup({ run: async () => ({}), cancelAudit: async (runId) => {
    sends++
    return { run_id: runId, status: "cancelling" }
  }, getAuditSnapshot: async (runId) => ({ run_id: runId, status: "cancelled" }) })
  await h.db.agentExecution.update({ where: { id: h.execution.id }, data: { result: '{"attributes":["security"]}' } })
  const requested = await h.app.inject({ method: "POST", url: h.url })
  assert.equal(requested.statusCode, 202)
  assert.equal(sends, 0)
  await h.app.close()
  await h.db.$disconnect()
  const restarted = await buildApp(h.options)
  try {
    await restarted.app.ready()
    assert.equal(sends, 0)
    const callback = await restarted.app.inject({ method: "POST", url: `/api/agent-executions/${h.execution.id}/running`, payload: { runId: "b".repeat(32) } })
    assert.equal(callback.statusCode, 200)
    let stored = await restarted.db.agentExecution.findUniqueOrThrow({ where: { id: h.execution.id } })
    for (let attempt = 0; stored.status !== "Completed" && attempt < 250; attempt++) {
      await new Promise((resolve) => setTimeout(resolve, 10))
      stored = await restarted.db.agentExecution.findUniqueOrThrow({ where: { id: h.execution.id } })
    }
    assert.equal(sends, 1)
    assert.equal(stored.interruptionReason, "cancelled")
    assert.equal(stored.cancellationRequestedAt!.toISOString(), requested.json().cancellationRequestedAt)
    assert.equal(JSON.parse(stored.result!).run_id, "b".repeat(32))
  } finally { await restarted.app.close(); await restarted.db.$disconnect() }
})
