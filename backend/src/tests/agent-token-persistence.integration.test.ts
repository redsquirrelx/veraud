import assert from "node:assert/strict"
import { execFileSync } from "node:child_process"
import { once } from "node:events"
import { mkdtempSync, readFileSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { test } from "node:test"
import { DatabaseSync } from "node:sqlite"
import { buildApp } from "../app.js"
import { makeTestAgentCatalogSource } from "./helpers/agentCatalog.js"
import { AgentSettingsRepository } from "../modules/agent-settings/agent-settings.repository.js"
import { AgentExecutionRepository } from "../modules/agent-execution/agent-execution.repository.js"
import { AgentConfigurationError } from "../modules/agent-settings/agent-configuration.js"
import { auditResponseSerialization } from "./helpers/responseSerializationAudit.js"

test("absolute-limit migration preserves saved budgets, usage and historical snapshots", () => {
  const db = new DatabaseSync(":memory:")
  try {
    db.exec(`
      CREATE TABLE agent_settings (
        agent_type TEXT PRIMARY KEY,
        verification_fingerprint TEXT,
        verification_checked_at DATETIME,
        verification_error TEXT
      );
      CREATE TABLE agent_execution (
        id INTEGER PRIMARY KEY, input_tokens INTEGER, output_tokens INTEGER,
        result TEXT, configuration_snapshot TEXT
      );
    `)
    db.exec(readFileSync(new URL("../../prisma/migrations/20261014000000_agent_token_budget/migration.sql", import.meta.url), "utf8"))
    db.exec(`
      INSERT INTO agent_settings (agent_type, token_budget, token_tolerance_percent, verification_fingerprint)
      VALUES ('orientation', 10001, 20, 'old-check'), ('architecture', 20000, 0, 'old-check'), ('dummy', NULL, NULL, 'unchanged-check');
    `)
    const snapshot = { tokenBudget: 10001, tokenTolerancePercent: 20, absoluteTokenLimit: 12001, model: { name: "historical-model" } }
    db.prepare("INSERT INTO agent_execution (id, input_tokens, output_tokens, result, configuration_snapshot, estimated_tokens, accounted_tokens, interruption_reason) VALUES (1, 8000, 2000, ?, ?, 1000, 11000, 'token_budget_exhausted')")
      .run('{"summary":"partial"}', JSON.stringify(snapshot))
    db.exec(readFileSync(new URL("../../prisma/migrations/20261014010000_agent_absolute_token_limit/migration.sql", import.meta.url), "utf8"))
    assert.equal(db.prepare("SELECT absolute_token_limit FROM agent_settings WHERE agent_type = 'orientation'").get()?.absolute_token_limit, 12001)
    assert.equal(db.prepare("SELECT absolute_token_limit FROM agent_settings WHERE agent_type = 'architecture'").get()?.absolute_token_limit, 20000)
    assert.equal(db.prepare("SELECT absolute_token_limit FROM agent_settings WHERE agent_type = 'dummy'").get()?.absolute_token_limit, null)
    assert.equal(db.prepare("SELECT verification_fingerprint FROM agent_settings WHERE agent_type = 'dummy'").get()?.verification_fingerprint, "unchanged-check")
    assert.throws(() => db.prepare("SELECT token_tolerance_percent FROM agent_settings"))
    assert.throws(() => db.exec("UPDATE agent_settings SET absolute_token_limit = 10000 WHERE agent_type = 'orientation'"))
    const historical = db.prepare("SELECT * FROM agent_execution WHERE id = 1").get()!
    assert.deepEqual(JSON.parse(historical.configuration_snapshot as string), {
      tokenBudget: 10001, absoluteTokenLimit: 12001, model: { name: "historical-model" },
    })
    assert.equal(historical.result, '{"summary":"partial"}')
    assert.equal(historical.accounted_tokens, 11000)
    assert.equal(historical.interruption_reason, "token_budget_exhausted")
    db.exec(readFileSync(new URL("../../prisma/migrations/20261014020000_derive_agent_token_total/migration.sql", import.meta.url), "utf8"))
    assert.throws(() => db.prepare("SELECT accounted_tokens FROM agent_execution"))
    const derived = db.prepare("SELECT input_tokens + output_tokens + estimated_tokens AS total FROM agent_execution WHERE id = 1").get()
    assert.equal(derived?.total, 11000)
  } finally { db.close() }
})

test("token budgets, immutable snapshots and cumulative usage survive persistence", async () => {
  const directory = mkdtempSync(join(tmpdir(), "veraud-token-persistence-"))
  const databaseUrl = `file:${join(directory, "test.db")}`
  execFileSync(process.execPath, ["node_modules/prisma/build/index.js", "migrate", "deploy"], {
    env: { ...process.env, DATABASE_URL: databaseUrl }, stdio: "ignore",
  })
  const { app, db } = await buildApp({ databaseUrl, workspaceDir: join(directory, "workspace"), silent: true, makeAgentCatalogSource: makeTestAgentCatalogSource })
  auditResponseSerialization(app)
  try {
    const provider = await db.aiProvider.findFirstOrThrow({ where: { name: "OpenAI" } })
    const model = await db.aiModel.create({ data: { name: "test-model", aiProviderId: provider.id } })
    const credential = await db.aiCredential.create({ data: { name: "test-key", apiKey: "secret", aiProviderId: provider.id } })
    const settings = new AgentSettingsRepository(db)
    const executions = new AgentExecutionRepository(db, settings)
    const assignment = { modelId: model.id, credentialId: credential.id }
    const save = (options: object) => app.inject({ method: "PUT", url: "/api/agent-settings/orientation", payload: { ...assignment, ...options } })

    const initial = await db.agentSettings.findUniqueOrThrow({ where: { agentType: "orientation" } })
    assert.equal(initial.tokenBudget, null)
    assert.equal(initial.absoluteTokenLimit, null)
    const saved = await save({ tokenBudget: 10001, absoluteTokenLimit: 12001 })
    assert.equal(saved.statusCode, 200, saved.body)
    assert.equal(saved.json().configuration.absoluteTokenLimit, 12001)
    assert.equal((await save({ temperature: 0.5 })).json().configuration.tokenBudget, 10001)
    for (const invalid of [
      { tokenBudget: 0 }, { tokenBudget: 1.5 }, { absoluteTokenLimit: 0 },
      { absoluteTokenLimit: 1.5 }, { tokenBudget: 2147483648 }, { absoluteTokenLimit: 2147483648 },
    ]) assert.equal((await save(invalid)).statusCode, 400)
    assert.equal((await save({ absoluteTokenLimit: 10000 })).statusCode, 422)
    assert.equal((await save({ tokenBudget: 12002 })).statusCode, 422)
    assert.equal((await db.agentSettings.findUniqueOrThrow({ where: { agentType: "orientation" } })).tokenBudget, 10001)

    const prepared = await settings.prepare("orientation")
    const execution = await executions.create({ agentType: "orientation", evaluationId: null, configuration: prepared })
    assert.equal(execution.inputTokens, null)
    assert.equal(execution.configuration?.absoluteTokenLimit, 12001)
    const strict = await save({ tokenBudget: 20000, absoluteTokenLimit: 20000 })
    assert.equal(strict.statusCode, 200, strict.body)
    assert.equal((await executions.findById(execution.id))?.configuration?.tokenBudget, 10001)
    await assert.rejects(executions.create({ agentType: "orientation", evaluationId: null, configuration: prepared }), AgentConfigurationError)

    await executions.markRunning(execution.id)
    const progressUrl = `/api/agent-executions/${execution.id}/progress`
    const usage = { inputTokens: 8000, outputTokens: 2000, estimatedTokens: 1000 }
    await app.ready()
    const socket = await app.injectWS("/ws")
    try {
      const nextEvent = once(socket, "message", { signal: AbortSignal.timeout(5000) })
      const progress = await app.inject({ method: "POST", url: progressUrl, payload: usage })
      assert.equal(progress.statusCode, 200, progress.body)
      assert.equal(progress.json().estimatedTokens, 1000)
      assert.equal(progress.json().status, "Running")
      const [message] = await nextEvent
      const event = JSON.parse(String(message))
      assert.equal(event.type, "agent-execution.updated")
      assert.equal(event.execution.id, execution.id)
      assert.equal(event.execution.inputTokens, 8000)
      assert.equal(event.execution.estimatedTokens, 1000)
    } finally { socket.terminate() }
    assert.equal((await app.inject({ method: "POST", url: progressUrl, payload: usage })).json().inputTokens, 8000)
    const stale = await executions.updateUsage(execution.id, { inputTokens: 100, outputTokens: 100, estimatedTokens: 0 })
    assert.equal(stale.inputTokens, 8000)
    await assert.rejects(executions.updateUsage(execution.id, { ...usage, estimatedTokens: -1 }), RangeError)
    for (const invalid of [{ inputTokens: -1, outputTokens: 0 }, { inputTokens: 1.5, outputTokens: 0 }, { inputTokens: 2147483648, outputTokens: 0 }, { inputTokens: 1 }]) {
      assert.equal((await app.inject({ method: "POST", url: progressUrl, payload: invalid })).statusCode, 400)
    }
    assert.equal((await app.inject({ method: "POST", url: "/api/agent-executions/999999/progress", payload: usage })).statusCode, 404)

    const partial = '{"summary":"partial analysis"}'
    const completion = await app.inject({ method: "POST", url: `/api/agent-executions/${execution.id}/completion`, payload: {
      status: "Failed", result: partial, error: "Absolute token limit reached",
      inputTokens: null, outputTokens: null, interruptionReason: "token_budget_exhausted",
    } })
    assert.equal(completion.statusCode, 200, completion.body)
    const completed = (await executions.findById(execution.id))!
    assert.equal(completed.inputTokens, 8000)
    assert.equal(completed.outputTokens, 2000)
    assert.equal(completed.estimatedTokens, 1000)
    assert.equal(completed.interruptionReason, "token_budget_exhausted")
    const late = await executions.updateUsage(execution.id, { inputTokens: 9000, outputTokens: 2000, estimatedTokens: 1000 })
    assert.deepEqual(late, completed)
    const persisted = await db.agentExecution.findUniqueOrThrow({ where: { id: execution.id } })
    assert.equal(persisted.result, partial)
    assert.equal((persisted.inputTokens ?? 0) + (persisted.outputTokens ?? 0) + (persisted.estimatedTokens ?? 0), 11000)
    assert.equal(persisted.interruptionReason, "token_budget_exhausted")
    const stored = (await app.inject({ url: `/api/agent-executions/${execution.id}` })).json()
    assert.equal(stored.estimatedTokens, 1000)
    assert.equal(stored.interruptionReason, "token_budget_exhausted")
    assert.equal((await app.inject({ method: "POST", url: `/api/agent-executions/${execution.id}/running` })).json().status, "Failed")

    const cleared = await save({ tokenBudget: null, absoluteTokenLimit: null })
    assert.equal(cleared.json().configuration.tokenBudget, null)
    assert.equal(cleared.json().configuration.absoluteTokenLimit, null)
  } finally {
    await app.close()
    await db.$disconnect()
    rmSync(directory, { recursive: true, force: true })
  }
})
