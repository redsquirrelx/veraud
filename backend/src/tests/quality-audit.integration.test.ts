import { it } from "node:test"
import { once } from "node:events"
import assert from "node:assert/strict"
import { execSync } from "node:child_process"
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { buildApp } from "../app.js"
import { AuditSettingsService } from "../modules/quality-audit/audit-settings.service.js"
import { makeQualityAuditCatalogSource, TEST_MAINTAINABILITY_AGENTS } from "./helpers/agentCatalog.js"
import { auditResponseSerialization } from "./helpers/responseSerializationAudit.js"
import type { AgentInput, PipelineInput } from "../infrastructure/agent-server-client/agent-server.client.js"
import { AgentTransportError } from "../infrastructure/agent-server-client/agent-server.client.js"

const selections = [["maintainability"], ["security"], ["maintainability", "security"], ["security", "maintainability"],
  ["functional_adequacy"], ["maintainability", "functional_adequacy"], ["security", "functional_adequacy"],
  ["maintainability", "security", "functional_adequacy"]]
for (const { attributes, disconnect } of [...selections.map((attributes) => ({ attributes, disconnect: false })),
  { attributes: ["maintainability"], disconnect: true }]) {
it(`runs a ${attributes.join("+")} audit${disconnect ? " after losing its HTTP connection" : ""} and persists one partial report and Word artifact independently of architecture`, async () => {
  const agentType = attributes.includes("maintainability") ? "maintainability_manager" : attributes.includes("security") ? "security" : "functional_adequacy"
   const agents = [...(attributes.includes("maintainability") ? TEST_MAINTAINABILITY_AGENTS : []),
     ...(attributes.includes("security") ? ["security"] : []),
     ...(attributes.includes("functional_adequacy") ? ["functional_adequacy"] : [])]
  const dir = mkdtempSync(join(tmpdir(), "veraud-quality-"))
  const databaseUrl = `file:${join(dir, "test.db")}`
  execSync("pnpm prisma migrate deploy", {
    cwd: fileURLToPath(new URL("../../", import.meta.url)), env: { ...process.env, DATABASE_URL: databaseUrl }, stdio: "ignore",
  })
  const workspaceDir = join(dir, "workspace")
  mkdirSync(join(workspaceDir, "555-acme-shop"), { recursive: true })
  writeFileSync(join(workspaceDir, "555-acme-shop", "main.ts"), "export const value = 1")
  let finish!: (result: Record<string, AgentInput>) => void
  const pending = new Promise<Record<string, AgentInput>>((resolve) => { finish = resolve })
  let loseConnection!: () => void
  const connectionLost = new Promise<void>((resolve) => { loseConnection = resolve })
  let reconciled!: () => void
  const recovering = new Promise<void>((resolve) => { reconciled = resolve })
  let dispatches = 0
  let seen: PipelineInput | undefined
  const options = { databaseUrl, workspaceDir, silent: true, makeAgentCatalogSource: makeQualityAuditCatalogSource, makeModelAccessVerifier: () => ({ verify: async () => {} }) }
  const { app, db } = await buildApp({ ...options, makeAgentInvoker: () => ({
     run: async () => ({}), runPipelineByName: async (name, input, ids, configs) => {
      dispatches++
      assert.equal(name, "quality-audit")
       assert.ok(ids[agentType])
        assert.equal(Object.keys(ids).length, 1)
       assert.deepEqual(Object.keys(configs).sort(), agents.sort())
       for (const participant of agents) {
          assert.equal(configs[participant]?.api_key, participant === "security" ? "security-test-key" : "secret-test-key")
          assert.equal(configs[participant]?.model.max_tokens, null, "unset agent output inherits instead of imposing a hidden cap")
      }
       seen = input
       if (disconnect) {
         await connectionLost
         throw new AgentTransportError("ECONNRESET", true)
       }
       return pending
     },
     getAuditResult: async (runId, selected) => {
       assert.equal(runId, "b".repeat(32))
       assert.deepEqual(selected, attributes)
       reconciled()
       return (await pending)["audit"] ?? null
     },
  }) })
  auditResponseSerialization(app)
  const hash = "a".repeat(40)
  const report = { schema_version: "1.0", identification: { status: "partial", audit_id: "audit-123" }, executive_summary: { conclusion: "Cobertura pendiente" } }
  const word = Buffer.from("PK-original-word-artifact")
  let executionId: number
  let projectId: number
  try {
    if (attributes.length === 1 && attributes[0] === "functional_adequacy") {
      const originalFetch = globalThis.fetch
      const saved = { audit_budget: { max_total_tokens: 300000000000 },
        agent_defaults: { max_context_characters: 240000, max_output_tokens: 12000 }, functional_config: { retrieval_top_k: 3 } }
      globalThis.fetch = async (_url, init) => new Response(JSON.stringify(init?.method === "POST"
        ? { values: JSON.parse(String(init.body)) } : { schema: { type: "object" }, level: "developer" }))
      try {
        const service = new AuditSettingsService(db, "http://configuration.test")
        await service.save("functional_adequacy", saved)
        assert.deepEqual((await new AuditSettingsService(db, "http://configuration.test").get("functional_adequacy")).values, saved,
          "saved settings survive service recreation")
        assert.deepEqual((await service.get("security")).values, { audit_budget: saved.audit_budget },
          "shared budget is global while category operating overrides stay scoped")
         assert.deepEqual(await service.executionOptions(["functional_adequacy"], {}), {
          audit_budget: saved.audit_budget,
          attribute_options: { functional_adequacy: { agent_defaults: saved.agent_defaults, functional_config: saved.functional_config } },
         })
         await db.auditSettings.create({ data: { attribute: "security", options: JSON.stringify({
           security_config: { max_scan_files: 30, max_output_tokens: 6000 },
         }) } })
         const legacy = await service.get("security")
         assert.deepEqual(legacy.values, { audit_budget: saved.audit_budget,
           security_config: { max_scan_files: 30 }, agent_defaults: { max_output_tokens: 6000 } })
         await service.save("security", { ...legacy.values, agent_defaults: { max_output_tokens: 16000 } })
         const effective = await service.executionOptions(["security"], {})
         assert.deepEqual(effective.attribute_options?.security, {
           security_config: { max_scan_files: 30 }, agent_defaults: { max_output_tokens: 16000 },
         }, "editing the canonical output control must replace the legacy security value")
        await db.auditSettings.deleteMany()
      } finally { globalThis.fetch = originalFetch }
    }
    const project = await db.project.create({ data: { githubRepositoryId: 555n, repositoryOwner: "acme", repositoryName: "shop", status: "READY" } })
    projectId = project.id
    const version = await db.projectVersion.create({ data: { projectId, branch: "main", commitHash: hash, analysisStatus: "Completed" } })
    const architecture = await db.evaluation.create({ data: { projectVersionId: version.id, type: "Analysis" } })
    const url = `/api/projects/${projectId}/audits`
    const options = {
      agent_defaults: { max_context_characters: 20000000, max_output_tokens: 16000, max_total_tokens: 80000000, max_model_calls: 20, max_tool_calls: 30 },
      audit_budget: { max_total_tokens: 3000000000 },
      ...(attributes.includes("security") ? { security_config: { max_scan_files: 30, max_source_lines: 200 } } : {}),
      ...(attributes.includes("functional_adequacy") ? { functional_requirements: [{ requirement_id: "REQ-001", description: "Export a value." }] } : {}),
    }
    const body = { branch: "main", commitHash: hash, attributes, ...options }
    await db.auditSettings.createMany({ data: [
      { attribute: "global", options: JSON.stringify({ audit_budget: { max_total_tokens: 300000000000 } }) },
      ...attributes.map((attribute, index) => ({ attribute, options: JSON.stringify({
        agent_defaults: { max_context_characters: 220000 + index, max_output_tokens: 12000, max_total_tokens: 90000000 },
        ...(attribute === "functional_adequacy" ? { functional_config: { retrieval_top_k: 3 } } : {}),
      }) })),
    ] })
    assert.equal((await app.inject({ method: "POST", url, payload: { ...body, attributes: ["unsupported"] } })).statusCode, 400)
    assert.equal((await app.inject({ method: "POST", url, payload: body })).statusCode, 422)
    assert.equal(await db.evaluation.count(), 1, "invalid configurations create no audit rows")
    const provider = await db.aiProvider.create({ data: { name: "test" } })
    const model = await db.aiModel.create({ data: { name: "test-model", aiProviderId: provider.id } })
    const credential = await db.aiCredential.create({ data: { name: "test-key", apiKey: "secret-test-key", aiProviderId: provider.id } })
    const securityCredential = await db.aiCredential.create({ data: { name: "security-key", apiKey: "security-test-key", aiProviderId: provider.id } })
    for (const selected of attributes) {
      await db.agentSettings.update({ where: { agentType: selected === "maintainability" ? "maintainability_manager" : selected },
        data: { aiModelId: model.id, aiCredentialId: selected === "security" ? securityCredential.id : credential.id } })
    }
    const opened = await app.inject({ method: "POST", url, payload: body })
    assert.equal(opened.statusCode, 202, opened.body)
    executionId = opened.json().executionId
    const monitored = await app.inject({ url: `/api/agent-executions/${executionId}` })
    assert.equal(monitored.statusCode, 200)
    assert.deepEqual(monitored.json().monitorContext.project, { id: projectId, repositoryOwner: "acme", repositoryName: "shop" })
    assert.equal(monitored.json().monitorContext.branch, "main")
    assert.equal(monitored.json().monitorContext.commitHash, hash)
    assert.equal(monitored.json().monitorContext.evaluationType, "QualityAudit")
    assert.equal((await app.inject({ method: "POST", url, payload: body })).statusCode, 422)
    for (let i = 0; !seen && i < 100; i++) await new Promise((resolve) => setTimeout(resolve, 10))
    assert.deepEqual(seen?.attributes, attributes)
    assert.deepEqual(seen?.agent_defaults, options.agent_defaults)
    assert.deepEqual(seen?.audit_budget, options.audit_budget)
    for (const attribute of attributes) {
      assert.deepEqual(seen?.attribute_options?.[attribute]?.agent_defaults, options.agent_defaults,
        "explicit run overrides take precedence over persisted category defaults")
    }
    if (attributes.includes("functional_adequacy")) assert.deepEqual(seen?.attribute_options?.functional_adequacy?.functional_config,
      { retrieval_top_k: 3 }, "saved exclusive operating settings are forwarded without being repeated by the execution form")
    assert.deepEqual(seen?.security_config, options.security_config)
    assert.equal(seen?.commit_hash, hash)
    if (attributes.includes("functional_adequacy")) {
      assert.deepEqual(seen?.functional_requirements, options.functional_requirements)
      const missing = await app.inject({ method: "POST", url, payload: { ...body, functional_requirements: undefined } })
      assert.equal(missing.statusCode, 400)
      const duplicate = await app.inject({ method: "POST", url, payload: { ...body,
        functional_requirements: [options.functional_requirements![0], options.functional_requirements![0]] } })
      assert.equal(duplicate.statusCode, 400)
    }
    const waiting = await app.inject({ url })
    assert.equal(waiting.json()[0].reportAvailable, false)
    assert.equal(waiting.json()[0].runId, null)
    assert.equal(waiting.json().length, 1)
    assert.deepEqual(waiting.json()[0].attributes, attributes)
    assert.equal((await app.inject({ url: `${url}/${executionId}/report.docx` })).statusCode, 422)
    // The agent-server reports the audit id as soon as it creates it, while the audit still runs.
    const started = await app.inject({ method: "POST", url: `/api/agent-executions/${executionId}/running`,
      payload: { runId: "b".repeat(32) } })
    assert.equal(started.statusCode, 200)
     assert.equal((await app.inject({ url })).json()[0].runId, "b".repeat(32))
     if (disconnect) {
       loseConnection()
       await recovering
       const stillRunning = await app.inject({ url: `/api/agent-executions/${executionId}?monitor=true` })
       assert.equal(stillRunning.json().status, "Running", "socket loss is not a confirmed audit failure")
       assert.equal(stillRunning.json().error, null)
       assert.equal(stillRunning.json().finishedAt, null)
       assert.equal(dispatches, 1, "recovery must not start a duplicate audit")
     }
    const receipt = { invocation_id: "manager-live", parent_invocation_id: null, agent_id: agentType,
      run_id: "b".repeat(32), status: "running", started_at: "2026-10-20T10:00:00Z", finished_at: null,
      input_tokens: null, output_tokens: null, error: null }
    const callbackUrl = `/api/agent-executions/${executionId}/invocations`
    const send = (payload: object) => app.inject({ method: "POST", url: callbackUrl, payload })
    assert.equal((await send(receipt)).statusCode, 200)
    const child = { ...receipt, invocation_id: "child-live", parent_invocation_id: receipt.invocation_id, agent_id: "modularity",
      phase: "plan_assessment", phase_sequence: 1 }
    const socket = await app.injectWS("/ws")
    try {
      const nextEvent = once(socket, "message", { signal: AbortSignal.timeout(5000) })
      assert.equal((await send(child)).statusCode, 200)
      const [message] = await nextEvent
      const event = JSON.parse(String(message))
      assert.equal(event.type, "agent-execution.updated")
      assert.equal(event.execution.result, null)
      assert.equal(event.execution.invocations[1].invocation_id, "child-live")
      assert.equal(event.execution.invocations[1].parent_invocation_id, "manager-live")
      assert.equal(event.execution.invocations[1].phase, "plan_assessment")
    } finally { socket.terminate() }
    const live = (await app.inject({ url: `/api/agent-executions/${executionId}?monitor=true` })).json()
    assert.equal(live.status, "Running")
    assert.equal(live.invocations.length, 2, "children arrive before the final report")
    assert.equal(live.invocations[1].parent_invocation_id, "manager-live")
    assert.equal((await send({ ...child, phase: "synthesize_findings", phase_sequence: 3 })).statusCode, 200)
    const stalePhase = await send({ ...child, phase: "collect_findings", phase_sequence: 2 })
    assert.equal(stalePhase.json().invocations[1].phase, "synthesize_findings")
    assert.equal((await send({ ...child, run_id: "wrong-run" })).statusCode, 422)
    assert.equal((await send({ ...receipt, parent_invocation_id: "child-live" })).statusCode, 422)
    assert.equal((await send({ ...child, status: "completed", finished_at: "2026-10-20T10:01:00Z", input_tokens: 32 })).statusCode, 200)
    const late = await send(child)
    assert.equal(late.statusCode, 200)
    assert.equal(late.json().invocations[1].status, "completed")
    assert.equal(late.json().invocations[1].input_tokens, 32)
    assert.equal(late.json().invocations[1].phase, null)
    assert.deepEqual((await app.inject({ url })).json()[0].attributes, attributes)
    assert.equal((await app.inject({ method: "POST", url: `/api/agent-executions/${executionId}/running`,
      payload: { runId: "not-a-run-id" } })).statusCode, 400)
    finish({ audit: { attributes, status: "partial", run_id: "audit-123", report,
      blackboard: { evidence: [{ id: "source-1", commit: hash }] }, docx_base64: word.toString("base64") } })
    for (let i = 0; i < 100; i++) {
      if ((await db.agentExecution.findUniqueOrThrow({ where: { id: executionId } })).status === "Completed") break
      await new Promise((resolve) => setTimeout(resolve, 10))
    }
    const rows = (await app.inject({ url })).json()
    assert.equal(rows[0].auditStatus, "partial")
    assert.equal(rows[0].reportAvailable, true)
    assert.equal(rows[0].runId, "audit-123", "the delivered envelope remains the stored run id")
    const compact = await app.inject({ url: `/api/agent-executions/${executionId}?monitor=true` })
    assert.equal(compact.statusCode, 200)
    assert.deepEqual(JSON.parse(compact.json().result).attributes, attributes)
    assert.equal(JSON.parse(compact.json().result).status, "partial")
    assert.doesNotMatch(compact.body, /docx_base64|source-1|blackboard/)
    assert.equal(JSON.stringify(rows).includes("secret-test-key"), false)
    const versions = (await app.inject({ url: `/api/projects/${projectId}/versions` })).json()
    assert.equal(versions[0].evaluationId, architecture.id, "audits do not replace architecture history")
  } finally { await app.close(); await db.$disconnect() }

  // Restart without any agent-server connection: both artifacts remain available.
  const restarted = await buildApp(options)
  try {
    const url = `/api/projects/${projectId}/audits/${executionId}`
    const restored = await restarted.app.inject({ url: `${url}/report` })
    assert.equal(restored.statusCode, 200)
    assert.deepEqual(restored.json(), report)
    const download = await restarted.app.inject({ url: `${url}/report.docx` })
    assert.equal(download.statusCode, 200)
    assert.deepEqual(download.rawPayload, word)
    assert.match(download.headers["content-disposition"] as string, /attachment/)
    assert.equal((await restarted.app.inject({ url: `/api/projects/999/audits/${executionId}/report` })).statusCode, 404)
  } finally { await restarted.app.close(); await restarted.db.$disconnect() }
})
}
