import assert from "node:assert/strict"
import { execFileSync } from "node:child_process"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { test } from "node:test"
import { fileURLToPath } from "node:url"
import { buildApp } from "../app.js"
import { PROJECT_ARCHITECTURE_AGENT_TYPE } from "../modules/agent-settings/agent-types.js"
import { DUMMY_AGENT_TYPE } from "../modules/agent-settings/agent-types.js"
import { AgentSettingsRepository } from "../modules/agent-settings/agent-settings.repository.js"
import { TEST_AGENT_TYPES, makeTestAgentCatalogSource, testAgentCatalog } from "./helpers/agentCatalog.js"
import { auditResponseSerialization } from "./helpers/responseSerializationAudit.js"

test("agent settings list discovered types and preserve assignments without exposing keys", async () => {
  const directory = mkdtempSync(join(tmpdir(), "veraud-agent-settings-"))
  const databaseUrl = `file:${join(directory, "test.db")}`
  execFileSync(process.execPath, ["node_modules/prisma/build/index.js", "migrate", "deploy"], {
    cwd: fileURLToPath(new URL("../../", import.meta.url)),
    env: { ...process.env, DATABASE_URL: databaseUrl },
    stdio: "ignore",
  })
  const { app, db } = await buildApp({
    databaseUrl, workspaceDir: join(directory, "workspace"), silent: true,
    makeAgentCatalogSource: makeTestAgentCatalogSource,
  })
  auditResponseSerialization(app)
  try {
    const initial = await app.inject({ url: "/api/agent-settings" })
    assert.equal(initial.statusCode, 200)
    assert.deepEqual(initial.json().map(({ agentType, configured, configuration, verification }: { agentType: string, configured: boolean, configuration: unknown, verification: unknown }) => ({ agentType, configured, configuration, verification })), [...TEST_AGENT_TYPES].sort().map((agentType) => ({
      agentType, configured: false, configuration: null, verification: { status: "not_verified", checkedAt: null, message: null },
    })))
    const defaults = await db.agentSettings.findMany({ orderBy: { agentType: "asc" }, select: { agentType: true, aiModelId: true, aiCredentialId: true, temperature: true, maxTokens: true } })
    assert.deepEqual(defaults.map((row) => ({ ...row })), [...TEST_AGENT_TYPES].sort().map((agentType) => ({
      agentType, aiModelId: null, aiCredentialId: null, temperature: null, maxTokens: null,
    })))
    const openai = await db.aiProvider.findFirstOrThrow({ where: { name: "OpenAI" } })
    const google = await db.aiProvider.findFirstOrThrow({ where: { name: "Google" } })
    const model = await db.aiModel.create({ data: { aiProviderId: openai.id, name: "example-model" } })
    const credential = await db.aiCredential.create({ data: { aiProviderId: openai.id, name: "production", apiKey: "private-key-not-for-public-responses" } })
    const foreignCredential = await db.aiCredential.create({ data: { aiProviderId: google.id, name: "google", apiKey: "another-private-key" } })
    await db.agentSettings.update({ where: { agentType: PROJECT_ARCHITECTURE_AGENT_TYPE }, data: { aiModelId: model.id, aiCredentialId: credential.id, temperature: 0.25, maxTokens: 2048 } })
    await db.agentSettings.update({ where: { agentType: DUMMY_AGENT_TYPE }, data: { aiModelId: model.id, aiCredentialId: foreignCredential.id } })
    await db.agentSettings.create({ data: { agentType: "retired", aiModelId: model.id, aiCredentialId: credential.id } })
    const repository = new AgentSettingsRepository(db)
    const existing = await db.agentSettings.findMany({ orderBy: { agentType: "asc" } })
    await repository.synchronizeCatalog(testAgentCatalog())
    await repository.synchronizeCatalog(testAgentCatalog())
    assert.deepEqual(await db.agentSettings.findMany({ orderBy: { agentType: "asc" } }), existing)

    const response = await app.inject({ url: "/api/agent-settings" })
    assert.equal(response.statusCode, 200)
    const rows = response.json()
    assert.deepEqual(rows.map((row: { agentType: string }) => row.agentType), [...TEST_AGENT_TYPES].sort())
    assert.equal(rows[0].configured, true)
    assert.equal(rows[0].configuration.model.name, "example-model")
    assert.deepEqual(rows[0].configuration.credential, { id: credential.id, name: "production", providerId: openai.id, providerName: "OpenAI" })
    assert.equal(rows[0].configuration.temperature, 0.25)
    assert.equal(rows[0].configuration.maxTokens, 2048)
    const dummy = rows.find((row: { agentType: string }) => row.agentType === DUMMY_AGENT_TYPE)
    assert.equal(dummy.configured, false)
    assert.equal(dummy.configuration.credential.providerName, "Google")
    assert.doesNotMatch(response.body, /private-key|apiKey|api_key/)

    for (const payload of [
      { modelId: model.id, credentialId: foreignCredential.id },
      { modelId: 999999, credentialId: credential.id },
      { modelId: model.id, credentialId: 999999 },
    ]) {
      const invalid = await app.inject({ method: "PUT", url: "/api/agent-settings/architecture", payload })
      assert.equal(invalid.statusCode, 422)
    }
    assert.deepEqual(await db.agentSettings.findUnique({ where: { agentType: PROJECT_ARCHITECTURE_AGENT_TYPE } }), existing.find((row) => row.agentType === PROJECT_ARCHITECTURE_AGENT_TYPE))
    assert.equal((await app.inject({ method: "PUT", url: "/api/agent-settings/not-an-agent", payload: { modelId: model.id, credentialId: credential.id } })).statusCode, 404)
    assert.equal((await app.inject({ method: "PUT", url: "/api/agent-settings/architecture", payload: { modelId: model.id } })).statusCode, 400)
    const secondModel = await db.aiModel.create({ data: { aiProviderId: openai.id, name: "second-model" } })
    const saved = await app.inject({ method: "PUT", url: "/api/agent-settings/architecture", payload: { modelId: secondModel.id, credentialId: credential.id } })
    assert.equal(saved.statusCode, 200)
    assert.equal(saved.json().configuration.model.id, secondModel.id)
    assert.equal(saved.json().configuration.temperature, 0.25)
    assert.equal(saved.json().configuration.maxTokens, 2048)
    assert.doesNotMatch(saved.body, /private-key|apiKey|api_key/)
    assert.equal((await app.inject({ url: "/api/agent-settings" })).json()[0].configuration.model.id, secondModel.id)

    const assignment = { modelId: secondModel.id, credentialId: credential.id }
    for (const options of [{ temperature: -0.1 }, { temperature: 2.1 }, { maxTokens: 0 }, { maxTokens: 1.5 }, { maxTokens: 2147483648 }]) {
      assert.equal((await app.inject({ method: "PUT", url: "/api/agent-settings/architecture", payload: { ...assignment, ...options } })).statusCode, 400)
    }
    const parameters = await app.inject({ method: "PUT", url: "/api/agent-settings/architecture", payload: { ...assignment, temperature: 0, maxTokens: 4096 } })
    assert.equal(parameters.statusCode, 200)
    assert.equal(parameters.json().configuration.temperature, 0)
    assert.equal(parameters.json().configuration.maxTokens, 4096)
    assert.equal(Number((await db.agentSettings.findUniqueOrThrow({ where: { agentType: PROJECT_ARCHITECTURE_AGENT_TYPE } })).temperature), 0)
    const cleared = await app.inject({ method: "PUT", url: "/api/agent-settings/architecture", payload: { ...assignment, temperature: null, maxTokens: null } })
    assert.equal(cleared.statusCode, 200)
    assert.equal(cleared.json().configuration.temperature, null)
    assert.equal(cleared.json().configuration.maxTokens, null)

    await db.agentSettings.update({
      where: { agentType: PROJECT_ARCHITECTURE_AGENT_TYPE },
      data: { aiCredentialId: foreignCredential.id, temperature: null, maxTokens: null },
    })
    const mismatched = (await app.inject({ url: "/api/agent-settings" })).json()
    assert.equal(mismatched[0].configured, false)
    assert.equal(mismatched[0].configuration.temperature, null)
    assert.equal(mismatched[0].configuration.maxTokens, null)
    await db.agentSettings.delete({ where: { agentType: DUMMY_AGENT_TYPE } })
    await repository.synchronizeCatalog(testAgentCatalog())
    assert.deepEqual(await db.agentSettings.findUnique({ where: { agentType: DUMMY_AGENT_TYPE }, select: { agentType: true, aiModelId: true, aiCredentialId: true, temperature: true, maxTokens: true } }), {
      agentType: DUMMY_AGENT_TYPE, aiModelId: null, aiCredentialId: null, temperature: null, maxTokens: null,
    })
    const savedDummy = await app.inject({ method: "PUT", url: "/api/agent-settings/dummy", payload: { modelId: model.id, credentialId: credential.id } })
    assert.equal(savedDummy.statusCode, 200)
    assert.equal(savedDummy.json().configured, true)
  } finally {
    await app.close()
    await db.$disconnect()
    rmSync(directory, { recursive: true, force: true })
  }
})
