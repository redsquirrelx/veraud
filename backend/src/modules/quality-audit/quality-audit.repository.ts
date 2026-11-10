import type { PrismaClient } from "../../generated/prisma/client.js"
import type { AuditReportSection } from "./audit-report-sections.js"
import { UnknownExecutionTargetError } from "../agent-execution/agent-execution.repository.js"
import { AgentConfigurationError } from "../agent-settings/agent-configuration.js"
import { architectureContextResult } from "../agent-execution/architecture-context.js"

/** Audit artifacts live in the existing version/evaluation/execution storage. */
export class QualityAuditRepository {
  constructor(private db: PrismaClient) {}

  /** Most recent usable immutable artifact for exactly this project revision.
   * A failed regeneration does not invalidate an earlier valid context. */
  async architectureContext(projectId: number, commitHash: string) {
    let cursor: number | undefined
    while (true) {
      const artifacts = await this.db.architectureContextArtifact.findMany({
        where: { projectVersion: { projectId, commitHash }, executionStatus: { in: ["complete", "partial"] },
          execution: { agentType: "architecture_context", status: "Completed",
            evaluation: { projectVersion: { projectId, commitHash } } },
          ...(cursor === undefined ? {} : { executionId: { lt: cursor } }),
        }, orderBy: { executionId: "desc" }, take: 20,
      })
      for (const artifact of artifacts) {
        try {
          const parsed = architectureContextResult(artifact.result, commitHash)
          if (parsed.schemaVersion === artifact.schemaVersion && parsed.executionStatus === artifact.executionStatus) return artifact
        } catch { /* Corrupted/legacy artifacts are not a prerequisite. */ }
      }
      if (artifacts.length < 20) return null
      cursor = artifacts.at(-1)!.executionId
    }
  }

  /** The deterministic functional adapter has no model snapshot to prepare.
   *  It uses the same QualityAudit rows and dispatch/cancellation lifecycle. */
  async createExploratoryFunctionalAudit(projectId: number, branch: string, commitHash: string) {
    return this.db.$transaction(async (tx) => {
      const agent = await tx.agentSettings.findUnique({ where: { agentType: "functional_adequacy" },
        select: { catalogDeclared: true, availability: true } })
      if (!agent?.catalogDeclared || agent.availability !== "available") {
        throw new AgentConfigurationError([{ agentType: "functional_adequacy", reason: "Agent is not available in the agent-server catalog" }])
      }
      const running = await tx.agentExecution.findFirst({ where: {
        status: { in: ["Waiting", "Running"] }, evaluation: { projectVersion: { projectId, commitHash } },
      } })
      if (running) throw new UnknownExecutionTargetError(`Version ${commitHash.slice(0, 7)} is already being analyzed (execution ${running.id})`)
      const version = await tx.projectVersion.upsert({
        where: { projectId_commitHash: { projectId, commitHash } },
        create: { projectId, branch, commitHash, analysisStatus: "Pending" }, update: { branch },
      })
      await tx.project.update({ where: { id: projectId }, data: { selectedVersionId: version.id } })
      const evaluation = await tx.evaluation.create({ data: { projectVersionId: version.id, type: "QualityAudit" } })
      const execution = await tx.agentExecution.create({ data: {
        evaluationId: evaluation.id, agentType: "functional_adequacy", status: "Waiting",
        result: JSON.stringify({ attributes: ["functional_adequacy"] }),
      } })
      return { versionId: version.id, evaluationId: evaluation.id, executionId: execution.id }
    })
  }

  async projectExists(projectId: number) {
    return await this.db.project.findUnique({ where: { id: projectId }, select: { id: true } }) !== null
  }

