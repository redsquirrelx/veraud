import { describe, it } from "node:test"
import assert from "node:assert/strict"
import type { StoredTask, TaskStore } from "./task.repository.js"
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
    const service = new TaskService(store)

    assert.deepEqual(await service.listActive(), rows)
  })
})
