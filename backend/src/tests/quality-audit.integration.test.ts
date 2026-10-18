import { it } from "node:test"
import assert from "node:assert/strict"
import { execSync } from "node:child_process"
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { buildApp } from "../app.js"
import { auditResponseSerialization } from "./helpers/responseSerializationAudit.js"
import type { AgentInput, PipelineInput } from "../infrastructure/agent-server-client/agent-server.client.js"
import { MAINTAINABILITY_AUDIT_AGENTS } from "../modules/agent-settings/agent-types.js"

for (const attribute of ["maintainability", "security"]) {
it(`runs a ${attribute} audit and persists its original partial report and Word artifact independently of architecture`, async () => {
  const agentType = attribute === "security" ? "security" : "maintainability_manager"
  const agents = attribute === "security" ? ["security"] : [...MAINTAINABILITY_AUDIT_AGENTS]
  const dir = mkdtempSync(join(tmpdir(), "veraud-quality-"))
  const databaseUrl = `file:${join(dir, "test.db")}`
  execSync("pnpm prisma migrate deploy", {
    cwd: fileURLToPath(new URL("../../", import.meta.url)), env: { ...process.env, DATABASE_URL: databaseUrl }, stdio: "ignore",
  })
  const workspaceDir = join(dir, "workspace")
  mkdirSync(join(workspaceDir, "555-acme-shop"), { recursive: true })
  writeFileSync(join(workspaceDir, "555-acme-shop", "main.ts"), "export const value = 1")
  let finish!: (result: Record<string, AgentInput>) => void
  const pending = new Promise<Record<string, AgentInput>>((resolve) => { finish = resolve })
  let seen: PipelineInput | undefined
  const options = { databaseUrl, workspaceDir, silent: true, makeModelAccessVerifier: () => ({ verify: async () => {} }) }
  const { app, db } = await buildApp({ ...options, makeAgentInvoker: () => ({
    run: async () => ({}), runPipelineByName: async (name, input, ids, configs) => {
      assert.equal(name, "quality-audit")
       assert.ok(ids[agentType])
       assert.equal(configs[agentType]?.api_key, "secret-test-key")
       assert.deepEqual(Object.keys(configs).sort(), agents.sort())
       for (const participant of agents) {
         assert.deepEqual(configs[participant], configs[agentType],
           `${participant} must receive the common model and credential explicitly`)
      }
      seen = input
      return pending
    },
  }) })
  auditResponseSerialization(app)
  const hash = "a".repeat(40)
  const report = { schema_version: "1.0", identification: { status: "partial", audit_id: "audit-123" }, executive_summary: { conclusion: "Cobertura pendiente" } }
  const word = Buffer.from("PK-original-word-artifact")
  let executionId: number
  let projectId: number
  try {
    const project = await db.project.create({ data: { githubRepositoryId: 555n, repositoryOwner: "acme", repositoryName: "shop", status: "READY" } })
    projectId = project.id
    const version = await db.projectVersion.create({ data: { projectId, branch: "main", commitHash: hash, analysisStatus: "Completed" } })
    const architecture = await db.evaluation.create({ data: { projectVersionId: version.id, type: "Analysis" } })
    const url = `/api/projects/${projectId}/audits`
    const body = { branch: "main", commitHash: hash, attributes: [attribute] }
    assert.equal((await app.inject({ method: "POST", url, payload: { ...body, attributes: ["unsupported"] } })).statusCode, 400)
    assert.equal((await app.inject({ method: "POST", url, payload: body })).statusCode, 422)
    assert.equal(await db.evaluation.count(), 1, "invalid configurations create no audit rows")
    const provider = await db.aiProvider.create({ data: { name: "test" } })
    const model = await db.aiModel.create({ data: { name: "test-model", aiProviderId: provider.id } })
    const credential = await db.aiCredential.create({ data: { name: "test-key", apiKey: "secret-test-key", aiProviderId: provider.id } })
    await db.agentSettings.update({ where: { agentType }, data: { aiModelId: model.id, aiCredentialId: credential.id } })
    const opened = await app.inject({ method: "POST", url, payload: body })
    assert.equal(opened.statusCode, 202, opened.body)
    executionId = opened.json().executionId
    assert.equal((await app.inject({ method: "POST", url, payload: body })).statusCode, 422)
    for (let i = 0; !seen && i < 100; i++) await new Promise((resolve) => setTimeout(resolve, 10))
    assert.deepEqual(seen?.attributes, [attribute])
    assert.equal(seen?.commit_hash, hash)
    const waiting = await app.inject({ url })
    assert.equal(waiting.json()[0].reportAvailable, false)
    assert.equal(waiting.json()[0].runId, null)
    assert.equal((await app.inject({ url: `${url}/${executionId}/report.docx` })).statusCode, 422)
    // The agent-server reports the audit id as soon as it creates it, while the audit still runs.
    const started = await app.inject({ method: "POST", url: `/api/agent-executions/${executionId}/running`,
      payload: { runId: "b".repeat(32) } })
    assert.equal(started.statusCode, 200)
    assert.equal((await app.inject({ url })).json()[0].runId, "b".repeat(32))
    assert.equal((await app.inject({ method: "POST", url: `/api/agent-executions/${executionId}/running`,
      payload: { runId: "not-a-run-id" } })).statusCode, 400)
    finish({ audit: { attributes: [attribute], status: "partial", run_id: "audit-123", report,
      blackboard: { evidence: [{ id: "source-1", commit: hash }] }, docx_base64: word.toString("base64") } })
    for (let i = 0; i < 100; i++) {
      if ((await db.agentExecution.findUniqueOrThrow({ where: { id: executionId } })).status === "Completed") break
      await new Promise((resolve) => setTimeout(resolve, 10))
    }
    const rows = (await app.inject({ url })).json()
    assert.equal(rows[0].auditStatus, "partial")
    assert.equal(rows[0].reportAvailable, true)
    assert.equal(rows[0].runId, "audit-123", "the delivered envelope remains the stored run id")
    assert.equal(JSON.stringify(rows).includes("secret-test-key"), false)
    const versions = (await app.inject({ url: `/api/projects/${projectId}/versions` })).json()
    assert.equal(versions[0].evaluationId, architecture.id, "audits do not replace architecture history")
  } finally { await app.close(); await db.$disconnect() }

  // Restart without any agent-server connection: both artifacts remain available.
  const restarted = await buildApp(options)
  try {
    const url = `/api/projects/${projectId}/audits/${executionId}`
    const restored = await restarted.app.inject({ url: `${url}/report` })
    assert.equal(restored.statusCode, 200)
    assert.deepEqual(restored.json(), report)
    const download = await restarted.app.inject({ url: `${url}/report.docx` })
    assert.equal(download.statusCode, 200)
    assert.deepEqual(download.rawPayload, word)
    assert.match(download.headers["content-disposition"] as string, /attachment/)
    assert.equal((await restarted.app.inject({ url: `/api/projects/999/audits/${executionId}/report` })).statusCode, 404)
  } finally { await restarted.app.close(); await restarted.db.$disconnect() }
})
}
