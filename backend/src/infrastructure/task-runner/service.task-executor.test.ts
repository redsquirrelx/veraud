import { describe, it } from "node:test"
import assert from "node:assert/strict"
import { setImmediate } from "node:timers/promises"
import { createServer } from "node:http"
import { once } from "node:events"
import type { AddressInfo } from "node:net"
import type { FastifyBaseLogger } from "fastify"
import { logger } from "../../config/logger.js"
import type { StoredTask, TaskStore, TaskUpdate } from "../../modules/task/task.repository.js"
import { TaskService } from "../../modules/task/task.service.js"
import type { TaskEvent } from "../realtime-gateway/realtime.gateway.js"
import { gitTaskExecutor } from "./git.task-executor.js"
import { serviceTask, serviceTaskExecutor, type ServiceTaskHandler } from "./service.task-executor.js"
import { TaskRunner } from "./task.runner.js"
import type { TaskCommand } from "./task.types.js"

logger.configure({ child: () => ({ info() {}, warn() {}, error() {}, debug() {} }) } as unknown as FastifyBaseLogger)

function deferred() {
  let resolve!: () => void
  const promise = new Promise<void>((done) => { resolve = done })
  return { promise, resolve }
}

function harness(handlers: Record<string, ServiceTaskHandler>) {
  const rows = new Map<number, StoredTask>()
  const updates: TaskUpdate[] = []
  const events: TaskEvent[] = []
  const projectStatuses: string[] = []
  const synced: number[] = []
  const gitCalls: string[][] = []
  const git = deferred()
  let gitFails = false
  const store: TaskStore = {
    async create(data) {
      const task = { id: rows.size + 1, repositoryOwner: "acme", repositoryName: "demo", exitCode: null, ...data }
      rows.set(task.id, task)
      return task
    },
    async update(id, data) {
      updates.push(data)
      const task = { ...rows.get(id)!, ...data }
      rows.set(id, task)
      return task
    },
    async findById(id) { return rows.get(id) ?? null },
    async findActive() { return [...rows.values()].filter((row) => ["Queued", "Running"].includes(row.status)) },
    async delete(id) { rows.delete(id) },
  }
  const runner = new TaskRunner(store, {
    async setStatus(_id, status) { projectStatuses.push(status) },
    async markSynced(id) { synced.push(id) },
  }, { broadcast(event) { events.push(event) } }, [
    gitTaskExecutor("workspace", async (_binary, argv) => {
      gitCalls.push(argv)
      await git.promise
      if (gitFails) throw new Error("clone failed")
      return { stdout: "git output", stderr: "" }
    }),
    serviceTaskExecutor(handlers),
  ])
  const tasks = new TaskService(store, runner)
  const launch = (command: TaskCommand, projectId = 1) => tasks.launch(projectId, "Background work", command)
  return { tasks, runner, store, rows, updates, events, projectStatuses, synced, gitCalls, git, launch,
    failGit: () => { gitFails = true; git.resolve() } }
}

