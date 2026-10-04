import type { StoredTask, TaskStore } from "./task.repository.js"
import type { TaskCommand, TaskQueue, TaskResult } from "../../infrastructure/task-runner/task.runner.js"

export class TaskService {
  constructor(private tasks: TaskStore, private runner: TaskQueue) {}

  listActive() {
    return this.tasks.findActive()
  }

  async launch(
    projectId: number,
    description: string,
    command: TaskCommand
  ): Promise<{ task: StoredTask, result: TaskResult }> {
    const task = await this.tasks.create({
      projectId,
      description,
      status: "Queued",
      kind: command.kind,
    })

    const result = await this.runner.enqueue({
      taskId: task.id,
      projectId,
      command,
    })

    return { task, result }
  }

  async remove(taskId: number): Promise<void> {
    await this.tasks.delete(taskId)
  }
}
