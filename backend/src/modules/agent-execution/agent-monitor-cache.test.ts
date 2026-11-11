import assert from "node:assert/strict"
import { test } from "node:test"
import Fastify from "fastify"
import { logger } from "../../config/logger.js"
import type { AgentInvoker } from "../../infrastructure/agent-server-client/agent-server.client.js"
import type { AgentTargetResolver } from "../../infrastructure/agent-target/agent-target.resolver.js"
import type { AgentSettingsService } from "../agent-settings/agent-settings.service.js"
import type { AgentExecutionStore, StoredAgentExecution } from "./agent-execution.repository.js"
import { AgentExecutionNotFoundError, AgentExecutionService } from "./agent-execution.service.js"

function harness() {
  const app = Fastify({ logger: false })
  logger.configure(app.log)
  let fingerprint = "running:123"
  let row: StoredAgentExecution = {
    id: 1, evaluationId: 1, agentType: "maintainability_manager", status: "Running",
    result: JSON.stringify({ attributes: ["maintainability"], status: "running", run_id: "run-1",
      blackboard: { assessments: [] },
      report: { quality_results: { attributes: [{ id: "maintainability", status: "passed" }] },
        annexes_and_traceability: { executions: [{ agent_id: "maintainability_manager", invocation_id: "i-1",
          status: "running", parent_invocation_id: null, consumption: { input_tokens: 10, output_tokens: 5 } }] } },
      docx_base64: "AAAA" }),
    error: null, inputTokens: 10, outputTokens: 5, estimatedTokens: 0, interruptionReason: null,
    createdAt: new Date(), startedAt: new Date(), finishedAt: null,
    cancellationRequestedAt: null, dispatchStartedAt: new Date(),
    monitorContext: { project: null, branch: "main", commitHash: "abc123", evaluationType: "QualityAudit",
      qualityAttributes: ["maintainability"], workflowIds: ["maintainability"] },
  }
  let findByIdCalls = 0
  const unused = async (): Promise<never> => { throw new Error("Unexpected store operation") }
  const store: AgentExecutionStore = {
    findMonitorFingerprint: async () => fingerprint,
    findById: async () => { findByIdCalls += 1; return row },
    recentIds: unused, create: unused, createExecutionsForProject: unused, updateUsage: unused, patchResult: unused,
    requestAuditCancellation: unused, claimAuditDispatch: unused, pendingAuditCancellations: unused,
    markRunning: unused, recordInvocation: unused,
    complete: async (_id, completion) => {
      row = { ...row, ...completion, finishedAt: new Date() }
      fingerprint = `${completion.status}:9999`
      return row
    },
  }
  const service = new AgentExecutionService(store, { run: async () => ({}) } as unknown as AgentInvoker,
    { resolve: async () => ({ root_path: "checkout" }) } as AgentTargetResolver,
    { broadcast: () => {} }, "unused", {} as AgentSettingsService)
  return { service, calls: () => findByIdCalls, close: async () => { await app.close() } }
}

test("monitor polls reuse the cached compact projection until something mutates the row", async () => {
  const h = harness()
  try {
    const first = await h.service.findMonitorExecution(1)
    const second = await h.service.findMonitorExecution(1)
    assert.equal(second, first, "repeated polls serve the cached projection")
    assert.equal(h.calls(), 1)
    const compact = JSON.parse(first.result ?? "null") as { attributes: string[], status: string, run_id: string }
    assert.deepEqual(compact.attributes, ["maintainability"])
    assert.equal(
      (JSON.parse(first.result!) as { report: { annexes_and_traceability: { executions: unknown[] } } })
        .report.annexes_and_traceability.executions.length,
      1)
    await h.service.complete(1, { status: "Completed", result: null, error: null,
      inputTokens: null, outputTokens: null })
    const before = h.calls()
    await h.service.findMonitorExecution(1)
    assert.equal(h.calls(), before + 1, "a completion re-projects instead of serving the stale cache")
  } finally { await h.close() }
})

test("an unknown execution is reported as not found", async () => {
  const app = Fastify({ logger: false })
  logger.configure(app.log)
  const unused = async (): Promise<never> => { throw new Error("Unexpected store operation") }
  const store: AgentExecutionStore = {
    findMonitorFingerprint: async () => null, findById: unused, recentIds: unused, create: unused,
    createExecutionsForProject: unused, updateUsage: unused, patchResult: unused,
    requestAuditCancellation: unused, claimAuditDispatch: unused, pendingAuditCancellations: unused,
    markRunning: unused, recordInvocation: unused, complete: unused,
  }
  const service = new AgentExecutionService(store, { run: async () => ({}) } as unknown as AgentInvoker,
    { resolve: async () => ({ root_path: "checkout" }) } as AgentTargetResolver,
    { broadcast: () => {} }, "unused", {} as AgentSettingsService)
  try {
    await assert.rejects(() => service.findMonitorExecution(404), AgentExecutionNotFoundError)
  } finally { await app.close() }
})
