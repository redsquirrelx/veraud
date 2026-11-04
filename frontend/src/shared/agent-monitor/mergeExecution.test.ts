// @vitest-environment node
import { expect, it } from "vitest"
import type { AgentExecution, AgentInvocation, ExecutionErrorDetail } from "../../infrastructure/http-client/httpClient.ts"
import { mergeExecution, mergeInvocations } from "./mergeExecution.ts"

const detail: ExecutionErrorDetail = { agentId: "investigator", invocationId: "child", occurredAt: "2026-10-30T12:00:00Z",
  code: "execution_timeout", exceptionType: "TimeoutError", message: "The child timed out." }

it("keeps the newest phase across stale hydration and clears it at completion", () => {
  const current: AgentInvocation = { invocation_id: "agent-1", parent_invocation_id: null, agent_id: "security",
    run_id: "audit", status: "running", started_at: "2026-10-20T10:00:00Z", finished_at: null,
    input_tokens: null, output_tokens: null, error: null, phase: "security_remediation", phase_sequence: 3 }
  const stale = { ...current, phase: "security_scan", phase_sequence: 2 }
  expect(mergeInvocations([current], [stale])[0]?.phase).toBe("security_remediation")
  expect(mergeInvocations([stale], [current])[0]?.phase).toBe("security_remediation")
  const finished = { ...current, status: "completed" as const, finished_at: "2026-10-20T10:01:00Z" }
  expect(mergeInvocations([current], [finished])[0]?.phase).toBeNull()
  expect(mergeInvocations([finished], [current])[0]?.phase).toBeNull()
})

it("preserves the original incident across stale and metadata-less root updates", () => {
  const execution: AgentExecution = { id: 1, evaluationId: 1, agentType: "security", status: "Failed",
    error: "failed", errorDetail: detail, result: null, inputTokens: 8, outputTokens: 2,
    createdAt: "2026-10-30T11:00:00Z", startedAt: null, finishedAt: "2026-10-30T12:01:00Z" }
  const late = { ...execution, status: "Running", errorDetail: null, finishedAt: null }
  expect(mergeExecution(execution, late)).toMatchObject({ status: "Failed", errorDetail: detail, finishedAt: execution.finishedAt })
  expect(mergeExecution(execution, { ...execution, errorDetail: { ...detail, occurredAt: "2026-10-31T12:00:00Z" } }).errorDetail).toEqual(detail)
  expect(mergeExecution({ ...execution, errorDetail: null }, execution).errorDetail).toEqual(detail)
})

it("enriches terminal child receipts with missing metadata without reopening or replacing the cause", () => {
  const receipt: AgentInvocation = { invocation_id: "child", parent_invocation_id: "root", agent_id: "investigator",
    run_id: "audit", status: "failed", started_at: "2026-10-30T11:00:00Z", finished_at: "2026-10-30T12:01:00Z",
    error: "failed", input_tokens: 8, output_tokens: 2 }
  const complete = { ...receipt, error_detail: detail }
  expect(mergeInvocations([receipt], [complete])[0]?.error_detail).toEqual(detail)
  expect(mergeInvocations([complete], [{ ...receipt, error_detail: null }])[0]?.error_detail).toEqual(detail)
  expect(mergeInvocations([complete], [{ ...complete, error_detail: { ...detail, message: "replacement" } }])[0]?.error_detail).toEqual(detail)
  expect(mergeInvocations([complete], [{ ...receipt, status: "running", finished_at: null }])[0]).toMatchObject({
    status: "failed", error_detail: detail, finished_at: receipt.finished_at,
  })
})
