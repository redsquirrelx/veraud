import { expect, it } from "vitest"
import type { AgentInvocation } from "../../infrastructure/http-client/httpClient.ts"
import { mergeInvocations } from "./mergeExecution.ts"

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
