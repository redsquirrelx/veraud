import type { AgentExecution, AgentSettings } from "../../infrastructure/http-client/httpClient.ts"

export const EXPLORER_CATALOG: AgentSettings[] = [
  { agentType: "maintainability_manager", name: "Maintainability manager", role: "manager", qualityAttributes: ["maintainability"], workflowIds: [], configured: true, configuration: null },
  { agentType: "maintainability_coordinator", name: "Maintainability coordinator", role: "coordinator", qualityAttributes: ["maintainability"], workflowIds: [], configured: true, configuration: null },
  { agentType: "modularity", name: "Modularity investigator", role: "investigator", qualityAttributes: ["maintainability"], workflowIds: [], configured: true, configuration: null },
  { agentType: "complexity", name: "Complexity investigator", role: "investigator", qualityAttributes: ["maintainability"], workflowIds: [], configured: true, configuration: null },
  { agentType: "security", name: "Security", role: "manager", qualityAttributes: ["security"], workflowIds: [], configured: true, configuration: null },
  { agentType: "security_sast", name: "SAST analysis", role: "investigator", qualityAttributes: ["security"], workflowIds: [], configured: true, configuration: null },
  { agentType: "orientation", name: "Orientation", role: "agent", qualityAttributes: [], workflowIds: [], configured: true, configuration: null },
  { agentType: "architecture", name: "Architecture analyzer", role: "agent", qualityAttributes: [], workflowIds: [], configured: true, configuration: null },
  { agentType: "semantic_validation", name: "Semantic validation", role: "agent", qualityAttributes: [], workflowIds: [], configured: true, configuration: null },
] as AgentSettings[]

function base(partial: Partial<AgentExecution> & Pick<AgentExecution, "id" | "evaluationId" | "agentType" | "status">): AgentExecution {
  return {
    errorDetail: null,
    cancellationRequestedAt: null,
    invocations: [],
    monitorContext: undefined,
    configuration: null,
    inputTokens: null,
    outputTokens: null,
    estimatedTokens: null,
    interruptionReason: null,
    result: null,
    error: null,
    createdAt: "2026-11-16T08:00:00Z",
    startedAt: null,
    finishedAt: null,
    ...partial,
  } as AgentExecution
}

const receipt = (partial?: Partial<NonNullable<AgentExecution["invocations"]>[number]> & Pick<NonNullable<AgentExecution["invocations"]>[number], "invocation_id" | "agent_id" | "status">): NonNullable<AgentExecution["invocations"]>[number] => ({
  invocation_id: "inv",
  parent_invocation_id: null,
  run_id: "run-x",
  phase: null,
  started_at: "2026-11-16T08:00:05Z",
  finished_at: "2026-11-16T08:05:00Z",
  input_tokens: null,
  output_tokens: null,
  unknown_usage_attempts: 0,
  error: null,
  ...partial,
} as NonNullable<AgentExecution["invocations"]>[number])

function monitor(evaluationType: string, qualityAttributes: string[]) {
  return {
    project: { id: 2, repositoryOwner: "acme", repositoryName: "Demo" },
    branch: "main",
    commitHash: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    evaluationType,
    qualityAttributes,
    workflowIds: [],
  }
}

/** Running maintainability audit: manager → coordinator → [modularity (done), complexity (running)]. */
export const maintainabilityRunning: AgentExecution = base({
  id: 101,
  evaluationId: 7,
  agentType: "maintainability_manager",
  status: "Running",
  result: JSON.stringify({ attributes: ["maintainability"] }),
  createdAt: "2026-11-16T08:00:00Z",
  startedAt: "2026-11-16T08:00:02Z",
  finishedAt: null,
  monitorContext: monitor("QualityAudit", ["maintainability"]),
  invocations: [
    receipt({ invocation_id: "inv-manager", agent_id: "maintainability_manager", status: "running", phase: "investigate", started_at: "2026-11-16T08:00:02Z", finished_at: null, input_tokens: 600, output_tokens: 80 }),
    receipt({ invocation_id: "inv-coordinator", agent_id: "maintainability_coordinator", parent_invocation_id: "inv-manager", status: "running", started_at: "2026-11-16T08:00:30Z", finished_at: null, input_tokens: 250, output_tokens: 30 }),
    receipt({ invocation_id: "inv-mod", agent_id: "modularity", parent_invocation_id: "inv-coordinator", status: "completed", started_at: "2026-11-16T08:00:35Z", finished_at: "2026-11-16T08:02:00Z", input_tokens: 120, output_tokens: 30 }),
    receipt({ invocation_id: "inv-cplx", agent_id: "complexity", parent_invocation_id: "inv-coordinator", status: "running", phase: "synthesize_findings", started_at: "2026-11-16T08:00:40Z", finished_at: null, input_tokens: 130, output_tokens: 40 }),
  ],
})

