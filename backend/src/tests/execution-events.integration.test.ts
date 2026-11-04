import assert from "node:assert/strict"
import { execFileSync } from "node:child_process"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { randomUUID } from "node:crypto"
import { test } from "node:test"
import { buildApp } from "../app.js"
import { makeTestAgentCatalogSource } from "./helpers/agentCatalog.js"
import { ExecutionEventRepository, type ExecutionEventInput } from "../modules/agent-execution/execution-events.js"

test("durable events are append-only, idempotent, chronological, isolated and content-free", async () => {
  const directory = mkdtempSync(join(tmpdir(), "veraud-events-"))
  const databaseUrl = `file:${join(directory, "test.db")}`
  execFileSync(process.execPath, ["node_modules/prisma/build/index.js", "migrate", "deploy"], {
    env: { ...process.env, DATABASE_URL: databaseUrl }, stdio: "ignore",
  })
  const { app, db } = await buildApp({ databaseUrl, workspaceDir: join(directory, "workspace"), silent: true, makeAgentCatalogSource: makeTestAgentCatalogSource })
  try {
    const first = await db.agentExecution.create({ data: { agentType: "orientation", status: "Completed", result: '{"run_id":"audit"}' } })
    const second = await db.agentExecution.create({ data: { agentType: "orientation", status: "Waiting" } })
    const streamId = randomUUID()
    const event = (sequence: number): ExecutionEventInput => ({ eventId: randomUUID(), streamId, sequence,
      occurredAt: `2026-10-31T10:00:0${sequence}Z`, runId: "audit", invocationId: "child", parentInvocationId: "root",
      agentId: "orientation", actionId: "action", parentActionId: null, sourceId: "tool-call-1", kind: "tool.started", name: "list_files", status: "running", metadata: { attempt: sequence, cache_hit: true } })
    const earlier = event(1)
    const later = event(2)
    const post = (id: number, events: ExecutionEventInput[]) => app.inject({ method: "POST", url: `/api/agent-executions/${id}/events`, payload: { events } })
    // Delayed events are accepted even after completion; immutable history must not mutate lifecycle state.
    assert.equal((await post(first.id, [later, earlier])).statusCode, 200)
    assert.equal((await post(first.id, [earlier, later])).statusCode, 200)
    assert.equal(await db.executionEvent.count(), 2)
    assert.equal((await db.agentExecution.findUniqueOrThrow({ where: { id: first.id } })).status, "Completed")
    assert.equal((await post(first.id, [{ ...earlier, status: "failed" }])).statusCode, 422)
    assert.equal((await post(first.id, [{ ...earlier, eventId: randomUUID() }])).statusCode, 422)
    assert.equal((await post(second.id, [earlier])).statusCode, 422)
    assert.equal((await post(first.id, [{ ...event(3), runId: "another-audit" }])).statusCode, 422)
    assert.equal((await post(999999, [event(3)])).statusCode, 404)
    assert.equal((await post(first.id, [{ ...event(3), occurredAt: "invalid" }])).statusCode, 400)
    assert.equal((await post(first.id, Array.from({ length: 101 }, (_, i) => event(i + 3)))).statusCode, 400)
    const response = await app.inject(`/api/agent-executions/${first.id}/events?limit=1`)
    assert.equal(response.statusCode, 200, response.body)
    assert.equal(response.json().total, 2)
    assert.equal(response.json().events[0].eventId, earlier.eventId)
    assert.equal(response.json().events[0].parentInvocationId, "root")
    assert.equal(response.json().events[0].sourceId, "tool-call-1")
    assert.equal(response.json().events[0].metadata.cache_hit, true)
    assert.equal((await app.inject(`/api/agent-executions/${first.id}/events?offset=1`)).json().events[0].eventId, later.eventId)
    assert.equal((await app.inject(`/api/agent-executions/${second.id}/events`)).json().total, 0)
    assert.equal((await app.inject(`/api/agent-executions/${first.id}/events?limit=201`)).statusCode, 400)
    // The persistence boundary also projects safe metadata when called without HTTP validation.
    const privateEvent = { ...event(3), name: "sk-fake-key", metadata: { input_tokens: 12, password: "private", prompt: "Bearer private" } }
    await new ExecutionEventRepository(db).append(first.id, [privateEvent])
    const serialized = (await app.inject(`/api/agent-executions/${first.id}/events`)).body
    assert(!serialized.includes("private"))
    assert(!serialized.includes("sk-fake-key"))
    assert(!serialized.includes("password"))
    assert.equal((await db.executionEvent.findUniqueOrThrow({ where: { eventId: privateEvent.eventId } })).metadata, '{"input_tokens":12}')
  } finally {
    await app.close()
    await db.$disconnect()
    rmSync(directory, { recursive: true, force: true })
  }
})
