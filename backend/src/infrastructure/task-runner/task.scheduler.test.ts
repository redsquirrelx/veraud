import { describe, it } from "node:test"
import assert from "node:assert/strict"
import { setImmediate } from "node:timers/promises"
import type { FastifyBaseLogger } from "fastify"
import { logger } from "../../config/logger.js"
import type { StoredTask, TaskStore } from "../../modules/task/task.repository.js"
import type { TaskCommand } from "./task.runner.js"
import { TaskRunner } from "./task.runner.js"

logger.configure({ child: () => ({ info() {}, warn() {}, error() {}, debug() {} }) } as unknown as FastifyBaseLogger)

function harness() {
  const tasks = new Map<number, StoredTask>()
  const started: Array<{ argv: string[], finish: () => void, fail: () => void }> = []
  const store: TaskStore = {
    create: async () => { throw new Error("Not used") },
    update: async (id, data) => {
      const task = { ...tasks.get(id)!, ...data }
      tasks.set(id, task)
      return task
    },
    findById: async (id) => tasks.get(id) ?? null,
    findActive: async () => [],
    delete: async () => {},
  }
  const runner = new TaskRunner(store, { setStatus: async () => {}, markSynced: async () => {} },
    { broadcast: () => {} }, "workspace", async (_binary, argv) => {
      return new Promise((resolve, reject) => {
        started.push({ argv, finish: () => resolve({ stdout: "ok", stderr: "" }), fail: () => reject(new Error("clone failed")) })
      })
    })
  let id = 0
  function enqueue(projectId: number, kind: TaskCommand["kind"]) {
    const taskId = ++id
    tasks.set(taskId, {
      id: taskId, projectId, repositoryOwner: "acme", repositoryName: "Demo",
      description: kind, status: "Queued", kind, exitCode: null,
    })
    const folder = `project-${projectId}`
    let command: TaskCommand
    if (kind === "clone") command = { kind, folder, cloneUrl: "repo" }
    else if (kind === "checkout-branch" || kind === "rev-parse") command = { kind, folder, branch: "main" }
    else if (kind === "checkout-detach") command = { kind, folder, commitHash: "a".repeat(40) }
    else if (kind === "log-commits") command = { kind, folder, branch: "main", limit: 10, offset: 0 }
    else command = { kind, folder }
    return runner.enqueue({ taskId, projectId, command })
  }
  return { enqueue, started, tasks }
}

describe("TaskRunner scheduling", { timeout: 5000 }, () => {
  it("keeps clones FIFO while unrelated queries run in parallel", async () => {
    const h = harness()
    const first = h.enqueue(1, "clone")
    const second = h.enqueue(2, "clone")
    const query = h.enqueue(3, "list-branches")
    await setImmediate()
    assert.equal(h.started.length, 2)
    const cloning = h.started.find((job) => job.argv[0] === "clone")!
    const reading = h.started.find((job) => job.argv[2] === "branch")!
    assert.ok(cloning.argv.at(-1)?.endsWith("project-1"))
    reading.finish()
    await query
    assert.equal(h.started.length, 2)
    cloning.finish()
    await first
    await setImmediate()
    assert.equal(h.started.length, 3)
    assert.ok(h.started[2]!.argv.at(-1)?.endsWith("project-2"))
    h.started[2]!.finish()
    await second
  })

  it("blocks commands for both queued and active clones of their project", async () => {
    const h = harness()
    const first = h.enqueue(1, "clone")
    const second = h.enqueue(2, "clone")
    const query = h.enqueue(2, "list-branches")
    await setImmediate()
    assert.equal(h.started.length, 1)
    h.started[0]!.finish()
    await first
    await setImmediate()
    assert.equal(h.started.length, 2)
    assert.equal(h.tasks.get(3)!.status, "Queued")
    h.started[1]!.finish()
    await second
    await setImmediate()
    assert.equal(h.started.length, 3)
    h.started[2]!.finish()
    await query
  })

  it("allows concurrent reads but does not let reads overtake a waiting writer", async () => {
    const h = harness()
    const read1 = h.enqueue(1, "list-branches")
    const read2 = h.enqueue(1, "rev-parse")
    const writer = h.enqueue(1, "checkout-branch")
    const read3 = h.enqueue(1, "list-tree")
    await setImmediate()
    assert.equal(h.started.length, 2)
    h.started[0]!.finish()
    await read1
    assert.equal(h.started.length, 2)
    h.started[1]!.finish()
    await read2
    await setImmediate()
    assert.equal(h.started.length, 3)
    assert.equal(h.started[2]!.argv[2], "checkout")
    h.started[2]!.finish()
    await writer
    await setImmediate()
    assert.equal(h.started.length, 4)
    h.started[3]!.finish()
    await read3
  })

  for (const kind of ["pull", "fetch", "checkout-branch", "checkout-detach"] as const) {
    it(`makes ${kind} exclusive only within its project`, async () => {
      const h = harness()
      const writer = h.enqueue(1, kind)
      const sameProject = h.enqueue(1, "list-branches")
      const otherProject = h.enqueue(2, kind)
      await setImmediate()
      assert.equal(h.started.length, 2)
      assert.ok(h.started[1]!.argv[1]?.endsWith("project-2"))
      h.started[0]!.finish()
      h.started[1]!.finish()
      await Promise.all([writer, otherProject])
      await setImmediate()
      assert.equal(h.started.length, 3)
      h.started[2]!.finish()
      await sameProject
    })
  }

  it("fails clone dependents without executing them and continues the clone queue", async () => {
    const h = harness()
    const clone = h.enqueue(1, "clone")
    const dependent = h.enqueue(1, "list-branches")
    const nextClone = h.enqueue(2, "clone")
    await setImmediate()
    h.started[0]!.fail()
    assert.equal((await clone).status, "Failed")
    const result = await dependent
    assert.equal(result.status, "Failed")
    assert.match(result.logTrail!, /clone task 1 failed/)
    assert.equal(h.tasks.get(2)!.status, "Failed")
    await setImmediate()
    assert.equal(h.started.length, 2)
    h.started[1]!.finish()
    assert.equal((await nextClone).status, "Succeded")
  })

  it("waits for active reads before cloning and lets a pending clone precede waiting reads", async () => {
    const h = harness()
    const reading = h.enqueue(1, "list-branches")
    await setImmediate()
    const waitingRead = h.enqueue(1, "list-tree")
    const clone = h.enqueue(1, "clone")
    await setImmediate()
    assert.equal(h.started.length, 1)
    h.started[0]!.finish()
    await reading
    await setImmediate()
    assert.equal(h.started.length, 2)
    assert.equal(h.started[1]!.argv[0], "clone")
    h.started[1]!.finish()
    await clone
    await setImmediate()
    assert.equal(h.started.length, 3)
    h.started[2]!.finish()
    await waitingRead
  })
})
