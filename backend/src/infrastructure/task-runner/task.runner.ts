import { execFile } from "node:child_process"
import { promisify } from "node:util"
import type { TaskStore } from "../../modules/task/task.repository.js"
import type { TaskEvent } from "../realtime-gateway/realtime.gateway.js"
import { logger } from "../../config/logger.js"
import { describeGitCommand, formatCommand, isGitCommand } from "./git.executor.js"
import type { GitCommand } from "./git.executor.js"

const runFile = promisify(execFile)

export interface EventSink {
  broadcast(event: TaskEvent): void
}

export interface ProjectStatusWriter {
  setStatus(id: number, status: string): Promise<void>
  markSynced(id: number, at: Date): Promise<void>
}

export type { GitCommand }

export type TaskCommand = GitCommand

export interface QueuedTask {
  taskId: number
  projectId: number
  command: TaskCommand
}

export interface TaskResult {
  status: string
  exitCode: number | null
  logTrail: string | null
  output?: string
}

export function taskOutput(result: TaskResult): string {
  return result.output ?? result.logTrail ?? ""
}

export interface TaskQueue {
  enqueue(task: QueuedTask): Promise<TaskResult>
}

interface RunnerJob extends QueuedTask {
  execution: ReturnType<typeof describeGitCommand>
  done: (result: TaskResult) => void
  ready: boolean
  blockedFailure?: string
}

type CommandExecutor = (binary: string, argv: string[]) => Promise<{ stdout: string, stderr: string }>

function isExclusive(command: TaskCommand): boolean {
  return command.kind === "clone" || command.kind === "pull" || command.kind === "fetch"
    || command.kind === "checkout-branch" || command.kind === "checkout-detach"
}

export class TaskRunner implements TaskQueue {
  private log = logger.withTag("task-runner")
  private queue: RunnerJob[] = []
  private active = new Set<RunnerJob>()

  constructor(
    private tasks: TaskStore,
    private projects: ProjectStatusWriter,
    private gateway: EventSink,
    private workspaceDir: string,
    private execute: CommandExecutor = runFile
  ) {}

  async enqueue(task: QueuedTask): Promise<TaskResult> {
    if (!isGitCommand(task.command)) {
      throw new Error(`Unsupported command kind ${(task.command as { kind: string }).kind}`)
    }
    const execution = describeGitCommand(task.command, this.workspaceDir)
    let job!: RunnerJob
    const joined = new Promise<TaskResult>((done) => {
      job = { ...task, execution, done, ready: false }
      this.queue.push(job)
    })
    try {
      await this.tasks.update(task.taskId, {
        status: "Queued",
        exitCode: null,
        logTrail: null,
        command: formatCommand(execution.binary, execution.argv),
      })
      this.log.info(`Task ${task.taskId} queued`)
      await this.announce(task.taskId)
      job.ready = true
    } catch (error) {
      this.queue.splice(this.queue.indexOf(job), 1)
      throw error
    } finally {
      this.drain()
    }
    return joined
  }

  private async announce(taskId: number): Promise<void> {
    const task = await this.tasks.findById(taskId)

    if (task === null) {
      return
    }

    this.gateway.broadcast({
      type: "task.updated",
      task: {
        id: task.id,
        projectId: task.projectId,
        description: task.description,
        command: task.command ?? null,
        status: task.status,
        kind: task.kind,
        exitCode: task.exitCode,
      },
    })
  }

  private drain(): void {
    for (const job of [...this.queue]) {
      if (!job.ready || !this.canRun(job)) continue
      this.queue.splice(this.queue.indexOf(job), 1)
      this.active.add(job)
      void this.runScheduled(job)
    }
  }