describe("service tasks", { timeout: 5000 }, () => {
  it("runs registered procedures with context, persisted states and events, without CLI or project sync", async () => {
    const finished = deferred()
    const inputs: unknown[] = []
    const h = harness({ "project.index": { async run(input, context) {
      inputs.push(input, context)
      await finished.promise
      return { output: "index artifact", logTrail: "x".repeat(5000) }
    } } })
    const running = h.launch(serviceTask("project.index", { revision: "a".repeat(40) }))
    await setImmediate()
    assert.deepEqual(inputs, [{ revision: "a".repeat(40) }, { taskId: 1, projectId: 1 }])
    assert.equal((await h.tasks.listActive())[0]!.kind, "project.index")
    assert.equal(h.rows.get(1)!.command, null)
    assert.deepEqual(h.events.map((event) => event.task.status), ["Queued", "Running"])
    finished.resolve()
    const { result } = await running
    assert.equal(result.status, "Succeded")
    assert.equal(result.exitCode, null)
    assert.equal(result.output, "index artifact")
    assert.equal(result.logTrail!.length, 4000)
    assert.deepEqual(h.events.map((event) => event.task.status), ["Queued", "Running", "Succeded"])
    assert.deepEqual(h.gitCalls, [])
    assert.deepEqual(h.projectStatuses, [])
    assert.deepEqual(h.synced, [])
    assert.deepEqual(await h.tasks.listActive(), [])
  })

  it("supports async service calls and handlers with no return value", async () => {
    let calls = 0
    const client = { async synchronize(projectId: number) { calls++; assert.equal(projectId, 1) } }
    const h = harness({ "service.sync": { async run(_input, context) { await client.synchronize(context.projectId) } } })
    const { result } = await h.launch(serviceTask("service.sync"))
    assert.equal(calls, 1)
    assert.deepEqual(result, { status: "Succeded", exitCode: null, logTrail: null, output: "" })
  })

  it("can call an HTTP service without launching a command", async () => {
    let requests = 0
    const server = createServer((_request, response) => { requests++; response.end("synchronized") })
    server.listen(0, "127.0.0.1")
    await once(server, "listening")
    try {
      const url = `http://127.0.0.1:${(server.address() as AddressInfo).port}`
      const h = harness({ sync: { async run() {
        const response = await fetch(url)
        if (!response.ok) throw new Error("Service unavailable")
        return { output: await response.text() }
      } } })
      assert.equal((await h.launch(serviceTask("sync"))).result.output, "synchronized")
      assert.equal(requests, 1)
      assert.deepEqual(h.gitCalls, [])
    } finally {
      server.closeAllConnections()
      await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()))
    }
  })

  it("fails unknown handlers without leaving queued rows or executing arbitrary work", async () => {
    const h = harness({})
    for (const name of ["missing", "toString", "__proto__"]) {
      const { task, result } = await h.launch(serviceTask(name, { token: "private-input" }))
      assert.equal(result.status, "Failed")
      assert.equal(h.rows.get(task.id)!.status, "Failed")
    }
    assert.deepEqual(await h.tasks.listActive(), [])
    assert.ok(!JSON.stringify(h.updates).includes("private-input"))
    assert.deepEqual(h.gitCalls, [])
  })

  it("persists service failure safely, releases its locks and continues the queue", async () => {
    const ready = deferred()
    const h = harness({
      fail: { projectAccess: "exclusive", async run() { await ready.promise; throw new Error("secret-service-token") } },
      next: { projectAccess: "shared", async run() { return { output: "next ran" } } },
    })
    const failed = h.launch(serviceTask("fail"))
    const next = h.launch(serviceTask("next"))
    await setImmediate()
    assert.equal(h.rows.get(2)!.status, "Queued")
    ready.resolve()
    assert.equal((await failed).result.status, "Failed")
    assert.equal((await next).result.output, "next ran")
    assert.equal(h.rows.get(1)!.status, "Failed")
    assert.ok(!JSON.stringify(h.updates).includes("secret-service-token"))
    assert.deepEqual(h.projectStatuses, [])
  })

  it("does not execute work if its Running state cannot be persisted and releases the queue", async () => {
    let calls = 0
    const h = harness({ work: { projectAccess: "exclusive", async run() { calls++ } } })
    const update = h.store.update.bind(h.store)
    h.store.update = async (id, data) => {
      if (id === 1 && data.status === "Running") throw new Error("storage unavailable")
      return update(id, data)
    }
    const first = h.launch(serviceTask("work"))
    const next = h.launch(serviceTask("work"))
    assert.equal((await first).result.status, "Failed")
    assert.equal((await next).result.status, "Succeded")
    assert.equal(calls, 1)
    assert.equal(h.rows.get(1)!.status, "Failed")
  })

  it("lets independent services run during clone, but checkout readers wait", async () => {
    const started: string[] = []
    const h = harness({
      independent: { async run() { started.push("independent") } },
      graph: { projectAccess: "shared", async run() { started.push("graph") } },
    })
    const clone = h.launch({ kind: "clone", folder: "repo", cloneUrl: "repo" })
    const graph = h.launch(serviceTask("graph"))
    const independent = h.launch(serviceTask("independent"))
    await independent
    assert.deepEqual(started, ["independent"])
    h.git.resolve()
    await Promise.all([clone, graph])
    assert.deepEqual(started, ["independent", "graph"])
    assert.deepEqual(h.projectStatuses, ["SYNCING", "READY"])
  })

  it("fails checkout-dependent services if clone fails, without invoking them", async () => {
    let calls = 0
    const h = harness({ graph: { projectAccess: "shared", async run() { calls++ } } })
    const clone = h.launch({ kind: "clone", folder: "repo", cloneUrl: "repo" })
    const graph = h.launch(serviceTask("graph"))
    await setImmediate()
    h.failGit()
    assert.equal((await clone).result.status, "Failed")
    const { result } = await graph
    assert.match(result.logTrail!, /clone task 1 failed/)
    assert.equal(result.status, "Failed")
    assert.equal(calls, 0)
  })

  it("shares checkout locks with Git and does not let a later reader overtake a writer", async () => {
    const ready = deferred()
    const started: string[] = []
    const h = harness({
      reader: { projectAccess: "shared", async run() { started.push("reader"); await ready.promise } },
      later: { projectAccess: "shared", async run() { started.push("later") } },
    })
    const reader = h.launch(serviceTask("reader"))
    const writer = h.launch({ kind: "checkout-branch", folder: "repo", branch: "main" })
    const later = h.launch(serviceTask("later"))
    await setImmediate()
    assert.deepEqual(started, ["reader"])
    assert.equal(h.gitCalls.length, 0)
    ready.resolve()
    await reader
    await setImmediate()
    assert.equal(h.gitCalls.length, 1)
    assert.deepEqual(started, ["reader"])
    h.git.resolve()
    await Promise.all([writer, later])
    assert.deepEqual(started, ["reader", "later"])
  })

  it("serializes a service group across projects without blocking unrelated work", async () => {
    const ready = deferred()
    const started: number[] = []
    const h = harness({ limited: { serialGroup: "indexer", async run(_input, context) {
      started.push(context.projectId)
      await ready.promise
    } }, other: { async run() {} } })
    const first = h.launch(serviceTask("limited"), 1)
    const second = h.launch(serviceTask("limited"), 2)
    await h.launch(serviceTask("other"), 3)
    assert.deepEqual(started, [1])
    ready.resolve()
    await Promise.all([first, second])
    assert.deepEqual(started, [1, 2])
  })
})
