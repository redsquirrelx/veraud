import assert from "node:assert/strict"
import { test } from "node:test"
import Fastify from "fastify"
import { logger } from "../../config/logger.js"
import { AgentTransportError, AuditRunUnavailableError, type AgentInvoker } from "../../infrastructure/agent-server-client/agent-server.client.js"
import type { AgentTargetResolver } from "../../infrastructure/agent-target/agent-target.resolver.js"
import type { AgentSettingsService } from "../agent-settings/agent-settings.service.js"
import type { AgentExecutionStore, StoredAgentExecution } from "./agent-execution.repository.js"
import { AgentExecutionService } from "./agent-execution.service.js"

function harness(agents: AgentInvoker) {
  let row: StoredAgentExecution = { id: 1, evaluationId: 1, agentType: "security", status: "Running",
    result: JSON.stringify({ run_id: "existing-run", attributes: ["security"] }), error: null,
    inputTokens: 123, outputTokens: 45, estimatedTokens: 0, interruptionReason: null,
    createdAt: new Date(), startedAt: new Date(), finishedAt: null }
  const events: string[] = []
  const unused = async (): Promise<never> => { throw new Error("Unexpected store operation during reconciliation") }
  const store = {
    recordInvocation: unused, create: unused, updateUsage: unused,
    patchResult: unused, createExecutionsForProject: unused,
    findById: async () => row,
    markRunning: async () => row,
    complete: async (_id, completion) => {
      row = { ...row, ...completion, finishedAt: new Date() }
      return row
    },
  } satisfies AgentExecutionStore
  // These cases enter dispatch/reconciliation after configuration has been captured.
  const service = new AgentExecutionService(store, agents,
    { resolve: async () => ({ root_path: "checkout" }) } as AgentTargetResolver,
    { broadcast: (event) => { events.push(event.execution.status) } }, "unused", {} as AgentSettingsService)
  return { service, row: () => row, events }
}

test("an active run remains Running across status polls and closes only when its report is recovered", async (context) => {
  const app = Fastify({ logger: false })
  logger.configure(app.log)
  context.mock.timers.enable({ apis: ["setTimeout", "Date"] })
  let polls = 0
  try {
    const { service, row, events } = harness({ run: async () => ({}), getAuditResult: async () => {
      polls++
      if (polls === 1) return null
      return { run_id: "existing-run", status: "partial", report: { status: "partial" }, docx_base64: "UEs=" }
    } })
    const recovering = service["reconcileAudit"](1, ["security"], Date.now() + 60000)
    await new Promise<void>((resolve) => setImmediate(resolve))
    assert.equal(polls, 1)
    assert.equal(row().status, "Running")
    assert.deepEqual(events, [])
    context.mock.timers.tick(5000)
    await recovering
    assert.equal(polls, 2)
    assert.equal(row().status, "Completed")
    assert.equal(row().interruptionReason, "partial")
    assert.deepEqual(events, ["Completed"])
  } finally { await app.close() }
})

test("transient reconciliation errors preserve Running; recovery has a finite deadline", async () => {
  const app = Fastify({ logger: false })
  logger.configure(app.log)
  try {
    const { service, row, events } = harness({ run: async () => ({}), getAuditResult: async () => { throw new Error("network unavailable") } })
    await assert.rejects(() => service["reconcileAudit"](1, ["security"], Date.now() - 1), /outcome could not be confirmed/)
    assert.equal(row().status, "Running", "a failed status request is not an agent failure")
    assert.equal(row().finishedAt, null)
    assert.deepEqual(events, [])
  } finally { await app.close() }
})

test("a missing retained run terminates recovery explicitly instead of waiting forever", async () => {
  const app = Fastify({ logger: false })
  logger.configure(app.log)
  try {
    const { service } = harness({ run: async () => ({}), getAuditResult: async () => { throw new AuditRunUnavailableError() } })
    await assert.rejects(() => service["reconcileAudit"](1, ["security"], Date.now() + 60000), /no longer retains the run/)
  } finally { await app.close() }
})

test("dispatch preserves the run identity when recovery is unavailable, instead of recording a generic agent failure", async () => {
  const app = Fastify({ logger: false })
  logger.configure(app.log)
  try {
    const { service, row } = harness({ run: async () => ({}),
      runPipelineByName: async () => { throw new AgentTransportError("ECONNRESET", true) },
      getAuditResult: async () => { throw new AuditRunUnavailableError() } })
    await service["dispatchQualityAudit"](row(), {}, "a".repeat(40), ["security"], {})
    assert.equal(row().status, "Failed")
    assert.match(row().error!, /outcome could not be recovered/)
    assert.doesNotMatch(row().error!, /fetch failed/)
    assert.equal(row().interruptionReason, "audit_outcome_unconfirmed")
    assert.equal(JSON.parse(row().result!)["run_id"], "existing-run")
  } finally { await app.close() }
})

test("a connection refused before dispatch fails promptly without polling a nonexistent audit", async () => {
  const app = Fastify({ logger: false })
  logger.configure(app.log)
  let queried = false
  try {
    const { service, row } = harness({ run: async () => ({}),
      runPipelineByName: async () => { throw new AgentTransportError("ECONNREFUSED", false) },
      getAuditResult: async () => { queried = true; return null } })
    await service["dispatchQualityAudit"](row(), {}, "a".repeat(40), ["security"], {})
    assert.equal(row().status, "Failed")
    assert.equal(queried, false)
    assert.match(row().error!, /ECONNREFUSED/)
  } finally { await app.close() }
})
