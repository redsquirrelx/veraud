import type { AgentExecutionService } from "../agent-execution/agent-execution.service.js"
import { InvalidGitRequestError, ProjectNotFoundError, type ProjectService } from "../project/project.service.js"
import type { QualityAuditRepository } from "./quality-audit.repository.js"

export class AuditNotFoundError extends Error {}
export class AuditReportUnavailableError extends Error {}

type AuditRow = NonNullable<Awaited<ReturnType<QualityAuditRepository["find"]>>>
interface AuditArtifacts {
  run_id?: string
  attributes: string[]
  status: string
  report: Record<string, unknown>
  docx_base64: string
}

function artifacts(row: AuditRow): AuditArtifacts | null {
  return row.result === null ? null : JSON.parse(row.result) as AuditArtifacts
}

function summary(row: AuditRow) {
  const result = artifacts(row)
  return {
    id: row.id,
    runId: result?.run_id ?? null,
    evaluationId: row.evaluationId,
    branch: row.evaluation!.projectVersion.branch,
    commitHash: row.evaluation!.projectVersion.commitHash,
    attributes: result?.attributes ?? ["maintainability"],
    executionStatus: row.status,
    auditStatus: result?.status ?? null,
    error: row.error,
    createdAt: row.createdAt,
    finishedAt: row.finishedAt,
    reportAvailable: result?.report != null,
  }
}

export class QualityAuditService {
  constructor(private repository: QualityAuditRepository, private projects: ProjectService, private executions: AgentExecutionService) {}

  async start(projectId: number, branch: string, commitHash: string, attributes: string[]) {
    if (attributes.length !== 1 || attributes[0] !== "maintainability") {
      throw new InvalidGitRequestError("Select supported quality attributes: maintainability")
    }
    if (!/^[a-fA-F0-9]{40}$/.test(commitHash)) throw new InvalidGitRequestError("Select a full commit hash")
    const { project, cleanBranch, cleanHash } = await this.projects.validateAnalysisTarget(projectId, branch, commitHash)
    return this.executions.openQualityAudit(project.id, cleanBranch, cleanHash, attributes)
  }

  async list(projectId: number) {
    if (!await this.repository.projectExists(projectId)) throw new ProjectNotFoundError("Project not found")
    return (await this.repository.list(projectId)).map(summary)
  }

  async report(projectId: number, id: number) {
    return (await this.requireArtifacts(projectId, id)).report
  }

  async document(projectId: number, id: number) {
    return Buffer.from((await this.requireArtifacts(projectId, id)).docx_base64, "base64")
  }

  private async requireArtifacts(projectId: number, id: number) {
    const row = await this.repository.find(projectId, id)
    if (!row) throw new AuditNotFoundError("Audit not found for this project")
    const result = artifacts(row)
    if (!result?.report || !result.docx_base64) throw new AuditReportUnavailableError("The audit report is not available yet")
    return result
  }
}
