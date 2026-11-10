import { afterEach, describe, it } from "node:test"
import assert from "node:assert/strict"
import { execSync } from "node:child_process"
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { buildApp } from "../app.js"
import { makeQualityAuditCatalogSource } from "./helpers/agentCatalog.js"
import { seedArchitectureContext } from "./helpers/architectureContext.js"
import type { AgentInput, PipelineInput } from "../infrastructure/agent-server-client/agent-server.client.js"

const hash = "a".repeat(40)
describe("automatic maintainability context", () => {
  const closers: (() => Promise<void>)[] = []
  afterEach(async () => { for (const close of closers.splice(0)) await close() })

  async function start() {
    const directory = mkdtempSync(join(tmpdir(), "veraud-maintenance-context-"))
    const databaseUrl = `file:${join(directory, "test.db")}`
    execSync("pnpm prisma migrate deploy", { cwd: fileURLToPath(new URL("../../", import.meta.url)),
      env: { ...process.env, DATABASE_URL: databaseUrl }, stdio: "ignore" })
    const workspaceDir = join(directory, "workspace")
    mkdirSync(join(workspaceDir, "123-acme-demo"), { recursive: true })
    writeFileSync(join(workspaceDir, "123-acme-demo", "README.md"), "# documentation")
    const inputs: PipelineInput[] = []
    const { app, db } = await buildApp({ databaseUrl, workspaceDir, silent: true,
      makeAgentCatalogSource: makeQualityAuditCatalogSource,
      makeModelAccessVerifier: () => ({ verify: async () => {} }),
      makeAgentInvoker: () => ({ run: async () => ({}), runPipelineByName: async (_pipeline, input) => {
        inputs.push(input)
        return new Promise<Record<string, AgentInput>>(() => {})
      } }),
    })
    closers.push(async () => { await app.close(); await db.$disconnect() })
    const project = await db.project.create({ data: { githubRepositoryId: 123n, repositoryOwner: "acme", repositoryName: "demo", status: "Ready" } })
    const provider = await db.aiProvider.create({ data: { name: "offline" } })
    const model = await db.aiModel.create({ data: { name: "offline", aiProviderId: provider.id } })
    const credential = await db.aiCredential.create({ data: { name: "offline", apiKey: "test", aiProviderId: provider.id } })
    for (const agentType of ["maintainability_manager", "security"]) await db.agentSettings.update({ where: { agentType },
      data: { aiModelId: model.id, aiCredentialId: credential.id } })
    const availability = (commitHash = hash, projectId = project.id) => app.inject({
      url: `/api/projects/${projectId}/architecture-context?commitHash=${commitHash}`,
    })
    const content = (commitHash = hash, projectId = project.id) => app.inject({
      url: `/api/projects/${projectId}/architecture-context/content?commitHash=${commitHash}`,
    })
    const audit = (attributes = ["maintainability"], commitHash = hash, options = {}) => app.inject({
      method: "POST", url: `/api/projects/${project.id}/audits`,
      payload: { branch: "main", commitHash, attributes, ...options },
    })
    return { app, db, project, availability, content, audit, inputs }
  }

  it("blocks missing/wrong-project/wrong-commit context before creating an audit, but allows security", async () => {
    const { db, project, availability, content, audit } = await start()
    assert.equal((await availability()).json().available, false)
    assert.equal((await content()).statusCode, 404)
    assert.equal((await audit()).statusCode, 422)
    assert.equal((await audit(["maintainability", "security"])).statusCode, 422)
    assert.equal(await db.evaluation.count({ where: { type: "QualityAudit" } }), 0)
    await seedArchitectureContext(db, project.id, "b".repeat(40))
    const other = await db.project.create({ data: { repositoryOwner: "other", repositoryName: "repo", status: "Ready" } })
    await seedArchitectureContext(db, other.id, hash)
    assert.equal((await availability()).json().available, false)
    assert.equal((await audit()).statusCode, 422)
    assert.equal((await audit(["security"])).statusCode, 202)
  })

  it("forwards the latest usable JSON unchanged and pins its identity in the audit snapshot", async () => {
    const { db, project, availability, content, audit, inputs } = await start()
    await seedArchitectureContext(db, project.id, hash)
    const source = await seedArchitectureContext(db, project.id, hash)
    const failed = await seedArchitectureContext(db, project.id, hash)
    await db.architectureContextArtifact.update({ where: { executionId: failed.executionId },
      data: { executionStatus: "failed", result: JSON.stringify({ ...failed.result, execution_status: "failed" }) } })
    const corrupted = await seedArchitectureContext(db, project.id, hash)
    await db.architectureContextArtifact.update({ where: { executionId: corrupted.executionId }, data: { result: "{}" } })
    const status = await availability()
    assert.equal(status.statusCode, 200, status.body)
    assert.equal(status.json().executionId, source.executionId)
    assert.equal(status.json().executionStatus, "partial")
    assert.equal("result" in status.json(), false, "Availability must not transfer the full documentary payload")
    const full = await content()
    assert.equal(full.statusCode, 200, full.body)
    assert.equal(full.json().executionId, source.executionId)
    assert.equal(full.json().schemaVersion, "1")
    assert.equal(full.json().data?.document_index?.commit, hash)
    assert.equal(full.json().data?.execution_status, "partial")
    assert.match(full.headers["cache-control"] ?? "", /no-store/)
    const opened = await audit(["maintainability", "security"])
    assert.equal(opened.statusCode, 202, opened.body)
    const executionId = opened.json().executionId as number
    const deadline = Date.now() + 3000
    while (!inputs.length && Date.now() < deadline) await new Promise((resolve) => setTimeout(resolve, 10))
    assert.deepEqual(inputs[0]?.request, { documented_architecture: source.result })
    const row = await db.agentExecution.findUniqueOrThrow({ where: { id: executionId } })
    const snapshot = JSON.parse(row.configurationSnapshot!)
    assert.deepEqual(snapshot.auditConfiguration.architectureContext, { executionId: source.executionId,
      projectVersionId: source.projectVersionId, schemaVersion: "1", executionStatus: "partial" })
    const newer = await seedArchitectureContext(db, project.id, hash)
    await db.architectureContextArtifact.update({ where: { executionId: newer.executionId }, data: {
      executionStatus: "complete", result: JSON.stringify({ ...newer.result, execution_status: "complete",
        covered_categories: newer.result.pending_categories, pending_categories: [],
        evaluated_categories: newer.result.pending_categories, coverage_assessment_status: "completed",
        finalization_reason: "coverage_complete" }),
    } })
    assert.equal((await availability()).json().executionId, newer.executionId)
    assert.equal((await availability()).json().executionStatus, "complete")
    const unchanged = await db.agentExecution.findUniqueOrThrow({ where: { id: executionId } })
    assert.equal(unchanged.configurationSnapshot, row.configurationSnapshot)
  })

  it("rejects manual substitution, failed-only context and malformed availability queries", async () => {
    const { db, project, availability, audit } = await start()
    const failed = await seedArchitectureContext(db, project.id, hash)
    await db.architectureContextArtifact.update({ where: { executionId: failed.executionId }, data: {
      executionStatus: "failed", result: JSON.stringify({ ...failed.result, execution_status: "failed" }),
    } })
    assert.equal((await availability()).json().available, false)
    assert.equal((await audit()).statusCode, 422)
    assert.equal((await audit(["maintainability"], hash, { request: { documented_architecture: failed.result } })).statusCode, 400)
    assert.equal((await availability("HEAD")).statusCode, 400)
    assert.equal((await availability(hash, 999999)).statusCode, 404)
    assert.equal(await db.evaluation.count({ where: { type: "QualityAudit" } }), 0)
  })
})