  async list(projectId: number, limit = 2147483647, offset = 0) {
    const where = { evaluation: { type: "QualityAudit", projectVersion: { projectId } } }
    return this.db.$transaction(async (tx) => {
      const total = await tx.agentExecution.count({ where })
      const hasRunning = await tx.agentExecution.count({ where: { ...where, status: { in: ["Waiting", "Running"] } } }) > 0
      const actualOffset = total === 0 ? 0 : offset >= total ? Math.floor((total - 1) / limit) * limit : offset
      const rows = await tx.agentExecution.findMany({
        where, take: limit, skip: actualOffset, orderBy: [{ createdAt: "desc" }, { id: "desc" }],
        select: { id: true, agentType: true, evaluationId: true, status: true, error: true, createdAt: true,
          startedAt: true, finishedAt: true, cancellationRequestedAt: true,
          evaluation: { select: { projectVersion: { select: { branch: true, commitHash: true } } } } },
      })
      // SQLite projects only summary metadata; result contains Blackboard and base64 DOCX.
      const projections = await tx.$queryRaw<Array<{ id: number, runId: string | null, attributes: string | null,
        auditStatus: string | null, reportType: string | null, configurationSnapshot: string | null }>>`
        WITH page AS (
          SELECT a.id FROM agent_execution a JOIN evaluation e ON e.id = a.evaluation_id
            JOIN project_version v ON v.id = e.project_version_id
          WHERE v.project_id = ${projectId} AND e.type = 'QualityAudit'
          ORDER BY a.created_at DESC, a.id DESC LIMIT ${limit} OFFSET ${actualOffset}
        )
        SELECT a.id,
          CASE WHEN json_valid(a.result) THEN COALESCE(json_extract(a.result, '$.run_id'), json_extract(a.result, '$.report.identification.audit_id')) END AS runId,
          CASE WHEN json_valid(a.result) THEN json_extract(a.result, '$.attributes') END AS attributes,
          CASE WHEN json_valid(a.result) THEN json_extract(a.result, '$.status') END AS auditStatus,
          CASE WHEN json_valid(a.result) THEN json_type(a.result, '$.report') END AS reportType,
          CASE WHEN json_valid(a.configuration_snapshot) THEN json_object('auditConfiguration', json_object(
            'version', json_extract(a.configuration_snapshot, '$.auditConfiguration.version'),
            'branch', json_extract(a.configuration_snapshot, '$.auditConfiguration.branch'),
            'commitHash', json_extract(a.configuration_snapshot, '$.auditConfiguration.commitHash'),
            'attributes', json_extract(a.configuration_snapshot, '$.auditConfiguration.attributes')
          )) END AS configurationSnapshot
        FROM page JOIN agent_execution a ON a.id = page.id
      `
      const byId = new Map(projections.map((projection) => [projection.id, projection]))
      return { total, hasRunning, offset: actualOffset, limit, items: rows.map((row) => {
        const projection = byId.get(row.id)!
        return { row: { ...row, configurationSnapshot: projection.configurationSnapshot }, projection }
      }) }
    })
  }

  async find(projectId: number, executionId: number) {
    return this.db.agentExecution.findFirst({
      where: { id: executionId, evaluation: { type: "QualityAudit", projectVersion: { projectId } } },
      include: { evaluation: { include: { projectVersion: true } } },
    })
  }

  async findSummary(projectId: number, executionId: number) {
    // Do not materialize result: it also contains Blackboard data and base64 DOCX.
    const [row, projected] = await this.db.$transaction([
      this.db.agentExecution.findFirst({
        where: { id: executionId, evaluation: { type: "QualityAudit", projectVersion: { projectId } } },
        select: { id: true, agentType: true, evaluationId: true, status: true, error: true, createdAt: true, startedAt: true, finishedAt: true,
          cancellationRequestedAt: true, errorDetail: true,
          configurationSnapshot: true, evaluation: { select: { projectVersion: { select: { branch: true, commitHash: true } } } } },
      }),
      this.db.$queryRaw<Array<{ runId: string | null, attributes: string | null, auditStatus: string | null, reportType: string | null }>>`
        SELECT CASE WHEN json_valid(a.result) THEN COALESCE(json_extract(a.result, '$.run_id'), json_extract(a.result, '$.report.identification.audit_id')) END AS runId,
          CASE WHEN json_valid(a.result) THEN json_extract(a.result, '$.attributes') END AS attributes,
          CASE WHEN json_valid(a.result) THEN json_extract(a.result, '$.status') END AS auditStatus,
          CASE WHEN json_valid(a.result) THEN json_type(a.result, '$.report') END AS reportType
        FROM agent_execution a JOIN evaluation e ON e.id = a.evaluation_id
          JOIN project_version v ON v.id = e.project_version_id
        WHERE a.id = ${executionId} AND v.project_id = ${projectId} AND e.type = 'QualityAudit'
      `,
    ])
    return row && projected[0] ? { row, projection: projected[0] } : null
  }

  async findReportSection(projectId: number, executionId: number, section: AuditReportSection) {
    const path = `$.report.${section}`
    const rows = await this.db.$queryRaw<Array<{ reportType: string | null, data: string | null }>>`
      SELECT CASE WHEN json_valid(a.result) THEN json_type(a.result, '$.report') END AS reportType,
        CASE WHEN json_valid(a.result) THEN json_quote(json_extract(a.result, ${path})) END AS data
      FROM agent_execution a JOIN evaluation e ON e.id = a.evaluation_id
        JOIN project_version v ON v.id = e.project_version_id
      WHERE a.id = ${executionId} AND v.project_id = ${projectId} AND e.type = 'QualityAudit'
    `
    return rows[0] ?? null
  }

  async findConfiguration(projectId: number, executionId: number) {
    return this.db.agentExecution.findFirst({
      where: { id: executionId, evaluation: { type: "QualityAudit", projectVersion: { projectId } } },
      select: { configurationSnapshot: true, invocationReceipts: true },
    })
  }
}
