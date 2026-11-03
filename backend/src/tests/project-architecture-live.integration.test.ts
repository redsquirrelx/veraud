import { describe, it } from "node:test"
import assert from "node:assert/strict"
import { execSync, spawn, type ChildProcess } from "node:child_process"
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { createServer } from "node:net"
import { buildApp } from "../app.js"
import { projectWorkspaceFolder } from "../modules/project/project-workspace.js"
import { auditResponseSerialization } from "./helpers/responseSerializationAudit.js"

const backendRoot = fileURLToPath(new URL("../../", import.meta.url))
const agentServerRoot = join(backendRoot, "..", "agent-server")
const agentServerPython = process.platform === "win32"
  ? join(agentServerRoot, ".venv", "Scripts", "python.exe")
  : join(agentServerRoot, ".venv", "bin", "python")

function freshDatabase(): string {
  const dir = mkdtempSync(join(tmpdir(), "veraud-palv-"))
  const url = `file:${join(dir, "test.db")}`
  execSync("pnpm prisma migrate deploy", {
    cwd: backendRoot,
    env: { ...process.env, DATABASE_URL: url },
    stdio: "ignore",
  })
  return url
}

async function freePort(): Promise<number> {
  const server = createServer()
  await new Promise<void>((done) => server.listen(0, "127.0.0.1", done))
  const address = server.address()
  assert.ok(address && typeof address !== "string")
  const port = address.port
  await new Promise<void>((done) => server.close(() => done()))
  return port
}

async function waitForAgentServer(baseUrl: string, timeoutMs: number): Promise<void> {
  const deadline = Date.now() + timeoutMs
  for (;;) {
    try {
      const response = await fetch(`${baseUrl}/api/status`)
      if (response.ok) return
    } catch {
      // Not up yet.
    }
    if (Date.now() >= deadline) throw new Error(`Agent-server did not start at ${baseUrl}`)
    await new Promise((done) => setTimeout(done, 1000))
  }
}

