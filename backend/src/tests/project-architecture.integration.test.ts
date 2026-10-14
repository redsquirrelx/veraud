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
  const dir = mkdtempSync(join(tmpdir(), "veraud-parch-"))
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
const STAGES = ["orientation", "architecture", "semantic_validation"] as const

describe("project architecture endpoint", () => {
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

    // The default invoker has no pipeline support: rows fail closed the way
    // dispatchPipelineByName does when the agent-server cannot be reached.
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
        githubRepositoryId: 555n,
        repositoryOwner: "acme",
        repositoryName: "shop",
        status: "READY",
      },
    })

    return { app, db, project }
  }

  async function seedPipeline(db: Awaited<ReturnType<typeof buildApp>>["db"], stages: readonly string[] = STAGES) {
    const provider = await db.aiProvider.create({ data: { name: "test-provider" } })
    const model = await db.aiModel.create({ data: { name: "test-model", aiProviderId: provider.id } })
    const credential = await db.aiCredential.create({
      data: { name: "test-credential", apiKey: "test-key", aiProviderId: provider.id },
    })
    for (const agentType of stages) {
      await db.agentSettings.upsert({
        where: { agentType },
        create: { agentType, aiModelId: model.id, aiCredentialId: credential.id },
        update: { aiModelId: model.id, aiCredentialId: credential.id },
      })
    }
  }

  it("saves the version, creates an evaluation and starts the three-stage pipeline", async () => {
    const seen: Array<{ pipeline: string; input: PipelineInput; executionIds: Record<string, number>; configs: Record<string, unknown> }> = []
    const { app, db, project } = await start({
      invoker: {
        run: async () => ({ kind: "library" }),
        runPipelineByName: async (pipeline, input, executionIds, configs) => {
          seen.push({ pipeline, input, executionIds, configs })
          return {}
        },
      },
    })
    await seedPipeline(db)

    const response = await app.inject({
      method: "POST",
      url: `/api/projects/${project.id}/architecture`,
      payload: { branch: "main", commitHash: COMMIT },
    })

    assert.equal(response.statusCode, 201)

    const body = response.json()
    assert.equal(typeof body.versionId, "number")
    assert.equal(typeof body.evaluationId, "number")
    for (const stage of STAGES) {
      assert.equal(body.executions[stage].agentType, stage)
      assert.equal(body.executions[stage].evaluationId, body.evaluationId)
      assert.equal(body.executions[stage].status, "Waiting")
    }

    const evaluation = await db.evaluation.findUnique({ where: { id: body.evaluationId } })
    assert.equal(evaluation?.projectVersionId, body.versionId)
    assert.equal(evaluation?.type, "Analysis")

    const deadline = Date.now() + 5000
    while (seen.length === 0 && Date.now() < deadline) {
      await new Promise((done) => setTimeout(done, 20))
    }
    assert.equal(seen.length, 1)
    assert.equal(seen[0]?.pipeline, "project-architecture")
    for (const stage of STAGES) {
      assert.equal(seen[0]?.executionIds[stage], body.executions[stage].id)
      assert.ok(seen[0]?.configs[stage], `stage ${stage} travels with its configuration`)
    }
    // The pipeline resolves the same checkout a single-agent run would.
    assert.match(String(seen[0]?.input.root_path), /555-acme-shop/)
  })

  it("lists versions with all three pipeline runs", async () => {
    const { app, db, project } = await start({
      invoker: {
        run: async () => ({}),
        runPipelineByName: async () => ({}),
      },
    })
    await seedPipeline(db)

    const opened = await app.inject({
      method: "POST",
      url: `/api/projects/${project.id}/architecture`,
      payload: { branch: "main", commitHash: COMMIT },
    })
    assert.equal(opened.statusCode, 201)

    for (const stage of STAGES) {
      const completed = await app.inject({
        method: "POST",
        url: `/api/agent-executions/${opened.json().executions[stage].id}/completion`,
        payload: { status: "Completed", result: "{}" },
      })
      assert.equal(completed.statusCode, 200)
    }

    const listed = await app.inject({ method: "GET", url: `/api/projects/${project.id}/versions` })
    assert.equal(listed.statusCode, 200)

    const versions = listed.json()
    assert.equal(versions.length, 1)
    assert.equal(versions[0].executions.length, 3)
    assert.deepEqual(versions[0].executions.map((execution: { agentType: string }) => execution.agentType), [...STAGES])
    assert.equal(versions[0].derivedStatus, "Completed")
  })

  it("merges the pipeline-level diagram into the finished architecture row", async () => {
    let appRef: Awaited<ReturnType<typeof start>>["app"] | null = null
    const { app, db, project } = await start({
      invoker: {
        run: async () => ({}),
        runPipelineByName: async (_pipeline, _input, executionIds) => {
          const deadline = Date.now() + 5000
          while (appRef === null && Date.now() < deadline) {
            await new Promise((done) => setTimeout(done, 20))
          }
          assert.ok(appRef !== null)
          const completed = await appRef.inject({
            method: "POST",
            url: `/api/agent-executions/${executionIds["architecture"]}/completion`,
            payload: {
              status: "Completed",
              result: JSON.stringify({ completion_status: "complete", architecture: { organization: [] } }),
            },
          })
          assert.equal(completed.statusCode, 200)
          return {
            diagram: {
              mermaid: "flowchart LR\n  core[core]",
              report_origin: "original",
              report_hash: "abc123",
            },
          }
        },
      },
    })
    appRef = app
    await seedPipeline(db)

    const opened = await app.inject({
      method: "POST",
      url: `/api/projects/${project.id}/architecture`,
      payload: { branch: "main", commitHash: COMMIT },
    })
    assert.equal(opened.statusCode, 201)

    const deadline = Date.now() + 8000
    let mermaid: unknown = null
    while (Date.now() < deadline) {
      const listed = await app.inject({ method: "GET", url: `/api/projects/${project.id}/versions` })
      assert.equal(listed.statusCode, 200)
      const architecture = listed.json()[0].executions.find(
        (execution: { agentType: string }) => execution.agentType === "architecture",
      )
      if (typeof architecture?.result === "string" && architecture.result.includes("flowchart LR")) {
        mermaid = JSON.parse(architecture.result).architecture_diagram
        break
      }
      await new Promise((done) => setTimeout(done, 50))
    }
    assert.equal(typeof mermaid, "object")
    assert.equal((mermaid as { mermaid: string }).mermaid, "flowchart LR\n  core[core]")
    assert.equal((mermaid as { report_origin: string }).report_origin, "original")
  })

  it("404s for an unknown project", async () => {
    const { app } = await start()

    const response = await app.inject({
      method: "POST",
      url: "/api/projects/4242/architecture",
      payload: { branch: "main", commitHash: COMMIT },
    })

    assert.equal(response.statusCode, 404)
  })

  it("400s for a malformed hash", async () => {
    const { app, project } = await start()

    const response = await app.inject({
      method: "POST",
      url: `/api/projects/${project.id}/architecture`,
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
      url: `/api/projects/${project.id}/architecture`,
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
      url: `/api/projects/${project.id}/architecture`,
      payload: { branch: "main", commitHash: COMMIT },
    })

    assert.equal(response.statusCode, 422)
  })

  it("422s naming the stage without model and credential configured", async () => {
    const { app, db, project } = await start()
    // orientation + architecture configured, semantic_validation missing:
    // no partial analysis may be created.
    const provider = await db.aiProvider.create({ data: { name: "test-provider" } })
    const model = await db.aiModel.create({ data: { name: "test-model", aiProviderId: provider.id } })
    const credential = await db.aiCredential.create({
      data: { name: "test-credential", apiKey: "test-key", aiProviderId: provider.id },
    })
    for (const agentType of ["orientation", "architecture"]) {
      await db.agentSettings.upsert({
        where: { agentType },
        create: { agentType, aiModelId: model.id, aiCredentialId: credential.id },
        update: { aiModelId: model.id, aiCredentialId: credential.id },
      })
    }

    const response = await app.inject({
      method: "POST",
      url: `/api/projects/${project.id}/architecture`,
      payload: { branch: "main", commitHash: COMMIT },
    })

    assert.equal(response.statusCode, 422)
    assert.match(response.json().message, /semantic_validation/)
  })

  it("422s when the same version already has an open run", async () => {
    const stalling: AgentInvoker = {
      run: () => new Promise<AgentInput>(() => {}),
      runPipelineByName: () => new Promise<never>(() => {}),
    }
    const { app, db, project } = await start({ invoker: stalling })
    await seedPipeline(db)

    const first = await app.inject({
      method: "POST",
      url: `/api/projects/${project.id}/architecture`,
      payload: { branch: "main", commitHash: COMMIT },
    })
    assert.equal(first.statusCode, 201)

    const second = await app.inject({
      method: "POST",
      url: `/api/projects/${project.id}/architecture`,
      payload: { branch: "main", commitHash: COMMIT },
    })

    assert.equal(second.statusCode, 422)
    assert.match(second.json().message, /already being analyzed/)
  })

  it("fails all three rows when the pipeline cannot start", async () => {
    const unreachable: AgentInvoker = {
      run: async () => ({ kind: "library" }),
      runPipelineByName: async () => {
        throw new Error("Could not reach the agent-server: ECONNREFUSED")
      },
    }
    const { app, db, project } = await start({ invoker: unreachable })
    await seedPipeline(db)

    const opened = await app.inject({
      method: "POST",
      url: `/api/projects/${project.id}/architecture`,
      payload: { branch: "main", commitHash: COMMIT },
    })
    assert.equal(opened.statusCode, 201)

    const deadline = Date.now() + 5000
    let executions: Array<{ status: string }> = []
    while (Date.now() < deadline) {
      const listed = await app.inject({ method: "GET", url: `/api/projects/${project.id}/versions` })
      executions = listed.json()[0]?.executions ?? []
      if (executions.length === 3 && executions.every((execution) => execution.status === "Failed")) {
        break
      }
      await new Promise((done) => setTimeout(done, 20))
    }

    assert.equal(executions.length, 3)
    assert.deepEqual(executions.map((execution) => execution.status), ["Failed", "Failed", "Failed"])
  })
})
