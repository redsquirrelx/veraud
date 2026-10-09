import { afterEach, describe, it } from "node:test"
import assert from "node:assert/strict"
import { execSync } from "node:child_process"
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { buildApp } from "../app.js"
import type { AgentInput, AgentInvoker } from "../infrastructure/agent-server-client/agent-server.client.js"

const backendRoot = fileURLToPath(new URL("../../", import.meta.url))

function freshDatabase(): string {
  const dir = mkdtempSync(join(tmpdir(), "veraud-panalyze-"))
  const url = `file:${join(dir, "test.db")}`
  execSync("pnpm prisma migrate deploy", {
    cwd: backendRoot,
    env: { ...process.env, DATABASE_URL: url },
    stdio: "ignore",
  })
  return url
}

const noopRunner = {
  enqueue: async () => ({ status: "Succeded", exitCode: 0, logTrail: "" }),
}

const COMMIT = "a".repeat(40)

describe("project analyze endpoint", () => {
  let closers: Array<() => Promise<void>> = []

  afterEach(async () => {
    for (const close of closers) {
      await close()
    }
    closers = []
  })

  async function start(options: { invoker?: AgentInvoker; withCheckout?: boolean } = {}) {
    const workspaceDir = mkdtempSync(join(tmpdir(), "veraud-paws-"))

    if (options.withCheckout !== false) {
      const checkout = join(workspaceDir, "555-acme-shop")
      mkdirSync(checkout, { recursive: true })
      writeFileSync(join(checkout, "README.md"), "# fixtures\n")
    }

    const { app, db } = await buildApp({
      databaseUrl: freshDatabase(),
      workspaceDir,
      silent: true,
      makeRunner: () => noopRunner,
      makeAgentInvoker: () => options.invoker ?? { run: async () => ({ kind: "library" }) },
    })

    closers.push(async () => {
      await app.close()
      await db.$disconnect()
    })

    const project = await db.project.create({
      data: {
        githubRepositoryId: 555n,
        repositoryOwner: "acme",
        repositoryName: "shop",
        status: "READY",
      },
    })

    return { app, db, project }
  }

  async function seedAnalyzer(db: Awaited<ReturnType<typeof buildApp>>["db"]) {
    const provider = await db.aiProvider.create({ data: { name: "test-provider" } })
    const model = await db.aiModel.create({ data: { name: "test-model", aiProviderId: provider.id } })
    const credential = await db.aiCredential.create({
      data: { name: "test-credential", apiKey: "test-key", aiProviderId: provider.id },
    })
    await db.agentSettings.create({
      data: { agentType: "analyzer", aiModelId: model.id, aiCredentialId: credential.id },
    })
  }

  it("saves the version, creates an evaluation and starts the agent", async () => {
    const seen: Array<{ agentType: string; input: AgentInput; executionId: number }> = []
    const { app, db, project } = await start({
      invoker: {
        run: async (agentType, input, executionId) => {
          seen.push({ agentType, input, executionId })
          return { kind: "library" }
        },
      },
    })
    await seedAnalyzer(db)

    const response = await app.inject({
      method: "POST",
      url: `/api/projects/${project.id}/analyze`,
      payload: { branch: "main", commitHash: COMMIT },
    })

    assert.equal(response.statusCode, 201)

    const body = response.json()
    assert.equal(typeof body.versionId, "number")
    assert.equal(typeof body.evaluationId, "number")
    assert.equal(body.execution.agentType, "analyzer")
    assert.equal(body.execution.evaluationId, body.evaluationId)
    assert.equal(body.execution.status, "Waiting")

    const version = await db.projectVersion.findUnique({ where: { id: body.versionId } })
    assert.equal(version?.projectId, project.id)
    assert.equal(version?.branch, "main")
    assert.equal(version?.commitHash, COMMIT)
    assert.equal(version?.analysisStatus, "Pending")

    const updated = await db.project.findUnique({ where: { id: project.id } })
    assert.equal(updated?.selectedVersionId, body.versionId)

    const evaluation = await db.evaluation.findUnique({ where: { id: body.evaluationId } })
    assert.equal(evaluation?.projectVersionId, body.versionId)
    assert.equal(evaluation?.type, "Analysis")

    const deadline = Date.now() + 5000
    while (seen.length === 0 && Date.now() < deadline) {
      await new Promise((done) => setTimeout(done, 20))
    }
    assert.equal(seen.length, 1)
    assert.equal(seen[0]?.agentType, "analyzer")
    assert.equal(seen[0]?.executionId, body.execution.id)
  })

  it("reuses the version row when the same commit is analyzed again", async () => {
    const { app, db, project } = await start()
    await seedAnalyzer(db)

    const first = await app.inject({
      method: "POST",
      url: `/api/projects/${project.id}/analyze`,
      payload: { branch: "main", commitHash: COMMIT },
    })
    assert.equal(first.statusCode, 201)

    await app.inject({
      method: "POST",
      url: `/api/agent-executions/${first.json().execution.id}/completion`,
      payload: { status: "Completed", result: "{}" },
    })

    const second = await app.inject({
      method: "POST",
      url: `/api/projects/${project.id}/analyze`,
      payload: { branch: "main", commitHash: COMMIT },
    })

    assert.equal(first.statusCode, 201)
    assert.equal(second.statusCode, 201)
    assert.equal(second.json().versionId, first.json().versionId)
    assert.notEqual(second.json().evaluationId, first.json().evaluationId)

    const versions = await db.projectVersion.count({ where: { projectId: project.id } })
    assert.equal(versions, 1)
  })

  it("404s for an unknown project", async () => {
    const { app } = await start()

    const response = await app.inject({
      method: "POST",
      url: "/api/projects/4242/analyze",
      payload: { branch: "main", commitHash: COMMIT },
    })

    assert.equal(response.statusCode, 404)
  })

  it("400s for a malformed hash", async () => {
    const { app, project } = await start()

    const response = await app.inject({
      method: "POST",
      url: `/api/projects/${project.id}/analyze`,
      payload: { branch: "main", commitHash: "zzz" },
    })

    assert.equal(response.statusCode, 400)
  })

  it("422s when the project has no checkout", async () => {
    const { app, db, project } = await start({ withCheckout: false })
    await seedAnalyzer(db)

    const response = await app.inject({
      method: "POST",
      url: `/api/projects/${project.id}/analyze`,
      payload: { branch: "main", commitHash: COMMIT },
    })

    assert.equal(response.statusCode, 422)
  })

  it("422s when the analyzer is not registered", async () => {
    const { app, project } = await start()

    const response = await app.inject({
      method: "POST",
      url: `/api/projects/${project.id}/analyze`,
      payload: { branch: "main", commitHash: COMMIT },
    })

    assert.equal(response.statusCode, 422)
    assert.match(response.json().message, /analyzer/)
  })
})
