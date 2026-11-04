import type { StoredTask, TaskStore } from "../../modules/task/task.repository.js"
import type { TaskEvent } from "../realtime-gateway/realtime.gateway.js"
import { logger } from "../../config/logger.js"
import type { QueuedTask, TaskExecutor, TaskPlan, TaskQueue, TaskResult } from "./task.types.js"

export type { GitCommand } from "./git.executor.js"
export type { QueuedTask, TaskCommand, TaskQueue, TaskResult } from "./task.types.js"

export interface EventSink {
  broadcast(event: TaskEvent): void
}

export interface ProjectStatusWriter {
  setStatus(id: number, status: string): Promise<void>
  markSynced(id: number, at: Date): Promise<void>
}

export function taskOutput(result: TaskResult): string {
  return result.output ?? result.logTrail ?? ""
}

interface RunnerJob extends QueuedTask {
  plan: TaskPlan
  done: (result: TaskResult) => void
  ready: boolean
  blockedFailure?: string
}

export class TaskRunner implements TaskQueue {
  private log = logger.withTag("task-runner")
  private queue: RunnerJob[] = []
  private active = new Set<RunnerJob>()

  constructor(
    private tasks: TaskStore,
    private projects: ProjectStatusWriter,
    private gateway: EventSink,
    private executors: readonly TaskExecutor[],
  ) {}

  async enqueue(task: QueuedTask): Promise<TaskResult> {
    let plan: TaskPlan | undefined
    try {
      for (const executor of this.executors) {
        plan = executor.prepare(task.command, { taskId: task.taskId, projectId: task.projectId })
        if (plan) break
      }
      if (!plan) throw new Error("Unsupported task kind")
      if (plan.initializesProject && plan.projectAccess !== "exclusive") {
        throw new Error("Project initialization requires exclusive checkout access")
      }
    } catch {
      const result: TaskResult = { status: "Failed", exitCode: null, logTrail: "Task executor unavailable", output: "" }
      this.announce(await this.tasks.update(task.taskId, {
        status: result.status, exitCode: result.exitCode, logTrail: result.logTrail, command: null,
      }))
      return result
    }

    let job!: RunnerJob
    const joined = new Promise<TaskResult>((done) => {
      job = { ...task, plan, done, ready: false }
      this.queue.push(job)
    })
    try {
      const stored = await this.tasks.update(task.taskId, {
        status: "Queued", exitCode: null, logTrail: null, command: plan.command,
      })
      this.announce(stored)
      job.ready = true
    } catch (error) {
      this.queue.splice(this.queue.indexOf(job), 1)
      throw error
    } finally {
      this.drain()
    }
    return joined
  }

  private announce(task: StoredTask): void {
    this.log.info(`Task ${task.id} is now ${task.status}`)
    this.gateway.broadcast({ type: "task.updated", task: {
      id: task.id, projectId: task.projectId, description: task.description,
      command: task.command ?? null, status: task.status, kind: task.kind, exitCode: task.exitCode,
    } })
  }

  private drain(): void {
    for (const job of [...this.queue]) {
      if (!job.ready || !this.canRun(job)) continue
      this.queue.splice(this.queue.indexOf(job), 1)
      this.active.add(job)
      void this.run(job)
    }
  }

  private canRun(job: RunnerJob): boolean {
    if (job.blockedFailure !== undefined) return true
    const { plan } = job
    const active = [...this.active]
    if (plan.serialGroup) {
      if (active.some((other) => other.plan.serialGroup === plan.serialGroup)) return false
      if (this.queue.find((other) => other.plan.serialGroup === plan.serialGroup) !== job) return false
    }
    if (!plan.projectAccess) return true
    const sameProject = active.filter((other) => other.projectId === job.projectId && other.plan.projectAccess)
    if (plan.initializesProject) return sameProject.length === 0
    if (this.queue.some((other) => other.projectId === job.projectId && other.plan.initializesProject)) return false
    const conflicts = (other: RunnerJob) => other.projectId === job.projectId && other.plan.projectAccess
      && (plan.projectAccess === "exclusive" || other.plan.projectAccess === "exclusive")
    if (sameProject.some(conflicts)) return false
    return !this.queue.slice(0, this.queue.indexOf(job)).some(conflicts)
  }

  private async run(job: RunnerJob): Promise<void> {
    let result: TaskResult
    try {
      if (job.blockedFailure !== undefined) {
        result = { status: "Failed", exitCode: null, logTrail: job.blockedFailure, output: "" }
      } else {
        await this.update(job, { status: "Running", exitCode: null, logTrail: null })
        const output = await job.plan.run()
        result = { status: "Succeded", exitCode: output?.exitCode ?? null,
          logTrail: output?.logTrail?.slice(-4000) ?? null, output: output?.output ?? "" }
      }
      await this.update(job, result)
    } catch (error) {
      result = { status: "Failed", exitCode: job.plan.failureExitCode ?? null,
        logTrail: job.plan.failureMessage ?? (error instanceof Error ? error.message : String(error)).slice(-4000), output: "" }
      try { await this.update(job, result) }
      catch { this.log.error(`Task ${job.taskId} failure could not be persisted or announced`) }
    }
    if (job.plan.initializesProject && result.status !== "Succeded") {
      for (const waiting of this.queue) {
        if (waiting.projectId === job.projectId && waiting.plan.projectAccess && !waiting.plan.initializesProject) {
          waiting.blockedFailure = `Task blocked because ${job.plan.initializationLabel ?? "initialization"} task ${job.taskId} failed`
        }
      }
    }
    this.active.delete(job)
    job.done(result)
    this.drain()
  }

  private async update(job: RunnerJob, result: TaskResult): Promise<void> {
    const { status, exitCode, logTrail } = result
    const task = await this.tasks.update(job.taskId, { status, exitCode, logTrail })
    if (job.plan.updatesProjectStatus && job.blockedFailure === undefined) {
      if (status === "Running") await this.projects.setStatus(job.projectId, "SYNCING")
      if (status === "Succeded") {
        await this.projects.setStatus(job.projectId, "READY")
        await this.projects.markSynced(job.projectId, new Date())
      }
    }
    this.announce(task)
  }
}
