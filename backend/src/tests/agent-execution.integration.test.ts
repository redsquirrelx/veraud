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

/** The folder the project module clones into, and what an agent gets pointed at. */
const CHECKOUT = "999888777-acme-widgets"

/** open() now starts the agent in the background, so the endpoint tests below
 *  need it to stay put: a run that finished on its own would race their
 *  assertions. Each of those tests is about the endpoints, not the dispatch. */
const stallingInvoker: AgentInvoker = {
  run: () => new Promise<AgentInput>(() => {}),
}

describe("agent execution endpoints", () => {
  let closers: Array<() => Promise<void>> = []

  afterEach(async () => {
    for (const close of closers) {
      await close()
    }
    closers = []
  })

  /** A project with a real checkout is the normal case, so it is the default: the
 *  background dispatch only stays quiet when it can resolve its input. */
async function start(options: { invoker?: AgentInvoker; withCheckout?: boolean } = {}) {
    const workspaceDir = mkdtempSync(join(tmpdir(), "veraud-ws-"))

    if (options.withCheckout !== false) {
      const checkout = join(workspaceDir, CHECKOUT)
      mkdirSync(checkout, { recursive: true })
      // An empty directory does not count as a checkout: the resolver wants
      // something in it, exactly as it does for a real clone.
      writeFileSync(join(checkout, "README.md"), "# fixtures\n")
    }

    const { app, db } = await buildApp({
      databaseUrl: freshDatabase(),
      workspaceDir,
      silent: true,
      makeRunner: () => noopRunner,
      makeAgentInvoker: () => options.invoker ?? stallingInvoker,
    })

    closers.push(async () => {
      await app.close()
      await db.$disconnect()
    })

    return { app, db, workspaceDir }
  }

  type Db = Awaited<ReturnType<typeof buildApp>>["db"]

  /** open() dispatches in the background, so a test has to wait for the row to
   *  settle rather than assume it already has. */
  async function waitForStatus(db: Db, id: number, expected: string) {
    const deadline = Date.now() + 5000

    while (Date.now() < deadline) {
      const row = await db.agentExecution.findUnique({ where: { id } })

      if (row !== null && row.status === expected) {
        return row
      }

      await tick()
    }

    throw new Error(`Execution ${id} never reached ${expected}`)
  }

  /** Polls until `ready` holds, so a background dispatch can be observed. */
  async function waitFor(ready: () => boolean): Promise<void> {
    const deadline = Date.now() + 5000

    while (Date.now() < deadline) {
      if (ready()) {
        return
      }

      await tick()
    }

    throw new Error("Timed out waiting for the background dispatch")
  }

  const tick = (): Promise<void> => new Promise((done) => setTimeout(done, 20))

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

  it("returns before the agent finishes", async () => {
    const { app, db } = await start({ withCheckout: true })
    await seedSettings(db, "analyzer")
    const { evaluation } = await seedEvaluation(db)

    const opened = await app.inject({
      method: "POST",
      url: "/api/agent-executions",
      payload: { agentType: "analyzer", evaluationId: evaluation.id },
    })

    // The invoker never settles, so this holds only if open() did not wait.
    assert.equal(opened.statusCode, 201)
    assert.equal(opened.json().status, "Waiting")
  })

  it("invokes the agent with the checkout path and this execution's id", async () => {
    const seen: Array<{ agentType: string; input: AgentInput; executionId: number }> = []
    const invoker: AgentInvoker = {
      run: async (agentType, input, executionId) => {
        seen.push({ agentType, input, executionId })
        return { kind: "library", confidence: "high" }
      },
    }

    const { app, db, workspaceDir } = await start({ invoker, withCheckout: true })
    await seedSettings(db, "analyzer")
    const { evaluation } = await seedEvaluation(db)

    const opened = await app.inject({
      method: "POST",
      url: "/api/agent-executions",
      payload: { agentType: "analyzer", evaluationId: evaluation.id },
    })

    const id = opened.json().id as number

    await waitFor(() => seen.length === 1)

    assert.equal(seen[0]?.agentType, "analyzer")
    assert.equal(seen[0]?.input.root_path, join(workspaceDir, CHECKOUT))
    // The agent reports its own progress against this id, so it has to be the
    // row this run created.
    assert.equal(seen[0]?.executionId, id)

    // A successful hand-off is not a finished run: the agent closes the row.
    const row = await db.agentExecution.findUnique({ where: { id } })
    assert.equal(row?.status, "Waiting")
  })

  it("records the result the agent reports back", async () => {
    const { app, db } = await start({ withCheckout: true })
    await seedSettings(db, "analyzer")
    const { evaluation } = await seedEvaluation(db)

    const opened = await app.inject({
      method: "POST",
      url: "/api/agent-executions",
      payload: { agentType: "analyzer", evaluationId: evaluation.id },
    })

    const { id } = opened.json()
    const description = JSON.stringify({ kind: "library", confidence: "high" })

    await app.inject({
      method: "POST",
      url: `/api/agent-executions/${id}/running`,
    })

    await app.inject({
      method: "POST",
      url: `/api/agent-executions/${id}/completion`,
      payload: { status: "Completed", result: description },
    })

    const row = await waitForStatus(db, id, "Completed")

    assert.equal(row.result, description)
    assert.notEqual(row.startedAt, null)
    assert.notEqual(row.finishedAt, null)
  })

  it("records the failure the agent reports back", async () => {
    const { app, db } = await start({ withCheckout: true })
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
      payload: { status: "Failed", error: "Agent timed out after 120s" },
    })

    const row = await waitForStatus(db, id, "Failed")

    assert.match(row.error ?? "", /timed out/)
    assert.equal(row.result, null)
  })

  it("fails the run when the agent-server cannot be reached", async () => {
    const invoker: AgentInvoker = {
      run: async () => {
        throw new Error("Could not reach the agent-server: ECONNREFUSED")
      },
    }

    const { app, db } = await start({ invoker, withCheckout: true })
    await seedSettings(db, "analyzer")
    const { evaluation } = await seedEvaluation(db)

    const opened = await app.inject({
      method: "POST",
      url: "/api/agent-executions",
      payload: { agentType: "analyzer", evaluationId: evaluation.id },
    })

    const row = await waitForStatus(db, opened.json().id, "Failed")

    assert.match(row.error ?? "", /ECONNREFUSED/)
    assert.equal(row.result, null)
    assert.notEqual(row.finishedAt, null)
  })

  it("never reaches the agent when the project has no checkout", async () => {
    let called = false
    const invoker: AgentInvoker = {
      run: async () => {
        called = true
        return {}
      },
    }

    const { app, db } = await start({ invoker, withCheckout: false })
    await seedSettings(db, "analyzer")
    const { evaluation } = await seedEvaluation(db)

    const opened = await app.inject({
      method: "POST",
      url: "/api/agent-executions",
      payload: { agentType: "analyzer", evaluationId: evaluation.id },
    })

    const row = await waitForStatus(db, opened.json().id, "Failed")

    assert.equal(called, false)
    assert.match(row.error ?? "", /no local checkout/)
  })

  it("422s when the evaluation does not exist", async () => {
    const { app, db } = await start()
    await seedSettings(db, "analyzer")

    const response = await app.inject({
      method: "POST",
      url: "/api/agent-executions",
      payload: { agentType: "analyzer", evaluationId: 9999 },
    })

    // evaluation_id is a foreign key, so the row cannot exist. That is a bad
    // request, not a server fault.
    assert.equal(response.statusCode, 422)
    assert.match(response.json().error, /evaluation 9999 does not exist/)
  })

