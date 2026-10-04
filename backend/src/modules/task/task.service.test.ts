import { describe, it } from "node:test"
import assert from "node:assert/strict"
import type { NewTask, StoredTask, TaskStore } from "./task.repository.js"
import type { QueuedTask, TaskQueue, TaskResult } from "../../infrastructure/task-runner/task.runner.js"
import { TaskService } from "./task.service.js"

describe("TaskService.listActive", () => {
  it("returns whatever the repository reports", async () => {
    const rows: StoredTask[] = [{
      id: 1,
      projectId: 2,
      repositoryOwner: "octocat",
      repositoryName: "Hello-World",
      description: "cloning octocat/Hello-World",
      status: "Running",
      exitCode: null,
    }]
    const store: TaskStore = {
      create: async () => { throw new Error("not used here") },
      update: async () => { throw new Error("not used here") },
      delete: async () => { throw new Error("not used here") },
      findById: async () => null,
      findActive: async () => rows,
    }
    const runner: TaskQueue = {
      enqueue: async () => { throw new Error("not used here") },
    }
    const service = new TaskService(store, runner)

    assert.deepEqual(await service.listActive(), rows)
  })
})

describe("TaskService.launch", () => {
  it("creates a queued task and awaits its queueing", async () => {
    const created: Array<NewTask> = []
    const enqueued: Array<QueuedTask> = []
    const store: TaskStore = {
      create: async (data: NewTask): Promise<StoredTask> => {
        created.push(data)
        return { id: 4, projectId: data.projectId, repositoryOwner: "acme", repositoryName: "Demo", description: data.description, status: data.status, exitCode: null }
      },
      update: async () => { throw new Error("not used here") },
      delete: async () => { throw new Error("not used here") },
      findById: async () => null,
      findActive: async () => [],
    }
    const runner: TaskQueue = {
      enqueue: async (task: QueuedTask): Promise<TaskResult> => {
        enqueued.push(task)
        return { status: "Succeded", exitCode: 0, logTrail: "" }
      },
    }
    const service = new TaskService(store, runner)

    const { task, result } = await service.launch(2, "listing branches acme/Demo", { kind: "list-branches", folder: "folder" })

    assert.deepEqual(created, [{ projectId: 2, description: "listing branches acme/Demo", status: "Queued" }])
    assert.deepEqual(enqueued, [{ taskId: 4, projectId: 2, command: { kind: "list-branches", folder: "folder" } }])
    assert.equal(task.id, 4)
    assert.equal(result.status, "Succeded")
  })

  it("removes tasks by id", async () => {
    const removed: Array<number> = []
    const store: TaskStore = {
      create: async () => { throw new Error("not used here") },
      update: async () => { throw new Error("not used here") },
      delete: async (id: number) => { removed.push(id) },
      findById: async () => null,
      findActive: async () => [],
    }
    const runner: TaskQueue = {
      enqueue: async () => { throw new Error("not used here") },
    }
    const service = new TaskService(store, runner)

    await service.remove(9)

    assert.deepEqual(removed, [9])
  })
})
