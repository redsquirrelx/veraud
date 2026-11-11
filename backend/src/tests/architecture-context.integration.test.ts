import { afterEach, describe, it } from "node:test"
import assert from "node:assert/strict"
import { execSync } from "node:child_process"
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { buildApp } from "../app.js"
import { testAgentCatalog } from "./helpers/agentCatalog.js"
import type { AgentInput } from "../infrastructure/agent-server-client/agent-server.client.js"

const commit = "a".repeat(40)
function result(status = "partial", hash = commit) {
  return JSON.stringify({ schema_version: "1", document_index: { index_id: "index", repository_id: "repo", commit: hash },
    execution_status: status, knowledge: [], knowledge_issues: [], covered_categories: [], pending_categories: ["components"],
    evaluated_categories: [], coverage_assessment_status: "not_run", consulted_documents: [], section_paths: {},
    validation_errors: [], finalization_reason: "incomplete_coverage", execution_error: null })
}

describe("version-bound architecture context", () => {
  const closers: (() => Promise<void>)[] = []
  afterEach(async () => { for (const close of closers.splice(0)) await close() })

  async function start() {
    const directory = mkdtempSync(join(tmpdir(), "veraud-context-"))
    const databaseUrl = `file:${join(directory, "test.db")}`
    execSync("pnpm prisma migrate deploy", { cwd: fileURLToPath(new URL("../../", import.meta.url)),
      env: { ...process.env, DATABASE_URL: databaseUrl }, stdio: "ignore" })
    const calls: { input: AgentInput; id: number }[] = []
    const workspaceDir = join(directory, "workspace")
    const root = join(workspaceDir, "777-acme-demo")
    mkdirSync(root, { recursive: true })
    writeFileSync(join(root, "README.md"), "# architecture")
    const catalog = testAgentCatalog()
    catalog.agents.push({ ...catalog.agents[0]!, agent_id: "architecture_context", name: "Architecture Context",
      model_configuration_id: "architecture_context" })
    const { app, db } = await buildApp({ databaseUrl, workspaceDir, silent: true,
      makeRunner: () => ({ enqueue: async () => ({ status: "Succeded", exitCode: 0, logTrail: "" }) }),
      makeAgentCatalogSource: () => ({ getAgentCatalog: async () => catalog }),
      makeModelAccessVerifier: () => ({ verify: async () => {} }),
      makeAgentInvoker: () => ({ run: async (_type, input, id) => {
        calls.push({ input, id })
        return new Promise<AgentInput>(() => {})
      } }),
    })
    closers.push(async () => { await app.close(); await db.$disconnect() })
    const project = await db.project.create({ data: {
      githubRepositoryId: 777n, repositoryOwner: "acme", repositoryName: "demo", status: "Ready",
    } })
    const provider = await db.aiProvider.create({ data: { name: "test-provider" } })
    const model = await db.aiModel.create({ data: { name: "test-model", aiProviderId: provider.id } })
    const credential = await db.aiCredential.create({ data: { name: "test", apiKey: "test", aiProviderId: provider.id } })
    await db.agentSettings.update({ where: { agentType: "architecture_context" }, data: {
      aiModelId: model.id, aiCredentialId: credential.id,
    } })
    const open = (hash = commit) => app.inject({ method: "POST", url: "/api/agent-executions/direct", payload: {
      agentType: "architecture_context", project: { projectId: project.id, branch: "main", commitHash: hash },
    } })
    const finish = (id: number, output = result()) => app.inject({ method: "POST",
      url: `/api/agent-executions/${id}/completion`, payload: { status: "Completed", result: output } })
    return { app, db, project, root, calls, open, finish }
  }

  it("discovers active context even when newer completed executions fill the recent window", async () => {
    const { app, db } = await start()
    const active = await db.agentExecution.create({ data: { agentType: "architecture_context", status: "Running" } })
    await db.agentExecution.createMany({ data: Array.from({ length: 55 }, () => ({
      agentType: "architecture_context", status: "Completed", result: "large private documentary payload",
    })) })
    const recent = await app.inject({ url: "/api/agent-executions/recent" })
    assert.equal(recent.statusCode, 200)
    assert.equal(recent.json().ids.length, 50)
    assert.ok(recent.json().ids.includes(active.id))
    assert.doesNotMatch(recent.body, /private|documentary/)
  })

  it("resolves the path server-side, adopts an active execution and atomically retains native JSON by version", async () => {
    const { app, db, project, root, calls, open, finish } = await start()
    const response = await open()
    assert.equal(response.statusCode, 201, response.body)
    const execution = response.json<{ id: number; evaluationId: number }>()
    assert.ok(execution.evaluationId)
    const deadline = Date.now() + 3000
    while (!calls.length && Date.now() < deadline) await new Promise((resolve) => setTimeout(resolve, 10))
    assert.deepEqual(calls, [{ id: execution.id, input: { root_path: root, commit_hash: commit } }])
    const duplicate = await open()
    assert.equal(duplicate.json().id, execution.id)
    assert.equal(calls.length, 1)
    const discovered = await app.inject({ url: "/api/agent-executions/recent" })
    assert.equal(discovered.statusCode, 200)
    assert.ok(discovered.json().ids.includes(execution.id))
    assert.equal((await finish(execution.id)).statusCode, 200)
    const artifact = await db.architectureContextArtifact.findUniqueOrThrow({ where: { executionId: execution.id },
      include: { projectVersion: true } })
    assert.equal(artifact.projectVersion.projectId, project.id)
    assert.equal(artifact.projectVersion.commitHash, commit)
    assert.equal(artifact.executionStatus, "partial")
    assert.equal(artifact.result, result())
    assert.equal((await finish(execution.id, result("failed"))).statusCode, 200)
    assert.equal((await db.architectureContextArtifact.findUniqueOrThrow({ where: { executionId: execution.id } })).result, result())
    assert.equal((await app.inject({ method: "GET", url: `/api/agent-executions/${execution.id}` })).json().result, result())
    const monitor = (await app.inject({ url: `/api/agent-executions/${execution.id}?monitor=true` })).json()
    assert.equal(monitor.monitorContext.project.id, project.id)
    assert.equal(monitor.monitorContext.commitHash, commit)
    assert.equal(JSON.parse(monitor.result).execution_status, "partial")
    assert.equal("knowledge" in JSON.parse(monitor.result), false)
    assert.equal((await db.project.findUniqueOrThrow({ where: { id: project.id } })).selectedVersionId, null)
  })

  it("rejects stale/missing artifacts without closing the execution, preserves retries and separates commits", async () => {
    const { db, open, finish } = await start()
    const first = (await open()).json<{ id: number }>()
    assert.equal((await finish(first.id, result("complete", "b".repeat(40)))).statusCode, 422)
    assert.equal((await finish(first.id, "null")).statusCode, 422)
    assert.equal(await db.architectureContextArtifact.count(), 0)
    assert.equal((await db.agentExecution.findUniqueOrThrow({ where: { id: first.id } })).status, "Waiting")
    assert.equal((await finish(first.id)).statusCode, 200)
    const retry = (await open()).json<{ id: number }>()
    assert.notEqual(retry.id, first.id)
    assert.equal((await finish(retry.id, result("failed"))).statusCode, 200)
    const other = (await open("b".repeat(40))).json<{ id: number }>()
    assert.equal((await finish(other.id, result("partial", "b".repeat(40)))).statusCode, 200)
    assert.equal(await db.architectureContextArtifact.count(), 3)
    assert.equal(await db.projectVersion.count(), 2)
  })

  it("keeps explicit direct input unassociated and rejects ambiguous or invalid project targets", async () => {
    const { app, db, project } = await start()
    const direct = await app.inject({ method: "POST", url: "/api/agent-executions/direct", payload: {
      agentType: "architecture_context", input: { root_path: "777-acme-demo", commit_hash: commit },
    } })
    assert.equal(direct.statusCode, 201)
    assert.equal(direct.json().evaluationId, null)
    for (const payload of [
      { agentType: "architecture_context", input: { root_path: "elsewhere" }, project: { projectId: project.id, branch: "main", commitHash: commit } },
      { agentType: "architecture_context", project: { projectId: project.id, branch: "main", commitHash: "HEAD" } },
      { agentType: "dummy", project: { projectId: project.id, branch: "main", commitHash: commit } },
      { agentType: "architecture_context", project: { projectId: 99999, branch: "main", commitHash: commit } },
    ]) {
      const response = await app.inject({ method: "POST", url: "/api/agent-executions/direct", payload })
      assert.ok([400, 422].includes(response.statusCode), response.body)
    }
    assert.equal(await db.evaluation.count(), 0)
  })
})
