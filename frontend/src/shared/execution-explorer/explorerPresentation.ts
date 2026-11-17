import type { TFunction, ParseKeys } from "i18next"
import { agentTree, pipelineLabelKey, type AuditAgentNode, type AuditAgentRun, type AuditStatusModel } from "../audit-monitor/auditStatus.ts"

/** "Maintainability + Security · #1231"; attributes keep backend order, joints join with " + ". */
export function auditExplorerTitle(audit: AuditStatusModel, tProjects: TFunction<"projects">): string {
  const labels = audit.pipelines.map((pipeline) => {
    const key = pipelineLabelKey(pipeline.id)
    return key === null ? pipeline.id : tProjects(key as ParseKeys<"projects">)
  })
  return labels.length === 0 ? `#${audit.id}` : `${labels.join(" + ")} · #${audit.id}`
}

/** Display name for an agent: catalog name when declared, localized fallback for
 *  undeclared internal agents, else the raw backend identifier. */
export function displayAgentName(agent: import("../audit-monitor/auditStatus.ts").AuditAgentRun, t: TFunction<"executionExplorer">): string {
  if (agent.name?.trim()) return agent.name
  switch (agent.agentType) {
    case "verification_suite": return t("agent.verificationSuite")
    case "finding_test_generation": return t("agent.findingTestGeneration")
    case "testability_probe": return t("agent.testabilityProbe")
    default: return agent.agentType
  }
}

/** One forest over every pipeline's agent tree, preserving pipeline order. */
export function agentForest(audit: AuditStatusModel): AuditAgentNode[] {
  return audit.pipelines.flatMap((pipeline) => agentTree(pipeline.agents))
}

export function countAgents(audit: AuditStatusModel): number {
  let count = 0
  const visit = (nodes: AuditAgentNode[]) => {
    for (const node of nodes) {
      count += 1
      visit(node.children)
    }
  }
  visit(agentForest(audit))
  return count
}

export function flattenAgents(audit: AuditStatusModel): AuditAgentRun[] {
  const flattened: AuditAgentRun[] = []
  const visit = (nodes: AuditAgentNode[]) => {
    for (const node of nodes) {
      flattened.push(node.agent)
      visit(node.children)
    }
  }
  visit(agentForest(audit))
  return flattened
}

export function findAgent(audit: AuditStatusModel, agentId: string | number): AuditAgentRun | null {
  return flattenAgents(audit).find((agent) => String(agent.id) === String(agentId)) ?? null
}
