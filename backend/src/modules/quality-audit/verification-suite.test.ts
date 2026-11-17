import { describe, it } from "node:test"
import assert from "node:assert/strict"
import { mkdtemp, mkdir, writeFile } from "node:fs/promises"
import { tmpdir } from "node:os"
import { join } from "node:path"
import Fastify from "fastify"
import { registerApiSchemas } from "../../infrastructure/openapi/registerApiSchemas.js"
import { registerQualityAuditRoutes } from "./quality-audit.controller.js"
import { AuditArtifactStore, auditArtifactFormat } from "./audit-artifacts.js"
import { QualityAuditService } from "./quality-audit.service.js"
import type { QualityAuditRepository } from "./quality-audit.repository.js"
import type { AgentExecutionService } from "../agent-execution/agent-execution.service.js"
import type { ProjectService } from "../project/project.service.js"
import type { VerificationSuiteOptions } from "../../infrastructure/agent-server-client/agent-server.client.js"
import type { AgentSettingsService } from "../agent-settings/agent-settings.service.js"
import { AgentConfigurationError } from "../agent-settings/agent-configuration.js"

const runId = "b".repeat(32)
const COMMIT = "b".repeat(40)
const suiteConfig = { model: { provider: "OpenAI", name: "suite-model", temperature: 0, max_tokens: 24000 }, api_key: "suite-test-secret" }
const configuredModels = { prepareExecution: async (agentTypes: readonly string[]) => {
  assert.deepEqual(agentTypes, ["verification_suite"])
  return [{ agentType: "verification_suite", transport: suiteConfig }]
} } as Pick<AgentSettingsService, "prepareExecution">
const sections = [
  "identification", "executive_summary", "objectives_and_scope", "methodology_and_criteria", "software_description",
  "quality_results", "consolidated_risks", "general_conclusions", "recommendations_and_improvement_plan", "annexes_and_traceability",
]
const qualityResults = {
  findings: [{ id: "F-1", title: "Violating call", description: "Outbound call", kind: "violation",
    components: ["Service"], evidence_ids: ["E-1"], justification: "Route", severity: "high", confidence: 0.9,
    recommendation: "Extract", verification_status: "verified",
    criterion: { id: "C-1", description: "SRP", origin: "explicit", provenance: "docs" } }],
}

async function harness(agents: {
  requestVerificationSuite: (runId: string, options?: VerificationSuiteOptions) => Promise<Record<string, unknown>>
  getVerificationSuite?: (runId: string) => Promise<Record<string, unknown> | null>
}, withSummaryAction: "create" | "execute" | null = null, models: Pick<AgentSettingsService, "prepareExecution"> | undefined = configuredModels) {
  const root = await mkdtemp(join(tmpdir(), "veraud-suite-"))
  const target = join(root, runId)
  await mkdir(join(target, "sections"), { recursive: true })
  const report = JSON.stringify({ quality_results: qualityResults })
  const document = Buffer.from("PK-test-artifact")
  await writeFile(join(target, "report.json"), report)
  await writeFile(join(target, "report.docx"), document)
  if (withSummaryAction) {
    await writeFile(join(target, "verification-suite-summary.json"), JSON.stringify({
      run_id: runId, ok: true, termination_reason: withSummaryAction === "execute" ? "suite_validated" : "suite_packaged",
      verifications: [{ verification_id: "verification-001", status: "VIOLATION_PRESENT" }],
      validation_status: "partial", limitations: [], action: withSummaryAction,
    }))
  }
  const manifest = { format: auditArtifactFormat, run_id: runId, report_bytes: Buffer.byteLength(report), docx_bytes: document.byteLength, sections }
  const row = { id: 12, agentType: "maintainability_manager", status: "Completed", evaluation: { projectVersion: { branch: "main", commitHash: COMMIT } },
    result: JSON.stringify({ attributes: ["maintainability"], status: "completed", run_id: runId, error_detail: null, artifacts: manifest }) }
  const repository = { find: async (projectId: number, id: number) => projectId === 9 && id === 12 ? row : null } as unknown as QualityAuditRepository
  const executions = {} as unknown as AgentExecutionService
  const service = new QualityAuditService(repository, {} as ProjectService, executions, undefined,
    { requestVerificationSuite: agents.requestVerificationSuite, ...(agents.getVerificationSuite ? { getVerificationSuite: agents.getVerificationSuite } : {}) }, new AuditArtifactStore(undefined, root), models)
  const app = Fastify({ logger: false })
  registerApiSchemas(app)
  registerQualityAuditRoutes(app, service)
  return { app, service, target }
}

