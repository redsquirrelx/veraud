import type { TaskStore } from "./task.repository.js"

export class TaskService {
  constructor(private tasks: TaskStore) {}

  listActive() {
    return this.tasks.findActive()
  }
}
