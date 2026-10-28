import type { AgentExecutionService } from "../agent-execution/agent-execution.service.js"
import type { AuditSettingsService } from "./audit-settings.service.js"
import type { AuditOperatingOptions } from "../../infrastructure/agent-server-client/agent-server.client.js"
import { InvalidGitRequestError, ProjectNotFoundError, type ProjectService } from "../project/project.service.js"
import type { QualityAuditRepository } from "./quality-audit.repository.js"
import type { AuditRunConfiguration } from "./audit-run-configuration.js"
import type { InvocationReceipt } from "../agent-execution/invocationReceipt.js"

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
  const configuration = savedConfiguration(row)
  return {
    id: row.id,
    runId: result?.run_id ?? null,
    evaluationId: row.evaluationId,
    branch: configuration?.branch ?? row.evaluation!.projectVersion.branch,
    commitHash: configuration?.commitHash ?? row.evaluation!.projectVersion.commitHash,
    attributes: configuration?.attributes ?? result?.attributes ?? [row.agentType === "maintainability_manager" ? "maintainability" : row.agentType],
    configurationAvailable: configuration !== null,
    executionStatus: row.status,
    auditStatus: result?.status ?? null,
    error: row.error,
    createdAt: row.createdAt,
    finishedAt: row.finishedAt,
    reportAvailable: result?.report != null,
  }
}

function savedConfiguration(row: AuditRow): AuditRunConfiguration | null {
  try {
    const snapshot = JSON.parse(row.configurationSnapshot ?? "null") as { auditConfiguration?: AuditRunConfiguration } | null
    return snapshot?.auditConfiguration?.version === 1 ? snapshot.auditConfiguration : null
  } catch { return null }
}

export class QualityAuditService {
  constructor(private repository: QualityAuditRepository, private projects: ProjectService, private executions: AgentExecutionService,
    private settings?: AuditSettingsService) {}

  async start(projectId: number, branch: string, commitHash: string, attributes: string[], options: AuditOperatingOptions = {}) {
    if (!attributes.length || new Set(attributes).size !== attributes.length
      || attributes.some((attribute) => !["maintainability", "security", "functional_adequacy"].includes(attribute))) {
      throw new InvalidGitRequestError("Select distinct supported quality attributes: maintainability, security, functional_adequacy")
    }
    const requirements = options.functional_requirements
    if (options.maintainability_selection !== undefined && !attributes.includes("maintainability")) {
      throw new InvalidGitRequestError("maintainability_selection requires maintainability in attributes")
    }
    if (attributes.includes("functional_adequacy")) {
      if (!requirements?.length || requirements.length > 100
        || requirements.some((item) => !item.requirement_id?.trim() || !item.description?.trim())
        || new Set(requirements.map((item) => item.requirement_id.trim())).size !== requirements.length) {
        throw new InvalidGitRequestError("Functional adequacy requires 1–100 functional requirements with distinct IDs and nonempty descriptions")
      }
    } else if (requirements !== undefined) {
      throw new InvalidGitRequestError("functional_requirements requires functional_adequacy in attributes")
    }
    if (options.security_config && !attributes.includes("security")) {
      throw new InvalidGitRequestError("security_config requires security in attributes")
    }
    if (options.call_limits && !attributes.includes("maintainability")) {
      throw new InvalidGitRequestError("call_limits requires maintainability; use security_config for security")
    }
    if (options.functional_config && !attributes.includes("functional_adequacy")) {
      throw new InvalidGitRequestError("functional_config requires functional_adequacy in attributes")
    }
    if (options.attribute_options && Object.keys(options.attribute_options).some((attribute) => !attributes.includes(attribute))) {
      throw new InvalidGitRequestError("attribute_options must belong to selected attributes")
    }
    if (!/^[a-fA-F0-9]{40}$/.test(commitHash)) throw new InvalidGitRequestError("Select a full commit hash")
    const { project, cleanBranch, cleanHash } = await this.projects.validateAnalysisTarget(projectId, branch, commitHash)
    const effective = this.settings ? await this.settings.executionOptions(attributes, options) : options
    return this.executions.openQualityAudit(project.id, cleanBranch, cleanHash, attributes, effective)
  }

  async list(projectId: number) {
    if (!await this.repository.projectExists(projectId)) throw new ProjectNotFoundError("Project not found")
    return (await this.repository.list(projectId)).map(summary)
  }

  async report(projectId: number, id: number) {
    return (await this.requireArtifacts(projectId, id)).report
  }

  async configuration(projectId: number, id: number) {
    const row = await this.repository.find(projectId, id)
    if (!row) throw new AuditNotFoundError("Audit not found for this project")
    const receipts = JSON.parse(row.invocationReceipts) as InvocationReceipt[]
    return { configuration: savedConfiguration(row), invocations: receipts.map((receipt) => ({
      id: receipt.invocation_id, agentId: receipt.agent_id, status: receipt.status,
    })) }
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
