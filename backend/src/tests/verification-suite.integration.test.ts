import { it } from "node:test"
import assert from "node:assert/strict"
import { execSync } from "node:child_process"
import { mkdirSync, mkdtempSync, readFileSync, statSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { buildApp } from "../app.js"
import { makeQualityAuditCatalogSource } from "./helpers/agentCatalog.js"
import { auditResponseSerialization } from "./helpers/responseSerializationAudit.js"
import type { AgentInvoker, AgentInput, PipelineInput, VerificationSuiteOptions } from "../infrastructure/agent-server-client/agent-server.client.js"
import type { AgentCatalogSource } from "../modules/agent-settings/agent-catalog.js"

/** Integration coverage for the verification-suite HTTP surface through the real app wiring:
 *  Fastify routes → QualityAuditService → AgentExecutionService → SQLite (prisma migrate) + the
 *  artifact store on disk. The agent-server boundary is stubbed with a fake invoker; everything
 *  else (routes, schemas, database, artifact manifest parsing, credential resolution) is real. */
const runId = "c".repeat(32)
const hash = "1".repeat(40)
const sections = ["identification"] as const
const suiteSummary = { run_id: runId, action: "create", ok: true, termination_reason: "suite_packaged",
  zip_path: "/tmp/verification-suite.zip", verifications: [{ verification_id: "verification-001", status: "VIOLATION_PRESENT" }],
  validation_status: "partial", limitations: [] }

const suiteCatalog: AgentCatalogSource = (() => {
  const source = makeQualityAuditCatalogSource()
  return { getAgentCatalog: async () => {
    const catalog = await source.getAgentCatalog()
    return { ...catalog, agents: [...catalog.agents, {
      agent_id: "verification_suite", name: "Verification Suite", role: "generator", requires_model: true,
      model_configuration_id: "verification_suite", execution_modes: ["internal"], availability: "available",
      quality_attributes: [], workflow_ids: [], parent_ids: [], child_ids: [],
    }] }
  } }
})()

const flush = () => new Promise<void>((resolve) => { setImmediate(() => setImmediate(() => resolve())) })

it("runs the verification suite end-to-end over HTTP against a completed audit with artifacts", async () => {
  const dir = mkdtempSync(join(tmpdir(), "veraud-suite-it-"))
  const databaseUrl = `file:${join(dir, "test.db")}`
  execSync("pnpm prisma migrate deploy", {
    cwd: fileURLToPath(new URL("../../", import.meta.url)), env: { ...process.env, DATABASE_URL: databaseUrl }, stdio: "ignore",
  })
  const workspaceDir = join(dir, "workspace")
  mkdirSync(join(workspaceDir, "555-acme-shop"), { recursive: true })
  writeFileSync(join(workspaceDir, "555-acme-shop", "main.ts"), "export const value = 1")
  const artifactDir = join(dir, "artifacts")
  const previousArtifacts = process.env.VERAUD_ARTIFACT_DIR
  process.env.VERAUD_ARTIFACT_DIR = artifactDir

  type AuditPayload = Record<string, AgentInput>
  let resolveAudit: (value: AuditPayload) => void = () => {}
  const pendingAudit = new Promise<AuditPayload>((resolve) => { resolveAudit = resolve })
  let suiteDispatched = 0
  let suiteOptions: VerificationSuiteOptions | undefined
  const invoker: AgentInvoker = {
    run: async () => ({}),
    runPipelineByName: async (_name: string, _input: PipelineInput, _executionIds?: Record<string, number>, _configurations?: unknown) => pendingAudit,
    getAuditResult: async (_runId, _selected) => {
      const payload = await pendingAudit
      return (payload["audit"] as AgentInput | undefined) ?? null
    },
    requestVerificationSuite: async (_runId: string, options?: VerificationSuiteOptions) => {
      suiteDispatched += 1
      suiteOptions = options
      return { ...suiteSummary, action: options?.action }
    },
    getVerificationSuite: async () => suiteSummary,
    downloadVerificationSuite: async () => new Response(Buffer.from("PK-suite-zip")),
  }

  try {
    const { app, db } = await buildApp({ databaseUrl, workspaceDir, silent: true, makeAgentCatalogSource: () => suiteCatalog, makeAgentInvoker: () => invoker,
      makeModelAccessVerifier: () => ({ verify: async () => {} }) })
    auditResponseSerialization(app)
    try {
      const project = await db.project.create({ data: { githubRepositoryId: 555n, repositoryOwner: "acme", repositoryName: "shop", status: "READY" } })
      // 1. Seed provider/model/credential; the catalog sync at boot creates the rows (including verification_suite).
      const provider = await db.aiProvider.create({ data: { name: "test-openai" } })
      const model = await db.aiModel.create({ data: { name: "suite-model", aiProviderId: provider.id } })
      const credential = await db.aiCredential.create({ data: { name: "suite-key", apiKey: "suite-test-secret", aiProviderId: provider.id } })
      await db.agentSettings.update({ where: { agentType: "verification_suite" }, data: { aiModelId: model.id, aiCredentialId: credential.id } })

      // 2. Start the (deterministic, model-free) functional adequacy audit and complete it through the mocked pipeline.
      const opened = await app.inject({ method: "POST", url: `/api/projects/${project.id}/audits`, payload: {
        branch: "main", commitHash: hash, attributes: ["functional_adequacy"],
      } })
      assert.equal(opened.statusCode, 202, opened.body)
      const executionId = opened.json().executionId as number
      resolveAudit({ audit: { attributes: ["functional_adequacy"], status: "completed", run_id: runId,
        report: { identification: { audit_id: runId } }, docx_base64: Buffer.from("PK-test-docx").toString("base64") } as AgentInput })
      for (let attempt = 0; attempt < 200; attempt++) {
        if ((await db.agentExecution.findUniqueOrThrow({ where: { id: executionId } })).status === "Completed") break
        await new Promise((resolve) => setTimeout(resolve, 10))
      }
      assert.equal((await db.agentExecution.findUniqueOrThrow({ where: { id: executionId } })).status, "Completed")

      // 3. Materialize the artifact store the way publish_audit_artifacts would, then register the manifest in the row.
      const report = JSON.stringify({ identification: { audit_id: runId }, quality_results: {} })
      const docx = Buffer.from("PK-test-docx")
      const artifactPath = join(artifactDir, runId)
      mkdirSync(join(artifactPath, "sections"), { recursive: true })
      writeFileSync(join(artifactPath, "report.json"), report)
      writeFileSync(join(artifactPath, "report.docx"), docx)
      for (const section of sections) writeFileSync(join(artifactPath, "sections", `${section}.json`), JSON.stringify({ audit_id: runId }))
      const manifest = { format: "veraud.audit.artifacts.v1", run_id: runId,
        report_bytes: Buffer.byteLength(report), docx_bytes: docx.byteLength, sections: [...sections] }
      const stored = await db.agentExecution.findUniqueOrThrow({ where: { id: executionId } })
      const storedResult = JSON.parse(stored.result ?? "{}") as Record<string, unknown>
      storedResult.run_id = runId
      storedResult.artifacts = manifest
      await db.agentExecution.update({ where: { id: executionId }, data: { result: JSON.stringify(storedResult) } })

      // 4. The completed audit's artifacts are served over HTTP (report, DOCX, sections).
      const served = await app.inject({ url: `/api/projects/${project.id}/audits/${executionId}/report` })
      assert.equal(served.statusCode, 200)
      assert.equal(JSON.parse(served.body).identification.audit_id, runId)
      const section = await app.inject({ url: `/api/projects/${project.id}/audits/${executionId}/report/sections/identification` })
      assert.equal(section.statusCode, 200)
      assert.equal(JSON.parse(section.body).data.audit_id, runId)
      const document = await app.inject({ url: `/api/projects/${project.id}/audits/${executionId}/report.docx` })
      assert.equal(document.statusCode, 200)

      // 5. Start the verification-suite generation; the response must not leak the credential.
      const created = await app.inject({ method: "POST", url: `/api/projects/${project.id}/audits/${executionId}/verification-suite` })
      assert.equal(created.statusCode, 202, created.body)
      assert.deepEqual(Object.keys(created.json()).sort(), ["action", "run_id", "status"])
      assert.equal(created.json().status, "building")
      assert.doesNotMatch(created.body, /suite-test-secret/)
      await flush()
      assert.equal(suiteDispatched, 1)
      assert.equal(suiteOptions?.action, "create")
      assert.equal(suiteOptions?.allowExecution, true)
      assert.equal(suiteOptions?.llm, "provider")
      assert.equal((suiteOptions?.config as Record<string, unknown> | undefined)?.["api_key"], "suite-test-secret")

      // 6. A VerificationSuite evaluation and execution row are registered under the audit's project version.
      const suiteEvaluation = await db.evaluation.findFirstOrThrow({ where: { type: "VerificationSuite" } })
      const suiteExecution = await db.agentExecution.findFirstOrThrow({ where: { agentType: "verification_suite" } })
      assert.equal(suiteExecution.evaluationId, suiteEvaluation.id)
      assert.notEqual(suiteExecution.status, "Failed")

      // 7. Poll the status route until the in-memory outcome settles to ready.
      let statusBody = ""
      for (let attempt = 0; attempt < 200; attempt++) {
        const polled = await app.inject({ url: `/api/projects/${project.id}/audits/${executionId}/verification-suite` })
        assert.equal(polled.statusCode, 200)
        statusBody = polled.body
        if (JSON.parse(statusBody).status !== "building") break
        await new Promise((resolve) => setTimeout(resolve, 10))
      }
      const ready = JSON.parse(statusBody)
      assert.equal(ready.status, "ready")
      assert.equal(ready.verifications.length, 1)
      assert.doesNotMatch(statusBody, /suite-test-secret/)

      // 8. The portable ZIP is downloadable.
      const zip = await app.inject({ url: `/api/projects/${project.id}/audits/${executionId}/verification-suite.zip` })
      assert.equal(zip.statusCode, 200)
      assert.match(zip.headers["content-type"] ?? "", /application\/zip/)

      // 9. Artifact bytes on disk match the manifest the report route relied on.
      assert.equal(readFileSync(join(artifactPath, "report.json"), "utf8"), report)
      assert.equal(statSync(join(artifactPath, "report.docx")).size, manifest.docx_bytes)
    } finally {
      await app.close()
      await db.$disconnect()
    }
  } finally {
    if (previousArtifacts === undefined) delete process.env.VERAUD_ARTIFACT_DIR
    else process.env.VERAUD_ARTIFACT_DIR = previousArtifacts
  }
})
