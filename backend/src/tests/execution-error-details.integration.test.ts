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
import type { ExecutionErrorDetail } from "../modules/agent-execution/execution-error-detail.js"

const detail: ExecutionErrorDetail = { agentId: "investigator", invocationId: "child",
  occurredAt: "2026-10-30T12:01:00.000Z", code: "execution_timeout", exceptionType: "TimeoutError",
  message: "The investigator exceeded its execution deadline." }

async function setup() {
  const base = process.platform === "win32" && process.env.LOCALAPPDATA
    ? join(process.env.LOCALAPPDATA, "Temp", "opencode") : tmpdir()
  const directory = mkdtempSync(join(base, "veraud-errors-"))
  const databaseUrl = `file:${join(directory, "test.db")}`
  execSync("pnpm prisma migrate deploy", { cwd: fileURLToPath(new URL("../../", import.meta.url)),
    env: { ...process.env, DATABASE_URL: databaseUrl }, stdio: "ignore" })
  const options = { databaseUrl, workspaceDir: join(directory, "workspace"), silent: true,
    makeAgentCatalogSource: makeQualityAuditCatalogSource, makeAgentInvoker: () => ({ run: async () => ({}) }) }
  const { app, db } = await buildApp(options)
  auditResponseSerialization(app)
  const project = await db.project.create({ data: { githubRepositoryId: 456n, repositoryOwner: "acme", repositoryName: "errors", status: "READY" } })
  const version = await db.projectVersion.create({ data: { projectId: project.id, branch: "main", commitHash: "a".repeat(40), analysisStatus: "Completed" } })
  const evaluation = await db.evaluation.create({ data: { projectVersionId: version.id, type: "QualityAudit" } })
  await db.agentSettings.upsert({ where: { agentType: "security" }, create: { agentType: "security" }, update: {} })
  const create = () => db.agentExecution.create({ data: { evaluationId: evaluation.id, agentType: "security", status: "Running",
    result: JSON.stringify({ run_id: "b".repeat(32), attributes: ["security"] }), inputTokens: 12, outputTokens: 3 } })
  return { app, db, options, project, create }
}

test("structured errors survive callbacks, projections, stale updates and database reconnection", async (t) => {
  const h = await setup()
  let retainedId = 0
  let retainedChildId = 0
  try {
    await t.test("root completion preserves source attribution across HTTP, WebSocket and audit summaries", async () => {
      const row = await h.create()
      retainedId = row.id
      await h.app.ready()
      const socket = await h.app.injectWS("/ws")
      const messages: string[] = []
      socket.on("message", (message) => messages.push(String(message)))
      try {
        const result = JSON.stringify({ status: "failed", run_id: "b".repeat(32), attributes: ["security"],
          report: { quality_results: {}, annexes_and_traceability: {} }, blackboard: { private: "source inventory" }, docx_base64: "binary" })
        const response = await h.app.inject({ method: "POST", url: `/api/agent-executions/${row.id}/completion`,
          payload: { status: "Completed", result, errorDetail: detail } })
        assert.equal(response.statusCode, 200, response.body)
        assert.deepEqual(response.json().errorDetail, detail)
        for (let attempt = 0; !messages.length && attempt < 30; attempt++) await new Promise((resolve) => setTimeout(resolve, 10))
        assert.deepEqual(JSON.parse(messages[0]!).execution.errorDetail, detail)
        const monitor = await h.app.inject(`/api/agent-executions/${row.id}?monitor=true`)
        assert.deepEqual(monitor.json().errorDetail, detail)
        assert.doesNotMatch(monitor.json().result, /source inventory|binary|blackboard/)
        const summary = await h.app.inject(`/api/projects/${h.project.id}/audits/${row.id}`)
        assert.deepEqual(summary.json().errorDetail, detail)
        const history = await h.app.inject(`/api/projects/${h.project.id}/audits`)
        assert.deepEqual(history.json().find((item: { id: number }) => item.id === row.id).errorDetail, detail)
        const repeated = await h.app.inject({ method: "POST", url: `/api/agent-executions/${row.id}/completion`,
          payload: { status: "Failed", error: "late", errorDetail: { ...detail, occurredAt: "2026-10-30T13:00:00Z", message: "replacement" } } })
        assert.deepEqual(repeated.json().errorDetail, detail)
        const stored = await h.db.agentExecution.findUniqueOrThrow({ where: { id: row.id } })
        assert.equal(stored.status, "Completed")
        assert.equal(stored.inputTokens, 12)
        assert.equal(stored.outputTokens, 3)
      } finally { socket.terminate() }
    })

    await t.test("child incidents persist under the root and terminal callbacks cannot replace or erase them", async () => {
      const row = await h.create()
      retainedChildId = row.id
      const receipt = { invocation_id: "parent", parent_invocation_id: null, agent_id: "security", run_id: "b".repeat(32),
        status: "partial", started_at: "2026-10-30T12:00:00Z", finished_at: "2026-10-30T12:02:00Z",
        input_tokens: 9, output_tokens: 2, error: detail.message, error_detail: detail }
      const url = `/api/agent-executions/${row.id}/invocations`
      const response = await h.app.inject({ method: "POST", url, payload: receipt })
      assert.equal(response.statusCode, 200, response.body)
      assert.deepEqual(response.json().invocations[0].error_detail, detail)
      const late = await h.app.inject({ method: "POST", url, payload: { ...receipt, status: "running", finished_at: null, error_detail: null } })
      assert.equal(late.json().invocations[0].status, "partial")
      assert.deepEqual(late.json().invocations[0].error_detail, detail)
      const changed = await h.app.inject({ method: "POST", url, payload: { ...receipt, error_detail: { ...detail, message: "changed" } } })
      assert.deepEqual(changed.json().invocations[0].error_detail, detail)
      const repository = new AgentExecutionRepository(h.db, new AgentSettingsRepository(h.db))
      assert.deepEqual((await repository.findById(row.id))!.invocations![0]!.error_detail, detail)
    })

    await t.test("legacy failures retain only known data and malformed metadata is rejected", async () => {
      const row = await h.create()
      const url = `/api/agent-executions/${row.id}/completion`
      for (const errorDetail of [{ ...detail, occurredAt: "not-a-date" }, { ...detail, code: "" }, { ...detail, message: "x".repeat(2001) }]) {
        const invalid = await h.app.inject({ method: "POST", url, payload: { status: "Failed", error: "legacy", errorDetail } })
        assert.equal(invalid.statusCode, 400)
      }
      const response = await h.app.inject({ method: "POST", url, payload: { status: "Failed", error: "legacy" } })
      assert.equal(response.statusCode, 200)
      assert.equal(response.json().errorDetail, null)
      assert.equal(response.json().error, "legacy")
      const stored = await h.db.agentExecution.findUniqueOrThrow({ where: { id: row.id } })
      assert.equal(stored.errorDetail, null)
    })
  } finally { await h.app.close(); await h.db.$disconnect() }
  const restarted = await buildApp(h.options)
  try {
    const response = await restarted.app.inject(`/api/agent-executions/${retainedId}?monitor=true`)
    assert.deepEqual(response.json().errorDetail, detail)
    const childResponse = await restarted.app.inject(`/api/agent-executions/${retainedChildId}?monitor=true`)
    assert.deepEqual(childResponse.json().invocations[0].error_detail, detail)
  } finally { await restarted.app.close(); await restarted.db.$disconnect() }
})
