import { test } from "node:test"
import assert from "node:assert/strict"
import { execFileSync } from "node:child_process"
import { mkdtempSync, mkdirSync, writeFileSync, existsSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { buildApp } from "../app.js"
import { makeQualityAuditCatalogSource } from "./helpers/agentCatalog.js"
import type { AgentInvoker } from "../infrastructure/agent-server-client/agent-server.client.js"

async function setup(invoker: AgentInvoker, projectDeletion?: { timeoutMs: number, pollMs: number }) {
  const directory = mkdtempSync(join(tmpdir(), "veraud-delete-"))
  const databaseUrl = `file:${join(directory, "test.db")}`
  const backendRoot = fileURLToPath(new URL("../../", import.meta.url))
  execFileSync(process.execPath, ["node_modules/prisma/build/index.js", "migrate", "deploy"], {
    cwd: backendRoot, env: { ...process.env, DATABASE_URL: databaseUrl }, stdio: "ignore",
  })
  const workspaceDir = join(directory, "workspace")
  const options = { databaseUrl, workspaceDir, silent: true,
    makeAgentCatalogSource: makeQualityAuditCatalogSource,
    makeAgentInvoker: () => invoker,
    ...(projectDeletion === undefined ? {} : { projectDeletionTimeoutMs: projectDeletion.timeoutMs, projectDeletionPollMs: projectDeletion.pollMs }) }
  return { ...(await buildApp(options)), workspaceDir, options }
}

/** Seeds one project with a version, evaluation, agents and disk artifacts. */
async function seedProject(db: Awaited<ReturnType<typeof buildApp>>["db"], workspaceDir: string) {
  const project = await db.project.create({ data: { githubRepositoryId: 123n, repositoryOwner: "acme", repositoryName: "demo", status: "READY" } })
  const version = await db.projectVersion.create({ data: { projectId: project.id, branch: "main", commitHash: "a".repeat(40), analysisStatus: "Completed" } })
  await db.agentSettings.upsert({ where: { agentType: "security" }, create: { agentType: "security" }, update: {} })
  const evaluation = await db.evaluation.create({ data: { projectVersionId: version.id, type: "QualityAudit" } })
  const execution = await db.agentExecution.create({ data: { evaluationId: evaluation.id, agentType: "security", status: "Completed",
    finishedAt: new Date(), result: JSON.stringify({ run_id: "b".repeat(32), attributes: ["security"] }) } })
  await db.executionEventStream.create({ data: { id: "stream-delete-1", executionId: execution.id, runId: "b".repeat(32) } })
  await db.executionEvent.create({ data: { eventId: "event-delete-1", streamId: "stream-delete-1", sequence: 0, occurredAt: new Date(), actionId: "agent", kind: "agent", metadata: "{}" } })
  await db.architectureContextArtifact.create({ data: { executionId: execution.id, projectVersionId: version.id, schemaVersion: "1", executionStatus: "completed", result: "{}" } })
  const succeededTask = await db.task.create({ data: { projectId: project.id, description: "clone", status: "Succeeded", kind: "clone" } })
  await db.graphExtraction.create({ data: { taskId: succeededTask.id, projectId: project.id, branch: "main", commitHash: "a".repeat(40), phase: "completed" } })
  const artifact = join(workspaceDir, ".veraud-artifacts", "b".repeat(32))
  mkdirSync(artifact, { recursive: true })
  writeFileSync(join(artifact, "report.json"), "{}")
  const clone = join(workspaceDir, "123-acme-demo")
  mkdirSync(clone, { recursive: true })
  writeFileSync(join(clone, ".git-marker"), "head")
  return { project, version, evaluation, execution, artifact, clone }
}

test("delete wipes the project database rows, event streams, tasks, artifacts and the checkout", async () => {
  const invoker = { run: async () => ({}) } as unknown as AgentInvoker
  const h = await setup(invoker)
  try {
    await h.app.ready()
    const seed = await seedProject(h.db, h.workspaceDir)
    const response = await h.app.inject({ method: "DELETE", url: `/api/projects/${seed.project.id}` })
    assert.equal(response.statusCode, 200)
    const body = response.json() as { status: string, counts: Record<string, number>, disk: { artifactsRemoved: string[], cloneRemoved: boolean, artifactFailures: string[] } }
    assert.equal(body.status, "deleted")
    assert.deepEqual(body.counts, { versions: 1, evaluations: 1, executions: 1, events: 1, architectureArtifacts: 1, tasks: 1, graphExtractions: 1 })
    assert.deepEqual(body.disk.artifactsRemoved, ["b".repeat(32)])
    assert.equal(body.disk.cloneRemoved, true)
    assert.deepEqual(body.disk.artifactFailures, [])
    assert.equal(await h.db.project.findUnique({ where: { id: seed.project.id } }), null)
    assert.equal(await h.db.projectVersion.count(), 0)
    assert.equal(await h.db.evaluation.count(), 0)
    assert.equal(await h.db.agentExecution.count(), 0)
    assert.equal(await h.db.executionEventStream.count(), 0)
    assert.equal(await h.db.executionEvent.count(), 0)
    assert.equal(await h.db.architectureContextArtifact.count(), 0)
    assert.equal(await h.db.task.count(), 0)
    assert.equal(await h.db.graphExtraction.count(), 0)
    assert.equal(existsSync(seed.artifact), false)
    assert.equal(existsSync(seed.clone), false)
    const again = await h.app.inject({ method: "DELETE", url: `/api/projects/${seed.project.id}` })
    assert.equal(again.statusCode, 404)
  } finally { await h.app.close(); await h.db.$disconnect() }
})

test("an open audit execution is asked to cancel first; nothing is deleted until it terminates", async () => {
  let sends = 0
  const invoker = { run: async () => ({}), cancelAudit: async () => { sends += 1; return { run_id: "c".repeat(32), status: "cancelling" } },
    getAuditSnapshot: async () => ({ run_id: "c".repeat(32), status: "cancelling" }) } as unknown as AgentInvoker
  const h = await setup(invoker, { timeoutMs: 400, pollMs: 50 })
  try {
    await h.app.ready()
    const project = await h.db.project.create({ data: { githubRepositoryId: 321n, repositoryOwner: "acme", repositoryName: "open", status: "READY" } })
    const version = await h.db.projectVersion.create({ data: { projectId: project.id, branch: "main", commitHash: "a".repeat(40), analysisStatus: "Completed" } })
    await h.db.agentSettings.upsert({ where: { agentType: "security" }, create: { agentType: "security" }, update: {} })
    const evaluation = await h.db.evaluation.create({ data: { projectVersionId: version.id, type: "QualityAudit" } })
    const execution = await h.db.agentExecution.create({ data: { evaluationId: evaluation.id, agentType: "security", status: "Running",
      dispatchStartedAt: new Date(), result: JSON.stringify({ run_id: "c".repeat(32) }) } })
    const response = await h.app.inject({ method: "DELETE", url: `/api/projects/${project.id}` })
    assert.equal(response.statusCode, 202)
    const body = response.json() as { status: string, pendingExecutionIds: number[] }
    assert.equal(body.status, "cancelling")
    assert.deepEqual(body.pendingExecutionIds, [execution.id])
    for (let attempt = 0; sends === 0 && attempt < 40; attempt++) { await new Promise((resolve) => { setTimeout(resolve, 25) }) }
    assert.equal(sends, 1)
    assert.ok((await h.db.project.findUnique({ where: { id: project.id } })) !== null)
    assert.equal(await h.db.agentExecution.count(), 1)
    const requested = await h.db.agentExecution.findUniqueOrThrow({ where: { id: execution.id } })
    assert.equal(requested.interruptionReason, "cancellation_requested")
    await h.db.agentExecution.update({ where: { id: execution.id }, data: { status: "Failed", finishedAt: new Date() } })
    const done = await h.app.inject({ method: "DELETE", url: `/api/projects/${project.id}` })
    assert.equal(done.statusCode, 200)
    assert.equal((await h.db.project.findUnique({ where: { id: project.id } })), null)
  } finally { await h.app.close(); await h.db.$disconnect() }
})

test("a project with a queued/running git task cannot be deleted", async () => {
  const invoker = { run: async () => ({}) } as unknown as AgentInvoker
  const h = await setup(invoker)
  try {
    await h.app.ready()
    const project = await h.db.project.create({ data: { githubRepositoryId: 654n, repositoryOwner: "acme", repositoryName: "busy", status: "READY" } })
    await h.db.task.create({ data: { projectId: project.id, description: "git checkout", status: "Running", kind: "git" } })
    const response = await h.app.inject({ method: "DELETE", url: `/api/projects/${project.id}` })
    assert.equal(response.statusCode, 422)
    assert.equal((await h.db.project.findUnique({ where: { id: project.id } })) !== null, true)
  } finally { await h.app.close(); await h.db.$disconnect() }
})