// Live crossing: real backend HTTP + real agent-server process + real
// callbacks. Only the model calls are offline (AGENT_SERVER_SMOKE_MODELS),
// so snapshots, graphs, hooks, tracing ports and rows are all exercised.
describe("live pipelines", () => {
  it("runs architecture and exploratory functional adequacy over real HTTP", { timeout: 300_000 }, async () => {
    // Live crossing needs the real shared workspace: the agent-server only
    // accepts checkouts directly inside it (same default both sides resolve).
    const workspaceDir = join(backendRoot, "..", "appdata", "workspace")
    const githubRepositoryId = BigInt(Date.now()) * 1000n + BigInt(Math.floor(Math.random() * 1000))
    const noopRunner = { enqueue: async () => ({ status: "Succeded", exitCode: 0, logTrail: "" }) }
    let checkout: string | null = null
    let checkoutCreated = false

    // Both ports are fixed upfront: the agent-server needs PORT_BACKEND at
    // boot for callbacks, and the backend needs the agent-server URL to
    // dispatch. The backend listens on its port right after building.
    const backendPort = await freePort()
    const agentPort = await freePort()
    const agentBase = `http://127.0.0.1:${agentPort}`

    const stderr: string[] = []
    const child: ChildProcess = spawn(
      agentServerPython,
      ["-m", "uvicorn", "server.main:app", "--host", "127.0.0.1", "--port", String(agentPort)],
      {
        cwd: join(agentServerRoot, "src"),
        env: {
          ...process.env,
          PORT_BACKEND: String(backendPort),
          PORT_AGENTSERVER: String(agentPort),
          LLM_API_KEY: "dummy-live-key",
          LANGSMITH_API_KEY: "",
          AGENT_SERVER_SMOKE_MODELS: "1",
        },
        stdio: ["ignore", "ignore", "pipe"],
      },
    )
    child.stderr?.on("data", (chunk: Buffer) => stderr.push(chunk.toString()))
    child.on("error", () => {})

    const { app, db } = await buildApp({
      databaseUrl: freshDatabase(),
      workspaceDir,
      silent: true,
      makeRunner: () => noopRunner,
      makeModelAccessVerifier: () => ({ verify: async () => {} }),
      agentServerUrl: agentBase,
    })
    auditResponseSerialization(app)
    await new Promise<void>((resolve, reject) => {
      app.listen({ port: backendPort, host: "127.0.0.1" }, (error) => {
        if (error) reject(error)
        else resolve()
      })
    })

    try {
      await waitForAgentServer(agentBase, 120_000)

      const project = await db.project.create({
        data: { githubRepositoryId, repositoryOwner: "acme", repositoryName: "live-shop", status: "READY" },
      })
      checkout = join(workspaceDir, projectWorkspaceFolder(project))
      mkdirSync(checkout)
      checkoutCreated = true
      writeFileSync(join(checkout, "main.py"), "def main():\n    return 1\n")
      writeFileSync(join(checkout, "README.md"), "# shop\n")

      const provider = await db.aiProvider.create({ data: { name: "test-provider" } })
      const model = await db.aiModel.create({ data: { name: "test-model", aiProviderId: provider.id } })
      const credential = await db.aiCredential.create({
        data: { name: "test-credential", apiKey: "test-key", aiProviderId: provider.id },
      })
      for (const agentType of ["orientation", "architecture", "semantic_validation"]) {
        await db.agentSettings.upsert({
          where: { agentType },
          create: { agentType, aiModelId: model.id, aiCredentialId: credential.id },
          update: { aiModelId: model.id, aiCredentialId: credential.id },
        })
      }

      const opened = await app.inject({
        method: "POST",
        url: `/api/projects/${project.id}/architecture`,
        payload: { branch: "main", commitHash: "a".repeat(40) },
      })
      assert.equal(opened.statusCode, 201, `expected 201, got ${opened.statusCode}: ${opened.body.slice(0, 500)}`)

      const deadline = Date.now() + 240_000
      let executions: Array<{ agentType: string; status: string; result: string | null; error: string | null }> = []
      let derived = ""
      while (Date.now() < deadline) {
        const listed = await app.inject({ method: "GET", url: `/api/projects/${project.id}/versions` })
        executions = listed.json()[0]?.executions ?? []
        derived = listed.json()[0]?.derivedStatus ?? ""
        if (derived === "Completed" || derived === "Failed") break
        await new Promise((done) => setTimeout(done, 2000))
      }

      assert.equal(derived, "Completed", `pipeline did not complete (agent-server stderr: ${stderr.join("").slice(-2000)})`)
      assert.deepEqual(executions.map((execution) => execution.agentType), ["orientation", "architecture", "semantic_validation"])
      for (const execution of executions) {
        assert.equal(execution.status, "Completed")
        assert.ok(execution.result, `stage ${execution.agentType} stored no result`)
        const parsed = JSON.parse(execution.result!) as { completion_status?: string }
        assert.ok(typeof parsed === "object" && parsed !== null)
      }

      const functionalHash = "b".repeat(40)
      const functionalOpened = await app.inject({
        method: "POST",
        url: `/api/projects/${project.id}/functional-adequacy`,
        payload: { branch: "main", commitHash: functionalHash },
      })
      assert.equal(functionalOpened.statusCode, 201, `expected 201, got ${functionalOpened.statusCode}: ${functionalOpened.body.slice(0, 500)}`)

      const functionalDeadline = Date.now() + 120_000
      let functionalExecution: { status: string; result: string | null; error: string | null } | null = null
      let functionalDerived = ""
      while (Date.now() < functionalDeadline) {
        const listed = await app.inject({ method: "GET", url: `/api/projects/${project.id}/versions` })
        const version = (listed.json() as Array<{ commitHash: string, derivedStatus: string, executions: Array<{ agentType: string, status: string, result: string | null, error: string | null }> }>)
          .find((item) => item.commitHash === functionalHash)
        functionalExecution = version?.executions.find((execution) => execution.agentType === "functional_adequacy") ?? null
        functionalDerived = version?.derivedStatus ?? ""
        if (functionalDerived === "Completed" || functionalDerived === "Failed") break
        await new Promise((done) => setTimeout(done, 2000))
      }

      assert.equal(functionalDerived, "Completed", `functional pipeline did not complete (agent-server stderr: ${stderr.join("").slice(-2000)})`)
      assert.ok(functionalExecution !== null)
      assert.equal(functionalExecution.status, "Completed")
      assert.ok(functionalExecution.result)
      const functional = JSON.parse(functionalExecution.result!) as {
        audit_mode?: string
        score_applicable?: boolean
        results?: unknown[]
        capabilities?: Array<{ evidence?: Array<{ file_path?: string, start_line?: number | null }> }>
        findings?: unknown[]
        subattributes?: Array<{ attribute?: string }>
      }
      assert.equal(functional.audit_mode, "exploratory")
      assert.equal(functional.score_applicable, false)
      assert.deepEqual(functional.results, [])
      assert.deepEqual((functional.subattributes ?? []).map((item) => item.attribute).sort(), ["completitud", "correccion", "pertinencia"])
      assert.ok((functional.capabilities ?? []).length > 0)
      assert.ok((functional.capabilities ?? []).some((capability) => (capability.evidence ?? []).some((evidence) => typeof evidence.file_path === "string" && evidence.file_path !== "" && typeof evidence.start_line === "number")))
    } finally {
      if (child !== null) {
        child.kill()
        await new Promise((done) => setTimeout(done, 1000))
        if (child.exitCode === null) child.kill("SIGKILL")
      }
      await app.close()
      await db.$disconnect()
      if (checkoutCreated && checkout !== null) rmSync(checkout, { recursive: true, force: true })
    }
  })
})
