import assert from "node:assert/strict"
import { test } from "node:test"
import { monitorExecution } from "./agent-execution.monitor.js"
import type { StoredAgentExecution } from "./agent-execution.repository.js"

test("compact monitor preserves actual invocation parents without exposing retained reports", () => {
  const traces = ["manager", "modularity-1", "boundary-1", "modularity-2", "boundary-2", "orphan"].map((id) => ({
    agent_id: id.split("-")[0], invocation_id: id, status: "completed", consumption: {},
  }))
  const child = (id: string, result = {}) => ({ assignment: { invocation_id: id }, result })
  const raw = { attributes: ["maintainability"], status: "completed",
    report: { annexes_and_traceability: { executions: traces } },
    blackboard: { assessments: [{ invocation_id: "manager", details: { report: {
      assessments: [child("modularity-1", { invocations: [child("boundary-1")] }),
        child("modularity-2", { invocations: [child("boundary-2")] })], private_evidence: "source contents",
    } } }] }, docx_base64: "binary artifact" }
  const execution = { result: JSON.stringify(raw), monitorContext: { evaluationType: "QualityAudit" } } as StoredAgentExecution
  const result = monitorExecution(execution).result!
  const compact = JSON.parse(result)
  assert.deepEqual(compact.report.annexes_and_traceability.executions.map((trace: { parent_invocation_id: string | null }) => trace.parent_invocation_id),
    [null, "manager", "modularity-1", "manager", "modularity-2", null])
  assert.doesNotMatch(result, /private_evidence|source contents|docx_base64|blackboard/)
  assert.equal(execution.result, JSON.stringify(raw), "original artifacts remain unchanged")
})
