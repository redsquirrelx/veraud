import { execFile } from "node:child_process"
import { promisify } from "node:util"
import type { TaskStore } from "../../modules/task/task.repository.js"
import type { TaskEvent } from "../realtime-gateway/realtime.gateway.js"
import { logger } from "../../config/logger.js"
import { describeGitCommand, isGitCommand } from "./git.executor.js"
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
  done: (result: TaskResult) => void
}

export class TaskRunner implements TaskQueue {
  private log = logger.withTag("task-runner")
  private queue: RunnerJob[] = []
  private running = false

  constructor(
    private tasks: TaskStore,
    private projects: ProjectStatusWriter,
    private gateway: EventSink,
    private workspaceDir: string
  ) {}

  async enqueue(task: QueuedTask): Promise<TaskResult> {
    const joined = new Promise<TaskResult>((done) => {
      this.queue.push({ ...task, done })
    })
    this.log.info(`Task ${task.taskId} queued`)
    await this.announce(task.taskId)
    void this.drain()
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
        status: task.status,
        kind: task.kind,
        exitCode: task.exitCode,
      },
    })
  }

  private async drain(): Promise<void> {
    if (this.running) {
      return
    }
    this.running = true

    while (this.queue.length > 0) {
      const job = this.queue.shift() as RunnerJob
      await this.runJob(job)
    }

    this.running = false
  }

  private async runJob(job: RunnerJob): Promise<void> {
    if (isGitCommand(job.command)) {
      await this.runDescribed(job, describeGitCommand(job.command, this.workspaceDir))
      return
    }

    throw new Error(`Unsupported command kind ${(job.command as { kind: string }).kind}`)
  }

  private async runDescribed(
    job: RunnerJob,
    description: { binary: string, argv: string[], mutating: boolean }
  ): Promise<void> {
    const announce = description.mutating ? this.update.bind(this) : this.updateTaskOnly.bind(this)

    await announce(job, "Running", null, null)

    try {
      const { stdout, stderr } = await runFile(description.binary, description.argv)
      const result = { status: "Succeded", exitCode: 0, logTrail: `${stdout}\n${stderr}`.slice(-4000), output: stdout }
      await announce(job, result.status, result.exitCode, result.logTrail)
      job.done(result)
    } catch (error) {
      const output = error instanceof Error ? error.message : String(error)
      const result = { status: "Failed", exitCode: 1, logTrail: output.slice(-4000), output: "" }
      await announce(job, result.status, result.exitCode, result.logTrail)
      job.done(result)
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
        status: task.status,
        kind: task.kind,
        exitCode: task.exitCode,
      },
    })
  }
}
