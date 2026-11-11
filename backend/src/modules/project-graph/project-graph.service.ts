import { createHash, randomBytes, timingSafeEqual } from "node:crypto"
import { join } from "node:path"
import type { PrismaClient } from "../../generated/prisma/client.js"
import type { TaskQueue } from "../../infrastructure/task-runner/task.types.js"
import type { ServiceTaskHandler } from "../../infrastructure/task-runner/service.task-executor.js"
import type { RealtimeGateway } from "../../infrastructure/realtime-gateway/realtime.gateway.js"
import type { StoredTask, TaskRepository } from "../task/task.repository.js"
import type { ProjectRepository } from "../project/project.repository.js"
import { projectWorkspaceFolder } from "../project/project-workspace.js"

export const GRAPH_PHASES = ["preparing", "extracting", "saving", "completed", "failed"] as const
export type GraphPhase = typeof GRAPH_PHASES[number]
export const GRAPH_ERROR_CODES = ["repository_unavailable", "commit_unavailable", "snapshot_failed", "extractor_unavailable", "timeout", "storage_failed", "extraction_failed", "interrupted", "service_unavailable", "queue_full"] as const
export type GraphErrorCode = typeof GRAPH_ERROR_CODES[number]
class GraphExecutionError extends Error {
  constructor(public code: GraphErrorCode) { super(code) }
}
const phaseOrder = ["queued", ...GRAPH_PHASES]

export class GraphRequestError extends Error {
  constructor(public statusCode: number, message: string) { super(message) }
}

interface PendingGraph {
  resolve(): void
  reject(error: Error): void
}

/** TaskRunner owns task lifecycle. Callbacks settle the remote executor, never an agent execution. */
export class ProjectGraphService {
  private pending = new Map<number, PendingGraph>()
  private starting = new Set<string>()
  private inFlight = new Set<Promise<unknown>>()
  private stopping = false

  constructor(
    private db: PrismaClient,
    private tasks: TaskRepository,
    private projects: ProjectRepository,
    private gateway: RealtimeGateway,
    private workspace: string,
    private agentUrl: string | undefined,
    private timeoutMs = 10 * 60 * 1000,
  ) {}

  handler(): ServiceTaskHandler {
    return {
      // A separate commit snapshot is made by the agent-server; never reads live HEAD.
      serialGroup: "graph.extract",
      run: async (_input, { taskId }) => this.execute(taskId),
    }
  }

  async start(projectId: number, branch: string, commitHash: string, queue: TaskQueue, regenerate = false) {
    if (this.stopping) throw new GraphRequestError(503, "Graph extraction service is stopping")
    const project = await this.projects.findById(projectId)
    if (!project) throw new GraphRequestError(404, "Project not found")
    const key = `${projectId}:${commitHash}`
    if (this.starting.has(key)) throw new GraphRequestError(409, "Graph extraction is already starting")
    this.starting.add(key)
    try {
      const existing = await this.db.graphExtraction.findFirst({
        where: { projectId, commitHash, task: { status: { in: ["Queued", "Running"] } } },
      })
      if (existing) return this.get(projectId, existing.taskId)
      if (!regenerate) {
        const cached = await this.db.graphExtraction.findFirst({
          where: { projectId, commitHash, phase: "completed", task: { status: "Succeded" } }, orderBy: { taskId: "desc" },
        })
        if (cached) return { ...await this.get(projectId, cached.taskId), reused: true }
      }
      if (!this.agentUrl) throw new GraphRequestError(503, "Graph extraction service is unavailable")
      if (project.status !== "READY") throw new GraphRequestError(409, "Project checkout is not ready")
      const task = await this.tasks.create({ projectId, description: `Graphify: ${branch} @ ${commitHash.slice(0, 7)}`, kind: "graph.extract", status: "Queued" })
      try {
        await this.db.graphExtraction.create({ data: { taskId: task.id, projectId, branch, commitHash } })
      } catch (error) {
        await this.tasks.update(task.id, { status: "Failed", exitCode: null, logTrail: "Could not prepare graph extraction" })
        throw error
      }
      // Deliberately detached from HTTP. The executor waits for a terminal callback.
      const execution = queue.enqueue({ taskId: task.id, projectId, command: { kind: "service", name: "graph.extract" } })
        .catch(async () => { await this.fail(task.id, "extraction_failed") })
        .catch(() => { /* Shutdown/storage failure: startup reconciliation handles persisted active tasks. */ })
      this.inFlight.add(execution)
      void execution.finally(() => this.inFlight.delete(execution))
      return this.get(projectId, task.id)
    } finally { this.starting.delete(key) }
  }

  async get(projectId: number, taskId?: number, commitHash?: string) {
    const row = await this.db.graphExtraction.findFirst({
      where: { projectId, ...(taskId === undefined ? {} : { taskId }), ...(commitHash === undefined ? {} : { commitHash }) },
      orderBy: { taskId: "desc" }, include: { task: true },
    })
    if (!row) return null
    const completed = row.task.status === "Succeded" && row.phase === "completed"
    const previous = !completed && taskId === undefined ? await this.db.graphExtraction.findFirst({
      where: { projectId, commitHash: row.commitHash, phase: "completed", task: { status: "Succeded" } }, orderBy: { taskId: "desc" },
      select: { taskId: true },
    }) : null
    return { taskId: row.taskId, projectId, branch: row.branch, commitHash: row.commitHash,
      status: row.task.status, phase: row.task.status === "Failed" ? "failed" : row.phase,
      error: row.task.status === "Failed" ? row.error ?? "extraction_failed" : row.error,
      createdAt: row.createdAt.toISOString(),
      graphAvailable: completed, previousGraphTaskId: previous?.taskId ?? null }
  }