/** Completed joint audit (shared evaluation): one row per attribute root. */
export const jointCompletedMaintainability: AgentExecution = base({
  id: 102,
  evaluationId: 9,
  agentType: "maintainability_manager",
  status: "Completed",
  result: JSON.stringify({ attributes: ["maintainability", "security"], status: "completed" }),
  createdAt: "2026-11-15T10:00:00Z",
  startedAt: "2026-11-15T10:00:05Z",
  finishedAt: "2026-11-15T10:20:00Z",
  monitorContext: monitor("QualityAudit", ["maintainability", "security"]),
  invocations: [
    receipt({ invocation_id: "inv-j-m", agent_id: "maintainability_manager", status: "completed", started_at: "2026-11-15T10:00:05Z", finished_at: "2026-11-15T10:19:00Z", input_tokens: 2000, output_tokens: 400 }),
  ],
})

export const jointCompletedSecurity: AgentExecution = base({
  id: 103,
  evaluationId: 9,
  agentType: "security",
  status: "Completed",
  result: JSON.stringify({ attributes: ["maintainability", "security"], status: "completed" }),
  createdAt: "2026-11-15T10:00:00Z",
  startedAt: "2026-11-15T10:00:06Z",
  finishedAt: "2026-11-15T10:21:00Z",
  monitorContext: monitor("QualityAudit", ["maintainability", "security"]),
  invocations: [
    receipt({ invocation_id: "inv-j-s", agent_id: "security", status: "completed", started_at: "2026-11-15T10:00:06Z", finished_at: "2026-11-15T10:20:30Z", input_tokens: 1500, output_tokens: 300 }),
    receipt({ invocation_id: "inv-j-sast", agent_id: "security_sast", parent_invocation_id: "inv-j-s", status: "completed", started_at: "2026-11-15T10:00:10Z", finished_at: "2026-11-15T10:15:00Z", input_tokens: 900, output_tokens: 150 }),
  ],
})

/** Failed maintainability audit with a failing investigator branch. */
export const failedAudit: AgentExecution = base({
  id: 104,
  evaluationId: 10,
  agentType: "maintainability_manager",
  status: "Failed",
  result: JSON.stringify({ attributes: ["maintainability"], status: "failed" }),
  createdAt: "2026-11-14T09:00:00Z",
  startedAt: "2026-11-14T09:00:05Z",
  finishedAt: "2026-11-14T09:06:00Z",
  error: "Audit failed",
  monitorContext: monitor("QualityAudit", ["maintainability"]),
  invocations: [
    receipt({ invocation_id: "inv-f-m", agent_id: "maintainability_manager", status: "failed", started_at: "2026-11-14T09:00:05Z", finished_at: "2026-11-14T09:05:58Z", input_tokens: 700, output_tokens: 100, error: "execution_timeout" }),
    receipt({ invocation_id: "inv-f-cplx", agent_id: "complexity", parent_invocation_id: "inv-f-m", status: "failed", started_at: "2026-11-14T09:00:20Z", finished_at: "2026-11-14T09:05:00Z", input_tokens: 500, output_tokens: 60, error: "execution_timeout" }),
  ],
})

/** WS-only audit group: no monitorContext yet — included via the audit root agent type. */
export const webSocketOnlyAudit: AgentExecution = base({
  id: 105,
  evaluationId: 11,
  agentType: "maintainability_manager",
  status: "Running",
  result: JSON.stringify({ attributes: ["maintainability"] }),
  createdAt: "2026-11-16T09:00:00Z",
  startedAt: "2026-11-16T09:00:02Z",
  finishedAt: null,
  invocations: [
    receipt({ invocation_id: "inv-ws-m", agent_id: "maintainability_manager", status: "running", started_at: "2026-11-16T09:00:02Z", finished_at: null, input_tokens: 100, output_tokens: 10 }),
  ],
})

/** WS-only architecture context run: no monitorContext yet — included via the agent type. */
export const webSocketOnlyAgent: AgentExecution = base({
  id: 202,
  evaluationId: 24,
  agentType: "architecture_context",
  status: "Running",
  result: JSON.stringify({ status: "running" }),
  createdAt: "2026-11-16T09:30:00Z",
  startedAt: "2026-11-16T09:30:02Z",
  finishedAt: null,
  invocations: [
    receipt({ invocation_id: "inv-ws-ac", agent_id: "architecture_context", status: "running", started_at: "2026-11-16T09:30:02Z", finished_at: null, input_tokens: 80, output_tokens: 7 }),
  ],
})

