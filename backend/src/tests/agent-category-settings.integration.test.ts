import assert from "node:assert/strict"
import { execFileSync } from "node:child_process"
import { mkdtempSync, rmSync } from "node:fs"
import { join } from "node:path"
import { tmpdir } from "node:os"
import { test } from "node:test"
import { buildApp } from "../app.js"
import { testAgentCatalog } from "./helpers/agentCatalog.js"

test("category assignments cover declared model owners atomically and shared agents verify effective access", async () => {
  const directory = mkdtempSync(join(tmpdir(), "veraud-category-"))
  const databaseUrl = `file:${join(directory, "test.db")}`
  execFileSync(process.execPath, ["node_modules/prisma/build/index.js", "migrate", "deploy"], {
    env: { ...process.env, DATABASE_URL: databaseUrl }, stdio: "ignore",
  })
  const catalog = testAgentCatalog()
  const base = catalog.agents[0]!
  catalog.agents.push(
    { ...base, agent_id: "new_investigator", name: "New", model_configuration_id: "new_investigator", quality_attributes: ["maintainability"] },
    { ...base, agent_id: "shared", name: "Shared", model_configuration_id: "security", quality_attributes: ["security"] },
    { ...base, agent_id: "deterministic", name: "Deterministic", requires_model: false, model_configuration_id: null, quality_attributes: ["maintainability", "security"] },
  )
  catalog.agents.find((agent) => agent.agent_id === "maintainability_manager")!.quality_attributes = ["maintainability"]
  catalog.agents.find((agent) => agent.agent_id === "security")!.quality_attributes = ["security"]
  let denied = false
  const checked: string[] = []
  const { app, db } = await buildApp({ databaseUrl, workspaceDir: join(directory, "workspace"), silent: true,
    makeAgentCatalogSource: () => ({ getAgentCatalog: async () => catalog }),
    makeModelAccessVerifier: () => ({ verify: async (config) => {
      checked.push(config.model.name)
      if (denied) throw new Error("Model access denied")
    } }),
  })
  try {
    const provider = await db.aiProvider.findFirstOrThrow({ where: { name: "OpenAI" } })
    const other = await db.aiProvider.findFirstOrThrow({ where: { name: "Google" } })
    const model = await db.aiModel.create({ data: { aiProviderId: provider.id, name: "category-model" } })
    const credential = await db.aiCredential.create({ data: { aiProviderId: provider.id, name: "key", apiKey: "private-category-key" } })
    const foreign = await db.aiCredential.create({ data: { aiProviderId: other.id, name: "foreign", apiKey: "private-foreign-key" } })
    await db.agentSettings.update({ where: { agentType: "new_investigator" }, data: { temperature: 0.7, tokenBudget: 12345 } })
    const assign = (category: string, credentialId = credential.id) => app.inject({ method: "PUT", url: `/api/agent-settings/categories/${category}`, payload: { modelId: model.id, credentialId } })
    const saved = await assign("maintainability")
    assert.equal(saved.statusCode, 200)
    assert.doesNotMatch(saved.body, /private-category-key|api_key/)
    for (const agentType of ["maintainability_manager", "new_investigator"]) {
      assert.equal((await db.agentSettings.findUniqueOrThrow({ where: { agentType } })).aiModelId, model.id)
    }
    const investigator = await db.agentSettings.findUniqueOrThrow({ where: { agentType: "new_investigator" } })
    assert.equal(Number(investigator.temperature), 0.7)
    assert.equal(investigator.tokenBudget, 12345)
    assert.equal((await db.agentSettings.findUniqueOrThrow({ where: { agentType: "security" } })).aiModelId, null)
    assert.equal((await db.agentSettings.findUniqueOrThrow({ where: { agentType: "deterministic" } })).aiModelId, null)
    assert.equal((await assign("unknown")).statusCode, 422)
    const before = await db.agentSettings.findMany()
    assert.equal((await assign("maintainability", foreign.id)).statusCode, 422)
    assert.deepEqual(await db.agentSettings.findMany(), before)
    assert.equal((await assign("security")).statusCode, 200)
    const verify = () => app.inject({ method: "POST", url: "/api/agent-settings/shared/verify" })
    assert.equal((await verify()).json().verification.status, "verified")
    assert.deepEqual(checked, ["category-model"])
    let rows = (await app.inject({ url: "/api/agent-settings" })).json()
    assert.equal(rows.find((row: { agentType: string }) => row.agentType === "shared").configuration.model.id, model.id)
    assert.equal(rows.find((row: { agentType: string }) => row.agentType === "security").verification.status, "verified")
    denied = true
    assert.equal((await verify()).json().verification.status, "failed")
    assert.equal((await app.inject({ method: "POST", url: "/api/agent-settings/deterministic/verify" })).statusCode, 422)
    await assign("security")
    rows = (await app.inject({ url: "/api/agent-settings" })).json()
    assert.equal(rows.find((row: { agentType: string }) => row.agentType === "shared").verification.status, "not_verified")
  } finally { await app.close(); await db.$disconnect(); rmSync(directory, { recursive: true, force: true }) }
})
