import { agentTree, type AuditAgentNode, type AuditPipelineRun } from "../../shared/audit-monitor/auditStatus.ts"

/** Same parent links as the monitor, but preserve every invocation and order globally,
 * not depth-first: parallel branches must not move an earlier execution below a later one. */
export function chronologyExecutions(pipelines: AuditPipelineRun[]) {
  const rows: { agent: AuditAgentNode["agent"], pipelineId: string, depth: number, parent: AuditAgentNode["agent"] | null, path: AuditAgentNode["agent"][] }[] = []
  for (const pipeline of pipelines) {
    function visit(nodes: AuditAgentNode[], ancestors: AuditAgentNode["agent"][]) {
      for (const node of nodes) {
        const path = [...ancestors, node.agent]
        rows.push({ agent: node.agent, pipelineId: pipeline.id, depth: ancestors.length, parent: ancestors.at(-1) ?? null, path })
        visit(node.children, path)
      }
    }
    visit(agentTree(pipeline.agents), [])
  }
  const timestamp = (value: string | null) => {
    const parsed = Date.parse(value ?? "")
    return Number.isNaN(parsed) ? Infinity : parsed
  }
  return rows.sort((a, b) => {
    const first = timestamp(a.agent.startedAt)
    const second = timestamp(b.agent.startedAt)
    return first === second ? 0 : first - second
  })
}
