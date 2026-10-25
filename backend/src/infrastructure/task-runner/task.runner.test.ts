import { describe, it } from "node:test"
import assert from "node:assert/strict"
import { execFileSync, execSync } from "node:child_process"
import { mkdtempSync, rmSync, writeFileSync } from "node:fs"
import { pathToFileURL } from "node:url"
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
  kind: "clone",
  exitCode: null,
}

describe("TaskRunner.enqueue", () => {
  it("clones only the latest commit in shallow mode and all history in full mode", async () => {
    const workspace = mkdtempSync(join(tmpdir(), "veraud-depth-"))
    const source = join(workspace, "source")
    const git = (...args: string[]) => execFileSync("git", args, { encoding: "utf8" }).trim()
    const store: TaskStore = {
      create: async () => stored,
      update: async (_id, data) => ({ ...stored, ...data }),
      delete: async () => {},
      findById: async () => stored,
      findActive: async () => [],
    }
    const runner = new TaskRunner(store, { setStatus: async () => {}, markSynced: async () => {} }, { broadcast: () => {} }, workspace)
    try {
      git("init", "-q", "-b", "main", source)
      for (const text of ["first", "second", "third"]) {
        writeFileSync(join(source, "file.txt"), text)
        git("-C", source, "add", ".")
        git("-C", source, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", text)
      }
      git("-C", source, "branch", "other")
      for (const shallowClone of [true, false]) {
        const folder = shallowClone ? "shallow" : "full"
        const target = join(workspace, folder)
        // A file URL makes Git honor --depth for a local repository.
        const result = await runner.enqueue({ taskId: 1, projectId: 2, command: { kind: "clone", cloneUrl: pathToFileURL(source).href, folder, shallowClone } })
        assert.equal(result.status, "Succeded", result.logTrail ?? "Clone failed")
        assert.equal(git("-C", target, "rev-parse", "--is-shallow-repository"), String(shallowClone))
        assert.equal(git("-C", target, "rev-list", "--count", "HEAD"), shallowClone ? "1" : "3")
        assert.equal(git("-C", target, "branch", "-r").includes("origin/other"), !shallowClone)
      }
    } finally {
      rmSync(workspace, { recursive: true, force: true })
    }
  })
  it("announces the queued task before running it", async () => {
    let persisted = { ...stored }
    const events: TaskEvent[] = []
    const projectStatuses: Array<{ id: number; status: string }> = []
    const syncedAt: Array<{ id: number; at: Date }> = []
    const store: TaskStore = {
      create: async () => stored,
      update: async (_id, data) => (persisted = { ...persisted, ...data }),
      delete: async () => {},
      findById: async () => persisted,
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
    assert.ok(persisted.command?.startsWith("git clone not-a-repo "))
    assert.deepEqual(events.map((event) => event.task.command), [persisted.command, persisted.command, persisted.command])
    assert.deepEqual(projectStatuses, [{ id: 2, status: "SYNCING" }])
    assert.deepEqual(syncedAt, [])
  })

  it("marks an SSH clone as failed and preserves the public-key diagnostic", async () => {
    let persisted = { ...stored }
    const events: TaskEvent[] = []
    const statuses: Array<{ id: number, status: string }> = []
    const executionOptions: Array<{ remote: boolean, timeoutMs?: number }> = []
    const store: TaskStore = {
      create: async () => stored,
      update: async (_id, data) => (persisted = { ...persisted, ...data }),
      delete: async () => {},
      findById: async () => persisted,
      findActive: async () => [],
    }
    const runner = new TaskRunner(
      store,
      { setStatus: async (id, status) => { statuses.push({ id, status }) }, markSynced: async () => {} },
      { broadcast: (event) => { events.push(event) } },
      mkdtempSync(join(tmpdir(), "veraud-ssh-failure-")),
      async (_binary, _argv, options) => {
        assert.ok(options)
        executionOptions.push(options)
        throw new Error("Permission denied (publickey)")
      },
    )

    const result = await runner.enqueue({
      taskId: 1,
      projectId: 2,
      command: { kind: "clone", cloneUrl: "git@github.com:acme/Demo.git", folder: "repo" },
    })

    assert.equal(result.status, "Failed")
    assert.match(result.logTrail ?? "", /Permission denied \(publickey\)/)
    assert.deepEqual(executionOptions, [{ remote: true, timeoutMs: 5 * 60 * 1000 }])
    assert.deepEqual(events.map((event) => event.task.status), ["Queued", "Running", "Failed"])
    assert.deepEqual(statuses, [{ id: 2, status: "SYNCING" }])
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

  it("pulls an existing checkout keeping its branch", async () => {    const events: TaskEvent[] = []
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

  it("fetches without moving a detached HEAD while marking sync", async () => {
    const projectStatuses: Array<{ id: number; status: string }> = []
    const syncedAt: Array<{ id: number }> = []
    const store: TaskStore = {
      create: async () => stored,
      update: async (id, data) => ({ ...stored, id, ...data }),
      delete: async () => {},
      findById: async (id) => ({ ...stored, id }),
      findActive: async () => [],
    }
    const projects = {
      setStatus: async (id: number, status: string) => {
        projectStatuses.push({ id, status })
      },
      markSynced: async (id: number) => {
        syncedAt.push({ id })
      },
    }
    const workspace = mkdtempSync(join(tmpdir(), "veraud-runner-"))
    const runner = new TaskRunner(store, projects, { broadcast: () => {} }, workspace)

    const source = join(mkdtempSync(join(tmpdir(), "veraud-src-")), "repo")
    execSync(`git init -q -b main "${source}"`)
    writeFileSync(join(source, "file.txt"), "hello")
    execSync(`git -C "${source}" add .`)
    execSync(`git -C "${source}" -c user.email=t@t -c user.name=t commit -qm init`)
    execSync(`git clone -q "${source}" "${join(workspace, "clone")}"`)
    const pinned = execSync(`git -C "${join(workspace, "clone")}" rev-parse HEAD`).toString().trim()
    execSync(`git -C "${join(workspace, "clone")}" checkout -q --detach "${pinned}"`)

    const fetched = await runner.enqueue({ taskId: 1, projectId: 2, command: { kind: "fetch", folder: "clone" } })

    assert.equal(fetched.status, "Succeded")
    assert.equal(execSync(`git -C "${join(workspace, "clone")}" rev-parse HEAD`).toString().trim(), pinned)
    assert.deepEqual(projectStatuses, [{ id: 2, status: "SYNCING" }, { id: 2, status: "READY" }])
    assert.deepEqual(syncedAt, [{ id: 2 }])
  })
})
