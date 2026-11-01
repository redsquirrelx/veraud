import assert from "node:assert/strict"
import { test } from "node:test"
import Fastify from "fastify"
import { logger } from "../../config/logger.js"
import type { AgentInvoker } from "../../infrastructure/agent-server-client/agent-server.client.js"
import type { AgentTargetResolver } from "../../infrastructure/agent-target/agent-target.resolver.js"
import type { AgentSettingsService } from "../agent-settings/agent-settings.service.js"
import type { AgentExecutionStore, StoredAgentExecution } from "./agent-execution.repository.js"
import { AgentExecutionService } from "./agent-execution.service.js"

function harness(agents: Partial<AgentInvoker> = {}) {
  const app = Fastify({ logger: false })
  logger.configure(app.log)
  let row: StoredAgentExecution = {
    id: 1, evaluationId: 1, agentType: "security", status: "Running",
    result: JSON.stringify({ run_id: "run-1", attributes: ["security"] }), error: null,
    inputTokens: 123, outputTokens: 45, estimatedTokens: 10, interruptionReason: null,
    createdAt: new Date(), startedAt: new Date(), finishedAt: null,
    cancellationRequestedAt: null, dispatchStartedAt: new Date(),
  }
  const events: StoredAgentExecution[] = []
  const unused = async (): Promise<never> => { throw new Error("Unexpected store operation") }
  const store: AgentExecutionStore = {
    create: unused, createExecutionsForProject: unused, updateUsage: unused, patchResult: unused,
    findById: async () => row,
    requestAuditCancellation: async () => {
      if (!["Completed", "Failed"].includes(row.status) && !row.cancellationRequestedAt) {
        row = { ...row, cancellationRequestedAt: new Date(), interruptionReason: "cancellation_requested" }
      }
      return row
    },
    claimAuditDispatch: async () => {
      if (row.cancellationRequestedAt || row.dispatchStartedAt || ["Completed", "Failed"].includes(row.status)) return false
      row = { ...row, dispatchStartedAt: new Date() }
      return true
    },
    pendingAuditCancellations: async () => row.cancellationRequestedAt && !row.finishedAt ? [row.id] : [],
    markRunning: async (_id, runId) => {
      row = { ...row, status: "Running", startedAt: new Date(),
        ...(runId ? { result: JSON.stringify({ attributes: ["security"], run_id: runId }) } : {}) }
      return row
    },
    recordInvocation: async (_id, receipt) => { row = { ...row, invocations: [receipt] }; return row },
    complete: async (_id, completion) => {
      if (!["Completed", "Failed"].includes(row.status)) {
        row = { ...row, ...completion, inputTokens: row.inputTokens, outputTokens: row.outputTokens, finishedAt: new Date() }
      }
      return row
    },
  }
  const service = new AgentExecutionService(store, { run: async () => ({}), ...agents },
    { resolve: async () => ({ root_path: "checkout" }) } as AgentTargetResolver,
    { broadcast: (event) => { events.push(event.execution as unknown as StoredAgentExecution) } }, "unused", {} as AgentSettingsService)
  return { service, store, row: () => row, set: (patch: Partial<StoredAgentExecution>) => { row = { ...row, ...patch } },
    events, close: async () => { await service.stopAuditCancellations(); await app.close() } }
}

const tick = () => new Promise<void>((resolve) => setImmediate(resolve))

test("a persisted request/remote acknowledgement is not terminal; repeated requests forward only once", async () => {
  let sends = 0
  let state = "cancelling"
  const h = harness({ cancelAudit: async () => { sends++; return { run_id: "run-1", status: "cancelling" } },
    getAuditSnapshot: async () => ({ run_id: "run-1", status: state, evidence: [{ id: "retained" }] }) })
  try {
    await h.service.cancelQualityAudit(1)
    await tick()
    const requested = h.row().cancellationRequestedAt
    assert.ok(requested)
    assert.equal(h.row().status, "Running")
    assert.equal(h.row().finishedAt, null)
    assert.equal(h.events[0]?.interruptionReason, "cancellation_requested")
    await h.service.cancelQualityAudit(1)
    await tick()
    assert.equal(sends, 1)
    assert.equal(h.row().cancellationRequestedAt, requested)
    state = "cancelled"
    await h.service["processAuditCancellation"](1)
    assert.equal(h.row().status, "Completed")
    assert.equal(h.row().interruptionReason, "cancelled")
    assert.equal(h.row().inputTokens, 123)
    assert.deepEqual(JSON.parse(h.row().result!).blackboard.evidence, [{ id: "retained" }])
  } finally { await h.close() }
})

