import assert from "node:assert/strict"
import { execFileSync } from "node:child_process"
import { mkdtempSync, rmSync } from "node:fs"
import { createServer } from "node:http"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { test } from "node:test"
import { buildApp } from "../app.js"
import type { AgentCatalog, CatalogAgent } from "../modules/agent-settings/agent-catalog.js"
import { auditResponseSerialization } from "./helpers/responseSerializationAudit.js"

function agent(id: string, parentIds: string[] = [], childIds: string[] = [], model = true): CatalogAgent {
  return { agent_id: id, name: `Name of ${id}`, role: "discovered_agent", requires_model: model,
    model_configuration_id: model ? id : null, execution_modes: ["internal"],
    quality_attributes: ["maintainability"], workflow_ids: ["quality-audit"],
    parent_ids: parentIds, child_ids: childIds, availability: "available" }
}

test("HTTP discovery synchronizes only declared agents and optional children, preserving selections and history", async () => {
  const directory = mkdtempSync(join(tmpdir(), "veraud-catalog-"))
  const databaseUrl = `file:${join(directory, "test.db")}`
  execFileSync(process.execPath, ["node_modules/prisma/build/index.js", "migrate", "deploy"], {
    env: { ...process.env, DATABASE_URL: databaseUrl }, stdio: "ignore",
  })
  const options = { databaseUrl, workspaceDir: join(directory, "workspace"), silent: true }
  const offline = await buildApp(options)
  assert.deepEqual((await offline.app.inject({ url: "/api/agent-settings" })).json(), [])
  assert.equal(await offline.db.agentSettings.count(), 0, "No hard-coded backend seed")
  assert.equal((await offline.app.inject({ method: "POST", url: "/api/agent-settings/sync" })).statusCode, 503)
  const provider = await offline.db.aiProvider.findFirstOrThrow()
  const model = await offline.db.aiModel.create({ data: { name: "saved-model", aiProviderId: provider.id } })
  const credential = await offline.db.aiCredential.create({ data: { name: "saved-credential", apiKey: "private-catalog-test-key", aiProviderId: provider.id } })
  await offline.db.agentSettings.create({ data: { agentType: "custom_manager", aiModelId: model.id, aiCredentialId: credential.id,
    temperature: 0.7, maxTokens: 2048, tokenBudget: 8000, verificationFingerprint: "existing-check" } })
  await offline.db.agentSettings.create({ data: { agentType: "legacy_only" } })
  const history = await offline.db.agentExecution.create({ data: { agentType: "custom_manager", status: "Completed", result: "original-result" } })
  await offline.app.close()
  await offline.db.$disconnect()

  let payload: unknown = { schema_version: "1.0", agents: [
    agent("custom_manager", [], ["custom_worker", "custom_report"]),
    agent("custom_worker", ["custom_manager"]), { ...agent("custom_report", ["custom_manager"], [], false),
      quality_attributes: ["maintainability", "security"] },
  ] } satisfies AgentCatalog
  let responseStatus = 200
  const paths: string[] = []
  const server = createServer((request, response) => {
    paths.push(request.url!)
    response.writeHead(responseStatus, { "content-type": "application/json" })
    response.end(JSON.stringify(payload))
  })
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve))
  const address = server.address()
  assert.ok(address && typeof address !== "string")
  const agentServerUrl = `http://127.0.0.1:${address.port}`
  const { app, db } = await buildApp({ ...options, agentServerUrl, makeModelAccessVerifier: () => ({ verify: async () => {} }) })
  auditResponseSerialization(app)
  const list = async () => (await app.inject({ url: "/api/agent-settings" })).json()
  const sync = () => app.inject({ method: "POST", url: "/api/agent-settings/sync" })
  try {
    assert.deepEqual(paths, ["/api/agents/catalog"])
    const rows = await list()
    assert.deepEqual(rows.map((row: { agentType: string }) => row.agentType), ["custom_manager", "custom_report", "custom_worker"])
    const manager = rows.find((row: { agentType: string }) => row.agentType === "custom_manager")
    assert.equal(manager.name, "Name of custom_manager")
    assert.deepEqual(manager.qualityAttributes, ["maintainability"])
    assert.deepEqual(manager.workflowIds, ["quality-audit"])
    assert.deepEqual(rows.find((row: { agentType: string }) => row.agentType === "custom_report").qualityAttributes, ["maintainability", "security"])
    assert.deepEqual(manager.parentAgentTypes, [])
    assert.deepEqual(manager.childAgentTypes, ["custom_report", "custom_worker"])
    assert.equal(manager.configuration.model.id, model.id)
    assert.equal(manager.configuration.temperature, 0.7)
    assert.equal(manager.configuration.tokenBudget, 8000)
    const original = await db.agentSettings.findMany({ orderBy: { agentType: "asc" } })
    assert.equal((await sync()).statusCode, 200)
    assert.deepEqual(await db.agentSettings.findMany({ orderBy: { agentType: "asc" } }), original, "Repeated sync must not overwrite user settings or verification")
    assert.equal(await db.agentHierarchy.count(), 2)
    assert.deepEqual((await list()).find((row: { agentType: string }) => row.agentType === "custom_worker").childAgentTypes, [])
    const save = (id: string) => app.inject({ method: "PUT", url: `/api/agent-settings/${id}`, payload: { modelId: model.id, credentialId: credential.id } })
    assert.equal((await save("custom_worker")).statusCode, 200, "New server agent names require no backend registration")
    assert.equal((await save("custom_report")).statusCode, 422, "Deterministic agents do not need credentials")
    assert.equal((await save("legacy_only")).statusCode, 404)
    assert.equal((await save("invented_locally")).statusCode, 404)
    assert.equal(await db.agentSettings.count({ where: { agentType: "invented_locally" } }), 0)
    assert.equal((await app.inject({ method: "POST", url: "/api/agent-settings/custom_worker/verify" })).statusCode, 200)

    payload = { schema_version: "1.0", agents: [{ ...agent("custom_worker", [], ["custom_report"]), quality_attributes: ["security"] },
      { ...agent("custom_report", ["custom_worker", "new_leaf"], [], false), quality_attributes: ["maintainability", "security"] },
      { ...agent("new_leaf", [], ["custom_report"]), quality_attributes: [], workflow_ids: ["another-workflow"] }] }
    assert.equal((await sync()).statusCode, 200)
    assert.deepEqual((await list()).map((row: { agentType: string }) => row.agentType), ["custom_report", "custom_worker", "new_leaf"])
    assert.equal((await db.agentSettings.findUniqueOrThrow({ where: { agentType: "custom_manager" } })).catalogDeclared, false)
    assert.equal((await db.agentSettings.findUniqueOrThrow({ where: { agentType: "custom_manager" } })).aiModelId, model.id)
    assert.equal((await db.agentExecution.findUniqueOrThrow({ where: { id: history.id } })).result, "original-result")
    assert.deepEqual(await db.agentHierarchy.findMany({ orderBy: { parentAgentType: "asc" } }), [
      { parentAgentType: "custom_worker", childAgentType: "custom_report" },
      { parentAgentType: "new_leaf", childAgentType: "custom_report" },
    ])
    assert.deepEqual((await list()).find((row: { agentType: string }) => row.agentType === "custom_report").parentAgentTypes, ["custom_worker", "new_leaf"])
    assert.deepEqual((await list()).find((row: { agentType: string }) => row.agentType === "custom_worker").qualityAttributes, ["security"])
    assert.deepEqual((await list()).find((row: { agentType: string }) => row.agentType === "new_leaf").qualityAttributes, [])
    assert.deepEqual((await list()).find((row: { agentType: string }) => row.agentType === "new_leaf").workflowIds, ["another-workflow"])
    assert.equal((await save("custom_manager")).statusCode, 404)

    const preserved = await db.agentSettings.findMany({ orderBy: { agentType: "asc" } })
    const preservedLinks = await db.agentHierarchy.findMany()
    for (const invalid of [
      { schema_version: "2.0", agents: [] },
      { schema_version: "1.0", agents: [agent("duplicate"), agent("duplicate")] },
      { schema_version: "1.0", agents: [agent("dangling", [], ["missing"])] },
      { schema_version: "1.0", agents: [agent("a", ["b"], ["b"]), agent("b", ["a"], ["a"])] },
      { schema_version: "1.0", agents: [{ ...agent("bad-context"), quality_attributes: ["security", "security"] }] },
      { schema_version: "1.0", agents: [{ ...agent("bad-context"), workflow_ids: "quality-audit" }] },
    ]) {
      payload = invalid
      assert.equal((await sync()).statusCode, 503)
      assert.deepEqual(await db.agentSettings.findMany({ orderBy: { agentType: "asc" } }), preserved)
      assert.deepEqual(await db.agentHierarchy.findMany(), preservedLinks)
    }
    responseStatus = 503
    assert.equal((await sync()).statusCode, 503)
    assert.doesNotMatch(JSON.stringify(await list()), /private-catalog-test-key|apiKey|api_key/)
  } finally {
    await app.close()
    await db.$disconnect()
    await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()))
  }
  const restarted = await buildApp({ ...options, agentServerUrl })
  try {
    const restored = (await restarted.app.inject({ url: "/api/agent-settings" })).json()
    assert.deepEqual(restored.map((row: { agentType: string }) => row.agentType), ["custom_report", "custom_worker", "new_leaf"])
    assert.deepEqual(restored.find((row: { agentType: string }) => row.agentType === "custom_report").qualityAttributes, ["maintainability", "security"])
    assert.deepEqual(restored.find((row: { agentType: string }) => row.agentType === "new_leaf").workflowIds, ["another-workflow"])
    assert.equal(await restarted.db.agentExecution.count(), 1)
  } finally {
    await restarted.app.close()
    await restarted.db.$disconnect()
    rmSync(directory, { recursive: true, force: true })
  }
})
