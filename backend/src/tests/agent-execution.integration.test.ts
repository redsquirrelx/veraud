import { afterEach, describe, it } from "node:test"
import assert from "node:assert/strict"
import { execSync } from "node:child_process"
import { mkdtempSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { buildApp } from "../app.js"

const backendRoot = fileURLToPath(new URL("../../", import.meta.url))

function freshDatabase(): string {
  const dir = mkdtempSync(join(tmpdir(), "veraud-ae-"))
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

describe("agent execution endpoints", () => {
  let closers: Array<() => Promise<void>> = []

  afterEach(async () => {
    for (const close of closers) {
      await close()
    }
    closers = []
  })

  async function start() {
    const { app, db } = await buildApp({
      databaseUrl: freshDatabase(),
      workspaceDir: mkdtempSync(join(tmpdir(), "veraud-ws-")),
      silent: true,
      makeRunner: () => noopRunner,
    })

    closers.push(async () => {
      await app.close()
      await db.$disconnect()
    })

    return { app, db }
  }

  /** agent_execution.agent_type is a foreign key to agent_settings, which in turn
   * references ai_model and ai_credential. Seed the whole chain. */
  async function seedSettings(db: Awaited<ReturnType<typeof buildApp>>["db"], agentType: string) {
    const provider = await db.aiProvider.create({
      data: { name: `test-provider-${agentType}` },
    })

    const model = await db.aiModel.create({
      data: { name: "test-model", aiProviderId: provider.id },
    })

    const credential = await db.aiCredential.create({
      data: { name: "test-credential", apiKey: "test-key", aiProviderId: provider.id },
    })

    await db.agentSettings.create({
      data: { agentType, aiModelId: model.id, aiCredentialId: credential.id },
    })
  }

  async function seedEvaluation(db: Awaited<ReturnType<typeof buildApp>>["db"]) {
    const project = await db.project.create({
      data: {
        githubRepositoryId: 999888777n,
        repositoryOwner: "acme",
        repositoryName: "widgets",
        status: "Ready",
      },
    })

    const version = await db.projectVersion.create({
      data: { projectId: project.id, analysisStatus: "Pending" },
    })

    const evaluation = await db.evaluation.create({
      data: { projectVersionId: version.id, type: "Analysis" },
    })

    return { project, version, evaluation }
  }

  it("registers an invocation and returns its id immediately", async () => {
    const { app, db } = await start()
    await seedSettings(db, "analyzer")
    const { evaluation } = await seedEvaluation(db)

    const response = await app.inject({
      method: "POST",
      url: "/api/agent-executions",
      payload: { agentType: "analyzer", evaluationId: evaluation.id },
    })

    assert.equal(response.statusCode, 201)

    const body = response.json()
    assert.equal(typeof body.id, "number")
    assert.equal(body.agentType, "analyzer")
    assert.equal(body.evaluationId, evaluation.id)
    assert.equal(body.status, "Waiting")
    assert.equal(body.result, null)
    assert.equal(body.finishedAt, null)
  })

  it("closes the run with the agent result", async () => {
    const { app, db } = await start()
    await seedSettings(db, "analyzer")
    const { evaluation } = await seedEvaluation(db)

    const opened = await app.inject({
      method: "POST",
      url: "/api/agent-executions",
      payload: { agentType: "analyzer", evaluationId: evaluation.id },
    })

    const { id } = opened.json()
    const description = JSON.stringify({ kind: "library", confidence: "high" })

    const closed = await app.inject({
      method: "POST",
      url: `/api/agent-executions/${id}/completion`,
      payload: {
        status: "Completed",
        result: description,
        inputTokens: 1200,
        outputTokens: 180,
      },
    })

    assert.equal(closed.statusCode, 200)

    const body = closed.json()
    assert.equal(body.status, "Completed")
    assert.equal(body.result, description)
    assert.equal(body.inputTokens, 1200)
    assert.notEqual(body.finishedAt, null)

    const read = await app.inject({ method: "GET", url: `/api/agent-executions/${id}` })
    assert.equal(read.statusCode, 200)
    assert.equal(read.json().status, "Completed")
  })

  it("records a failure with its error message", async () => {
    const { app, db } = await start()
    await seedSettings(db, "analyzer")
    const { evaluation } = await seedEvaluation(db)

    const opened = await app.inject({
      method: "POST",
      url: "/api/agent-executions",
      payload: { agentType: "analyzer", evaluationId: evaluation.id },
    })

    const { id } = opened.json()

    const closed = await app.inject({
      method: "POST",
      url: `/api/agent-executions/${id}/completion`,
      payload: { status: "Failed", error: "Error code: 401" },
    })

    assert.equal(closed.statusCode, 200)
    assert.equal(closed.json().status, "Failed")
    assert.equal(closed.json().error, "Error code: 401")
    assert.equal(closed.json().result, null)
  })

  it("refuses to mark a failure without an error", async () => {
    const { app, db } = await start()
    await seedSettings(db, "analyzer")
    const { evaluation } = await seedEvaluation(db)

    const opened = await app.inject({
      method: "POST",
      url: "/api/agent-executions",
      payload: { agentType: "analyzer", evaluationId: evaluation.id },
    })

    const response = await app.inject({
      method: "POST",
      url: `/api/agent-executions/${opened.json().id}/completion`,
      payload: { status: "Failed" },
    })

    assert.equal(response.statusCode, 422)
  })

  it("ignores a duplicate callback on a finished run", async () => {
    const { app, db } = await start()
    await seedSettings(db, "analyzer")
    const { evaluation } = await seedEvaluation(db)

    const opened = await app.inject({
      method: "POST",
      url: "/api/agent-executions",
      payload: { agentType: "analyzer", evaluationId: evaluation.id },
    })

    const { id } = opened.json()

    await app.inject({
      method: "POST",
      url: `/api/agent-executions/${id}/completion`,
      payload: { status: "Completed", result: '{"kind":"library"}' },
    })

    const second = await app.inject({
      method: "POST",
      url: `/api/agent-executions/${id}/completion`,
      payload: { status: "Failed", error: "late callback" },
    })

    assert.equal(second.statusCode, 200)
    assert.equal(second.json().status, "Completed")
    assert.equal(second.json().error, null)
  })

  it("marks a run as running", async () => {
    const { app, db } = await start()
    await seedSettings(db, "analyzer")
    const { evaluation } = await seedEvaluation(db)

    const opened = await app.inject({
      method: "POST",
      url: "/api/agent-executions",
      payload: { agentType: "analyzer", evaluationId: evaluation.id },
    })

    const response = await app.inject({
      method: "POST",
      url: `/api/agent-executions/${opened.json().id}/running`,
    })

    assert.equal(response.statusCode, 200)
    assert.equal(response.json().status, "Running")
  })

  it("404s for an unknown execution", async () => {
    const { app } = await start()

    const read = await app.inject({ method: "GET", url: "/api/agent-executions/4242" })
    assert.equal(read.statusCode, 404)

    const closed = await app.inject({
      method: "POST",
      url: "/api/agent-executions/4242/completion",
      payload: { status: "Completed", result: "{}" },
    })
    assert.equal(closed.statusCode, 404)
  })

  it("rejects a malformed id", async () => {
    const { app } = await start()

    const response = await app.inject({ method: "GET", url: "/api/agent-executions/abc" })
    assert.equal(response.statusCode, 400)
  })

  it("rejects an open request without an evaluation", async () => {
    const { app } = await start()

    const response = await app.inject({
      method: "POST",
      url: "/api/agent-executions",
      payload: { agentType: "analyzer" },
    })

    assert.equal(response.statusCode, 400)
  })
})