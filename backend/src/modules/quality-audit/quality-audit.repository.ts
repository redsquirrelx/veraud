import type { PrismaClient } from "../../generated/prisma/client.js"

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
}
