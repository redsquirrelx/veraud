import type { AuditAgentNode, AuditPipelineRun, AuditStatusModel } from "./auditStatus.ts"

function ownError(run: { state: string, error?: string | null }): boolean {
  return run.state === "failed" || Boolean(run.error?.trim())
}

export function agentHasError(node: AuditAgentNode): boolean {
  return ownError(node.agent) || node.children.some(agentHasError)
}

export function pipelineHasError(pipeline: AuditPipelineRun): boolean {
  return ownError(pipeline) || pipeline.agents.some(ownError)
}

export function auditHasError(audit: AuditStatusModel): boolean {
  return ownError(audit) || audit.pipelines.some(pipelineHasError)
}
