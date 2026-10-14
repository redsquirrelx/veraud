import assert from "node:assert/strict"
import { test } from "node:test"
import { execFileSync } from "node:child_process"
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs"
import { join } from "node:path"
import { tmpdir } from "node:os"
import { buildApp } from "../app.js"
import type { AgentRunConfig } from "../modules/agent-settings/agent-configuration.js"
import { AgentConfigurationError } from "../modules/agent-settings/agent-configuration.js"
import { AgentSettingsRepository } from "../modules/agent-settings/agent-settings.repository.js"
import { AgentSettingsService } from "../modules/agent-settings/agent-settings.service.js"
import { auditResponseSerialization } from "./helpers/responseSerializationAudit.js"

test("model access gates execution; immutable snapshots, credentials and verification revisions", async () => {
  const directory = mkdtempSync(join(tmpdir(), "veraud-config-execution-"))
  const databaseUrl = `file:${join(directory, "test.db")}`
  execFileSync(process.execPath, ["node_modules/prisma/build/index.js", "migrate", "deploy"], { env: { ...process.env, DATABASE_URL: databaseUrl }, stdio: "ignore" })
  let denied = false
  let deniedArchitecture = false
  let duringVerification: (() => Promise<void>) | null = null
  let duringArchitectureVerification: (() => Promise<void>) | null = null
  const dispatched: Array<{ pipeline: string, executionId: number, config: AgentRunConfig }> = []
  const verifier = { verify: async (config: AgentRunConfig) => {
    if (duringVerification) { const action = duringVerification; duringVerification = null; await action() }
    if (config.model.name === "model-B" && duringArchitectureVerification) {
      const action = duringArchitectureVerification; duringArchitectureVerification = null; await action()
    }
    if (denied) throw new Error("Model access denied")
    if (deniedArchitecture && config.model.name === "model-B") throw new Error("Architecture access denied")
  } }
  const { app, db } = await buildApp({
    databaseUrl, workspaceDir: join(directory, "workspace"), silent: true,
    makeModelAccessVerifier: () => verifier,
    makeAgentInvoker: () => ({ run: async (_type, _input, executionId, config) => {
      dispatched.push({ pipeline: "direct", executionId, config })
      return new Promise(() => {})
    }, runPipelineByName: async (pipeline, _input, ids, configs) => {
      for (const [stage, executionId] of Object.entries(ids)) dispatched.push({ pipeline, executionId, config: configs[stage]! })
      return new Promise(() => {})
    } }),
  })
  auditResponseSerialization(app)
  try {
    const provider = await db.aiProvider.findFirstOrThrow({ where: { name: "OpenAI" } })
    const google = await db.aiProvider.findFirstOrThrow({ where: { name: "Google" } })
    const model = await db.aiModel.create({ data: { name: "model-A", aiProviderId: provider.id } })
    const modelB = await db.aiModel.create({ data: { name: "model-B", aiProviderId: provider.id } })
    const credential = await db.aiCredential.create({ data: { name: "credential-A", apiKey: "secret-A", aiProviderId: provider.id } })
    const foreign = await db.aiCredential.create({ data: { name: "foreign", apiKey: "foreign-secret", aiProviderId: google.id } })
    const project = await db.project.create({ data: { repositoryOwner: "acme", repositoryName: "app", status: "READY" } })
    const checkout = join(directory, "workspace", `project-${project.id}-acme-app`)
    mkdirSync(checkout, { recursive: true }); writeFileSync(join(checkout, "README.md"), "fixture")
    const start = () => app.inject({ method: "POST", url: `/api/projects/${project.id}/architecture`, payload: { branch: "main", commitHash: "a".repeat(40) } })
    const direct = () => app.inject({ method: "POST", url: "/api/agent-executions/direct", payload: { agentType: "orientation", input: { code: "fixture" } } })
    const save = (agentType: string, modelId: number, temperature: number | null, maxTokens: number | null) => app.inject({ method: "PUT", url: `/api/agent-settings/${agentType}`, payload: { modelId, credentialId: credential.id, temperature, maxTokens } })
    const verify = () => app.inject({ method: "POST", url: "/api/agent-settings/orientation/verify" })
    const settings = async () => (await app.inject({ url: "/api/agent-settings" })).json().find((row: { agentType: string }) => row.agentType === "orientation")

    assert.equal((await start()).statusCode, 422)
    assert.equal(await db.evaluation.count(), 0)
    assert.equal(await db.projectVersion.count(), 0)
    await save("orientation", model.id, 0.2, 2048)
    await save("architecture", modelB.id, 0.5, 1024)
    await save("semantic_validation", model.id, 0.2, 2048)
    denied = true
    assert.equal((await verify()).json().verification.status, "failed")
    const blocked = await start()
    assert.equal(blocked.statusCode, 422)
    assert.equal(blocked.json().agents[0].agentType, "orientation")
    assert.equal(await db.evaluation.count(), 0)
    assert.equal(await db.agentExecution.count(), 0)

    denied = false
    assert.equal((await verify()).json().verification.status, "verified")
    assert.ok((await settings()).verification.checkedAt)
    deniedArchitecture = true
    const blockedArchitecture = await start()
    assert.equal(blockedArchitecture.statusCode, 422)
    assert.equal(blockedArchitecture.json().agents[0].agentType, "architecture")
    assert.equal(await db.evaluation.count(), 0)
    assert.equal(await db.projectVersion.count(), 0)
    assert.equal(await db.agentExecution.count(), 0)
    assert.equal(dispatched.length, 0)
    deniedArchitecture = false
    duringArchitectureVerification = async () => { await save("orientation", model.id, 0.3, 2048) }
    const changedDuringPipeline = await start()
    assert.equal(changedDuringPipeline.statusCode, 422)
    assert.match(changedDuringPipeline.json().message, /changed/)
    assert.equal(await db.projectVersion.count(), 0)
    assert.equal(await db.evaluation.count(), 0)
    assert.equal(await db.agentExecution.count(), 0)
    await save("orientation", model.id, 0.2, 2048)
    const first = await start()
    assert.equal(first.statusCode, 201, first.body)
    const firstId = first.json().executions.orientation.id
    assert.equal(first.json().executions.orientation.configuration.model.name, "model-A")
    assert.equal(first.json().executions.architecture.configuration.model.name, "model-B")
    assert.doesNotMatch(first.body, /secret-A|api_key|apiKey/)
    const deadline = Date.now() + 3000
    while (!dispatched.some((run) => run.executionId === firstId) && Date.now() < deadline) await new Promise((done) => setTimeout(done, 10))
    assert.equal(dispatched[0]?.pipeline, "project-architecture")
    assert.equal(dispatched[0]?.config.api_key, "secret-A")
    assert.equal(dispatched[0]?.config.model.max_tokens, 2048)
    assert.equal(dispatched.find((run) => run.executionId === first.json().executions.architecture.id)?.config.model.max_tokens, 1024)
    assert.equal(dispatched.find((run) => run.executionId === first.json().executions.architecture.id)?.config.model.temperature, 0.5)
    const snapshot = await db.agentExecution.findUniqueOrThrow({ where: { id: firstId } })

    await save("orientation", modelB.id, 0.8, 4096)
    assert.equal((await settings()).verification.status, "not_verified")
    const rotated = await app.inject({ method: "PATCH", url: `/api/ai-providers/${provider.id}/credentials/${credential.id}`, payload: { name: "credential-A", apiKey: "secret-B" } })
    assert.equal(rotated.statusCode, 200)
    const second = await direct()
    assert.equal(second.statusCode, 201, second.body)
    assert.equal(second.json().configuration.model.name, "model-B")
    assert.equal(second.json().configuration.temperature, 0.8)
    assert.equal(dispatched.find((run) => run.executionId === second.json().id)?.config.api_key, "secret-B")
    assert.deepEqual((await db.agentExecution.findUniqueOrThrow({ where: { id: firstId } })).configurationSnapshot, snapshot.configurationSnapshot)
    assert.equal(dispatched[0]?.config.api_key, "secret-A")
    assert.equal(dispatched[0]?.config.model.temperature, 0.2)
    assert.equal((await app.inject({ url: `/api/agent-executions/${firstId}` })).json().configuration.model.name, "model-A")
    assert.equal((await app.inject({ url: `/api/projects/${project.id}/versions` })).json()[0].execution.configuration.model.name, "model-A")

    await verify()
    await app.inject({ method: "PATCH", url: `/api/ai-providers/${provider.id}/models/${modelB.id}`, payload: { name: "model-renamed" } })
    assert.equal((await settings()).verification.status, "not_verified")
    await verify()
    await app.inject({ method: "PATCH", url: `/api/ai-providers/${provider.id}/credentials/${credential.id}`, payload: { name: "credential-A", apiKey: "secret-C" } })
    assert.equal((await settings()).verification.status, "not_verified")

    duringVerification = async () => { await save("orientation", model.id, 0.1, 1000) }
    const stale = await direct()
    assert.equal(stale.statusCode, 422)
    assert.match(stale.json().error, /changed/)
    assert.equal(await db.agentExecution.count(), 4)

    await db.agentSettings.update({ where: { agentType: "orientation" }, data: { aiCredentialId: foreign.id } })
    assert.equal((await direct()).statusCode, 422)
    const service = new AgentSettingsService(new AgentSettingsRepository(db), verifier)
    await assert.rejects(service.prepareExecution(["orientation", "dummy"]), (error: unknown) => {
      assert.ok(error instanceof AgentConfigurationError)
      assert.deepEqual(error.agents.map((agent) => agent.agentType), ["orientation", "dummy"])
      return true
    })
    assert.doesNotMatch((await app.inject({ url: "/api/agent-settings" })).body, /secret-[ABC]|foreign-secret|apiKey|api_key/)
  } finally {
    await app.close(); await db.$disconnect(); rmSync(directory, { recursive: true, force: true })
  }
})
