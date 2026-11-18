import { rm, stat } from "node:fs/promises"
import { join, resolve, sep } from "node:path"
import type { Prisma, PrismaClient } from "../../generated/prisma/client.js"
import { projectWorkspaceFolder } from "./project-workspace.js"
import type { AgentExecutionService } from "../agent-execution/agent-execution.service.js"

export class ProjectDeletionNotFoundError extends Error {
  constructor(message: string) {
    super(message)
    this.name = "ProjectDeletionNotFoundError"
  }
}

/** Git/clone tasks for the project are still queued or running; git operations
 *  cannot be cancelled through the task runner, so deletion is refused instead
 *  of deleting a checkout out from under a live process. */
export class ProjectDeletionBusyError extends Error {
  constructor(message: string) {
    super(message)
    this.name = "ProjectDeletionBusyError"
  }
}

export interface ProjectDeletionCounts {
  versions: number
  evaluations: number
  executions: number
  events: number
  architectureArtifacts: number
  tasks: number
  graphExtractions: number
}

export interface ProjectDeletionDisk {
  artifactsRemoved: string[]
  /** Artifact directories were found but rejected as unsafe to remove; no name is echoed. */
  artifactsSkipped: number
  artifactFailures: string[]
  cloneRemoved: boolean
  cloneFailure: string | null
}

export type ProjectDeletionOutcome =
  | { status: "deleted"; counts: ProjectDeletionCounts; disk: ProjectDeletionDisk }
  | { status: "cancelling"; pendingExecutionIds: number[] }

interface ProjectDeletionOptions {
  /** Wall-clock budget for in-flight audit executions to reach a terminal
   *  state after cancellation is requested. */
  timeoutMs?: number | undefined
  pollMs?: number | undefined
  sleep?: (ms: number) => Promise<void>
  removePath?: (target: string) => Promise<void>
}

const OPEN_EXECUTION_STATUSES = ["Waiting", "Running"] as const
const OPEN_TASK_STATUSES = ["Queued", "Running"] as const
/** run_ids name the on-disk artifact directories; strict form keeps path traversal out. */
const RUN_ID_PATTERN = /^[a-zA-Z0-9][a-zA-Z0-9-]{0,63}$/

/** Irreversible, project-scoped deletion: cancel open audit executions and wait
 *  for them to terminate, remove the database rows in one transaction
 *  (FK-ordered), then best-effort remove the checkout and run artifacts on disk.
 *  Disk failures are reported, never swallowed and never roll back the database. */
export class ProjectDeletionService {
  constructor(
    private db: PrismaClient,
    private agentExecutions: AgentExecutionService,
    private workspaceDir: string,
    private artifactDir?: string,
    private options: ProjectDeletionOptions = {},
  ) {}

  async deleteProject(id: number): Promise<ProjectDeletionOutcome> {
    const project = await this.db.project.findUnique({
      where: { id },
      select: { id: true, githubRepositoryId: true, repositoryOwner: true, repositoryName: true },
    })
    if (project === null) {
      throw new ProjectDeletionNotFoundError(`Project ${id} does not exist`)
    }

    const openTasks = await this.db.task.count({ where: { projectId: id, status: { in: [...OPEN_TASK_STATUSES] } } })
    if (openTasks > 0) {
      throw new ProjectDeletionBusyError(`The project has ${openTasks} ongoing operation${openTasks === 1 ? "" : "s"}; wait for them to finish`)
    }

    const open = await this.db.agentExecution.findMany({
      where: { status: { in: [...OPEN_EXECUTION_STATUSES] }, evaluation: { projectVersion: { projectId: id } } },
      select: { id: true },
    })
    const openIds = open.map((execution) => execution.id)
    for (const execution of open) {
      // Best effort: if the request cannot be persisted/delivered the execution
      // stays open and the wait loop reports it as pending below.
      try { await this.agentExecutions.cancelQualityAudit(execution.id) } catch { /* reported by the wait loop */ }
    }
    if (openIds.length > 0) {
      const timeoutMs = this.options.timeoutMs ?? 45_000
      const pollMs = this.options.pollMs ?? 500
      const sleep = this.options.sleep ?? ((ms: number) => new Promise((resolvePromise) => { setTimeout(resolvePromise, ms) }))
      const deadline = Date.now() + timeoutMs
      let pending = openIds
      while (Date.now() < deadline) {
        pending = (await this.db.agentExecution.findMany({
          where: { id: { in: openIds }, status: { in: [...OPEN_EXECUTION_STATUSES] } },
          select: { id: true },
        })).map((execution) => execution.id)
        if (pending.length === 0) break
        await sleep(pollMs)
      }
      if (pending.length > 0) {
        return { status: "cancelling", pendingExecutionIds: pending }
      }
    }

    const executions = await this.db.agentExecution.findMany({
      where: { evaluation: { projectVersion: { projectId: id } } },
      select: { result: true },
    })
    const runIds = new Set<string>()
    let rejected = 0
    for (const execution of executions) {
      const runId = readRunId(execution.result)
      if (runId !== null) {
        runIds.add(runId)
      } else if (mentionsRunId(execution.result)) {
        rejected += 1
      }
    }

    const counts = await this.deleteRows(id)
    const disk = await this.removeDisk(id, project, [...runIds], rejected)
    return { status: "deleted", counts, disk }
  }