it("422s when the agent type is not registered", async () => {
    const { app, db } = await start()
    const { evaluation } = await seedEvaluation(db)

    const response = await app.inject({
      method: "POST",
      url: "/api/agent-executions",
      payload: { agentType: "not-an-agent", evaluationId: evaluation.id },
    })

    assert.equal(response.statusCode, 422)
    assert.match(response.json().error, /not-an-agent/)
  })

  it("opens a direct run without an evaluation and hands the input over", async () => {
    const seen: Array<{ agentType: string; input: AgentInput; executionId: number }> = []
    const invoker: AgentInvoker = {
      run: async (agentType, input, executionId) => {
        seen.push({ agentType, input, executionId })
        return { kind: "library" }
      },
    }

    const { app, db, workspaceDir } = await start({ invoker, withCheckout: true })
    await seedSettings(db, "analyzer")

    const opened = await app.inject({
      method: "POST",
      url: "/api/agent-executions/direct",
      payload: { agentType: "analyzer", input: { root_path: CHECKOUT } },
    })

    assert.equal(opened.statusCode, 201)
    assert.equal(opened.json().agentType, "analyzer")
    assert.equal(opened.json().evaluationId, null)
    assert.equal(opened.json().status, "Waiting")

    const id = opened.json().id as number

    await waitFor(() => seen.length === 1)

    assert.equal(seen[0]?.agentType, "analyzer")
    assert.equal(seen[0]?.input.root_path, join(workspaceDir, CHECKOUT))
    assert.equal(seen[0]?.executionId, id)
  })

  it("passes a direct input without root_path through untouched", async () => {
    const seen: Array<{ agentType: string; input: AgentInput; executionId: number }> = []
    const invoker: AgentInvoker = {
      run: async (agentType, input, executionId) => {
        seen.push({ agentType, input, executionId })
        return { score: 80 }
      },
    }

    const { app, db } = await start({ invoker, withCheckout: true })
    await seedSettings(db, "dummy")

    const opened = await app.inject({
      method: "POST",
      url: "/api/agent-executions/direct",
      payload: { agentType: "dummy", input: { code: "print(1)" } },
    })

    assert.equal(opened.statusCode, 201)
    assert.equal(opened.json().evaluationId, null)

    await waitFor(() => seen.length === 1)

    assert.deepEqual(seen[0]?.input, { code: "print(1)" })
  })

  it("422s a direct run that escapes the workspace", async () => {
    const { app, db } = await start()
    await seedSettings(db, "analyzer")

    const response = await app.inject({
      method: "POST",
      url: "/api/agent-executions/direct",
      payload: { agentType: "analyzer", input: { root_path: "../evil" } },
    })

    assert.equal(response.statusCode, 422)
    assert.match(response.json().error, /workspace/)
  })

  it("400s a direct run without an input", async () => {
    const { app } = await start()

    const response = await app.inject({
      method: "POST",
      url: "/api/agent-executions/direct",
      payload: { agentType: "analyzer" },
    })

    assert.equal(response.statusCode, 400)
  })

  it("fails a direct run when the checkout is missing", async () => {
    let called = false
    const invoker: AgentInvoker = {
      run: async () => {
        called = true
        return {}
      },
    }

    const { app, db } = await start({ invoker, withCheckout: false })
    await seedSettings(db, "analyzer")

    const opened = await app.inject({
      method: "POST",
      url: "/api/agent-executions/direct",
      payload: { agentType: "analyzer", input: { root_path: "ghost" } },
    })

    assert.equal(opened.statusCode, 201)

    const row = await waitForStatus(db, opened.json().id, "Failed")

    assert.equal(called, false)
    assert.match(row.error ?? "", /No local checkout/)
  })

  it("422s a direct run with an unknown agent type", async () => {
    const { app } = await start({ withCheckout: true })

    const response = await app.inject({
      method: "POST",
      url: "/api/agent-executions/direct",
      payload: { agentType: "not-an-agent", input: { code: "x" } },
    })

    assert.equal(response.statusCode, 422)
    assert.match(response.json().error, /not-an-agent/)
  })
})