/** Architecture context run (completed) — appears as a standalone agent. */
export const architectureContextRun: AgentExecution = base({
  id: 201,
  evaluationId: 21,
  agentType: "architecture_context",
  status: "Completed",
  result: JSON.stringify({ status: "complete", execution_status: "complete" }),
  createdAt: "2026-11-16T07:00:00Z",
  startedAt: "2026-11-16T07:00:02Z",
  finishedAt: "2026-11-16T07:04:00Z",
  monitorContext: monitor("ArchitectureContext", []),
  invocations: [
    receipt({ invocation_id: "inv-ac", agent_id: "architecture_context", status: "completed", started_at: "2026-11-16T07:00:02Z", finished_at: "2026-11-16T07:04:00Z", input_tokens: 50, output_tokens: 12 }),
  ],
})

export const analysisOrientation: AgentExecution = base({
  id: 301,
  evaluationId: 22,
  agentType: "orientation",
  status: "Completed",
  result: JSON.stringify({}),
  createdAt: "2026-11-16T06:00:00Z",
  startedAt: "2026-11-16T06:00:02Z",
  finishedAt: "2026-11-16T06:01:00Z",
  monitorContext: monitor("Analysis", []),
  invocations: [
    receipt({ invocation_id: "inv-an-o", agent_id: "orientation", status: "completed", started_at: "2026-11-16T06:00:02Z", finished_at: "2026-11-16T06:01:00Z", input_tokens: 20, output_tokens: 4 }),
  ],
})

export const analysisArchitect: AgentExecution = base({
  id: 302,
  evaluationId: 22,
  agentType: "architecture",
  status: "Completed",
  result: JSON.stringify({}),
  createdAt: "2026-11-16T06:00:01Z",
  startedAt: "2026-11-16T06:00:03Z",
  finishedAt: "2026-11-16T06:02:00Z",
  monitorContext: monitor("Analysis", []),
  invocations: [
    receipt({ invocation_id: "inv-an-a", agent_id: "architecture", status: "completed", started_at: "2026-11-16T06:00:03Z", finished_at: "2026-11-16T06:02:00Z", input_tokens: 80, output_tokens: 18 }),
  ],
})

/** Verification-suite generation — appears as a standalone agent with ftg/probe children. */
export const verificationSuiteRun: AgentExecution = base({
  id: 501,
  evaluationId: 31,
  agentType: "verification_suite",
  status: "Running",
  result: JSON.stringify({ run_id: "suite-run-1" }),
  createdAt: "2026-11-16T10:00:00Z",
  startedAt: "2026-11-16T10:00:02Z",
  finishedAt: null,
  monitorContext: monitor("VerificationSuite", []),
  invocations: [
    receipt({ invocation_id: "inv-suite-root", agent_id: "verification_suite", parent_invocation_id: null, run_id: "suite-run-1", status: "running", phase: "generation", started_at: "2026-11-16T10:00:02Z", finished_at: null, input_tokens: null, output_tokens: null }),
    receipt({ invocation_id: "inv-suite-ftg", agent_id: "finding_test_generation", parent_invocation_id: "inv-suite-root", run_id: "suite-run-1", status: "completed", started_at: "2026-11-16T10:00:05Z", finished_at: "2026-11-16T10:04:00Z", input_tokens: 9000, output_tokens: 510, phase: "generation" }),
    receipt({ invocation_id: "inv-suite-probe", agent_id: "testability_probe", parent_invocation_id: "inv-suite-root", run_id: "suite-run-1", status: "running", phase: "generation", started_at: "2026-11-16T10:00:06Z", finished_at: null, input_tokens: 7000, output_tokens: 430, phase_sequence: 1 }),
  ],
})

export const findingResolutionRun: AgentExecution = base({
  id: 401,
  evaluationId: 23,
  agentType: "finding_resolution",
  status: "Running",
  result: JSON.stringify({}),
  createdAt: "2026-11-16T05:00:00Z",
  startedAt: "2026-11-16T05:00:02Z",
  finishedAt: null,
  monitorContext: monitor("FindingResolution", []),
  invocations: [
    receipt({ invocation_id: "inv-fr", agent_id: "finding_resolution", status: "running", started_at: "2026-11-16T05:00:02Z", finished_at: null, input_tokens: 60, output_tokens: 8 }),
  ],
})

export const allExecutions = [
  maintainabilityRunning,
  jointCompletedMaintainability,
  jointCompletedSecurity,
  failedAudit,
  webSocketOnlyAudit,
  architectureContextRun,
  analysisOrientation,
  analysisArchitect,
  findingResolutionRun,
  webSocketOnlyAgent,
  verificationSuiteRun,
]