  private async deleteRows(projectId: number): Promise<ProjectDeletionCounts> {
    return this.db.$transaction(async (tx) => {
      const versionRows = await tx.projectVersion.findMany({ where: { projectId }, select: { id: true } })
      const versionIds = versionRows.map((version) => version.id)
      const evaluationRows = versionIds.length === 0 ? [] : await tx.evaluation.findMany({ where: { projectVersionId: { in: versionIds } }, select: { id: true } })
      const evaluationIds = evaluationRows.map((evaluation) => evaluation.id)
      const executionRows = evaluationIds.length === 0 ? [] : await tx.agentExecution.findMany({ where: { evaluationId: { in: evaluationIds } }, select: { id: true } })
      const executionIds = executionRows.map((execution) => execution.id)
      const streamRows = executionIds.length === 0 ? [] : await tx.executionEventStream.findMany({ where: { executionId: { in: executionIds } }, select: { id: true } })
      const streamIds = streamRows.map((stream) => stream.id)
      const taskRows = await tx.task.findMany({ where: { projectId }, select: { id: true } })
      const taskIds = taskRows.map((task) => task.id)

      const events = streamIds.length === 0 ? 0 : (await tx.executionEvent.deleteMany({ where: { streamId: { in: streamIds } } })).count
      let architectureArtifacts = 0
      const artifactWhere: Prisma.ArchitectureContextArtifactWhereInput[] = []
      if (executionIds.length > 0) artifactWhere.push({ executionId: { in: executionIds } })
      if (versionIds.length > 0) artifactWhere.push({ projectVersionId: { in: versionIds } })
      if (artifactWhere.length > 0) {
        architectureArtifacts = (await tx.architectureContextArtifact.deleteMany({ where: { OR: artifactWhere } })).count
      }
      if (executionIds.length > 0) await tx.executionEventStream.deleteMany({ where: { executionId: { in: executionIds } } })
      const executions = executionIds.length === 0 ? 0 : (await tx.agentExecution.deleteMany({ where: { id: { in: executionIds } } })).count
      const evaluations = evaluationIds.length === 0 ? 0 : (await tx.evaluation.deleteMany({ where: { id: { in: evaluationIds } } })).count
      let graphExtractions = 0
      if (taskIds.length > 0) graphExtractions += (await tx.graphExtraction.deleteMany({ where: { taskId: { in: taskIds } } })).count
      graphExtractions += (await tx.graphExtraction.deleteMany({ where: { projectId } })).count
      const tasks = (await tx.task.deleteMany({ where: { projectId } })).count
      await tx.project.update({ where: { id: projectId }, data: { selectedVersionId: null } })
      const versions = (await tx.projectVersion.deleteMany({ where: { projectId } })).count
      await tx.project.delete({ where: { id: projectId } })
      return { versions, evaluations, executions, events, architectureArtifacts, tasks, graphExtractions }
    })
  }

  private async removeDisk(
    projectId: number,
    project: { githubRepositoryId: bigint | null; repositoryOwner: string; repositoryName: string },
    runIds: string[],
    skipped: number,
  ): Promise<ProjectDeletionDisk> {
    const removePath = this.options.removePath ?? ((target: string) => rm(target, { recursive: true, force: true }))
    const disk: ProjectDeletionDisk = { artifactsRemoved: [], artifactsSkipped: skipped, artifactFailures: [], cloneRemoved: false, cloneFailure: null }
    const artifactRoot = resolve(this.artifactDir ?? join(this.workspaceDir, ".veraud-artifacts"))
    for (const runId of runIds) {
      const target = safeArtifactDir(artifactRoot, runId)
      if (target === null) { disk.artifactsSkipped += 1; continue }
      try {
        if (await exists(target)) { await removePath(target); disk.artifactsRemoved.push(runId) }
      } catch (error) {
        disk.artifactFailures.push(`${runId}: ${errorMessage(error)}`)
      }
    }
    const folder = projectWorkspaceFolder({ id: projectId, ...project })
    const clone = resolve(this.workspaceDir, folder)
    if (clone.startsWith(resolve(this.workspaceDir) + sep)) {
      try {
        if (await exists(clone)) { await removePath(clone); disk.cloneRemoved = true }
      } catch (error) {
        disk.cloneFailure = errorMessage(error)
      }
    } else {
      disk.cloneFailure = "workspace path rejected"
    }
    return disk
  }
}

function readRunId(result: string | null): string | null {
  if (result === null) return null
  try {
    const parsed = JSON.parse(result) as { run_id?: unknown }
    return typeof parsed.run_id === "string" && RUN_ID_PATTERN.test(parsed.run_id) ? parsed.run_id : null
  } catch {
    return null
  }
}

function mentionsRunId(result: string | null): boolean {
  return result !== null && /"run_id"\s*:/.test(result)
}

function safeArtifactDir(root: string, runId: string): string | null {
  if (!RUN_ID_PATTERN.test(runId)) return null
  const target = resolve(root, runId)
  return target.startsWith(resolve(root) + sep) ? target : null
}

async function exists(target: string): Promise<boolean> {
  try { await stat(target); return true } catch { return false }
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}
