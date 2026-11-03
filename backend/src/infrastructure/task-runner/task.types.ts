import type { GitCommand } from "./git.executor.js"

/** Named, server-registered work; input is never persisted by the task runner. */
export interface ServiceTaskCommand {
  kind: "service"
  name: string
  input?: unknown
}

export type TaskCommand = GitCommand | ServiceTaskCommand

export interface TaskContext {
  taskId: number
  projectId: number
}

export interface QueuedTask extends TaskContext {
  command: TaskCommand
}

export interface TaskOutput {
  output?: string
  logTrail?: string | null
  exitCode?: number | null
}

export interface TaskResult {
  status: string
  exitCode: number | null
  logTrail: string | null
  output?: string
}

export interface TaskScheduling {
  /** Omit for work independent of the checkout; shared readers may run together. */
  projectAccess?: "shared" | "exclusive"
  /** Reserve the checkout ahead of waiting readers; fail dependents on failure. */
  initializesProject?: boolean
  /** Serialize this group across projects, in enqueue order. */
  serialGroup?: string
}

export interface TaskPlan extends TaskScheduling {
  command: string | null
  initializationLabel?: string
  updatesProjectStatus?: boolean
  failureExitCode?: number
  failureMessage?: string
  run(): Promise<TaskOutput | void>
}

export interface TaskExecutor {
  /** Return undefined for commands owned by a different executor. */
  prepare(command: TaskCommand, context: TaskContext): TaskPlan | undefined
}

export interface TaskQueue {
  enqueue(task: QueuedTask): Promise<TaskResult>
}
