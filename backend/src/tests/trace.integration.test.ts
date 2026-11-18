import { it } from "node:test"
import assert from "node:assert/strict"
import { execSync } from "node:child_process"
import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { buildApp } from "../app.js"
import { makeQualityAuditCatalogSource } from "./helpers/agentCatalog.js"
import type { AgentInvoker, AgentInput, PipelineInput } from "../infrastructure/agent-server-client/agent-server.client.js"

/** End-to-end trace integration: a real audit dispatched through the real app must produce a
 *  parseable NDJSON trace on disk (workspaceDir/logs) with the audit lifecycle events, and must
 *  not produce one when VERAUD_TRACE_ENABLED=0. The agent-server boundary is stubbed; all other
 *  components (routes, database, trace writer) are real. */
const hash = "a".repeat(40)
const runId = "d".repeat(32)

async function bootAndRunFunctionalAudit(workspaceDir: string, databaseUrl: string, envDisable: boolean) {
  type AuditPayload = Record<string, AgentInput>
  let resolveAudit: (value: AuditPayload) => void = () => {}
  const pending = new Promise<AuditPayload>((resolve) => { resolveAudit = resolve })
  const invoker: AgentInvoker = {
    run: async () => ({}),
    runPipelineByName: async (_name: string, _input: PipelineInput) => pending,
    getAuditResult: async () => (await pending)["audit"] ?? null,
  }
  const previous = { enabled: process.env.VERAUD_TRACE_ENABLED, traceDir: process.env.VERAUD_TRACE_DIR }
  delete process.env.VERAUD_TRACE_DIR
  if (envDisable) process.env.VERAUD_TRACE_ENABLED = "0"
  else delete process.env.VERAUD_TRACE_ENABLED
  const { app, db } = await buildApp({ databaseUrl, workspaceDir, silent: true,
    makeAgentCatalogSource: makeQualityAuditCatalogSource, makeAgentInvoker: () => invoker,
    makeModelAccessVerifier: () => ({ verify: async () => {} }) })
  try {
    const project = await db.project.create({ data: { githubRepositoryId: 555n, repositoryOwner: "acme", repositoryName: "shop", status: "READY" } })
    const provider = await db.aiProvider.create({ data: { name: "test-openai" } })
    const model = await db.aiModel.create({ data: { name: "audit-model", aiProviderId: provider.id } })
    const credential = await db.aiCredential.create({ data: { name: "audit-key", apiKey: "audit-test-secret", aiProviderId: provider.id } })
    await db.agentSettings.update({ where: { agentType: "functional_adequacy" }, data: { aiModelId: model.id, aiCredentialId: credential.id } })
    const opened = await app.inject({ method: "POST", url: `/api/projects/${project.id}/audits`, payload: {
      branch: "main", commitHash: hash, attributes: ["functional_adequacy"],
      functional_requirements: [{ requirement_id: "REQ-001", description: "List items." }],
    } })
    assert.equal(opened.statusCode, 202, opened.body)
    const executionId = opened.json().executionId as number
    resolveAudit({ audit: { attributes: ["functional_adequacy"], status: "completed", run_id: runId,
      report: { identification: { audit_id: runId } }, docx_base64: Buffer.from("PK").toString("base64") } as AgentInput })
    for (let attempt = 0; attempt < 200; attempt++) {
      if ((await db.agentExecution.findUniqueOrThrow({ where: { id: executionId } })).status === "Completed") break
      await new Promise((resolve) => setTimeout(resolve, 10))
    }
    return { app, db, executionId, projectId: project.id }
  } finally {
    process.env.VERAUD_TRACE_ENABLED = previous.enabled
    process.env.VERAUD_TRACE_DIR = previous.traceDir
  }
}

function preparation() {
  const dir = mkdtempSync(join(tmpdir(), "veraud-trace-it-"))
  const databaseUrl = `file:${join(dir, "test.db")}`
  execSync("pnpm prisma migrate deploy", {
    cwd: fileURLToPath(new URL("../../", import.meta.url)), env: { ...process.env, DATABASE_URL: databaseUrl }, stdio: "ignore",
  })
  const workspaceDir = join(dir, "workspace")
  mkdirSync(join(workspaceDir, "555-acme-shop"), { recursive: true })
  writeFileSync(join(workspaceDir, "555-acme-shop", "main.ts"), "export const value = 1")
  return { dir, databaseUrl, workspaceDir }
}

it("writes a parseable NDJSON trace for the audit lifecycle with schema-valid envelopes", async () => {
  const { databaseUrl, workspaceDir } = preparation()
  const { app, db, executionId } = await bootAndRunFunctionalAudit(workspaceDir, databaseUrl, false)
  try {
    assert.equal((await db.agentExecution.findUniqueOrThrow({ where: { id: executionId } })).status, "Completed")
    const logs = join(workspaceDir, "logs")
    assert.ok(existsSync(logs), "workspaceDir/logs is created")
    const traceDirs = readdirSync(logs, { withFileTypes: true }).filter((entry) => entry.isDirectory())
    const match = traceDirs.find((entry) => entry.name.endsWith(`-functional_adequacy-exec-${executionId}`))
    assert.ok(match, `trace directory for execution ${executionId} exists`)
    const ndjson = readFileSync(join(logs, match.name, "trace.ndjson"), "utf8")
    const envelopes = ndjson.trim().split("\n").map((line) => JSON.parse(line) as Record<string, unknown>)
    assert.ok(envelopes.length >= 3, "several lifecycle events were traced")
    for (const envelope of envelopes) {
      assert.equal(envelope["version"], 1)
      assert.equal(envelope["executionId"], executionId)
      assert.equal(envelope["agentType"], "functional_adequacy")
      assert.equal(envelope["service"], "backend")
      assert.equal(typeof envelope["traceId"], "string")
      assert.match(envelope["traceId"] as string, /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/)
      assert.ok(!Number.isNaN(Date.parse(envelope["at"] as string)), "at is an ISO timestamp")
    }
    const events = envelopes.map((entry) => entry["event"])
    assert.ok(events.includes("quality_audit.execution.opened"), `expected audit lifecycle events; got ${JSON.stringify(events)}`)
    assert.ok(events.includes("quality_audit.dispatch.sent"))
    assert.ok(events.includes("quality_audit.dispatch.response") || events.includes("quality_audit.audit.closed"))
    assert.ok(existsSync(join(logs, match.name, "backend.log")))
    assert.doesNotMatch(ndjson, /sk-|api_key|credential|password|secret/i, "no secret-looking content in the trace")
  } finally {
    await app.close()
    await db.$disconnect()
  }
})

it("VERAUD_TRACE_ENABLED=0 disables trace writes without breaking the audit", async () => {
  const { databaseUrl, workspaceDir } = preparation()
  const { app, db, executionId } = await bootAndRunFunctionalAudit(workspaceDir, databaseUrl, true)
  try {
    assert.equal((await db.agentExecution.findUniqueOrThrow({ where: { id: executionId } })).status, "Completed")
    const logs = join(workspaceDir, "logs")
    const created = existsSync(logs) ? readdirSync(logs).filter((entry) => entry.includes(`exec-${executionId}`)) : []
    assert.equal(created.length, 0, "no trace directory is created when tracing is disabled")
  } finally {
    await app.close()
    await db.$disconnect()
  }
})
