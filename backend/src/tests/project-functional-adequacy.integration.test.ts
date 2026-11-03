import { afterEach, describe, it } from "node:test"
import assert from "node:assert/strict"
import { execSync } from "node:child_process"
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { buildApp } from "../app.js"
import type { AgentInvoker, PipelineInput } from "../infrastructure/agent-server-client/agent-server.client.js"
import { auditResponseSerialization } from "./helpers/responseSerializationAudit.js"

const backendRoot = fileURLToPath(new URL("../../", import.meta.url))

function freshDatabase(): string {
  const dir = mkdtempSync(join(tmpdir(), "veraud-pfa-"))
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

const COMMIT = "b".repeat(40)

describe("project functional adequacy endpoint", () => {
  let closers: Array<() => Promise<void>> = []

  afterEach(async () => {
    for (const close of closers) {
      await close()
    }
    closers = []
  })

  async function start(options: { invoker?: AgentInvoker } = {}) {
    const workspaceDir = mkdtempSync(join(tmpdir(), "veraud-pfaws-"))
    const checkout = join(workspaceDir, "777-acme-shop")
    mkdirSync(checkout, { recursive: true })
    writeFileSync(join(checkout, "README.md"), "# fixtures\n")

    const { app, db } = await buildApp({
      databaseUrl: freshDatabase(),
      workspaceDir,
      silent: true,
      makeRunner: () => noopRunner,
      makeAgentInvoker: () => options.invoker ?? {
        run: async () => ({ kind: "library" }),
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
        githubRepositoryId: 777n,
        repositoryOwner: "acme",
        repositoryName: "shop",
        status: "READY",
      },
    })

    return { app, db, project }
  }

  it("opens an exploratory run without model configuration or credentials", async () => {
    const seen: Array<{ pipeline: string; input: PipelineInput; executionIds: Record<string, number>; configs: Record<string, unknown> }> = []
    const { app, db, project } = await start({
      invoker: {
        run: async () => ({}),
        runPipelineByName: async (pipeline, input, executionIds, configs) => {
          seen.push({ pipeline, input, executionIds, configs })
          return {}
        },
      },
    })

    const response = await app.inject({
      method: "POST",
      url: `/api/projects/${project.id}/functional-adequacy`,
      payload: { branch: "main", commitHash: COMMIT },
    })

    assert.equal(response.statusCode, 201)
    const body = response.json()
    assert.equal(body.executions.functional_adequacy.agentType, "functional_adequacy")
    assert.equal(body.executions.functional_adequacy.status, "Waiting")
    assert.equal(body.executions.functional_adequacy.evaluationId, body.evaluationId)

    const stored = await db.agentExecution.findUnique({ where: { id: body.executions.functional_adequacy.id } })
    assert.equal(stored?.configurationSnapshot, null)

    const deadline = Date.now() + 5000
    while (seen.length === 0 && Date.now() < deadline) {
      await new Promise((done) => setTimeout(done, 20))
    }
    assert.equal(seen.length, 1)
    assert.equal(seen[0]?.pipeline, "functional-adequacy")
    assert.equal(seen[0]?.executionIds.functional_adequacy, body.executions.functional_adequacy.id)
    assert.deepEqual(seen[0]?.configs, {})
    assert.equal(seen[0]?.input.requirements, undefined)
    assert.match(String(seen[0]?.input.root_path), /777-acme-shop/)
  })

  it("forwards requirements and captures the configured model", async () => {
    const seen: Array<{ input: PipelineInput; configs: Record<string, unknown> }> = []
    const { app, db, project } = await start({
      invoker: {
        run: async () => ({}),
        runPipelineByName: async (_pipeline, input, _executionIds, configs) => {
          seen.push({ input, configs })
          return {}
        },
      },
    })
    const provider = await db.aiProvider.create({ data: { name: "test-provider" } })
    const model = await db.aiModel.create({ data: { name: "test-model", aiProviderId: provider.id } })
    const credential = await db.aiCredential.create({
      data: { name: "test-credential", apiKey: "test-key", aiProviderId: provider.id },
    })
    await db.agentSettings.upsert({
      where: { agentType: "functional_adequacy" },
      create: { agentType: "functional_adequacy", aiModelId: model.id, aiCredentialId: credential.id },
      update: { aiModelId: model.id, aiCredentialId: credential.id },
    })

    const requirements = [
      { requirement_id: "RF-01", description: "The catalog lists available products" },
      { requirement_id: "RF-02", description: "Only administrators can delete products" },
    ]
    const response = await app.inject({
      method: "POST",
      url: `/api/projects/${project.id}/functional-adequacy`,
      payload: { branch: "main", commitHash: COMMIT, requirements },
    })

    assert.equal(response.statusCode, 201)
    const body = response.json()
    const stored = await db.agentExecution.findUnique({ where: { id: body.executions.functional_adequacy.id } })
    assert.ok(stored?.configurationSnapshot)

    const deadline = Date.now() + 5000
    while (seen.length === 0 && Date.now() < deadline) {
      await new Promise((done) => setTimeout(done, 20))
    }
    assert.equal(seen.length, 1)
    assert.deepEqual(seen[0]?.input.requirements, requirements)
    assert.ok(seen[0]?.configs.functional_adequacy)
  })

  it("422s naming the missing model when requirements need one", async () => {
    const { app, project } = await start()

    const response = await app.inject({
      method: "POST",
      url: `/api/projects/${project.id}/functional-adequacy`,
      payload: {
        branch: "main",
        commitHash: COMMIT,
        requirements: [{ requirement_id: "RF-01", description: "Catalog lists products" }],
      },
    })

    assert.equal(response.statusCode, 422)
    assert.match(response.json().message, /functional_adequacy/)
    const versions = await app.inject({ method: "GET", url: `/api/projects/${project.id}/versions` })
    assert.deepEqual(versions.json(), [])
  })

  it("404s for an unknown project", async () => {
    const { app } = await start()

    const response = await app.inject({
      method: "POST",
      url: "/api/projects/4242/functional-adequacy",
      payload: { branch: "main", commitHash: COMMIT },
    })

    assert.equal(response.statusCode, 404)
  })

  it("400s for an empty requirement identifier", async () => {
    const { app, project } = await start()

    const response = await app.inject({
      method: "POST",
      url: `/api/projects/${project.id}/functional-adequacy`,
      payload: {
        branch: "main",
        commitHash: COMMIT,
        requirements: [{ requirement_id: "", description: "Something" }],
      },
    })

    assert.equal(response.statusCode, 400)
  })
})