  private canRun(job: RunnerJob): boolean {
    if (job.blockedFailure !== undefined) return true
    const active = [...this.active]
    const sameProject = active.filter((other) => other.projectId === job.projectId)
    if (job.command.kind === "clone") {
      return !active.some((other) => other.command.kind === "clone")
        && sameProject.length === 0
        && this.queue.find((other) => other.command.kind === "clone") === job
    }
    // Even a clone that is still being persisted reserves its project's checkout.
    if (this.queue.some((other) => other.projectId === job.projectId && other.command.kind === "clone")) return false
    if (sameProject.some((other) => isExclusive(other.command))) return false
    if (isExclusive(job.command) && sameProject.length > 0) return false
    const earlier = this.queue.slice(0, this.queue.indexOf(job))
    return !earlier.some((other) => other.projectId === job.projectId
      && (isExclusive(job.command) || isExclusive(other.command)))
  }

  private async runScheduled(job: RunnerJob): Promise<void> {
    let result: TaskResult
    try {
      if (job.blockedFailure !== undefined) {
        result = { status: "Failed", exitCode: null, logTrail: job.blockedFailure, output: "" }
        await this.updateTaskOnly(job, result.status, result.exitCode, result.logTrail)
      } else {
        result = await this.runDescribed(job, job.execution)
      }
    } catch (error) {
      result = { status: "Failed", exitCode: null, logTrail: String(error).slice(-4000), output: "" }
      this.log.error(`Task ${job.taskId} could not be completed: ${result.logTrail}`)
    }
    if (job.command.kind === "clone" && result.status !== "Succeded") {
      for (const waiting of this.queue) {
        if (waiting.projectId === job.projectId && waiting.command.kind !== "clone") {
          waiting.blockedFailure = `Task blocked because clone task ${job.taskId} failed`
        }
      }
    }
    this.active.delete(job)
    job.done(result)
    this.drain()
  }

  private async runDescribed(
    job: RunnerJob,
    description: { binary: string, argv: string[], mutating: boolean }
  ): Promise<TaskResult> {
    const announce = description.mutating ? this.update.bind(this) : this.updateTaskOnly.bind(this)

    await announce(job, "Running", null, null)

    try {
      const { stdout, stderr } = await this.execute(description.binary, description.argv)
      const result = { status: "Succeded", exitCode: 0, logTrail: `${stdout}\n${stderr}`.slice(-4000), output: stdout }
      await announce(job, result.status, result.exitCode, result.logTrail)
      return result
    } catch (error) {
      const output = error instanceof Error ? error.message : String(error)
      const result = { status: "Failed", exitCode: 1, logTrail: output.slice(-4000), output: "" }
      await announce(job, result.status, result.exitCode, result.logTrail)
      return result
    }
  }

  private async updateTaskOnly(
    job: RunnerJob,
    status: string,
    exitCode: number | null,
    logTrail: string | null
  ): Promise<void> {
    const task = await this.tasks.update(job.taskId, { status, exitCode, logTrail })

    this.log.info(`Task ${task.id} is now ${task.status}`)

    this.gateway.broadcast({
      type: "task.updated",
      task: {
        id: task.id,
        projectId: task.projectId,
        description: task.description,
        command: task.command ?? null,
        status: task.status,
        kind: task.kind,
        exitCode: task.exitCode,
      },
    })
  }

  private async update(
    job: RunnerJob,
    status: string,
    exitCode: number | null,
    logTrail: string | null
  ): Promise<void> {
    const task = await this.tasks.update(job.taskId, { status, exitCode, logTrail })

    this.log.info(`Task ${task.id} is now ${task.status}`)

    if (status === "Running") {
      await this.projects.setStatus(job.projectId, "SYNCING")
    }
    if (status === "Succeded") {
      await this.projects.setStatus(job.projectId, "READY")
      await this.projects.markSynced(job.projectId, new Date())
    }

    this.gateway.broadcast({
      type: "task.updated",
      task: {
        id: task.id,
        projectId: task.projectId,
        description: task.description,
        command: task.command ?? null,
        status: task.status,
        kind: task.kind,
        exitCode: task.exitCode,
      },
    })
  }
}
