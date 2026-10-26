// @vitest-environment node
import { describe, expect, it } from "vitest"
import type { AgentExecution, AgentSettings } from "../../infrastructure/http-client/httpClient.ts"
import { agentTree, auditProgress, auditStateFrom } from "./auditStatus.ts"
import { executionAudits } from "./executionAudits.ts"

const execution: AgentExecution = {
  id: 7, evaluationId: 9, agentType: "maintainability_manager", status: "Running", result: null,
  error: null, inputTokens: 100, outputTokens: null, createdAt: "2026-10-18T10:00:00Z", startedAt: null, finishedAt: null,
  monitorContext: { project: { id: 5, repositoryOwner: "acme", repositoryName: "shop" }, branch: "main", commitHash: "a".repeat(40),
    evaluationType: "QualityAudit", qualityAttributes: ["maintainability"], workflowIds: ["quality-audit"] },
}
function agent(agentType: string, qualityAttributes: string[], workflowIds = ["quality-audit"]): AgentSettings {
  return { agentType, qualityAttributes, workflowIds, configured: false, configuration: null }
}

describe("executionAudits", () => {
  it("renders live invocations before a report and reconciles final receipts by invocation id", () => {
    const invocations: NonNullable<AgentExecution["invocations"]> = [
      { invocation_id: "manager", parent_invocation_id: null, agent_id: "maintainability_manager", run_id: "audit",
        status: "running", started_at: "2026-10-20T10:00:00Z", finished_at: null, input_tokens: 10, output_tokens: null, error: null },
      { invocation_id: "mod", parent_invocation_id: "manager", agent_id: "modularity", run_id: "audit",
        status: "running", phase: "investigate", phase_sequence: 2,
        started_at: "2026-10-20T10:00:01Z", finished_at: null, input_tokens: 5, output_tokens: 2, error: null },
    ]
    const live = { ...execution, invocations, configuration: {
      model: { id: 1, name: "test", providerId: 1, providerName: "test" },
      credential: { id: 1, name: "test", providerId: 1, providerName: "test" },
      temperature: null, maxTokens: null, tokenBudget: 100000, absoluteTokenLimit: 120000,
    } }
    const [audit] = executionAudits([live], [])
    const tree = agentTree(audit!.pipelines[0]!.agents)
    expect(tree).toHaveLength(1)
    expect(tree[0]!.agent.configuration).toMatchObject({ tokenBudget: 100000, absoluteTokenLimit: 120000 })
    expect(tree[0]!.children[0]!.agent.configuration).toBeNull()
    expect(tree[0]!.children[0]!.agent).toMatchObject({ id: "mod", state: "running", phase: "investigate", inputTokens: 5, startedAt: invocations[1]!.started_at })
    const [finished] = executionAudits([{ ...live, status: "Completed", result: JSON.stringify({
      attributes: ["maintainability"], report: { annexes_and_traceability: { executions: [
        { invocation_id: "mod", agent_id: "modularity", status: "completed", consumption: { input_tokens: 8 } },
      ] } },
    }) }], [])
    expect(finished!.pipelines[0]!.agents).toHaveLength(2)
    expect(agentTree(finished!.pipelines[0]!.agents)[0]!.children[0]!.agent).toMatchObject({ id: "mod", state: "completed", phase: null, inputTokens: 8, outputTokens: 2 })
  })
  it("reuses one row per agent for repeated coordinator and investigator invocations", () => {
    const traces = [
      { agent_id: "maintainability_manager", invocation_id: "manager" },
      { agent_id: "modularity", invocation_id: "mod-1", parent_invocation_id: "manager" },
      { agent_id: "architect_boundary", invocation_id: "boundary-1", parent_invocation_id: "mod-1" },
      { agent_id: "modularity", invocation_id: "mod-2", parent_invocation_id: "manager" },
      { agent_id: "architect_boundary", invocation_id: "boundary-2", parent_invocation_id: "mod-2" },
      { agent_id: "reusability", invocation_id: "reuse", parent_invocation_id: "manager" },
    ].map((trace) => ({ ...trace, status: "completed" }))
    const [audit] = executionAudits([{ ...execution, status: "Completed", result: JSON.stringify({
      attributes: ["maintainability"], report: { annexes_and_traceability: { executions: traces } },
    }) }], [agent("maintainability_manager", ["maintainability"])])
    expect(audit!.pipelines).toHaveLength(1)
    const tree = agentTree(audit!.pipelines[0]!.agents)
    expect(tree).toHaveLength(1)
    expect(tree[0]!.children.map((node) => node.agent.id)).toEqual(["mod-2", "reuse"])
    expect(tree[0]!.children[0]!.children[0]!.agent.id).toBe("boundary-2")
    expect(auditProgress(audit!)).toEqual({ total: 4, finished: 4 })
    const agents = audit!.pipelines[0]!.agents
    expect(agentTree([{ ...agents[0]!, parentId: "missing" }])).toHaveLength(1)
    expect(agentTree([{ ...agents[0]!, parentId: "mod-2" }, agents[1]!])).toHaveLength(2)
  })
  it("uses start time rather than callback order and reconnects retained children to the current coordinator", () => {
    const receipt = (invocation_id: string, agent_id: string, parent_invocation_id: string | null, started_at: string,
      status: "running" | "failed" = "running"): NonNullable<AgentExecution["invocations"]>[number] => ({
      invocation_id, agent_id, parent_invocation_id, started_at, status, run_id: "audit",
      finished_at: status === "failed" ? "2026-10-20T10:01:00Z" : null,
      error: status === "failed" ? "Old failure" : null, input_tokens: status === "failed" ? 100 : 2, output_tokens: null,
    })
    const current = receipt("mod-2", "modularity", "manager", "2026-10-20T10:02:00Z")
    const invocations = [
      receipt("manager", "maintainability_manager", null, "2026-10-20T10:00:00Z"), current,
      receipt("mod-1", "modularity", "manager", "2026-10-20T10:00:01Z", "failed"),
      receipt("boundary", "architecture_boundary", "mod-1", "2026-10-20T10:00:02Z"),
    ]
    const [audit] = executionAudits([{ ...execution, invocations }], [])
    const tree = agentTree(audit!.pipelines[0]!.agents)
    expect(tree[0]!.children).toHaveLength(1)
    expect(tree[0]!.children[0]!.agent).toMatchObject({ id: "mod-2", state: "running", runId: "audit",
      inputTokens: 2, error: null, finishedAt: null })
    expect(tree[0]!.children[0]!.children[0]!.agent).toMatchObject({ id: "boundary", parentId: "mod-2" })
    expect(auditProgress(audit!)).toEqual({ total: 3, finished: 0 })
  })
  it.each([false, true])("places a joint audit manager in maintainability before the report (catalog loaded: %s)", (loaded) => {
    const [audit] = executionAudits([{ ...execution, result: JSON.stringify({ attributes: ["maintainability", "security"] }) }], [
      ...(loaded ? [agent("maintainability_manager", ["maintainability", "security"]), agent("never_started", ["security"])] : []),
    ])
    expect(audit!.project?.id).toBe(5)
    expect(audit!.pipelines.find((pipeline) => pipeline.id === "security")).toMatchObject({ state: "unknown", agents: [] })
    expect(audit!.pipelines.find((pipeline) => pipeline.id === "maintainability")).toMatchObject({ state: "running", agents: [{ id: 7 }] })
    expect(audit!.pipelines.some((pipeline) => pipeline.id === "quality-audit")).toBe(false)
    expect(auditProgress(audit!)).toEqual({ total: 1, finished: 0 })
  })

  it.each([false, true])("keeps joint audit roots and descendants in their own attributes after completion (catalog loaded: %s)", (loaded) => {
    const traces = [
      { agent_id: "maintainability_manager", invocation_id: "manager" },
      { agent_id: "modularity", invocation_id: "mod", parent_invocation_id: "manager" },
      { agent_id: "architect_boundary", invocation_id: "boundary", parent_invocation_id: "mod" },
      { agent_id: "reusability", invocation_id: "reuse", parent_invocation_id: "manager" },
      { agent_id: "security", invocation_id: "security" },
      { agent_id: "security_child", invocation_id: "scanner", parent_invocation_id: "security" },
    ].map((trace) => ({ ...trace, status: "completed" }))
    const [audit] = executionAudits([{ ...execution, status: "Completed", result: JSON.stringify({
      attributes: ["maintainability", "security"], status: "completed",
      report: { annexes_and_traceability: { executions: traces } },
    }) }], loaded ? [agent("maintainability_manager", ["maintainability", "security"]),
      agent("security", ["maintainability", "security"])] : [])
    expect(audit!.pipelines.map((pipeline) => pipeline.id)).toEqual(["maintainability", "security"])
    expect(audit!.pipelines.map((pipeline) => pipeline.agents.map((run) => run.id)))
      .toEqual([["manager", "mod", "boundary", "reuse"], ["security", "scanner"]])
    expect(agentTree(audit!.pipelines[0]!.agents)[0]!.children.map((node) => node.agent.id)).toEqual(["mod", "reuse"])
    expect(auditProgress(audit!)).toEqual({ total: 6, finished: 6 })
  })

  it("shows real report invocations with their own outcomes, not duplicate backend totals", () => {
    const result = { attributes: ["maintainability", "security"], status: "partial", report: {
      quality_results: { attributes: [{ id: "maintainability", status: "completed" }, { id: "security", status: "partial" }] },
      annexes_and_traceability: { executions: [
        { invocation_id: "manager-invocation", agent_id: "maintainability_manager", status: "completed", consumption: { input_tokens: 80 } },
        { invocation_id: "security-invocation", agent_id: "security", status: "partial", consumption: {} },
      ] },
    } }
    const [audit] = executionAudits([{ ...execution, status: "Completed", result: JSON.stringify(result) }], [
      agent("maintainability_manager", ["maintainability"]), agent("security", ["security"]),
    ])
    expect(audit).toMatchObject({ state: "partial", reportAvailable: true })
    expect(audit!.pipelines.map((pipeline) => [pipeline.id, pipeline.state])).toEqual([["maintainability", "completed"], ["security", "partial"]])
    const runs = audit!.pipelines.flatMap((pipeline) => pipeline.agents)
    expect(runs.map((run) => run.id)).toEqual(["manager-invocation", "security-invocation"])
    expect(runs[0]!.inputTokens).toBe(80)
    expect(runs[1]!.inputTokens).toBeNull()
  })

  it("groups project stages by evaluation without merging different evaluations or direct runs", () => {
    const model = executionAudits([
      { ...execution, agentType: "orientation", monitorContext: { ...execution.monitorContext!, evaluationType: "Analysis", qualityAttributes: [], workflowIds: ["project-architecture"] } },
      { ...execution, id: 8, agentType: "architecture" },
      { ...execution, id: 10, evaluationId: 10 },
      { ...execution, id: 11, evaluationId: null, monitorContext: { ...execution.monitorContext!, project: null, branch: null, commitHash: null } },
    ], [agent("orientation", [], ["project-architecture"]), agent("architecture", [], ["project-architecture"])])
    expect(model).toHaveLength(3)
    expect(model.find((audit) => audit.id === 7)!.pipelines[0]!.agents).toHaveLength(2)
    expect(model.find((audit) => audit.id === 11)!.project).toBeNull()
  })

  it("keeps malformed output visible as a run and does not turn failed evaluation into success", () => {
    expect(executionAudits([{ ...execution, result: "invalid JSON", status: "Failed", error: "Dispatch unavailable" }], [])[0])
      .toMatchObject({ state: "failed", error: "Dispatch unavailable", reportAvailable: false })
    expect(auditStateFrom("Completed", "failed")).toBe("failed")
    expect(auditStateFrom("", null)).toBe("unknown")
  })
})