test("a cancellation requested before dispatch prevents the pipeline POST", async () => {
  let dispatched = false
  const h = harness({ runPipelineByName: async () => { dispatched = true; return {} } })
  h.set({ status: "Waiting", startedAt: null, dispatchStartedAt: null, result: '{"attributes":["security"]}' })
  try {
    await h.service.cancelQualityAudit(1)
    await h.service["dispatchQualityAudit"](h.row(), {}, "a".repeat(40), ["security"], {})
    await tick()
    assert.equal(dispatched, false)
    assert.equal(h.row().interruptionReason, "cancelled")
  } finally { await h.close() }
})

test("a request without run_id is resumed by the running callback and survives service recovery", async () => {
  let sends = 0
  const h = harness({ cancelAudit: async () => { sends++; return { run_id: "later", status: "cancelling" } },
    getAuditSnapshot: async () => ({ run_id: "later", status: "running" }) })
  h.set({ result: '{"attributes":["security"]}' })
  try {
    await h.service.cancelQualityAudit(1)
    await tick()
    assert.equal(sends, 0)
    await h.service.markRunning(1, "later")
    // Recovery uses persisted fields, not a request-local closure.
    await h.service["processAuditCancellation"](1)
    assert.equal(sends, 1)
    assert.equal(h.row().status, "Running")
  } finally { await h.close() }
})

test("an unavailable agent-server leaves the request pending, including failed execution callbacks", async () => {
  const h = harness({ cancelAudit: async () => { throw new Error("offline") }, getAuditSnapshot: async () => ({}) })
  try {
    await h.service.cancelQualityAudit(1)
    await tick()
    await h.service.complete(1, { status: "Failed", result: null, error: "pipeline interrupted", inputTokens: null, outputTokens: null })
    assert.equal(h.row().status, "Running")
    assert.ok(h.row().cancellationRequestedAt)
    assert.equal(h.row().finishedAt, null)
    assert.equal(h.row().inputTokens, 123)
  } finally { await h.close() }
})

test("an interrupted pipeline POST after a cancellation request preserves the pending run", async () => {
  const h = harness({ runPipelineByName: async () => {
    await h.service.cancelQualityAudit(1)
    throw new Error("pipeline HTTP request interrupted")
  } })
  h.set({ status: "Waiting", startedAt: null, dispatchStartedAt: null, result: '{"attributes":["security"]}' })
  try {
    await h.service["dispatchQualityAudit"](h.row(), {}, "a".repeat(40), ["security"], {})
    assert.equal(h.row().status, "Running")
    assert.equal(h.row().finishedAt, null)
    assert.ok(h.row().cancellationRequestedAt)
    assert.equal(h.row().error, null)
  } finally { await h.close() }
})

test("normal completion wins a concurrent cancellation response; late callbacks cannot overwrite it", async () => {
  const h = harness({ cancelAudit: async () => ({ run_id: "run-1", status: "cancelling" }),
    getAuditSnapshot: async () => {
      h.set({ status: "Completed", result: '{"status":"completed","report":{"original":true}}', finishedAt: new Date(), interruptionReason: null })
      return { run_id: "run-1", status: "cancelled" }
    } })
  try {
    await h.service.cancelQualityAudit(1)
    await tick()
    assert.equal(JSON.parse(h.row().result!).status, "completed")
    assert.equal(h.row().interruptionReason, null)
    const result = h.row().result
    await h.service.cancelQualityAudit(1)
    assert.equal(h.row().result, result)
  } finally { await h.close() }
})
