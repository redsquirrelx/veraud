import type { PrismaClient } from "../../generated/prisma/client.js"
import type { AuditReportSection } from "./audit-report-sections.js"

/** Audit artifacts live in the existing version/evaluation/execution storage. */
export class QualityAuditRepository {
  constructor(private db: PrismaClient) {}

  async projectExists(projectId: number) {
    return await this.db.project.findUnique({ where: { id: projectId }, select: { id: true } }) !== null
  }

  async list(projectId: number) {
    return this.db.agentExecution.findMany({
      where: { evaluation: { type: "QualityAudit", projectVersion: { projectId } } },
      include: { evaluation: { include: { projectVersion: true } } },
      orderBy: { id: "desc" },
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
          cancellationRequestedAt: true,
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