const flush = () => new Promise<void>((resolve) => { setImmediate(() => setImmediate(() => resolve())) })

describe("verification-suite fire-and-poll flow", () => {
  it("forwards saved suite access only for generation, without exposing the credential", async () => {
    const calls: VerificationSuiteOptions[] = []
    const { app } = await harness({ requestVerificationSuite: async (_id, options) => {
      calls.push(options!)
      return { run_id: runId, action: options?.action, ok: true }
    } })
    try {
      const created = await app.inject({ method: "POST", url: "/api/projects/9/audits/12/verification-suite" })
      assert.equal(created.statusCode, 202)
      assert.doesNotMatch(created.body, /suite-test-secret/)
      await flush()
      assert.deepEqual(calls[0]?.config, suiteConfig)
      assert.equal(calls[0]?.allowExecution, true, "generation must execute tests to validate and repair their oracles")
      assert.doesNotMatch((await app.inject({ url: "/api/projects/9/audits/12/verification-suite" })).body, /suite-test-secret/)
      await app.inject({ method: "POST", url: "/api/projects/9/audits/12/verification-suite", payload: { action: "execute" } })
      await flush()
      assert.equal(calls[1]?.config, undefined)
    } finally { await app.close() }
  })

  it("rejects unconfigured generation before dispatch but allows model-free re-execution", async () => {
    let calls = 0
    const models = { prepareExecution: async () => { throw new AgentConfigurationError([{ agentType: "verification_suite", reason: "Assign a model and credential in Settings" }]) } }
    const { app } = await harness({ requestVerificationSuite: async () => { calls += 1; return { run_id: runId } } }, null, models)
    try {
      const denied = await app.inject({ method: "POST", url: "/api/projects/9/audits/12/verification-suite" })
      assert.equal(denied.statusCode, 422)
      assert.match(denied.body, /verification_suite/)
      assert.equal(calls, 0)
      const executed = await app.inject({ method: "POST", url: "/api/projects/9/audits/12/verification-suite", payload: { action: "execute" } })
      assert.equal(executed.statusCode, 202)
      await flush()
      assert.equal(calls, 1)
    } finally { await app.close() }
  })
  it("forwards an explicit commit only for execution and rejects invalid hashes before dispatch", async () => {
    const seen: unknown[] = []
    const { app } = await harness({ requestVerificationSuite: async (_id, options) => {
      seen.push(options)
      return { run_id: runId, action: "execute", target_commit: options?.targetCommit, checkout_commit: options?.targetCommit }
    } })
    try {
      for (const payload of [{ action: "execute", targetCommit: "HEAD" }, { action: "create", targetCommit: "a".repeat(40) }]) {
        const invalid = await app.inject({ method: "POST", url: "/api/projects/9/audits/12/verification-suite", payload })
        assert.equal(invalid.statusCode, 400)
      }
      assert.equal(seen.length, 0)
      const response = await app.inject({ method: "POST", url: "/api/projects/9/audits/12/verification-suite", payload: { action: "execute", targetCommit: "A".repeat(40) } })
      assert.equal(response.statusCode, 202)
      await flush()
      assert.equal((seen[0] as { targetCommit: string }).targetCommit, "a".repeat(40))
      const result = (await app.inject({ method: "GET", url: "/api/projects/9/audits/12/verification-suite?action=execute" })).json()
      assert.equal(result.checkout_commit, "a".repeat(40))
    } finally { await app.close() }
  })
  it("POST returns 202 building and GET reaches ready with the agent summary", async () => {
    let calls = 0
    let finish!: () => void
    const gate = new Promise<void>((resolve) => { finish = resolve })
    const { app } = await harness({
      requestVerificationSuite: async () => { calls += 1; await gate; return { run_id: runId, ok: true, termination_reason: "suite_packaged", zip_path: "/tmp/verification-suite.zip", verifications: [{ verification_id: "verification-001", status: "VIOLATION_PRESENT" }], validation_status: "partial", limitations: [] } },
      getVerificationSuite: async () => ({ run_id: runId, ok: true, termination_reason: "suite_packaged", zip_path: "/tmp/verification-suite.zip", verifications: [{ verification_id: "verification-001", status: "VIOLATION_PRESENT" }], validation_status: "partial", limitations: [] }),
    })
    const posted = await app.inject({ method: "POST", url: "/api/projects/9/audits/12/verification-suite" })
    assert.equal(posted.statusCode, 202)
    assert.deepEqual(JSON.parse(posted.body), { status: "building", run_id: runId, action: "create" })
    assert.equal(calls, 1)
    const during = await app.inject({ method: "GET", url: "/api/projects/9/audits/12/verification-suite" })
    assert.equal(during.statusCode, 200)
    assert.equal(JSON.parse(during.body).status, "building")
    const double = await app.inject({ method: "POST", url: "/api/projects/9/audits/12/verification-suite" })
    assert.equal(double.statusCode, 202)
    assert.equal(calls, 1, "a second POST while building does not launch a duplicate pipeline")
    finish()
    await flush()
    const ready = await app.inject({ method: "GET", url: "/api/projects/9/audits/12/verification-suite" })
    assert.equal(ready.statusCode, 200)
    assert.equal(JSON.parse(ready.body).status, "ready")
    assert.equal(JSON.parse(ready.body).verifications.length, 1)
    await app.close()
  })

  it("failure of the agent call surfaces status=failed with the error message", async () => {
    const { app } = await harness({
      requestVerificationSuite: async () => { await Promise.resolve(); throw new Error("provider unusable") },
    })
    const posted = await app.inject({ method: "POST", url: "/api/projects/9/audits/12/verification-suite" })
    assert.equal(posted.statusCode, 202)
    await flush()
    const state = await app.inject({ method: "GET", url: "/api/projects/9/audits/12/verification-suite" })
    assert.equal(JSON.parse(state.body).status, "failed")
    assert.match(JSON.parse(state.body).message, /generation failed/)
    await app.close()
  })

  it("not built yet and unknown audit behave predictably", async () => {
    const { app } = await harness({
      requestVerificationSuite: async () => ({ run_id: runId }),
      getVerificationSuite: async () => null,
    })
    const missing = await app.inject({ method: "GET", url: "/api/projects/9/audits/99/verification-suite" })
    assert.equal(missing.statusCode, 404)
    const notBuilt = await app.inject({ method: "GET", url: "/api/projects/9/audits/12/verification-suite" })
    assert.equal(JSON.parse(notBuilt.body).status, "not_built")
    await app.close()
  })

  it("a summary on disk wins over the agent-server: status read works while the agent is busy", async () => {
    let agentReads = 0
    const { app } = await harness({
      requestVerificationSuite: async () => ({ run_id: runId }),
      getVerificationSuite: async () => { agentReads += 1; throw new Error("fetch failed") },
    }, "create")
    const state = await app.inject({ method: "GET", url: "/api/projects/9/audits/12/verification-suite" })
    assert.equal(JSON.parse(state.body).status, "ready")
    assert.equal(JSON.parse(state.body).verifications.length, 1)
    assert.equal(agentReads, 0, "the agent server is not consulted when the artifact exists")
    await app.close()
  })

  it("gates create and execute statuses against each other across actions", async () => {
    let seen: VerificationSuiteOptions | undefined
    const { app } = await harness({
      requestVerificationSuite: async (_runId, options) => { seen = options; return { run_id: runId } },
      getVerificationSuite: async () => null,
    }, "execute")
    const createState = await app.inject({ method: "GET", url: "/api/projects/9/audits/12/verification-suite?action=create" })
    assert.equal(JSON.parse(createState.body).status, "not_built")
    const executeState = await app.inject({ method: "GET", url: "/api/projects/9/audits/12/verification-suite?action=execute" })
    assert.equal(JSON.parse(executeState.body).status, "ready")
    assert.equal(JSON.parse(executeState.body).termination_reason, "suite_validated")
    const res = await app.inject({ method: "POST", url: "/api/projects/9/audits/12/verification-suite", payload: { action: "execute", greenControl: "C:/tmp/green" } })
    assert.equal(res.statusCode, 202)
    await flush()
    assert.deepEqual([seen?.action, seen?.allowExecution, seen?.greenControl === "C:/tmp/green"], ["execute", true, true])
    await app.close()
  })

  it("falls back to the agent-server when the disk summary is absent", async () => {
    let agentReads = 0
    const { app } = await harness({
      requestVerificationSuite: async () => ({ run_id: runId }),
      getVerificationSuite: async (runId: string) => { agentReads += 1; return { run_id: runId, ok: true, verifications: [], validation_status: "partial", limitations: [] } },
    }, null)
    const state = await app.inject({ method: "GET", url: "/api/projects/9/audits/12/verification-suite?action=create" })
    assert.equal(JSON.parse(state.body).status, "ready")
    assert.equal(agentReads, 1)
    await app.close()
  })

  it("an unreachable agent-server does not turn status reads into terminal failures", async () => {
    const { app } = await harness({
      requestVerificationSuite: async () => ({ run_id: runId }),
      getVerificationSuite: async () => { throw new Error("fetch failed") },
    })
    const state = await app.inject({ method: "GET", url: "/api/projects/9/audits/12/verification-suite" })
    assert.equal(JSON.parse(state.body).status, "recovering")
    assert.match(JSON.parse(state.body).message, /agent server/)
    await app.close()
  })

  it("recovers the current artifact after a transport failure, rejecting stale results and duplicate dispatch", async () => {
    let attemptId: string | undefined
    let calls = 0
    const { app, target } = await harness({
      requestVerificationSuite: async (_runId, options) => {
        calls += 1
        attemptId = options?.attemptId
        throw new TypeError("fetch failed")
      },
      getVerificationSuite: async () => { throw new TypeError("fetch failed") },
    }, "create")
    try {
      await app.inject({ method: "POST", url: "/api/projects/9/audits/12/verification-suite" })
      await flush()
      const read = () => app.inject({ method: "GET", url: "/api/projects/9/audits/12/verification-suite" })
      assert.equal((await read()).json().status, "recovering", "old summary must not masquerade as the current result")
      assert.ok(attemptId)
      await app.inject({ method: "POST", url: "/api/projects/9/audits/12/verification-suite" })
      assert.equal(calls, 1)
      await writeFile(join(target, "verification-suite-summary.json"), JSON.stringify({
        run_id: runId, action: "create", attempt_id: attemptId, ok: true,
        verifications: [{ verification_id: "current-test" }], validation_status: "generated", limitations: [],
      }))
      const result = (await read()).json()
      assert.equal(result.status, "ready")
      assert.equal(result.verifications[0].verification_id, "current-test")
      assert.equal(calls, 1, "recovery only reads, never regenerates")
    } finally { await app.close() }
  })

  it("threads a group filter through execute and rejects it for create", async () => {
    let seen: VerificationSuiteOptions | undefined
    const { app } = await harness({
      requestVerificationSuite: async (_runId, options) => { seen = options; return { run_id: runId, action: "execute", selection: options?.group ? [options.group] : ["all"] } },
      getVerificationSuite: async () => null,
    })
    try {
      for (const payload of [
        { action: "create", group: "testability" },
        { action: "execute", group: "Bad Group!" },
      ]) {
        const invalid = await app.inject({ method: "POST", url: "/api/projects/9/audits/12/verification-suite", payload })
        assert.equal(invalid.statusCode, 400)
      }
      const seenBeforeExecute = seen
      assert.equal(seenBeforeExecute, undefined)
      const res = await app.inject({ method: "POST", url: "/api/projects/9/audits/12/verification-suite", payload: { action: "execute", group: "testability" } })
      assert.equal(res.statusCode, 202)
      await flush()
      assert.equal(seen?.action, "execute")
      assert.equal(seen?.allowExecution, true)
      assert.equal(seen?.group, "testability")
      assert.equal(seen?.llm, "provider")
      assert.equal(seen?.timeoutMs, 1_800_000)
      const state = await app.inject({ method: "GET", url: "/api/projects/9/audits/12/verification-suite?action=execute&group=testability" })
      assert.equal(state.statusCode, 200)
      assert.equal(JSON.parse(state.body).status, "ready")
    } finally { await app.close() }
  })
})
