import { it } from "node:test"
import assert from "node:assert/strict"
import { execSync } from "node:child_process"
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { buildApp } from "../app.js"
import { makeQualityAuditCatalogSource } from "./helpers/agentCatalog.js"
import type { AgentInput } from "../infrastructure/agent-server-client/agent-server.client.js"
import { architectureContextFixture, seedArchitectureContext } from "./helpers/architectureContext.js"

it("replaces V1 without deleting history and automatically forwards the version's stored context", async () => {
  const dir = mkdtempSync(join(tmpdir(), "veraud-maintainability-v2-"))
  const databaseUrl = `file:${join(dir, "test.db")}`
  execSync("pnpm prisma migrate deploy", { cwd: fileURLToPath(new URL("../../", import.meta.url)),
    env: { ...process.env, DATABASE_URL: databaseUrl }, stdio: "ignore" })
  const workspaceDir = join(dir, "workspace")
  mkdirSync(join(workspaceDir, "555-acme-shop"), { recursive: true })
  writeFileSync(join(workspaceDir, "555-acme-shop", "main.py"), "value = 1")
  const oldCatalog = await makeQualityAuditCatalogSource().getAgentCatalog()
  let catalog = structuredClone(oldCatalog)
  let finish!: (result: Record<string, AgentInput>) => void
  const pending = new Promise<Record<string, AgentInput>>((resolve) => { finish = resolve })
  let dispatched!: () => void
  const dispatch = new Promise<void>((resolve) => { dispatched = resolve })
  const requestData = { documented_architecture: architectureContextFixture("a".repeat(40)) }
  const { app, db } = await buildApp({ databaseUrl, workspaceDir, silent: true,
    makeAgentCatalogSource: () => ({ getAgentCatalog: async () => catalog }),
    makeModelAccessVerifier: () => ({ verify: async () => {} }),
    makeAgentInvoker: () => ({ run: async () => ({}), runPipelineByName: async (name, input, ids, configs) => {
      assert.equal(name, "quality-audit")
      assert.deepEqual(Object.keys(configs).sort(), ["architecture_boundary", "maintainability_manager", "modularity"])
      assert.deepEqual(input.request, requestData)
      assert.deepEqual(input.maintainability_selection, { modularity: ["architecture_boundary"] })
      assert.ok(ids.maintainability_manager)
      dispatched()
      return pending
    } }),
  })
  try {
    const provider = await db.aiProvider.create({ data: { name: "offline" } })
    const model = await db.aiModel.create({ data: { name: "test-model", aiProviderId: provider.id } })
    const credential = await db.aiCredential.create({ data: { name: "test-key", apiKey: "private-key", aiProviderId: provider.id } })
    await db.agentSettings.update({ where: { agentType: "maintainability_manager" }, data: { aiModelId: model.id, aiCredentialId: credential.id } })
    const oldExecution = await db.agentExecution.create({ data: { agentType: "responsibility", status: "Completed", result: "historical-v1" } })
    const ids = ["maintainability_manager", "modularity", "architecture_boundary"]
    catalog = { ...catalog, agents: catalog.agents.filter((agent) => ids.includes(agent.agent_id)).map((agent) => ({ ...agent,
      child_ids: agent.child_ids.filter((id) => ids.includes(id)), parent_ids: agent.parent_ids.filter((id) => ids.includes(id)),
      quality_attributes: ["maintainability"], workflow_ids: ["quality-audit"],
    })) }
    assert.equal((await app.inject({ method: "POST", url: "/api/agent-settings/sync" })).statusCode, 200)
    const listed = (await app.inject({ url: "/api/agent-settings" })).json() as { agentType: string }[]
    assert.deepEqual(listed.map((agent) => agent.agentType).sort(), ids.sort())
    assert.equal((await db.agentExecution.findUniqueOrThrow({ where: { id: oldExecution.id } })).result, "historical-v1")
    assert.equal((await db.agentSettings.findUniqueOrThrow({ where: { agentType: "maintainability_manager" } })).aiModelId, model.id)
    const project = await db.project.create({ data: { githubRepositoryId: 555n, repositoryOwner: "acme", repositoryName: "shop", status: "READY" } })
    const hash = "a".repeat(40)
    const version = await db.projectVersion.create({ data: { projectId: project.id, branch: "main", commitHash: hash, analysisStatus: "Completed" } })
    await db.evaluation.create({ data: { projectVersionId: version.id, type: "Analysis" } })
    const source = await seedArchitectureContext(db, project.id, hash)
    const url = `/api/projects/${project.id}/audits`
    const body = { branch: "main", commitHash: hash, attributes: ["maintainability"] }
    assert.equal((await app.inject({ method: "POST", url, payload: { ...body, request: requestData } })).statusCode, 400)
    assert.equal((await app.inject({ method: "POST", url, payload: { ...body, maintainability_selection: { modularity: ["responsibility"] } } })).statusCode, 422)
    const opened = await app.inject({ method: "POST", url, payload: body })
    assert.equal(opened.statusCode, 202, opened.body)
    await dispatch
    const executionId = opened.json().executionId as number
    for (const [index, agent] of ["maintainability_manager", "modularity", "architecture_boundary"].entries()) {
      const receipt = { agent_id: agent, invocation_id: `v2-${index}`, run_id: "b".repeat(32),
        parent_invocation_id: index ? `v2-${index - 1}` : null, status: "completed",
        started_at: "2026-11-08T12:00:00Z", finished_at: "2026-11-08T12:00:01Z",
        input_tokens: 100, output_tokens: 100, error: null, phase: null, phase_sequence: 2 }
      const received = await app.inject({ method: "POST", url: `/api/agent-executions/${executionId}/invocations`, payload: receipt })
      assert.equal(received.statusCode, 200, received.body)
    }
    const stored = await db.agentExecution.findUniqueOrThrow({ where: { id: executionId } })
    assert.deepEqual(JSON.parse(stored.invocationReceipts).map((receipt: { agent_id: string }) => receipt.agent_id).sort(), [...ids].sort())
    const configuration = (await app.inject({ url: `${url}/${executionId}/configuration` })).json().configuration
    assert.deepEqual(configuration.architectureContext, { executionId: source.executionId, projectVersionId: source.projectVersionId,
      schemaVersion: "1", executionStatus: "partial" })
    assert.deepEqual(configuration.scopes[0].subcharacteristics.map((item: { id: string }) => item.id), ["modularity"])
    finish({ audit: { attributes: ["maintainability"], status: "completed", run_id: "b".repeat(32),
      report: { schema_version: "1.0", identification: { audit_id: "b".repeat(32), status: "completed" } },
      docx_base64: Buffer.from("PK-test-artifact").toString("base64"),
      blackboard: { findings: [], evidence: [], assessments: [] },
    } })
  } finally {
    finish?.({})
    await app.close()
    await db.$disconnect()
  }
})
