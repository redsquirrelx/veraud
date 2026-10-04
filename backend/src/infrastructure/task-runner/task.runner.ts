import { execFile } from "node:child_process"
import { promisify } from "node:util"
import { join } from "node:path"
import type { TaskStore } from "../../modules/task/task.repository.js"
import type { TaskEvent } from "../realtime-gateway/realtime.gateway.js"
import { logger } from "../../config/logger.js"

const runFile = promisify(execFile)

export interface EventSink {
  broadcast(event: TaskEvent): void
}

export interface ProjectStatusWriter {
  setStatus(id: number, status: string): Promise<void>
  markSynced(id: number, at: Date): Promise<void>
}

export type GitCommand =
  | { kind: "clone", cloneUrl: string, folder: string }

export interface QueuedTask {
  taskId: number
  projectId: number
  command: GitCommand
}

export interface TaskResult {
  status: string
  exitCode: number | null
  logTrail: string | null
}

export interface TaskQueue {
  enqueue(task: QueuedTask): Promise<TaskResult>
}

interface CloneJob extends QueuedTask {
  targetDir: string
  done: (result: TaskResult) => void
}

export class TaskRunner implements TaskQueue {
  private log = logger.withTag("task-runner")
  private queue: CloneJob[] = []
  private running = false

  constructor(
    private tasks: TaskStore,
    private projects: ProjectStatusWriter,
    private gateway: EventSink,
    private workspaceDir: string
  ) {}

  async enqueue(task: QueuedTask): Promise<TaskResult> {
    const joined = new Promise<TaskResult>((done) => {
      this.queue.push({ ...task, targetDir: join(this.workspaceDir, task.command.folder), done })
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
      const job = this.queue.shift() as CloneJob
      await this.runJob(job)
    }

    this.running = false
  }

  private async runJob(job: CloneJob): Promise<void> {
    if (job.command.kind === "clone") {
      await this.runClone(job, job.command.cloneUrl)
    }
  }

  private async runClone(job: CloneJob, cloneUrl: string): Promise<void> {
    await this.update(job, "Running", null, null)

    try {
      const { stdout, stderr } = await runFile("git", ["clone", cloneUrl, job.targetDir])
      const result = { status: "Succeded", exitCode: 0, logTrail: `${stdout}\n${stderr}`.slice(-4000) }
      await this.update(job, result.status, result.exitCode, result.logTrail)
      job.done(result)
    } catch (error) {
      const output = error instanceof Error ? error.message : String(error)
      const result = { status: "Failed", exitCode: 1, logTrail: output.slice(-4000) }
      await this.update(job, result.status, result.exitCode, result.logTrail)
      job.done(result)
    }
  }

  private async update(
    job: CloneJob,
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
        exitCode: task.exitCode,
      },
    })
  }
}
