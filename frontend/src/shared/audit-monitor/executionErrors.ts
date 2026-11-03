import type { AuditAgentNode, AuditPipelineRun, AuditStatusModel } from "./auditStatus.ts"
import type { ExecutionErrorDetail } from "../../infrastructure/http-client/httpClient.ts"

function ownError(run: { state: string, error?: string | null, errorDetail?: ExecutionErrorDetail | null }): boolean {
  return run.state === "failed" || Boolean(run.error?.trim()) || Boolean(run.errorDetail)
}

export function agentErrorIsInherited(node: AuditAgentNode): boolean {
  const source = node.agent.errorDetail
  return Boolean(source && (source.agentId && source.agentId !== node.agent.agentType
    || typeof node.agent.id === "string" && source.invocationId && source.invocationId !== node.agent.id))
    || !ownError(node.agent) && node.children.some(agentHasError)
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

export function auditErrorIsInherited(audit: AuditStatusModel): boolean {
  return !ownError(audit) && audit.pipelines.some(pipelineHasError)
    || Boolean(audit.errorDetail?.invocationId && audit.pipelines.some((pipeline) => pipeline.agents.some((agent) =>
      String(agent.id) === audit.errorDetail?.invocationId && agent.parentId != null)))
}