  async callback(taskId: number, token: string, phase: GraphPhase, errorCode: GraphErrorCode = "extraction_failed") {
    const pending = this.pending.get(taskId)
    const row = await this.db.graphExtraction.findUnique({ where: { taskId } })
    const received = Buffer.from(createHash("sha256").update(token).digest("hex"))
    const expected = Buffer.from(row?.callbackHash ?? "")
    if (!row || received.length !== expected.length || !timingSafeEqual(received, expected)) {
      throw new GraphRequestError(403, "Invalid graph callback")
    }
    // Duplicate/out-of-order delivery cannot regress progress or overwrite a terminal result.
    if (["completed", "failed"].includes(row.phase) || phaseOrder.indexOf(phase) <= phaseOrder.indexOf(row.phase)) return
    if (!pending) throw new GraphRequestError(409, "Graph task is no longer running")
    const changed = await this.db.graphExtraction.updateMany({
      where: { taskId, phase: { in: phaseOrder.slice(0, phaseOrder.indexOf(phase)).filter((value) => value !== "completed" && value !== "failed") } },
      data: { phase, error: phase === "failed" ? errorCode : null },
    })
    if (!changed.count) return
    const task = await this.tasks.findById(taskId)
    if (task) this.announce(task)
    if (phase === "completed") pending.resolve()
    if (phase === "failed") pending.reject(new GraphExecutionError(errorCode))
  }

  private async execute(taskId: number) {
    if (this.stopping) throw new GraphExecutionError("interrupted")
    const row = await this.db.graphExtraction.findUniqueOrThrow({ where: { taskId } })
    const project = await this.projects.findById(row.projectId)
    if (!project || !this.agentUrl) throw new GraphExecutionError("service_unavailable")
    const token = randomBytes(32).toString("hex")
    await this.db.graphExtraction.update({ where: { taskId }, data: { callbackHash: createHash("sha256").update(token).digest("hex") } })
    if (this.stopping) throw new GraphExecutionError("interrupted")
    let timer: ReturnType<typeof setTimeout> | undefined
    const finished = new Promise<void>((resolve, reject) => {
      this.pending.set(taskId, { resolve, reject })
      timer = setTimeout(() => reject(new GraphExecutionError("timeout")), this.timeoutMs)
    })
    // Attach a rejection handler before dispatch: a callback may arrive before acceptance.
    void finished.catch(() => {})
    try {
      const response = await fetch(`${this.agentUrl}/api/graphs`, {
        method: "POST", headers: { "Content-Type": "application/json" }, signal: AbortSignal.timeout(15_000),
        body: JSON.stringify({ task_id: taskId, project_id: row.projectId, branch: row.branch, commit_hash: row.commitHash,
          repository_path: join(this.workspace, projectWorkspaceFolder(project)), callback_token: token }),
      }).catch(() => { throw new GraphExecutionError("service_unavailable") })
      if (!response.ok) throw new GraphExecutionError(response.status === 429 ? "queue_full" : response.status === 422 ? "repository_unavailable" : "service_unavailable")
      await finished
    } catch (error) {
      const code = error instanceof GraphExecutionError ? error.code : "extraction_failed"
      await this.db.graphExtraction.update({ where: { taskId }, data: { phase: "failed", error: code } })
      // Best effort cleanup after lost acceptance/completion callbacks, timeout or shutdown.
      await fetch(`${this.agentUrl}/api/graphs/${taskId}`, {
        method: "DELETE", headers: { "X-Graph-Token": token }, signal: AbortSignal.timeout(2000),
      }).catch(() => {})
      throw new GraphExecutionError(code)
    } finally {
      if (timer) clearTimeout(timer)
      this.pending.delete(taskId)
    }
  }

  async artifact(projectId: number, taskId: number) {
    if (!this.agentUrl) throw new GraphRequestError(503, "Graph extraction service is unavailable")
    const graph = await this.get(projectId, taskId)
    if (!graph?.graphAvailable) throw new GraphRequestError(404, "Graph is not available")
    const response = await fetch(`${this.agentUrl}/api/graphs/${projectId}/${graph.commitHash}/${taskId}/artifact`, { signal: AbortSignal.timeout(30_000) })
      .catch(() => { throw new GraphRequestError(502, "Graph artifact is unavailable") })
    if (!response.ok || !response.body) throw new GraphRequestError(502, "Graph artifact is unavailable")
    return response
  }

  private async fail(taskId: number, error: string) {
    await this.db.graphExtraction.update({ where: { taskId }, data: { phase: "failed", error } })
    const task = await this.tasks.update(taskId, { status: "Failed", exitCode: null, logTrail: error })
    this.announce(task)
  }

  private announce(task: StoredTask) {
    this.gateway.broadcast({ type: "task.updated", task: {
      id: task.id, projectId: task.projectId, description: task.description, command: task.command ?? null,
      status: task.status, kind: task.kind, exitCode: task.exitCode,
    } })
  }

  async reconcile() {
    const orphaned = await this.db.graphExtraction.findMany({ where: { task: { status: { in: ["Queued", "Running"] } } } })
    for (const row of orphaned) await this.fail(row.taskId, "interrupted")
  }

  async close() {
    this.stopping = true
    for (const job of this.pending.values()) job.reject(new GraphExecutionError("interrupted"))
    await Promise.allSettled([...this.inFlight])
  }
}
