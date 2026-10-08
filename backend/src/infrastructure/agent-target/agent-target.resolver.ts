import { existsSync, readdirSync } from "node:fs"
import { join } from "node:path"
import type { PrismaClient } from "../../generated/prisma/client.js"
import { logger } from "../../config/logger.js"
import type { AgentInput } from "../agent-server-client/agent-server.client.js"

/** Builds the payload an agent is invoked with.
 *
 *  The backend owns this rather than the caller, so opening an execution is one
 *  call with no knowledge of what any particular agent expects. The shape is the
 *  analyzer's, which is the only agent registered today; a second agent with a
 *  different shape needs a branch here, not a change at the call site. */
export interface AgentTargetResolver {
  resolve(evaluationId: number): Promise<AgentInput>
}

export class WorkspaceMissingError extends Error {
  constructor(message: string) {
    super(message)
    this.name = "WorkspaceMissingError"
  }
}

export class EvaluationNotFoundError extends Error {
  constructor(id: number) {
    super(`Evaluation ${id} not found`)
    this.name = "EvaluationNotFoundError"
  }
}

export class AgentTargetResolverImpl implements AgentTargetResolver {
  private log = logger.withTag("agent-target")

  constructor(
    private db: PrismaClient,
    private workspaceDir: string,
  ) {}

  async resolve(evaluationId: number): Promise<AgentInput> {
    const evaluation = await this.db.evaluation.findUnique({
      where: { id: evaluationId },
      include: { projectVersion: { include: { project: true } } },
    })

    if (evaluation === null) {
      throw new EvaluationNotFoundError(evaluationId)
    }

    const project = evaluation.projectVersion.project
    const rootPath = this.workspaceOf(project.repositoryOwner, project.repositoryName, project.githubRepositoryId)

    this.log.info(`Evaluation ${evaluationId} resolves to ${rootPath}`)

    return { root_path: rootPath }
  }

  /** Same folder convention the project module clones into. */
  private workspaceOf(owner: string, name: string, githubRepositoryId: bigint): string {
    const folder = `${githubRepositoryId}-${owner}-${name}`
    const targetDir = join(this.workspaceDir, folder)

    if (existsSync(targetDir) === false || readdirSync(targetDir).length === 0) {
      throw new WorkspaceMissingError(`Project ${owner}/${name} has no local checkout`)
    }

    return targetDir
  }
}