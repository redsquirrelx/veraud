import { afterEach, describe, it } from "node:test"
import assert from "node:assert/strict"
import { execSync } from "node:child_process"
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { buildApp } from "../app.js"
import type { AgentInput, AgentInvoker, PipelineInput } from "../infrastructure/agent-server-client/agent-server.client.js"
import { auditResponseSerialization } from "./helpers/responseSerializationAudit.js"

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

    // The default invoker only covers single-agent runs. Its pipeline twin
    // returns without reporting, so rows stay open until the test closes them
    // the way the real pipeline would over HTTP.
    const quietPipeline = {
      runPipeline: async () => ({ analysis: {}, description: {} }),
    }

    const { app, db } = await buildApp({
      databaseUrl: freshDatabase(),
      workspaceDir,
      silent: true,
      makeRunner: () => noopRunner,
      makeAgentInvoker: () => options.invoker ?? {
        run: async () => ({ kind: "library" }),
        ...quietPipeline,
      },
      makeModelAccessVerifier: () => ({ verify: async () => {} }),
    })

    auditResponseSerialization(app)
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

  async function seedPipeline(db: Awaited<ReturnType<typeof buildApp>>["db"]) {
    const provider = await db.aiProvider.create({ data: { name: "test-provider" } })
    const model = await db.aiModel.create({ data: { name: "test-model", aiProviderId: provider.id } })
    const credential = await db.aiCredential.create({
      data: { name: "test-credential", apiKey: "test-key", aiProviderId: provider.id },
    })
    for (const agentType of ["analyzer", "architect"]) {
      await db.agentSettings.upsert({
        where: { agentType },
        create: { agentType, aiModelId: model.id, aiCredentialId: credential.id },
        update: { aiModelId: model.id, aiCredentialId: credential.id },
      })
    }
  }

  it("saves the version, creates an evaluation and starts the pipeline", async () => {
    const seen: Array<{ input: PipelineInput; executionIds: { analyzer: number; architect: number } }> = []
    const { app, db, project } = await start({
      invoker: {
        run: async () => ({ kind: "library" }),
        runPipeline: async (input, executionIds) => {
          seen.push({ input, executionIds })
          return { analysis: { kind: "library" }, description: { style: "layered" } }
        },
      },
    })
    await seedPipeline(db)

    const response = await app.inject({
      method: "POST",
      url: `/api/projects/${project.id}/analyze`,
      payload: { branch: "main", commitHash: COMMIT },
    })

    assert.equal(response.statusCode, 201)

    const body = response.json()
    assert.equal(typeof body.versionId, "number")
    assert.equal(typeof body.evaluationId, "number")
    assert.equal(body.executions.analyzer.agentType, "analyzer")
    assert.equal(body.executions.architect.agentType, "architect")
    assert.equal(body.executions.analyzer.evaluationId, body.evaluationId)
    assert.equal(body.executions.architect.evaluationId, body.evaluationId)
    assert.equal(body.executions.analyzer.status, "Waiting")
    assert.equal(body.executions.architect.status, "Waiting")

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
    assert.equal(seen[0]?.executionIds.analyzer, body.executions.analyzer.id)
    assert.equal(seen[0]?.executionIds.architect, body.executions.architect.id)
    // The pipeline resolves the same checkout a single-agent run would.
    assert.match(String(seen[0]?.input.root_path), /555-acme-shop/)
  })

  it("reuses the version row when the same commit is analyzed again", async () => {
    // The fake pipeline returns without reporting, so the test closes both
    // rows the way the real pipeline would before analyzing the commit again.
    const quiet: AgentInvoker = {
      run: async () => ({}),
      runPipeline: async () => ({ analysis: {}, description: {} }),
    }
    const { app, db, project } = await start({ invoker: quiet })
    await seedPipeline(db)

    const first = await app.inject({
      method: "POST",
      url: `/api/projects/${project.id}/analyze`,
      payload: { branch: "main", commitHash: COMMIT },
    })
    assert.equal(first.statusCode, 201)

    await app.inject({
      method: "POST",
      url: `/api/agent-executions/${first.json().executions.analyzer.id}/completion`,
      payload: { status: "Completed", result: "{}" },
    })
    await app.inject({
      method: "POST",
      url: `/api/agent-executions/${first.json().executions.architect.id}/completion`,
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

  it("422s when the project is syncing", async () => {
    const { app, db, project } = await start()
    await seedPipeline(db)
    await db.project.update({ where: { id: project.id }, data: { status: "SYNCING" } })

    const response = await app.inject({
      method: "POST",
      url: `/api/projects/${project.id}/analyze`,
      payload: { branch: "main", commitHash: COMMIT },
    })

    assert.equal(response.statusCode, 422)
    assert.match(response.json().message, /syncing/)
  })

  it("422s when the project has no checkout", async () => {
    const { app, db, project } = await start({ withCheckout: false })
    await seedPipeline(db)

    const response = await app.inject({
      method: "POST",
      url: `/api/projects/${project.id}/analyze`,
      payload: { branch: "main", commitHash: COMMIT },
    })

    assert.equal(response.statusCode, 422)
  })

  it("422s when the analyzer has no model and credential configured", async () => {
    const { app, project } = await start()

    const response = await app.inject({
      method: "POST",
      url: `/api/projects/${project.id}/analyze`,
      payload: { branch: "main", commitHash: COMMIT },
    })

    assert.equal(response.statusCode, 422)
    assert.match(response.json().message, /analyzer/)
  })

  it("422s when the architect is not registered", async () => {
    const { app, db, project } = await start()
    const provider = await db.aiProvider.create({ data: { name: "test-provider" } })
    const model = await db.aiModel.create({ data: { name: "test-model", aiProviderId: provider.id } })
    const credential = await db.aiCredential.create({
      data: { name: "test-credential", apiKey: "test-key", aiProviderId: provider.id },
    })
    await db.agentSettings.update({
      where: { agentType: "analyzer" },
      data: { aiModelId: model.id, aiCredentialId: credential.id },
    })

    const response = await app.inject({
      method: "POST",
      url: `/api/projects/${project.id}/analyze`,
      payload: { branch: "main", commitHash: COMMIT },
    })

    assert.equal(response.statusCode, 422)
    assert.match(response.json().message, /architect/)
  })

  it("422s when the same version already has an open run", async () => {
    const stalling: AgentInvoker = {
      run: () => new Promise<AgentInput>(() => {}),
      runPipeline: () => new Promise<never>(() => {}),
    }
    const { app, db, project } = await start({ invoker: stalling })
    await seedPipeline(db)

    const first = await app.inject({
      method: "POST",
      url: `/api/projects/${project.id}/analyze`,
      payload: { branch: "main", commitHash: COMMIT },
    })
    assert.equal(first.statusCode, 201)

    const second = await app.inject({
      method: "POST",
      url: `/api/projects/${project.id}/analyze`,
      payload: { branch: "main", commitHash: COMMIT },
    })

    assert.equal(second.statusCode, 422)
    assert.match(second.json().message, /already being analyzed/)
  })

  it("allows another version while one is running", async () => {
    const stalling: AgentInvoker = {
      run: () => new Promise<AgentInput>(() => {}),
      runPipeline: () => new Promise<never>(() => {}),
    }
    const { app, db, project } = await start({ invoker: stalling })
    await seedPipeline(db)

    const first = await app.inject({
      method: "POST",
      url: `/api/projects/${project.id}/analyze`,
      payload: { branch: "main", commitHash: COMMIT },
    })
    const second = await app.inject({
      method: "POST",
      url: `/api/projects/${project.id}/analyze`,
      payload: { branch: "main", commitHash: "b".repeat(40) },
    })

    assert.equal(first.statusCode, 201)
    assert.equal(second.statusCode, 201)
  })

  it("lists versions with both pipeline runs", async () => {
    const { app, db, project } = await start()
    await seedPipeline(db)

    const empty = await app.inject({ method: "GET", url: `/api/projects/${project.id}/versions` })
    assert.equal(empty.statusCode, 200)
    assert.deepEqual(empty.json(), [])

    const opened = await app.inject({
      method: "POST",
      url: `/api/projects/${project.id}/analyze`,
      payload: { branch: "main", commitHash: COMMIT },
    })
    const analyzerId = opened.json().executions.analyzer.id as number
    const architectId = opened.json().executions.architect.id as number

    await app.inject({
      method: "POST",
      url: `/api/agent-executions/${analyzerId}/completion`,
      payload: { status: "Completed", result: "{\"kind\":\"library\"}" },
    })
    await app.inject({
      method: "POST",
      url: `/api/agent-executions/${architectId}/completion`,
      payload: { status: "Completed", result: "{\"style\":\"layered\"}" },
    })

    const listed = await app.inject({ method: "GET", url: `/api/projects/${project.id}/versions` })
    assert.equal(listed.statusCode, 200)

    const versions = listed.json()
    assert.equal(versions.length, 1)
    assert.equal(versions[0].branch, "main")
    assert.equal(versions[0].commitHash, COMMIT)
    assert.equal(versions[0].evaluationId, opened.json().evaluationId)
    assert.equal(versions[0].executions.length, 2)
    assert.equal(versions[0].executions[0].id, analyzerId)
    assert.equal(versions[0].executions[0].agentType, "analyzer")
    assert.equal(versions[0].executions[0].status, "Completed")
    assert.equal(versions[0].executions[1].id, architectId)
    assert.equal(versions[0].executions[1].agentType, "architect")
    assert.equal(versions[0].executions[1].status, "Completed")
    assert.equal(versions[0].derivedStatus, "Completed")
  })

  it("derives the version status from both runs", async () => {
    const { app, db, project } = await start()
    await seedPipeline(db)

    const opened = await app.inject({
      method: "POST",
      url: `/api/projects/${project.id}/analyze`,
      payload: { branch: "main", commitHash: COMMIT },
    })
    const analyzerId = opened.json().executions.analyzer.id as number
    const architectId = opened.json().executions.architect.id as number

    const waiting = await app.inject({ method: "GET", url: `/api/projects/${project.id}/versions` })
    assert.equal(waiting.json()[0].derivedStatus, "Waiting")

    await app.inject({
      method: "POST",
      url: `/api/agent-executions/${analyzerId}/completion`,
      payload: { status: "Completed", result: "{}" },
    })

    const halfDone = await app.inject({ method: "GET", url: `/api/projects/${project.id}/versions` })
    assert.equal(halfDone.json()[0].derivedStatus, "Waiting")

    await app.inject({
      method: "POST",
      url: `/api/agent-executions/${architectId}/completion`,
      payload: { status: "Failed", error: "boom" },
    })

    const failed = await app.inject({ method: "GET", url: `/api/projects/${project.id}/versions` })
    assert.equal(failed.json()[0].derivedStatus, "Failed")
  })

  it("fails both rows when the pipeline cannot start", async () => {
    const unreachable: AgentInvoker = {
      run: async () => ({ kind: "library" }),
      runPipeline: async () => {
        throw new Error("Could not reach the agent-server: ECONNREFUSED")
      },
    }
    const { app, db, project } = await start({ invoker: unreachable })
    await seedPipeline(db)

    const opened = await app.inject({
      method: "POST",
      url: `/api/projects/${project.id}/analyze`,
      payload: { branch: "main", commitHash: COMMIT },
    })
    assert.equal(opened.statusCode, 201)

    const deadline = Date.now() + 5000
    let executions: Array<{ status: string }> = []
    while (Date.now() < deadline) {
      const listed = await app.inject({ method: "GET", url: `/api/projects/${project.id}/versions` })
      executions = listed.json()[0]?.executions ?? []
      if (executions.length === 2 && executions.every((execution) => execution.status === "Failed")) {
        break
      }
      await new Promise((done) => setTimeout(done, 20))
    }

    assert.equal(executions.length, 2)
    assert.deepEqual(executions.map((execution) => execution.status), ["Failed", "Failed"])
  })

  it("404s versions for an unknown project", async () => {
    const { app } = await start()

    const response = await app.inject({ method: "GET", url: "/api/projects/4242/versions" })

    assert.equal(response.statusCode, 404)
  })
})
