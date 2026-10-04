import { describe, it } from "node:test"
import assert from "node:assert/strict"
import { execSync } from "node:child_process"
import { mkdtempSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import type { FastifyBaseLogger } from "fastify"
import { logger } from "../../config/logger.js"
import type { TaskEvent } from "../realtime-gateway/realtime.gateway.js"
import type { StoredTask, TaskStore } from "../../modules/task/task.repository.js"
import { TaskRunner } from "./task.runner.js"

const quiet = { child: () => ({ info() {}, warn() {}, error() {}, debug() {} }) }
logger.configure(quiet as unknown as FastifyBaseLogger)

const stored: StoredTask = {
  id: 1,
  projectId: 2,
  repositoryOwner: "acme",
  repositoryName: "Demo",
  description: "cloning acme/Demo",
  status: "Queued",
  exitCode: null,
}

describe("TaskRunner.enqueue", () => {
  it("announces the queued task before running it", async () => {
    const events: TaskEvent[] = []
    const projectStatuses: Array<{ id: number; status: string }> = []
    const syncedAt: Array<{ id: number; at: Date }> = []
    const store: TaskStore = {
      create: async () => stored,
      update: async (_id, data) => ({ ...stored, ...data }),
      delete: async () => {},
      findById: async () => stored,
      findActive: async () => [],
    }
    const projects = {
      setStatus: async (id: number, status: string) => {
        projectStatuses.push({ id, status })
      },
      markSynced: async (id: number, at: Date) => {
        syncedAt.push({ id, at })
      },
    }
    const runner = new TaskRunner(
      store,
      projects,
      { broadcast: (event) => { events.push(event) } },
      mkdtempSync(join(tmpdir(), "veraud-runner-"))
    )

    const result = await runner.enqueue({ taskId: 1, projectId: 2, command: { kind: "clone", cloneUrl: "not-a-repo", folder: "folder" } })

    assert.equal(result.status, "Failed")
    assert.deepEqual(events.map((event) => event.task.status), ["Queued", "Running", "Failed"])
    assert.deepEqual(projectStatuses, [{ id: 2, status: "SYNCING" }])
    assert.deepEqual(syncedAt, [])
  })

  it("marks the project READY on success", async () => {
    const projectStatuses: Array<{ id: number; status: string }> = []
    const syncedAt: Array<{ id: number; at: Date }> = []
    const store: TaskStore = {
      create: async () => stored,
      update: async (_id, data) => ({ ...stored, ...data }),
      delete: async () => {},
      findById: async () => stored,
      findActive: async () => [],
    }
    const projects = {
      setStatus: async (id: number, status: string) => {
        projectStatuses.push({ id, status })
      },
      markSynced: async (id: number, at: Date) => {
        syncedAt.push({ id, at })
      },
    }
    const workspace = mkdtempSync(join(tmpdir(), "veraud-runner-"))
    const runner = new TaskRunner(store, projects, { broadcast: () => {} }, workspace)

    const source = join(mkdtempSync(join(tmpdir(), "veraud-src-")), "repo")
    execSync(`git init -q "${source}"`)
    writeFileSync(join(source, "file.txt"), "hello")
    execSync(`git -C "${source}" add .`)
    execSync(`git -C "${source}" -c user.email=t@t -c user.name=t commit -qm init`)

    const result = await runner.enqueue({ taskId: 1, projectId: 2, command: { kind: "clone", cloneUrl: source, folder: "clone" } })

    assert.equal(result.status, "Succeded")
    assert.deepEqual(projectStatuses, [{ id: 2, status: "SYNCING" }, { id: 2, status: "READY" }])
    assert.equal(syncedAt.length, 1)
    assert.equal(syncedAt[0]?.id, 2)
    assert.ok(syncedAt[0]?.at instanceof Date)
  })

  it("pulls an existing checkout keeping its branch", async () => {
    const events: TaskEvent[] = []
    const store: TaskStore = {
      create: async () => stored,
      update: async (id, data) => ({ ...stored, id, ...data }),
      delete: async () => {},
      findById: async (id) => ({ ...stored, id }),
      findActive: async () => [],
    }
    const projects = {
      setStatus: async () => {},
      markSynced: async () => {},
    }
    const workspace = mkdtempSync(join(tmpdir(), "veraud-runner-"))
    const runner = new TaskRunner(store, projects, { broadcast: (event) => { events.push(event) } }, workspace)

    const source = join(mkdtempSync(join(tmpdir(), "veraud-src-")), "repo")
    execSync(`git init -q -b main "${source}"`)
    writeFileSync(join(source, "file.txt"), "hello")
    execSync(`git -C "${source}" add .`)
    execSync(`git -C "${source}" -c user.email=t@t -c user.name=t commit -qm init`)

    const cloned = await runner.enqueue({ taskId: 1, projectId: 2, command: { kind: "clone", cloneUrl: source, folder: "clone" } })
    assert.equal(cloned.status, "Succeded")

    writeFileSync(join(source, "file.txt"), "hello again")
    execSync(`git -C "${source}" commit -qam second`)

    const pulled = await runner.enqueue({ taskId: 2, projectId: 2, command: { kind: "pull", folder: "clone" } })

    assert.equal(pulled.status, "Succeded")
    assert.equal(execSync(`git -C "${join(workspace, "clone")}" rev-parse --abbrev-ref HEAD`).toString().trim(), "main")
    assert.equal(events.filter((event) => event.task.id === 2).map((event) => event.task.status).join(","), "Queued,Running,Succeded")
  })
})
