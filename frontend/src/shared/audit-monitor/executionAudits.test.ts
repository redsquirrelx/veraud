import { describe, expect, it } from "vitest"
import type { AgentExecution, AgentSettings } from "../../infrastructure/http-client/httpClient.ts"
import { auditProgress, auditStateFrom } from "./auditStatus.ts"
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
  it("keeps a joint orchestrator once and leaves unreported attribute progress unknown", () => {
    const [audit] = executionAudits([{ ...execution, result: JSON.stringify({ attributes: ["maintainability", "security"] }) }], [
      agent("maintainability_manager", ["maintainability"]), agent("never_started", ["security"]),
    ])
    expect(audit!.project?.id).toBe(5)
    expect(audit!.pipelines.find((pipeline) => pipeline.id === "security")).toMatchObject({ state: "unknown", agents: [] })
    expect(audit!.pipelines.find((pipeline) => pipeline.id === "maintainability")).toMatchObject({ state: "unknown", agents: [] })
    expect(audit!.pipelines.find((pipeline) => pipeline.id === "quality-audit")!.agents).toHaveLength(1)
    expect(auditProgress(audit!)).toEqual({ total: 1, finished: 0 })
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
